from __future__ import annotations

import os
import resource
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
MAX_WORKERS = min(os.cpu_count() or 4, int(os.environ.get("MAX_WORKERS", "4")))

# pdfplumber no libera del todo la memoria entre archivos: se midió que
# evaluar un solo proponente grande (un consorcio con ~230 PDF anidados,
# revisando RUP/Cámara de Comercio de varias decenas de páginas) puede subir
# el RSS de un worker de ~330MB a más de 1.3GB, y esa memoria no baja
# después porque Python/glibc rara vez le devuelve memoria al sistema
# operativo. Como el worker se reutiliza para muchas peticiones seguidas,
# esto se va acumulando hasta agotar la RAM en una corrida larga (se
# confirmó así: la máquina se quedaba sin memoria varias evaluaciones
# después de procesar un proponente grande, no en la primera). La solución
# es reciclar cada worker después de pocas tareas, para que el sistema
# operativo recupere esa memoria al terminar el proceso viejo.
MAX_TAREAS_POR_WORKER = int(os.environ.get("MAX_TAREAS_POR_WORKER", "3"))

# Tope duro de memoria por worker. Es la red de seguridad más importante del
# sistema: sin esto, un solo proponente con documentos muy pesados puede
# hacer crecer al worker sin control hasta que el kernel se queda sin RAM y
# empieza a matar procesos al azar para salvarse — en la práctica mataba el
# VS Code del usuario y le colgaba el escritorio. Con el tope, el que muere
# es el worker (con MemoryError, que se reporta como un error normal de esa
# evaluación) y el resto del sistema sigue intacto.
MEMORIA_MAX_WORKER_MB = int(os.environ.get("MEMORIA_MAX_WORKER_MB", "2048"))

_pool: ProcessPoolExecutor | None = None


def _preparar_worker() -> None:
    """Se ejecuta una vez dentro de cada worker (incluidos los que reemplazan
    a los reciclados): le pone el tope de memoria e importa de una vez las
    librerías pesadas, para no pagar ese costo en la primera evaluación
    real."""
    limite_bytes = MEMORIA_MAX_WORKER_MB * 1024 * 1024
    try:
        _, tope_duro = resource.getrlimit(resource.RLIMIT_AS)
        if tope_duro == resource.RLIM_INFINITY or tope_duro > limite_bytes:
            resource.setrlimit(resource.RLIMIT_AS, (limite_bytes, tope_duro))
    except (ValueError, OSError):
        pass

    import app.evaluacion.formato1  # noqa: F401
    import googleapiclient.discovery  # noqa: F401
    import pdfplumber  # noqa: F401
    import pikepdf  # noqa: F401
    from cryptography.hazmat.primitives.serialization import pkcs7  # noqa: F401


def _precalentar() -> bool:
    return True


def iniciar_pool() -> None:
    """Crea el pool y espera a que cada worker termine de importar sus
    dependencias pesadas, para que la primera evaluación real de un usuario
    no pague ese costo."""
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(
            max_workers=MAX_WORKERS,
            max_tasks_per_child=MAX_TAREAS_POR_WORKER,
            initializer=_preparar_worker,
        )
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
