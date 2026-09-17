"""Evaluación de los requisitos de un proponente en una sola pasada.

Corre dentro de UN worker los 18 evaluadores seguidos sobre el mismo
proponente: el zip se descomprime una vez y el texto de cada página se
extrae una vez (ver app/procesamiento/memoria_proponente.py), en vez de
repetir todo ese trabajo por cada requisito."""
from __future__ import annotations

import gc
from collections.abc import Callable

from app.evaluacion.antecedentes import (
    evaluar_proponente_requisito5,
    evaluar_proponente_requisito14,
    evaluar_proponente_requisito15,
    evaluar_proponente_requisito16,
    evaluar_proponente_requisito17,
)
from app.evaluacion.camara_comercio import (
    evaluar_proponente_requisito6,
    evaluar_proponente_requisito7,
    evaluar_proponente_requisito8,
    evaluar_proponente_requisito9,
    evaluar_proponente_requisito10,
    evaluar_proponente_requisito18,
)
from app.evaluacion.copnia import evaluar_proponente_requisito2, evaluar_proponente_requisito3
from app.evaluacion.formato1 import evaluar_proponente
from app.evaluacion.garantia import evaluar_proponente_requisito11
from app.evaluacion.proponente_plural import evaluar_proponente_requisito4
from app.evaluacion.seguridad_social import evaluar_proponente_requisito12
from app.integrations import drive
from app.models.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from app.procesamiento import pdf_utils, zip_utils

EvaluadorProponente = Callable[[Proponente, ProcesoDocumentoBase], ResultadoRequisito]

# Un evaluador por requisito: recibe (proponente, proceso) y devuelve su
# ResultadoRequisito. Añadir un requisito nuevo es agregar una entrada aquí.
EVALUADORES_POR_REQUISITO: dict[int, EvaluadorProponente] = {
    1: evaluar_proponente,
    2: evaluar_proponente_requisito2,
    3: evaluar_proponente_requisito3,
    4: evaluar_proponente_requisito4,
    5: evaluar_proponente_requisito5,
    6: evaluar_proponente_requisito6,
    7: evaluar_proponente_requisito7,
    8: evaluar_proponente_requisito8,
    9: evaluar_proponente_requisito9,
    10: evaluar_proponente_requisito10,
    11: evaluar_proponente_requisito11,
    12: evaluar_proponente_requisito12,
    # 13 (RUT): el abogado indicó ignorarlo por completo. Sin resultado, la
    # fila del Excel queda como viene en la plantilla.
    14: evaluar_proponente_requisito14,
    15: evaluar_proponente_requisito15,
    16: evaluar_proponente_requisito16,
    17: evaluar_proponente_requisito17,
    18: evaluar_proponente_requisito18,
}


def liberar_memoria_proponente() -> None:
    """Suelta el zip, los PDF extraídos y el texto en memoria del proponente
    anterior. Sin esto, al empezar el siguiente convivían en el worker los
    documentos de los dos (se confirmó en la medición real: 4 proponentes
    pesados murieron por superar el tope de memoria del worker)."""
    zip_utils._ULTIMO_ZIP = None
    drive._ULTIMO_ZIP_LEIDO = None
    pdf_utils.limpiar_memoria_texto()
    gc.collect()


def evaluar_proponente_todos(proponente: Proponente, proceso: ProcesoDocumentoBase) -> list[ResultadoRequisito]:
    """Evalúa los 18 requisitos de un proponente. Un fallo en un requisito
    queda como error de ese requisito y no impide evaluar los demás."""
    liberar_memoria_proponente()
    try:
        return _evaluar_todos(proponente, proceso)
    finally:
        liberar_memoria_proponente()


def _evaluar_todos(proponente: Proponente, proceso: ProcesoDocumentoBase) -> list[ResultadoRequisito]:
    resultados = []
    for requisito, evaluador in EVALUADORES_POR_REQUISITO.items():
        try:
            resultados.append(evaluador(proponente, proceso))
        except MemoryError:
            raise
        except Exception as exc:  # noqa: BLE001
            resultados.append(
                ResultadoRequisito(
                    hoja=proponente.hoja,
                    numero_orden=proponente.numero_orden,
                    nombre_proponente=proponente.nombre_proponente,
                    requisito=requisito,
                    error=f"No se pudo evaluar automáticamente: {exc}",
                )
            )
    return resultados
