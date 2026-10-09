"""Turno de GPU entre la IA (Ollama) y el OCR (PaddleOCR).

En un equipo con una GPU pequeña (el portátil de desarrollo, 4 GB) no caben los
dos a la vez: el modelo que llega tarde se va al procesador y es muchísimo más
lento. Con GPU_COMPARTIDA=1 se turnan: un candado de archivo común
(cache/gpu.lock, el mismo que usa el servicio de OCR) y, al tomar el turno, se
le pide al otro que suelte la GPU. En producción (24 GB) caben los dos y esto
va apagado: no hace nada.
"""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

import requests

GPU_COMPARTIDA = os.environ.get("GPU_COMPARTIDA", "0") == "1"
LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:11434").rstrip("/")
# Un modelo que Ollama cargó con menos de esta fracción en la GPU se recarga (quedó
# en el procesador porque, al cargarlo, la GPU la tenía el OCR).
FRACCION_MINIMA_EN_GPU = 0.9
SEGUNDOS_ENTRE_RECARGAS = 120
# Si tras recargarlo sigue sin caber (el modelo de visión no entra en 4 GB con el
# escritorio usando parte), insistir solo estorba: cada recarga cuesta medio
# minuto y la consulta corre igual en el procesador. Se deja en paz un buen rato.
SEGUNDOS_SI_NO_CABE = 1800
_ultima_recarga: dict[str, float] = {}
_recargas_seguidas: dict[str, int] = {}
CANDADO = Path(os.environ.get("GPU_CANDADO") or Path(__file__).resolve().parent.parent / "cache" / "gpu.lock")
OCR_SERVICIO = os.environ.get("OCR_SERVICIO_URL", "http://127.0.0.1:8866").rstrip("/")


@contextmanager
def turno_ia():
    """Mientras dure, la GPU es de la IA: el OCR espera y suelta su modelo."""
    if not GPU_COMPARTIDA:
        yield
        return
    CANDADO.parent.mkdir(parents=True, exist_ok=True)
    with open(CANDADO, "a") as candado:
        fcntl.flock(candado, fcntl.LOCK_EX)
        try:
            try:
                requests.post(f"{OCR_SERVICIO}/liberar", timeout=30)
            except requests.RequestException:
                pass  # sin servicio de OCR no hay nada que liberar
            _recargar_si_quedo_en_procesador()
            yield
        finally:
            fcntl.flock(candado, fcntl.LOCK_UN)


def _recargar_si_quedo_en_procesador() -> None:
    """Ollama no mueve un modelo ya cargado: si lo cargó cuando la GPU la tenía
    el OCR, sigue en el procesador (lentísimo) aunque la GPU ya esté libre. Se
    descarga para que la próxima consulta lo cargue en la GPU. Como mucho una
    vez cada SEGUNDOS_ENTRE_RECARGAS por modelo, por si de verdad no cabe."""
    import time

    try:
        modelos = requests.get(f"{LLM_URL}/api/ps", timeout=5).json().get("models", [])
    except (requests.RequestException, ValueError):
        return
    for m in modelos:
        nombre, total, en_gpu = m.get("name"), m.get("size") or 0, m.get("size_vram") or 0
        if not nombre or not total:
            continue
        if en_gpu >= FRACCION_MINIMA_EN_GPU * total:
            _recargas_seguidas.pop(nombre, None)
            continue
        # Ya se recargó y volvió a quedar en el procesador: no cabe.
        espera = SEGUNDOS_SI_NO_CABE if _recargas_seguidas.get(nombre, 0) >= 1 else SEGUNDOS_ENTRE_RECARGAS
        if time.monotonic() - _ultima_recarga.get(nombre, -1e9) < espera:
            continue
        _ultima_recarga[nombre] = time.monotonic()
        _recargas_seguidas[nombre] = _recargas_seguidas.get(nombre, 0) + 1
        try:
            requests.post(f"{LLM_URL}/api/generate", json={"model": nombre, "keep_alive": 0}, timeout=30)
            # Se espera a que salga de la memoria (unos segundos) para que la próxima carga vea la GPU libre.
            for _ in range(20):
                if not any(x.get("name") == nombre for x in requests.get(f"{LLM_URL}/api/ps", timeout=5).json().get("models", [])):
                    break
                time.sleep(0.5)
        except (requests.RequestException, ValueError):
            pass

