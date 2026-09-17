from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app.evaluacion.todos import EVALUADORES_POR_REQUISITO, EvaluadorProponente, evaluar_proponente_todos
from app.excel.filler import fill_template
from app.integrations.drive import DriveAccessError, DriveConfigError, download_file_bytes, list_proponentes
from app.models.proceso import (
    AnalisisResponse,
    EvaluarProponenteRequest,
    EvaluarRequisitosRequest,
    GenerarExcelRequest,
    ProcesoDocumentoBase,
    Proponente,
    ResultadoRequisito,
    VerDocumentoRequest,
)
from app.parsers.documento_base import build_proceso
from app.procesamiento.zip_utils import extraer_pdfs
from app.workers import BrokenProcessPool, obtener_pool, obtener_pool_pesado

router = APIRouter(prefix="/api/procesos", tags=["procesos"])

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "plantilla_evaluacion_juridica.xlsx"


@router.post("/analizar", response_model=AnalisisResponse)
async def analizar_documento_base(
    codigo_proceso: str = Form(...),
    fecha_cierre: date = Form(...),
    archivo: UploadFile = File(...),
    carpeta_drive: str | None = Form(default=None),
) -> AnalisisResponse:
    if archivo.content_type not in ("application/pdf", "application/octet-stream") and not archivo.filename.lower().endswith(
        ".pdf"
    ):
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF.")

    pdf_bytes = await archivo.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="El archivo PDF está vacío.")

    try:
        proceso = await run_in_threadpool(build_proceso, codigo_proceso.strip(), fecha_cierre, pdf_bytes)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"No se pudo analizar el Documento Base: {exc}") from exc

    proponentes: list[Proponente] = []
    no_reconocidos: list[str] = []
    drive_error: str | None = None

    if carpeta_drive and carpeta_drive.strip():
        try:
            resultado = await run_in_threadpool(list_proponentes, carpeta_drive.strip())
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


@router.post("/generar-excel")
async def generar_excel(payload: GenerarExcelRequest) -> Response:
    if not TEMPLATE_PATH.exists():
        raise HTTPException(status_code=500, detail="No se encontró la plantilla de Excel en el servidor.")

    try:
        contenido = await run_in_threadpool(
            fill_template,
            str(TEMPLATE_PATH),
            payload.documento_base,
            payload.proponentes,
            payload.resultados,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"No se pudo generar el Excel: {exc}") from exc

    nombre_archivo = f"INFORME EVALUACION JURIDICA {payload.documento_base.codigo_proceso}.xlsx"
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )




async def _evaluar_en_proceso(
    evaluador: EvaluadorProponente, proponente: Proponente, proceso: ProcesoDocumentoBase, requisito: int
) -> ResultadoRequisito:
    """Corre la evaluación en el pool de procesos (CPU real, no solo hilos).

    Ningún fallo de un proponente puede tumbar la evaluación de los demás:
    si el pool se rompió (un worker murió con un PDF corrupto) se recrea y
    se reintenta una vez, y si aun así falla —o si el worker se quedó sin
    memoria con un proponente especialmente pesado— se devuelve un
    ResultadoRequisito con `error`, que la interfaz muestra como "revisar
    manualmente". Antes, una sola excepción aquí devolvía un 500 y se
    perdía el lote completo de 81 proponentes."""
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
    async def evaluar_batch(payload: EvaluarRequisitosRequest) -> list[ResultadoRequisito]:
        if not payload.proponentes:
            raise HTTPException(status_code=400, detail="No hay proponentes para evaluar.")
        resultados = await asyncio.gather(
            *(_evaluar_en_proceso(evaluador, p, payload.documento_base, numero) for p in payload.proponentes)
        )
        return sorted(resultados, key=lambda r: r.numero_orden)

    async def evaluar_individual(payload: EvaluarProponenteRequest) -> ResultadoRequisito:
        return await _evaluar_en_proceso(evaluador, payload.proponente, payload.documento_base, numero)

    router.add_api_route(
        f"/evaluar-requisito-{numero}",
        evaluar_batch,
        methods=["POST"],
        response_model=list[ResultadoRequisito],
        name=f"evaluar_requisito_{numero}",
    )
    router.add_api_route(
        f"/evaluar-requisito-{numero}/proponente",
        evaluar_individual,
        methods=["POST"],
        response_model=ResultadoRequisito,
        name=f"evaluar_requisito_{numero}_proponente",
    )


for _numero, _evaluador in EVALUADORES_POR_REQUISITO.items():
    _registrar_rutas_requisito(_numero, _evaluador)


_CARRIL_PESADO = asyncio.Lock()


async def _evaluar_todos_en_proceso(proponente: Proponente, proceso: ProcesoDocumentoBase) -> list[ResultadoRequisito]:
    """Los 18 requisitos de un proponente en un solo worker (ver
    app/evaluacion/todos.py). Si el worker muere (normalmente por memoria) o
    algún requisito queda con error, se reintenta el proponente SOLO en el
    carril pesado (un worker, más memoria, sin otra evaluación al lado) y se
    conserva el intento con menos errores. Nunca tumba la evaluación de los
    demás: en el peor caso cada requisito queda con `error` para revisión."""
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

    async with _CARRIL_PESADO:
        try:
            reintento = await loop.run_in_executor(obtener_pool_pesado(), evaluar_proponente_todos, proponente, proceso)
        except Exception:  # noqa: BLE001
            return resultados
    return reintento if errores(reintento) < errores(resultados) else resultados


@router.post("/evaluar-todos/proponente", response_model=list[ResultadoRequisito])
async def evaluar_todos_proponente(payload: EvaluarProponenteRequest) -> list[ResultadoRequisito]:
    return await _evaluar_todos_en_proceso(payload.proponente, payload.documento_base)


@router.post("/evaluar-todos", response_model=list[ResultadoRequisito])
async def evaluar_todos(payload: EvaluarRequisitosRequest) -> list[ResultadoRequisito]:
    if not payload.proponentes:
        raise HTTPException(status_code=400, detail="No hay proponentes para evaluar.")
    por_proponente = await asyncio.gather(
        *(_evaluar_todos_en_proceso(p, payload.documento_base) for p in payload.proponentes)
    )
    return sorted((r for lista in por_proponente for r in lista), key=lambda r: (r.numero_orden, r.requisito))


@router.post("/proponentes/documento")
async def ver_documento(payload: VerDocumentoRequest) -> Response:
    try:
        zip_bytes = await run_in_threadpool(download_file_bytes, payload.drive_file_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"No se pudo descargar el archivo de Drive: {exc}") from exc

    pdfs = await run_in_threadpool(extraer_pdfs, zip_bytes)
    contenido = pdfs.get(payload.archivo_evaluado)
    if contenido is None:
        raise HTTPException(status_code=404, detail="No se encontró ese documento dentro del archivo del proponente.")

    return Response(content=contenido, media_type="application/pdf")
