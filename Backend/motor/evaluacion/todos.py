"""Evaluación de los requisitos de un proponente en una sola pasada.

Corre dentro de UN worker los 18 evaluadores seguidos sobre el mismo
proponente: el zip se descomprime una vez y el texto de cada página se
extrae una vez (ver app/procesamiento/memoria_proponente.py), en vez de
repetir todo ese trabajo por cada requisito."""
from __future__ import annotations

import gc
from collections.abc import Callable

from motor.evaluacion.antecedentes import (
    evaluar_proponente_requisito5,
    evaluar_proponente_requisito14,
    evaluar_proponente_requisito15,
    evaluar_proponente_requisito16,
    evaluar_proponente_requisito17,
)
from motor.evaluacion.camara_comercio import (
    evaluar_proponente_requisito6,
    evaluar_proponente_requisito7,
    evaluar_proponente_requisito8,
    evaluar_proponente_requisito9,
    evaluar_proponente_requisito10,
    evaluar_proponente_requisito18,
)
from motor.evaluacion.copnia import evaluar_proponente_requisito2, evaluar_proponente_requisito3
from motor.evaluacion.formato1 import evaluar_proponente
from motor.evaluacion.garantia import evaluar_proponente_requisito11
from motor.evaluacion.personalizado import evaluar_requisito_personalizado
from motor.evaluacion.proponente_plural import evaluar_proponente_requisito4
from motor.evaluacion.seguridad_social import evaluar_proponente_requisito12
from motor import criterios
from motor.integrations import drive
from motor.esquemas.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from motor.procesamiento import pdf_utils, zip_utils

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
    """Evalúa los requisitos de un proponente. Un fallo en un requisito
    queda como error de ese requisito y no impide evaluar los demás."""
    liberar_memoria_proponente()
    try:
        if proceso.criterios is None:
            return _evaluar_todos(proponente, proceso)
        definicion = criterios.DefinicionEvaluacion.model_validate(proceso.criterios)
        with criterios.usar(definicion.parametros):
            return _evaluar_definicion(proponente, proceso, definicion)
    finally:
        liberar_memoria_proponente()


def _con_error(proponente: Proponente, requisito: int, exc: Exception) -> ResultadoRequisito:
    return ResultadoRequisito(
        hoja=proponente.hoja,
        numero_orden=proponente.numero_orden,
        nombre_proponente=proponente.nombre_proponente,
        requisito=requisito,
        error=f"No se pudo evaluar automáticamente: {exc}",
    )


def _evaluar_todos(proponente: Proponente, proceso: ProcesoDocumentoBase) -> list[ResultadoRequisito]:
    resultados = []
    for requisito, evaluador in EVALUADORES_POR_REQUISITO.items():
        try:
            resultados.append(evaluador(proponente, proceso))
        except MemoryError:
            raise
        except Exception as exc:  # noqa: BLE001
            resultados.append(_con_error(proponente, requisito, exc))
    return resultados


def _evaluar_definicion(
    proponente: Proponente, proceso: ProcesoDocumentoBase, definicion: criterios.DefinicionEvaluacion
) -> list[ResultadoRequisito]:
    """Requisitos en el orden y con la numeración de la entidad: verificaciones
    del motor (reutilizadas tal cual) o requisitos armados con bloques."""
    resultados = []
    for req in definicion.requisitos:
        try:
            resultados.append(evaluar_requisito(proponente, proceso, req))
        except MemoryError:
            raise
        except Exception as exc:  # noqa: BLE001
            resultados.append(_con_error(proponente, req.numero, exc))
    return resultados


def evaluar_requisito(
    proponente: Proponente, proceso: ProcesoDocumentoBase, req: criterios.RequisitoDefinicion
) -> ResultadoRequisito:
    if req.verificacion == criterios.PERSONALIZADO:
        return evaluar_requisito_personalizado(proponente, proceso, req)
    if req.verificacion == criterios.MANUAL:
        return ResultadoRequisito(
            hoja=proponente.hoja,
            numero_orden=proponente.numero_orden,
            nombre_proponente=proponente.nombre_proponente,
            requisito=req.numero,
            cumple=False,
            motivo=f"Verificación manual que exige el pliego: {req.verifica}",
        )
    interno = criterios.VERIFICACIONES[req.verificacion].numero_interno
    resultado = EVALUADORES_POR_REQUISITO[interno](proponente, proceso)
    # Los resultados cacheados son objetos compartidos: se copia antes de renumerar.
    return resultado.model_copy(update={"requisito": req.numero})


def probar_requisito(
    proponente: Proponente, proceso: ProcesoDocumentoBase, req: dict, parametros: dict
) -> ResultadoRequisito:
    """Evalúa un solo requisito (para probar uno nuevo antes de activarlo)."""
    liberar_memoria_proponente()
    try:
        with criterios.usar(parametros):
            return evaluar_requisito(proponente, proceso, criterios.RequisitoDefinicion.model_validate(req))
    except Exception as exc:  # noqa: BLE001
        return _con_error(proponente, req.get("numero", 0), exc)
    finally:
        liberar_memoria_proponente()
