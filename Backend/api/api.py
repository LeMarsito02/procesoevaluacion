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
import json
from datetime import date
from pathlib import Path
from uuid import UUID

from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import FileResponse, HttpRequest
from ninja import File, Form, NinjaAPI, Router, Schema
from ninja.errors import HttpError, Throttled
from ninja.files import UploadedFile
from ninja.throttling import AnonRateThrottle, AuthRateThrottle

from api.auth import router as auth_router
from api.configuracion import router as configuracion_router
from api.equipo import equipo, plataforma
from api.evaluaciones import router as evaluaciones_router
from cuentas.seguridad import auditar, sesion_activa, ve_datos_de
from evaluaciones import pliego as pliego_servicio
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
from motor.pliego import lectura
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


# --- Kit de demostración ---
# En el equipo de la presentación hay una carpeta (settings.DEMO_KIT_DIR) con el
# Documento Base, las ofertas y un demo.json con la fecha de cierre. Al escribir
# un código «DEMO-…» en «Crear proceso», el formulario la pide aquí y se llena
# solo. Sin esa carpeta no hay kit y el formulario funciona como siempre.
_EXTENSIONES_OFERTA = (".zip", ".rar", ".7z")


def _kit_demo() -> tuple[Path, dict] | None:
    carpeta = Path(settings.DEMO_KIT_DIR)
    if not (carpeta / "pliego.pdf").is_file() or not (carpeta / "ofertas").is_dir():
        return None
    try:
        info = json.loads((carpeta / "demo.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    return carpeta, info


def _ofertas_del_kit(carpeta: Path) -> list[str]:
    return sorted(p.name for p in (carpeta / "ofertas").iterdir() if p.is_file() and p.suffix.lower() in _EXTENSIONES_OFERTA)


@procesos.get("/demo-kit")
def demo_kit(request: HttpRequest) -> dict:
    if not puede_crear_procesos(request.auth):
        raise HttpError(403, "Su rol no permite crear procesos.")
    kit = _kit_demo()
    if kit is None:
        return {"disponible": False}
    carpeta, info = kit
    return {"disponible": True, "fecha_cierre": info.get("fecha_cierre"), "ofertas": _ofertas_del_kit(carpeta)}


@procesos.get("/demo-kit/archivo")
def demo_kit_archivo(request: HttpRequest, nombre: str) -> FileResponse:
    if not puede_crear_procesos(request.auth):
        raise HttpError(403, "Su rol no permite crear procesos.")
    kit = _kit_demo()
    if kit is None:
        raise HttpError(404, "No hay kit de demostración en este equipo.")
    carpeta, _ = kit
    # Solo lo que está en el kit, por nombre exacto: nada de rutas.
    if nombre == "pliego.pdf":
        ruta = carpeta / "pliego.pdf"
    elif nombre in _ofertas_del_kit(carpeta):
        ruta = carpeta / "ofertas" / nombre
    else:
        raise HttpError(404, "Ese archivo no está en el kit de demostración.")
    return FileResponse(ruta.open("rb"), as_attachment=False, filename=ruta.name)


# Cuánto se acepta en una sola carga de ofertas. Una oferta de obra pesa entre 20
# y 80 MB, así que esto da para unas veinte; si son más, se suben en varias veces.
LIMITE_OFERTAS_SUBIDAS = 2_000_000_000


@procesos.post("/analizar", response=AnalisisResponse, throttle=[AuthRateThrottle(settings.LIMITES_API["pesado"])])
async def analizar_documento_base(
    request: HttpRequest,
    codigo_proceso: Form[str],
    fecha_cierre: Form[date],
    archivo: File[UploadedFile],
    carpeta_drive: Form[str | None] = None,
    # Las ofertas subidas a mano, cuando no están en una carpeta compartida sino
    # en el disco (bajadas del SECOP una por una, por ejemplo).
    ofertas: File[list[UploadedFile] | None] = None,
    # Solo para el superadministrador, que elige en qué entidad crea el proceso.
    entidad_id: Form[UUID | None] = None,
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
        proceso = await asyncio.to_thread(build_proceso, codigo_proceso.strip().upper(), fecha_cierre, pdf_bytes)
    except Exception as exc:  # noqa: BLE001
        raise HttpError(422, f"No se pudo analizar el Documento Base: {exc}") from exc

    pliego, pliego_error = await _analizar_pliego(request, pdf_bytes, archivo.name or "pliego.pdf", entidad_id)

    proponentes: list[Proponente] = []
    no_reconocidos: list[str] = []
    drive_error: str | None = None
    if ofertas:
        from motor.integrations import ofertas_locales

        subidas = [(o.name or "sin nombre", o.read()) for o in ofertas]
        total = sum(len(c) for _, c in subidas)
        if total > LIMITE_OFERTAS_SUBIDAS:
            raise HttpError(413, f"Las ofertas pesan {total / 1e6:.0f} MB en total; el máximo por carga es "
                                 f"{LIMITE_OFERTAS_SUBIDAS / 1e6:.0f} MB. Súbelas en varias veces.")
        resultado_local = await asyncio.to_thread(ofertas_locales.desde_archivos, subidas)
        proponentes = resultado_local.proponentes
        no_reconocidos = resultado_local.no_reconocidos
    elif carpeta_drive and carpeta_drive.strip():
        try:
            directorio = await asyncio.to_thread(_directorio_microsoft, request.auth, entidad_id)
            resultado = await asyncio.to_thread(list_proponentes, carpeta_drive.strip(), directorio)
            proponentes = resultado.proponentes
            no_reconocidos = resultado.no_reconocidos
        except (DriveConfigError, DriveAccessError, ValueError) as exc:
            drive_error = str(exc)

    return AnalisisResponse(
        documento_base=proceso,
        proponentes=proponentes,
        proponentes_no_reconocidos=no_reconocidos,
        drive_error=drive_error,
        pliego=pliego,
        pliego_error=pliego_error,
    )


def _directorio_microsoft(usuario, entidad_id: UUID | None) -> str | None:
    """Directorio de Microsoft de la entidad en la que se crea el proceso: solo
    se leen enlaces de OneDrive de Microsoft 365 de ese directorio."""
    from cuentas.models import Entidad

    destino = usuario.entidad_id if not usuario.es_superadmin else entidad_id
    entidad = Entidad.objects.filter(pk=destino).first() if destino else None
    return entidad.microsoft_directorio or None if entidad else None


# --- Proceso a medio crear: la lectura va en segundo plano y queda guardada ---
def _preparacion_out(p) -> dict:
    return {
        "id": str(p.id), "codigo": p.codigo, "fecha_cierre": p.fecha_cierre.isoformat(), "carpeta_drive": p.carpeta_drive,
        "nombre_archivo": p.nombre_archivo, "ofertas_subidas": p.ofertas_subidas is not None,
        "estado": p.estado, "etapa": p.etapa, "progreso": p.progreso, "error": p.error,
        "creada_en": p.creada_en.isoformat(), "iniciada_en": p.iniciada_en.isoformat() if p.iniciada_en else None,
        "entidad_id": str(p.entidad_id), "resultado": p.resultado,
    }


def _preparacion_propia(request: HttpRequest, preparacion_id: UUID):
    from django.shortcuts import get_object_or_404

    from evaluaciones.models import PreparacionProceso

    return get_object_or_404(PreparacionProceso, pk=preparacion_id, creada_por=request.auth)


# --- Subida de ofertas por pedazos (hasta 10 GB por archivo, se retoma si se corta) ---
class SubidaIn(Schema):
    nombre: str
    tamano: int
    # Huella rápida del archivo (frontend/src/huella.ts): si ya se subió y repartió, no se sube otra vez.
    huella: str | None = None


def _subida_out(x) -> dict:
    return {"id": x.id, "nombre": x.nombre, "tamano": x.tamano, "recibido": x.recibido, "completa": x.completa,
            "reutilizada": x.reuso is not None, "ofertas": len(x.reuso["partes"]) if x.reuso else None}


def _subida_o_error(funcion, *args):
    from evaluaciones import subidas as subidas_servicio

    try:
        return funcion(*args)
    except subidas_servicio.ErrorSubida as exc:
        raise HttpError(exc.codigo, str(exc)) from exc


@procesos.post("/subidas")
def crear_subida(request: HttpRequest, datos: SubidaIn) -> dict:
    from evaluaciones import subidas as subidas_servicio

    if not puede_crear_procesos(request.auth):
        raise HttpError(403, "Su rol no permite crear procesos.")
    return _subida_out(_subida_o_error(subidas_servicio.crear, request.auth.id, datos.nombre, datos.tamano, datos.huella,
                                       _entidad_de_carga(request)))


def _entidad_de_carga(request: HttpRequest, entidad_id: UUID | None = None):
    usuario = request.auth
    return usuario.entidad_id if not usuario.es_superadmin else (entidad_id if ve_datos_de(usuario, entidad_id) else None)


@procesos.get("/cargas")
def listar_cargas(request: HttpRequest, entidad_id: UUID | None = None) -> list[dict]:
    """Las ofertas subidas desde el equipo que quedaron guardadas en el servidor
    (se reutilizan si se elige el mismo archivo)."""
    from evaluaciones import subidas as subidas_servicio

    entidad = _entidad_de_carga(request, entidad_id)
    return subidas_servicio.cargas_de(entidad) if entidad else []


@procesos.get("/cargas/{huella}")
def ver_carga(request: HttpRequest, huella: str, tamano: int, entidad_id: UUID | None = None) -> dict:
    """Si un archivo (por su huella) ya está guardado en el servidor."""
    from evaluaciones import subidas as subidas_servicio

    entidad = _entidad_de_carga(request, entidad_id)
    carga = subidas_servicio.buscar_carga(huella, tamano, entidad) if entidad else None
    return {"guardada": carga is not None, "ofertas": len(carga["partes"]) if carga else 0}


@procesos.delete("/cargas/{huella}")
def eliminar_carga(request: HttpRequest, huella: str, entidad_id: UUID | None = None) -> dict:
    from evaluaciones import subidas as subidas_servicio

    if not puede_crear_procesos(request.auth):
        raise HttpError(403, "Su rol no permite crear procesos.")
    entidad = _entidad_de_carga(request, entidad_id)
    borradas = _subida_o_error(subidas_servicio.eliminar_carga, huella, entidad)
    auditar(request, "ofertas.carga_eliminada", entidad_id=entidad, huella=huella[:16], ofertas_borradas=borradas)
    return {"ofertas_borradas": borradas}


@procesos.get("/subidas/{subida_id}")
def ver_subida(request: HttpRequest, subida_id: str) -> dict:
    from evaluaciones import subidas as subidas_servicio

    return _subida_out(_subida_o_error(subidas_servicio.ver, subida_id, request.auth.id))


@procesos.put("/subidas/{subida_id}")
def agregar_a_subida(request: HttpRequest, subida_id: str, desde: int) -> dict:
    """Un pedazo del archivo, en el cuerpo de la petición (application/octet-stream)."""
    from evaluaciones import subidas as subidas_servicio

    return _subida_out(_subida_o_error(subidas_servicio.agregar, subida_id, request.auth.id, desde, request.body))


@procesos.delete("/subidas/{subida_id}", response={204: None})
def eliminar_subida(request: HttpRequest, subida_id: str):
    from evaluaciones import subidas as subidas_servicio

    _subida_o_error(subidas_servicio.ver, subida_id, request.auth.id)
    subidas_servicio.borrar(subida_id)
    return 204, None


@procesos.post("/preparaciones", throttle=[AuthRateThrottle(settings.LIMITES_API["pesado"])])
def crear_preparacion(
    request: HttpRequest,
    codigo_proceso: Form[str],
    fecha_cierre: Form[date],
    archivo: File[UploadedFile],
    carpeta_drive: Form[str | None] = None,
    ofertas: File[list[UploadedFile] | None] = None,
    entidad_id: Form[UUID | None] = None,
    # Ofertas ya subidas por pedazos (/procesos/subidas): las reparte el trabajador.
    subidas: Form[list[str] | None] = None,
) -> dict:
    """Guarda lo que subió la persona y pone la lectura en la fila. Responde
    al instante; el avance se consulta con GET."""
    from evaluaciones.models import PreparacionProceso
    from motor.integrations import ofertas_locales

    usuario = request.auth
    if not puede_crear_procesos(usuario):
        raise HttpError(403, "Su rol no permite crear procesos.")
    entidad = usuario.entidad_id if not usuario.es_superadmin else (entidad_id if ve_datos_de(usuario, entidad_id) else None)
    if entidad is None:
        raise HttpError(400, "Elija la entidad en la que se crea el proceso.")
    nombre = (archivo.name or "").lower()
    if archivo.content_type not in ("application/pdf", "application/octet-stream") and not nombre.endswith(".pdf"):
        raise HttpError(400, "El Documento Base debe ser un PDF.")
    pdf = archivo.read()
    if not pdf:
        raise HttpError(400, "El PDF del Documento Base está vacío.")
    guardadas = None
    if subidas:
        # Ofertas subidas por pedazos: completas y de esta persona. Las reparte
        # el trabajador desde el disco (pueden ser 10 GB por archivo).
        from evaluaciones import subidas as subidas_servicio

        listas = [_subida_o_error(subidas_servicio.ver, x, usuario.id) for x in subidas]
        incompletas = [x.nombre for x in listas if not x.completa]
        if incompletas:
            raise HttpError(409, f"Aún no termina de subir: {', '.join(incompletas)}.")
        if sum(x.tamano for x in listas) > settings.SUBIDA_MAXIMA_CARGA:
            raise HttpError(413, f"Las ofertas pasan de {settings.SUBIDA_MAXIMA_CARGA / 1024**3:.0f} GB en total: súbalas en dos procesos o use una carpeta compartida.")
        guardadas = {"pendientes": [{"id": x.id, "nombre": x.nombre, "tamano": x.tamano, "reuso": x.reuso} for x in listas]}
    elif ofertas:
        contenidos = [(o.name or "sin nombre", o.read()) for o in ofertas]
        total = sum(len(c) for _, c in contenidos)
        if total > LIMITE_OFERTAS_SUBIDAS:
            raise HttpError(413, f"Las ofertas pesan {total / 1e6:.0f} MB en total; el máximo por carga es "
                                 f"{LIMITE_OFERTAS_SUBIDAS / 1e6:.0f} MB. Súbelas en varias veces.")
        r = ofertas_locales.desde_archivos(contenidos)
        guardadas = {"proponentes": [x.model_dump(mode="json") for x in r.proponentes], "no_reconocidos": r.no_reconocidos}
    from django.core.files.base import ContentFile

    p = PreparacionProceso(
        entidad_id=entidad, creada_por=usuario, codigo=codigo_proceso.strip().upper(), fecha_cierre=fecha_cierre,
        carpeta_drive=(carpeta_drive or "").strip(), nombre_archivo=archivo.name or "documento_base.pdf", ofertas_subidas=guardadas,
        etapa="En fila para leer",
    )
    p.archivo.save("documento_base.pdf", ContentFile(pdf), save=False)
    p.save()
    return _preparacion_out(p)


@procesos.get("/preparaciones")
def listar_preparaciones(request: HttpRequest) -> list[dict]:
    """Los procesos que la persona dejó a medio crear (los más recientes primero)."""
    from evaluaciones.models import PreparacionProceso

    return [{k: v for k, v in _preparacion_out(p).items() if k != "resultado"}
            for p in PreparacionProceso.objects.filter(creada_por=request.auth)[:10]]


@procesos.get("/preparaciones/{preparacion_id}")
def ver_preparacion(request: HttpRequest, preparacion_id: UUID) -> dict:
    return _preparacion_out(_preparacion_propia(request, preparacion_id))


@procesos.post("/preparaciones/{preparacion_id}/reintentar")
def reintentar_preparacion(request: HttpRequest, preparacion_id: UUID) -> dict:
    from evaluaciones.models import PreparacionProceso

    p = _preparacion_propia(request, preparacion_id)
    p.estado, p.error, p.progreso, p.etapa, p.resultado = PreparacionProceso.PENDIENTE, "", 0, "En fila para leer", None
    p.save(update_fields=["estado", "error", "progreso", "etapa", "resultado"])
    return _preparacion_out(p)


@procesos.delete("/preparaciones/{preparacion_id}", response={204: None})
def eliminar_preparacion(request: HttpRequest, preparacion_id: UUID):
    from evaluaciones import preparacion

    preparacion.borrar(_preparacion_propia(request, preparacion_id))
    return 204, None


@procesos.post("/pliego", throttle=[AuthRateThrottle(settings.LIMITES_API["pesado"])])
async def analizar_pliego(
    request: HttpRequest, archivo: File[UploadedFile], entidad_id: Form[UUID | None] = None
) -> dict:
    """Solo el pliego, cuando la entidad se elige después de leer el documento
    base (el superadministrador). Si el mismo PDF ya se leyó, se reutiliza."""
    if not puede_crear_procesos(request.auth):
        raise HttpError(403, "Su rol no permite crear procesos.")
    contenido = archivo.read()
    if not contenido:
        raise HttpError(400, "El archivo PDF está vacío.")
    pliego, error = await _analizar_pliego(request, contenido, archivo.name or "pliego.pdf", entidad_id)
    if pliego is None:
        raise HttpError(422, error or "No se pudo analizar el pliego.")
    return pliego


async def _analizar_pliego(
    request: HttpRequest, pdf_bytes: bytes, nombre: str, entidad_id: UUID | None
) -> tuple[dict | None, str | None]:
    """Lee el pliego completo (o reutiliza la lectura del mismo PDF) y lo
    compara con la evaluación de la entidad. La lectura corre en otro hilo; la
    base de datos solo se toca desde el hilo de la petición, que es el que
    tiene fijada la entidad para el aislamiento."""
    usuario = request.auth
    entidad = usuario.entidad_id if not usuario.es_superadmin else (entidad_id if ve_datos_de(usuario, entidad_id) else None)
    if entidad is None:
        return None, "Elija la entidad para analizar el pliego contra su forma de evaluar."
    try:
        sha = lectura.huella(pdf_bytes)
        analisis = await sync_to_async(pliego_servicio.vigente)(entidad, sha)
        reutilizado = analisis is not None
        if analisis is None:
            extraccion = await asyncio.to_thread(pliego_servicio.leer, pdf_bytes)
            analisis = await sync_to_async(pliego_servicio.guardar)(entidad, pdf_bytes, nombre, extraccion, usuario)
        payload = await sync_to_async(_payload_pliego)(analisis, reutilizado)
    except Exception as exc:  # noqa: BLE001
        return None, f"No se pudo analizar el pliego completo: {exc}"
    return payload, None


_payload_pliego = pliego_servicio.payload_creacion


@procesos.get("/pliego/{analisis_id}/archivo")
def ver_pliego_analizado(request: HttpRequest, analisis_id: UUID, entidad_id: UUID | None = None):
    """El PDF del pliego que se acaba de subir, para verlo dentro de la
    plataforma.

    Existe para que quien crea el proceso pueda comprobar en el pliego mismo lo
    que el programa leyó —y corregir lo que no pudo leer— sin buscar a mano en
    noventa páginas: la pantalla lo abre en la página donde está cada dato."""
    from django.http import FileResponse

    from evaluaciones.models import AnalisisPliego

    if not puede_crear_procesos(request.auth):
        raise HttpError(403, "Su rol no permite crear procesos.")
    usuario = request.auth
    entidad = usuario.entidad_id if not usuario.es_superadmin else (entidad_id if ve_datos_de(usuario, entidad_id) else None)
    analisis = AnalisisPliego.objects.filter(pk=analisis_id, entidad_id=entidad).first()
    if analisis is None or not analisis.archivo:
        raise HttpError(404, "No se encontró el pliego.")
    # El visor del pliego lo incrusta en la página: con el DENY por defecto de
    # Django el navegador mostraba «localhost refused to connect».
    respuesta = FileResponse(analisis.archivo.open("rb"), content_type="application/pdf", filename=analisis.nombre_archivo)
    respuesta["X-Frame-Options"] = "SAMEORIGIN"
    return respuesta


@procesos.get("/pliego/{analisis_id}")
async def estado_pliego(request: HttpRequest, analisis_id: UUID, entidad_id: UUID | None = None) -> dict:
    """El análisis del pliego con el avance de la lectura con IA: la pantalla
    lo consulta hasta que la IA termina y entonces muestra los hallazgos
    completos."""
    from evaluaciones.models import AnalisisPliego

    usuario = request.auth
    entidad = usuario.entidad_id if not usuario.es_superadmin else (entidad_id if ve_datos_de(usuario, entidad_id) else None)
    analisis = await sync_to_async(lambda: AnalisisPliego.objects.filter(pk=analisis_id, entidad_id=entidad).first())()
    if analisis is None:
        raise HttpError(404, "No se encontró el análisis del pliego.")
    return await sync_to_async(_payload_pliego)(analisis, True)


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
from api.transparencia import router as transparencia_router  # noqa: E402

api.add_router("/acerca", transparencia_router)
from api.metricas import router as metricas_router  # noqa: E402

api.add_router("/metricas", metricas_router)
from api.estructura import router as estructura_router  # noqa: E402

api.add_router("/estructura", estructura_router)
from api.asistente import router as asistente_router  # noqa: E402

api.add_router("/asistente", asistente_router)
from api.ops import router as ops_router  # noqa: E402

api.add_router("/ops", ops_router)
from api.tramite import router as tramite_router  # noqa: E402

api.add_router("/tramite", tramite_router)
from api.economica import router as economica_router  # noqa: E402

api.add_router("/economica", economica_router)
from api.coincidencias import router as coincidencias_router  # noqa: E402

api.add_router("/coincidencias", coincidencias_router)
