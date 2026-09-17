"""API HTTP de MiEvaluador (Django Ninja).

- /auth, /equipo, /plataforma: identidad y gestión (api.auth, api.equipo).
- /evaluaciones: procesos y evaluaciones guardados por entidad (api.evaluaciones).
- /procesos/analizar: lee el Documento Base y la carpeta de Drive antes de crear el proceso.
- /procesos/evaluar-*: evaluación directa sin guardar, solo para medición
  (DEBUG o superadmin); no expone datos de ninguna entidad.

La lógica de evaluación vive en el paquete `motor`, que no depende de Django.
"""
from __future__ import annotations

import asyncio
import atexit
from datetime import date

from django.conf import settings
from django.http import HttpRequest
from ninja import File, Form, NinjaAPI, Router
from ninja.errors import HttpError, Throttled
from ninja.files import UploadedFile
from ninja.throttling import AnonRateThrottle, AuthRateThrottle

from api.auth import router as auth_router
from api.configuracion import router as configuracion_router
from api.equipo import equipo, plataforma
from api.evaluaciones import router as evaluaciones_router
from cuentas.seguridad import sesion_activa
from evaluaciones.permisos import puede_crear_procesos
from motor.esquemas.proceso import (
    AnalisisResponse,
    EvaluarProponenteRequest,
    EvaluarRequisitosRequest,
    ProcesoDocumentoBase,
    Proponente,
    ResultadoRequisito,
)
from motor.evaluacion.todos import EVALUADORES_POR_REQUISITO, EvaluadorProponente
from motor.integrations.drive import DriveAccessError, DriveConfigError, list_proponentes
from motor.parsers.documento_base import build_proceso
from api.ejecucion import evaluar_todos_en_proceso as _evaluar_todos_en_proceso
from motor.workers import BrokenProcessPool, detener_pool, obtener_pool

api = NinjaAPI(
    title="MiEvaluador API",
    version="1.0",
    urls_namespace="api",
    throttle=[AnonRateThrottle(settings.LIMITES_API["anonimo"]), AuthRateThrottle(settings.LIMITES_API["usuario"])],
)
# Toda la evaluación exige sesión iniciada (y CSRF en las peticiones que modifican).
procesos = Router(tags=["procesos"], auth=sesion_activa)



def _solo_medicion(request: HttpRequest) -> None:
    if not (settings.DEBUG or request.auth.es_superadmin):
        raise HttpError(404, "No encontrado.")

atexit.register(detener_pool)


@api.exception_handler(Throttled)
def demasiadas_peticiones(request: HttpRequest, exc: Throttled):
    return api.create_response(request, {"detail": "Demasiadas solicitudes seguidas. Espere un momento e inténtelo de nuevo."}, status=429)


@api.get("/health", throttle=[])
def health(request: HttpRequest) -> dict[str, str]:
    return {"status": "ok"}


@procesos.post("/analizar", response=AnalisisResponse, throttle=[AuthRateThrottle(settings.LIMITES_API["pesado"])])
async def analizar_documento_base(
    request: HttpRequest,
    codigo_proceso: Form[str],
    fecha_cierre: Form[date],
    archivo: File[UploadedFile],
    carpeta_drive: Form[str | None] = None,
) -> AnalisisResponse:
    if not puede_crear_procesos(request.auth):
        raise HttpError(403, "Su rol no permite crear procesos.")
    nombre = (archivo.name or "").lower()
    if archivo.content_type not in ("application/pdf", "application/octet-stream") and not nombre.endswith(".pdf"):
        raise HttpError(400, "El archivo debe ser un PDF.")

    pdf_bytes = archivo.read()
    if not pdf_bytes:
        raise HttpError(400, "El archivo PDF está vacío.")

    try:
        proceso = await asyncio.to_thread(build_proceso, codigo_proceso.strip(), fecha_cierre, pdf_bytes)
    except Exception as exc:  # noqa: BLE001
        raise HttpError(422, f"No se pudo analizar el Documento Base: {exc}") from exc

    proponentes: list[Proponente] = []
    no_reconocidos: list[str] = []
    drive_error: str | None = None
    if carpeta_drive and carpeta_drive.strip():
        try:
            resultado = await asyncio.to_thread(list_proponentes, carpeta_drive.strip())
            proponentes = resultado.proponentes
            no_reconocidos = resultado.no_reconocidos
        except (DriveConfigError, DriveAccessError, ValueError) as exc:
            drive_error = str(exc)

    return AnalisisResponse(
        documento_base=proceso,
        proponentes=proponentes,
        proponentes_no_reconocidos=no_reconocidos,
        drive_error=drive_error,
    )


