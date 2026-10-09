"""Servicio local de OCR con PaddleOCR (PP-OCRv5, español).

Corre en su propio entorno de Python (Paddle aún no tiene paquetes para la
versión del backend) y solo escucha en el equipo: los documentos no salen del
servidor. El backend le envía la imagen de una página (PNG) y recibe el texto
en renglones, en orden de lectura.

    python servidor.py              # escucha en 127.0.0.1:8866
    OCR_PUERTO=8866 OCR_DISPOSITIVO=gpu python servidor.py

POST /ocr   cuerpo: PNG  →  {"texto": "...", "renglones": [...], "lineas": [{"texto", "caja"}], "segundos": 0.4}
GET  /salud               →  {"ok": true, "motor": "paddleocr", "dispositivo": "gpu"}
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PUERTO = int(os.environ.get("OCR_PUERTO", "8866"))
HOST = os.environ.get("OCR_HOST", "127.0.0.1")
DISPOSITIVO = os.environ.get("OCR_DISPOSITIVO", "")  # "gpu", "cpu" o vacío (el que haya)
MAXIMO_BYTES = 60 * 1024 * 1024
# GPU compartida con la IA (equipos con una GPU pequeña, como el portátil de
# desarrollo): se turnan con un candado de archivo común (GPU_CANDADO, el mismo
# que usa el backend), PaddleOCR suelta la GPU tras SEGUNDOS_OCIOSO sin trabajo
# y, antes de leer, le pide a Ollama que descargue sus modelos. En un servidor
# con GPU grande (24 GB) caben los dos y esto va apagado.
GPU_COMPARTIDA = os.environ.get("GPU_COMPARTIDA", "0") == "1"
GPU_CANDADO = os.environ.get("GPU_CANDADO") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "gpu.lock")
OLLAMA = os.environ.get("LLM_URL", "http://127.0.0.1:11434").rstrip("/")
SEGUNDOS_OCIOSO = int(os.environ.get("OCR_SEGUNDOS_OCIOSO", "30"))
# Lado mayor con que se lee una página: más grande no lee mejor (PaddleOCR la
# reduce a 4000 igual) y llena la GPU. Una hoja de 4500×5700 agotó los 4 GB.
LADO_MAXIMO = int(os.environ.get("OCR_LADO_MAXIMO", "3000"))

_lock = threading.Lock()  # el modelo no admite dos lecturas a la vez
_ocr = None
_ultimo_uso = 0.0


def _modelo():
    global _ocr
    if _ocr is None:
        from paddleocr import PaddleOCR

        opciones = {"lang": "es", "use_doc_orientation_classify": False, "use_doc_unwarping": False,
                    "use_textline_orientation": False}
        if DISPOSITIVO:
            opciones["device"] = DISPOSITIVO
        _ocr = PaddleOCR(**opciones)
    return _ocr


def _soltar() -> bool:
    """Descarga el modelo y devuelve la memoria de la GPU. True si había algo cargado."""
    global _ocr
    with _lock:
        if _ocr is None:
            return False
        _ocr = None
        import gc

        gc.collect()
        try:
            import paddle

            paddle.device.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
        return True


def _descargar_ollama() -> None:
    """Le pide a Ollama que suelte sus modelos de la GPU (los vuelve a cargar solo cuando los usen)."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/ps", timeout=3) as r:
            modelos = [m["name"] for m in json.load(r).get("models", [])]
        for nombre in modelos:
            pedido = urllib.request.Request(f"{OLLAMA}/api/generate", data=json.dumps({"model": nombre, "keep_alive": 0}).encode(),
                                            headers={"Content-Type": "application/json"})
            urllib.request.urlopen(pedido, timeout=30).read()
    except Exception:  # noqa: BLE001 — sin Ollama no hay nada que descargar
        pass


def _vigilar_ocio() -> None:
    while True:
        time.sleep(5)
        if _ocr is not None and time.time() - _ultimo_uso > SEGUNDOS_OCIOSO:
            if _soltar():
                print("OCR: GPU liberada por inactividad", flush=True)


def renglones(cajas: list[list[float]], textos: list[str]) -> list[str]:
    """Agrupa las líneas detectadas en renglones de la página: dos cajas van en
    el mismo renglón si sus alturas se solapan en más de la mitad. Así una fila
    de tabla queda con su etiqueta y sus datos juntos, como la lee una persona."""
    items = sorted(zip(cajas, textos), key=lambda x: ((x[0][1] + x[0][3]) / 2, x[0][0]))
    filas: list[list[tuple[list[float], str]]] = []
    for caja, texto in items:
        if not texto.strip():
            continue
        if filas:
            ultima = filas[-1]
            y0 = min(c[1] for c, _ in ultima)
            y1 = max(c[3] for c, _ in ultima)
            solape = min(y1, caja[3]) - max(y0, caja[1])
            alto = min(y1 - y0, caja[3] - caja[1]) or 1
            if solape / alto > 0.5:
                ultima.append((caja, texto))
                continue
        filas.append([(caja, texto)])
    return [" ".join(t for _, t in sorted(f, key=lambda x: x[0][0])) for f in filas]


