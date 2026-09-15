from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app.evaluacion.antecedentes import (
    evaluar_proponente_requisito5,
    evaluar_proponente_requisito14,
    evaluar_proponente_requisito15,
    evaluar_proponente_requisito16,
    evaluar_proponente_requisito17,
)
from app.evaluacion.copnia import evaluar_proponente_requisito2, evaluar_proponente_requisito3
from app.evaluacion.formato1 import evaluar_proponente
from app.evaluacion.proponente_plural import evaluar_proponente_requisito4
from app.evaluacion.trivial import evaluar_proponente_requisito13
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
from app.workers import BrokenProcessPool, obtener_pool

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


EvaluadorProponente = Callable[[Proponente, ProcesoDocumentoBase], ResultadoRequisito]


async def _evaluar_en_proceso(
    evaluador: EvaluadorProponente, proponente: Proponente, proceso: ProcesoDocumentoBase
) -> ResultadoRequisito:
    """Corre la evaluación en el pool de procesos (CPU real, no solo hilos).
    Si el pool se rompió (ej. un worker murió con un PDF corrupto), se
    recrea y se reintenta una vez antes de rendirse."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(obtener_pool(), evaluador, proponente, proceso)
    except BrokenProcessPool:
        return await loop.run_in_executor(obtener_pool(), evaluador, proponente, proceso)


# Un evaluador por requisito: recibe (proponente, proceso) y devuelve su
# ResultadoRequisito. Añadir un requisito nuevo es agregar una entrada aquí —
# las rutas /evaluar-requisito-N y /evaluar-requisito-N/proponente se generan
# solas más abajo, sin duplicar código por cada uno.
EVALUADORES_POR_REQUISITO: dict[int, EvaluadorProponente] = {
    1: evaluar_proponente,
    2: evaluar_proponente_requisito2,
    3: evaluar_proponente_requisito3,
    4: evaluar_proponente_requisito4,
    5: evaluar_proponente_requisito5,
    13: evaluar_proponente_requisito13,
    14: evaluar_proponente_requisito14,
    15: evaluar_proponente_requisito15,
    16: evaluar_proponente_requisito16,
    17: evaluar_proponente_requisito17,
}


def _registrar_rutas_requisito(numero: int, evaluador: EvaluadorProponente) -> None:
    async def evaluar_batch(payload: EvaluarRequisitosRequest) -> list[ResultadoRequisito]:
        if not payload.proponentes:
            raise HTTPException(status_code=400, detail="No hay proponentes para evaluar.")
        resultados = await asyncio.gather(
            *(_evaluar_en_proceso(evaluador, p, payload.documento_base) for p in payload.proponentes)
        )
        return sorted(resultados, key=lambda r: r.numero_orden)

    async def evaluar_individual(payload: EvaluarProponenteRequest) -> ResultadoRequisito:
        return await _evaluar_en_proceso(evaluador, payload.proponente, payload.documento_base)

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
