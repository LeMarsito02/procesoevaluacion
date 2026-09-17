"""API HTTP de MiEvaluador (Django Ninja).

Porta 1:1 los endpoints de la versión FastAPI (mismas rutas, mismos esquemas
y mismo formato de error `{"detail": ...}`), para que el frontend y los
scripts de medición sigan funcionando. La lógica de evaluación vive en el
paquete `motor`, que no depende de Django.
"""
from __future__ import annotations

import asyncio
import atexit
from datetime import date
from pathlib import Path

from django.http import HttpRequest, HttpResponse
from ninja import File, Form, NinjaAPI, Router
from ninja.errors import HttpError
from ninja.files import UploadedFile

from api.auth import router as auth_router
from api.equipo import equipo, plataforma
from cuentas.seguridad import sesion_activa
from motor.esquemas.proceso import (
    AnalisisResponse,
    EvaluarProponenteRequest,
    EvaluarRequisitosRequest,
    GenerarExcelRequest,
    ProcesoDocumentoBase,
    Proponente,
    ResultadoRequisito,
    VerDocumentoRequest,
)
from motor.evaluacion.todos import EVALUADORES_POR_REQUISITO, EvaluadorProponente, evaluar_proponente_todos
from motor.excel.filler import fill_template
from motor.integrations.drive import DriveAccessError, DriveConfigError, download_file_bytes, list_proponentes
from motor.parsers.documento_base import build_proceso
from motor.procesamiento.zip_utils import extraer_pdfs
from motor.workers import BrokenProcessPool, detener_pool, obtener_pool, obtener_pool_pesado

api = NinjaAPI(title="MiEvaluador API", version="1.0", urls_namespace="api")
# Toda la evaluación exige sesión iniciada (y CSRF en las peticiones que modifican).
procesos = Router(tags=["procesos"], auth=sesion_activa)

PLANTILLA_JURIDICA = Path(__file__).resolve().parent.parent / "motor" / "plantillas" / "plantilla_evaluacion_juridica.xlsx"

atexit.register(detener_pool)


@api.get("/health")
def health(request: HttpRequest) -> dict[str, str]:
    return {"status": "ok"}


@procesos.post("/analizar", response=AnalisisResponse)
async def analizar_documento_base(
    request: HttpRequest,
    codigo_proceso: Form[str],
    fecha_cierre: Form[date],
    archivo: File[UploadedFile],
    carpeta_drive: Form[str | None] = None,
) -> AnalisisResponse:
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


@procesos.post("/generar-excel")
async def generar_excel(request: HttpRequest, payload: GenerarExcelRequest) -> HttpResponse:
    if not PLANTILLA_JURIDICA.exists():
        raise HttpError(500, "No se encontró la plantilla de Excel en el servidor.")
    try:
        contenido = await asyncio.to_thread(
            fill_template, str(PLANTILLA_JURIDICA), payload.documento_base, payload.proponentes, payload.resultados
        )
    except Exception as exc:  # noqa: BLE001
        raise HttpError(500, f"No se pudo generar el Excel: {exc}") from exc

    nombre_archivo = f"INFORME EVALUACION JURIDICA {payload.documento_base.codigo_proceso}.xlsx"
    respuesta = HttpResponse(contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre_archivo}"'
    return respuesta


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
        if not payload.proponentes:
            raise HttpError(400, "No hay proponentes para evaluar.")
        resultados = await asyncio.gather(
            *(_evaluar_en_proceso(evaluador, p, payload.documento_base, numero) for p in payload.proponentes)
        )
        return sorted(resultados, key=lambda r: r.numero_orden)

    async def evaluar_individual(request: HttpRequest, payload: EvaluarProponenteRequest) -> ResultadoRequisito:
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


_CARRIL_PESADO: asyncio.Lock | None = None


def _carril_pesado() -> asyncio.Lock:
    # El candado se crea dentro del bucle de eventos que lo usa.
    global _CARRIL_PESADO
    if _CARRIL_PESADO is None:
        _CARRIL_PESADO = asyncio.Lock()
    return _CARRIL_PESADO


async def _evaluar_todos_en_proceso(proponente: Proponente, proceso: ProcesoDocumentoBase) -> list[ResultadoRequisito]:
    """Todos los requisitos de un proponente en un solo worker. Si el worker
    muere o algún requisito queda con error, se reintenta solo en el carril
    pesado y se conserva el intento con menos errores."""
    loop = asyncio.get_running_loop()

    def con_error(mensaje: str) -> list[ResultadoRequisito]:
        return [
            ResultadoRequisito(
                hoja=proponente.hoja,
                numero_orden=proponente.numero_orden,
                nombre_proponente=proponente.nombre_proponente,
                requisito=numero,
                error=mensaje,
            )
            for numero in EVALUADORES_POR_REQUISITO
        ]

    def errores(resultados: list[ResultadoRequisito]) -> int:
        return sum(1 for r in resultados if r.error)

    try:
        resultados = await loop.run_in_executor(obtener_pool(), evaluar_proponente_todos, proponente, proceso)
    except (BrokenProcessPool, MemoryError) as exc:
        resultados = con_error(
            f"No se pudo evaluar (el proceso murió, posiblemente por falta de memoria): {exc}. Revísalo manualmente."
        )
    except Exception as exc:  # noqa: BLE001
        resultados = con_error(f"No se pudo evaluar automáticamente: {exc}")

    if errores(resultados) == 0:
        return resultados

    async with _carril_pesado():
        try:
            reintento = await loop.run_in_executor(obtener_pool_pesado(), evaluar_proponente_todos, proponente, proceso)
        except Exception:  # noqa: BLE001
            return resultados
    return reintento if errores(reintento) < errores(resultados) else resultados


@procesos.post("/evaluar-todos/proponente", response=list[ResultadoRequisito])
async def evaluar_todos_proponente(request: HttpRequest, payload: EvaluarProponenteRequest) -> list[ResultadoRequisito]:
    return await _evaluar_todos_en_proceso(payload.proponente, payload.documento_base)


@procesos.post("/evaluar-todos", response=list[ResultadoRequisito])
async def evaluar_todos(request: HttpRequest, payload: EvaluarRequisitosRequest) -> list[ResultadoRequisito]:
    if not payload.proponentes:
        raise HttpError(400, "No hay proponentes para evaluar.")
    por_proponente = await asyncio.gather(*(_evaluar_todos_en_proceso(p, payload.documento_base) for p in payload.proponentes))
    return sorted((r for lista in por_proponente for r in lista), key=lambda r: (r.numero_orden, r.requisito))


@procesos.post("/proponentes/documento")
async def ver_documento(request: HttpRequest, payload: VerDocumentoRequest) -> HttpResponse:
    try:
        zip_bytes = await asyncio.to_thread(download_file_bytes, payload.drive_file_id)
    except Exception as exc:  # noqa: BLE001
        raise HttpError(502, f"No se pudo descargar el archivo de Drive: {exc}") from exc

    pdfs = await asyncio.to_thread(extraer_pdfs, zip_bytes)
    contenido = pdfs.get(payload.archivo_evaluado)
    if contenido is None:
        raise HttpError(404, "No se encontró ese documento dentro del archivo del proponente.")
    return HttpResponse(contenido, content_type="application/pdf")


api.add_router("/procesos", procesos)
api.add_router("/auth", auth_router)
api.add_router("/equipo", equipo)
api.add_router("/plataforma", plataforma)