def _devolver_memoria() -> None:
    try:
        import paddle

        paddle.device.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def _predecir(imagen):
    """Lee la imagen. Si la GPU se queda sin memoria, suelta todo y reintenta una
    vez: antes, tras el primer error, todas las páginas siguientes fallaban."""
    global _ultimo_uso
    for intento in (1, 2):
        try:
            with _lock:
                res = _modelo().predict(imagen)[0]
                _ultimo_uso = time.time()
            _devolver_memoria()  # lo que sobró vuelve a la GPU (la siguiente página puede ser más grande)
            return res
        except (MemoryError, RuntimeError) as exc:
            if intento == 2 or "memory" not in str(exc).lower():
                raise
            print("OCR: sin memoria en la GPU; se libera y se reintenta la página", flush=True)
            _soltar()


def leer(png: bytes) -> dict:
    import numpy as np
    from PIL import Image

    pil = Image.open(io.BytesIO(png)).convert("RGB")
    if max(pil.size) > LADO_MAXIMO:
        factor = LADO_MAXIMO / max(pil.size)
        pil = pil.resize((max(1, int(pil.width * factor)), max(1, int(pil.height * factor))), Image.LANCZOS)
    else:
        factor = 1.0
    imagen = np.array(pil)
    inicio = time.time()
    if GPU_COMPARTIDA:
        # Turno de GPU: mientras la IA lo tiene, se espera; al tomarlo, la IA suelta sus modelos.
        import fcntl

        os.makedirs(os.path.dirname(GPU_CANDADO), exist_ok=True)
        with open(GPU_CANDADO, "a") as candado:
            fcntl.flock(candado, fcntl.LOCK_EX)
            try:
                if _ocr is None:
                    _descargar_ollama()
                res = _predecir(imagen)
            finally:
                fcntl.flock(candado, fcntl.LOCK_UN)
    else:
        res = _predecir(imagen)
    # Las cajas vuelven a la escala de la imagen que se envió.
    cajas = [[v / factor for v in c] for c in res["rec_boxes"].tolist()]
    textos = list(res["rec_texts"])
    lineas = renglones(cajas, textos)
    return {
        "texto": "\n".join(lineas), "renglones": lineas,
        # Cada línea detectada con su caja [x0, y0, x1, y1] en píxeles de la imagen enviada.
        "lineas": [{"texto": t, "caja": [int(v) for v in c]} for c, t in zip(cajas, textos) if t.strip()],
        "segundos": round(time.time() - inicio, 3),
    }


class Manejador(BaseHTTPRequestHandler):
    def _json(self, codigo: int, datos: dict) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):  # noqa: N802
        if self.path == "/salud":
            self._json(200, {"ok": True, "motor": "paddleocr", "dispositivo": DISPOSITIVO or "auto", "cargado": _ocr is not None,
                             "gpu_compartida": GPU_COMPARTIDA})
        else:
            self._json(404, {"error": "no existe"})

    def do_POST(self):  # noqa: N802
        if self.path == "/liberar":
            # La IA va a usar la GPU (ya tiene el turno): se suelta el modelo.
            return self._json(200, {"liberada": _soltar()})
        if self.path != "/ocr":
            return self._json(404, {"error": "no existe"})
        largo = int(self.headers.get("Content-Length") or 0)
        if not 0 < largo <= MAXIMO_BYTES:
            return self._json(413, {"error": "imagen vacía o demasiado grande"})
        try:
            self._json(200, leer(self.rfile.read(largo)))
        except Exception as exc:  # noqa: BLE001
            import traceback

            traceback.print_exc()  # queda en el registro del servicio
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def log_message(self, formato, *args):  # sin una línea por petición
        pass


if __name__ == "__main__":
    if GPU_COMPARTIDA:
        # Se carga cuando llegue la primera página, no antes: la GPU puede estarla usando la IA.
        threading.Thread(target=_vigilar_ocio, daemon=True).start()
        print(f"OCR: GPU compartida con la IA (turno en {GPU_CANDADO}, se suelta tras {SEGUNDOS_OCIOSO} s sin trabajo)", flush=True)
    else:
        _modelo()  # carga el modelo antes de aceptar peticiones
    print(f"OCR (PaddleOCR) escuchando en {HOST}:{PUERTO}", flush=True)
    ThreadingHTTPServer((HOST, PUERTO), Manejador).serve_forever()
