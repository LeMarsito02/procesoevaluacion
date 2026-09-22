"""Ejecución del motor de evaluación en el pool de procesos, con reintento
en el carril pesado. La usan la API y las evaluaciones guardadas."""
from __future__ import annotations

import asyncio

from motor.esquemas.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from motor.evaluacion.todos import EVALUADORES_POR_REQUISITO, evaluar_proponente_todos
from motor.workers import BrokenProcessPool, obtener_pool, obtener_pool_pesado


_CARRIL_PESADO: asyncio.Lock | None = None


def _carril_pesado() -> asyncio.Lock:
    # El candado se crea dentro del bucle de eventos que lo usa.
    global _CARRIL_PESADO
    if _CARRIL_PESADO is None:
        _CARRIL_PESADO = asyncio.Lock()
    return _CARRIL_PESADO


async def evaluar_todos_en_proceso(proponente: Proponente, proceso: ProcesoDocumentoBase) -> list[ResultadoRequisito]:
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
            for numero in ([r["numero"] for r in (proceso.criterios or {}).get("requisitos", [])] or EVALUADORES_POR_REQUISITO)
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
