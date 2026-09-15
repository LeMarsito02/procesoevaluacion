from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

# Un pool de procesos separado (no hilos) para el trabajo de CPU de verdad
# (parsear PDFs con pdfplumber es Python puro y no se paraleliza entre hilos
# por el GIL). Se crea una sola vez al arrancar el servidor: la primera tanda
# paga el costo de que cada proceso importe pdfplumber/googleapiclient, las
# siguientes ya lo reutilizan.
#
# El límite real no es la CPU sino la RAM: cada worker puede tener en
# memoria a la vez un zip de proponente de hasta ~200 MB. En una máquina de
# escritorio normal (con Chrome, el IDE, etc. ya usando varios GB) 8 workers
# en paralelo puede saturar la RAM y colgar el sistema, así que se limita a
# un número más conservador aunque haya más núcleos disponibles.
MAX_WORKERS = min(os.cpu_count() or 4, 4)

_pool: ProcessPoolExecutor | None = None


def _precalentar() -> bool:
    """Importa, dentro del proceso worker, las librerías pesadas que usará
    la evaluación real (pdfplumber, cliente de Google) para pagar ese costo
    una sola vez al arrancar el servidor, no en la primera petición real."""
    import app.evaluacion.formato1  # noqa: F401
    import googleapiclient.discovery  # noqa: F401
    import pdfplumber  # noqa: F401
    import pikepdf  # noqa: F401
    from cryptography.hazmat.primitives.serialization import pkcs7  # noqa: F401

    return True


def iniciar_pool() -> None:
    """Crea el pool y espera a que cada worker termine de importar sus
    dependencias pesadas, para que la primera evaluación real de un usuario
    no pague ese costo."""
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=MAX_WORKERS)
        futuros = [_pool.submit(_precalentar) for _ in range(MAX_WORKERS)]
        for futuro in futuros:
            futuro.result()


def detener_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None


def obtener_pool() -> ProcessPoolExecutor:
    """Devuelve el pool de procesos, recreándolo si se rompió (ej. un worker
    murió al procesar un PDF corrupto) para que el resto de evaluaciones
    puedan seguir funcionando."""
    global _pool
    if _pool is None:
        iniciar_pool()
    assert _pool is not None
    if getattr(_pool, "_broken", False):
        detener_pool()
        iniciar_pool()
    assert _pool is not None
    return _pool


__all__ = ["iniciar_pool", "detener_pool", "obtener_pool", "BrokenProcessPool", "MAX_WORKERS"]