async def _evaluar_en_proceso(
    evaluador: EvaluadorProponente, proponente: Proponente, proceso: ProcesoDocumentoBase, requisito: int
) -> ResultadoRequisito:
    """Corre un requisito en el pool de procesos. Ningún fallo de un
    proponente tumba la evaluación de los demás: se reintenta si el pool se
    rompió y, en el peor caso, se devuelve el resultado con `error`."""
    loop = asyncio.get_running_loop()
    base = {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
        "requisito": requisito,
    }
    try:
        return await loop.run_in_executor(obtener_pool(), evaluador, proponente, proceso)
    except BrokenProcessPool:
        try:
            return await loop.run_in_executor(obtener_pool(), evaluador, proponente, proceso)
        except Exception as exc:  # noqa: BLE001
            return ResultadoRequisito(**base, error=f"No se pudo evaluar (el proceso murió, posiblemente por falta de memoria): {exc}")
    except MemoryError:
        return ResultadoRequisito(
            **base, error="No se pudo evaluar: el proponente superó el límite de memoria del servidor. Revísalo manualmente."
        )
    except Exception as exc:  # noqa: BLE001
        return ResultadoRequisito(**base, error=f"No se pudo evaluar automáticamente: {exc}")


def _registrar_rutas_requisito(numero: int, evaluador: EvaluadorProponente) -> None:
    async def evaluar_lote(request: HttpRequest, payload: EvaluarRequisitosRequest) -> list[ResultadoRequisito]:
        _solo_medicion(request)
        if not payload.proponentes:
            raise HttpError(400, "No hay proponentes para evaluar.")
        resultados = await asyncio.gather(
            *(_evaluar_en_proceso(evaluador, p, payload.documento_base, numero) for p in payload.proponentes)
        )
        return sorted(resultados, key=lambda r: r.numero_orden)

    async def evaluar_individual(request: HttpRequest, payload: EvaluarProponenteRequest) -> ResultadoRequisito:
        _solo_medicion(request)
        return await _evaluar_en_proceso(evaluador, payload.proponente, payload.documento_base, numero)

    procesos.add_api_operation(
        f"/evaluar-requisito-{numero}",
        ["POST"],
        evaluar_lote,
        response=list[ResultadoRequisito],
        url_name=f"evaluar_requisito_{numero}",
    )
    procesos.add_api_operation(
        f"/evaluar-requisito-{numero}/proponente",
        ["POST"],
        evaluar_individual,
        response=ResultadoRequisito,
        url_name=f"evaluar_requisito_{numero}_proponente",
    )


for _numero, _evaluador in EVALUADORES_POR_REQUISITO.items():
    _registrar_rutas_requisito(_numero, _evaluador)


@procesos.post("/evaluar-todos/proponente", response=list[ResultadoRequisito])
async def evaluar_todos_proponente(request: HttpRequest, payload: EvaluarProponenteRequest) -> list[ResultadoRequisito]:
    _solo_medicion(request)
    return await _evaluar_todos_en_proceso(payload.proponente, payload.documento_base)


@procesos.post("/evaluar-todos", response=list[ResultadoRequisito])
async def evaluar_todos(request: HttpRequest, payload: EvaluarRequisitosRequest) -> list[ResultadoRequisito]:
    _solo_medicion(request)
    if not payload.proponentes:
        raise HttpError(400, "No hay proponentes para evaluar.")
    por_proponente = await asyncio.gather(*(_evaluar_todos_en_proceso(p, payload.documento_base) for p in payload.proponentes))
    return sorted((r for lista in por_proponente for r in lista), key=lambda r: (r.numero_orden, r.requisito))


api.add_router("/procesos", procesos)
api.add_router("/auth", auth_router)
api.add_router("/equipo", equipo)
api.add_router("/plataforma", plataforma)
from api import historico as _historico  # noqa: E402,F401  (registra sus rutas en el router de evaluaciones)

api.add_router("/evaluaciones", evaluaciones_router)
api.add_router("/configuracion", configuracion_router)
