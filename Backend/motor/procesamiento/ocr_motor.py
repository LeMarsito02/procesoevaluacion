"""Qué motor de OCR lee las imágenes de las páginas.

- ``tesseract`` (por defecto): el de siempre, en este mismo proceso.
- ``paddle``: PaddleOCR (PP-OCRv5), que lee bien lo que Tesseract daña: celdas
  de tabla, sellos encima del texto y escaneos de baja calidad. Corre como un
  servicio local aparte (``Backend/ocr_servicio``) porque Paddle necesita otro
  Python; los documentos no salen del servidor.

``OCR_MOTOR=paddle`` lo activa y ``OCR_SERVICIO_URL`` dice dónde está el
servicio. Si el servicio no responde, se usa Tesseract para no detener la
evaluación, y queda en el registro como error: es una lectura de menor calidad
y alguien tiene que saberlo.
"""
from __future__ import annotations

import io
import logging
import os
import re
import subprocess

import requests

log = logging.getLogger(__name__)

MOTOR = os.environ.get("OCR_MOTOR", "tesseract").strip().lower()
SERVICIO = os.environ.get("OCR_SERVICIO_URL", "http://127.0.0.1:8866").rstrip("/")
TIEMPO_SERVICIO = int(os.environ.get("OCR_SERVICIO_TIEMPO", "180"))
# Resolución a la que se le envía la página a PaddleOCR (con 200 ppp lee igual
# que con 300 y la imagen pesa la mitad).
RESOLUCION_PADDLE = 200


def usa_paddle() -> bool:
    return MOTOR == "paddle"


def directorio_cache(base):
    """Cada motor guarda sus lecturas aparte: cambiar de motor no reutiliza las del otro."""
    return base.parent / f"{base.name}_paddle" if usa_paddle() else base


def _png(imagen) -> bytes:
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return buffer.getvalue()


def tesseract(imagen, psm: str | None, timeout: int) -> str:
    salida = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", "spa", *(["--psm", psm] if psm else [])],
        input=_png(imagen), capture_output=True, timeout=timeout, env={**os.environ, "OMP_THREAD_LIMIT": "2"},
    )
    return salida.stdout.decode("utf-8", errors="ignore")


# Un código o una cifra: letras mayúsculas, dígitos y separadores, con al
# menos dos dígitos («ICCU-LP-O14-2026», «900.258.7l1-1», «2O26»).
_CODIGO = re.compile(r"(?<![\w])(?=(?:[^\s]*\d){2})[A-Z0-9][A-Z0-9.\-/]*[A-Z0-9](?![\w])")
_O_ENTRE_CIFRAS = re.compile(r"(?<=[\d\-./])O(?=[\dO])|(?<=\d)O(?=[\-./]|$)|(?<=[\dO])O(?=\d)")


# Un porcentaje con la O por el cero: «(3O%)», «1O %», «1OO%». Con un solo
# dígito no entra en la regla de los códigos, y es justo donde más duele: el
# pliego ICCU-LP-014-2026 dice «TREINTA POR CIENTO (3O%)» en el anticipo y, sin
# leerlo, la financiera no podía calcular el capital de trabajo ni la capacidad
# residual de ningún proponente.
_O_EN_PORCENTAJE = re.compile(r"(?<![A-Za-zÁÉÍÓÚÑ])(\d[\dO]*|O\d[\dO]*)(?=\s?%)")


# La cifra que acompaña a un número escrito en letras: «TREINTA (3O) DIAS»,
# «DIEZ (1O) PUNTOS», «(O5)». Entre paréntesis y con al menos un dígito.
# También el decimal que empieza por la O: «CERO PUNTO VEINTICINCO (O.25) PUNTOS».
_O_ENTRE_PARENTESIS = re.compile(r"\(\s*((?=[\dOo.,]*\d)[\dOo]+(?:[.,][\dOo]+)*)\s*(?=%?\s*\))")
# La ele minúscula o la i mayúscula por el uno, solo ENTRE dígitos o separadores
# de cifra («900.258.7l1-1», «1l/09/2026»): nunca al borde, donde puede ser letra.
_L_ENTRE_CIFRAS = re.compile(r"(?<=\d)[lI|](?=\d)|(?<=\d[.,/\-])[l|](?=\d)|(?<=\d)[l|](?=[.,/\-]\d)")


# Un valor en pesos: «$ 1.OOO.OOO», «$5OO.OOO,OO». Tras el signo y con al menos un dígito.
_O_EN_PESOS = re.compile(r"(?<=\$)(\s*)((?=[O.,]*\d)[\dO][\dO.,]*[\dO])")


def corregir_porcentajes(texto: str) -> str:
    """Letras leídas en lugar de cifras en porcentajes, valores en pesos y
    cifras entre paréntesis."""
    texto = _O_EN_PORCENTAJE.sub(lambda m: m.group(1).replace("O", "0"), texto)
    texto = _O_EN_PESOS.sub(lambda m: m.group(1) + m.group(2).replace("O", "0"), texto)
    return _O_ENTRE_PARENTESIS.sub(lambda m: "(" + m.group(1).replace("O", "0").replace("o", "0"), texto)


def corregir_digitos(texto: str) -> str:
    """PaddleOCR a veces escribe la letra O por el cero dentro de un número o un
    código: «ICCU-LP-O14-2026» en el pliego ICCU-LP-014-2026. Se corrige solo
    dentro de algo que ya es un código o una cifra y solo junto a otro dígito o
    separador; las palabras no se tocan («OCHO», «OBRA», «ICCU»)."""
    def arreglar(m: re.Match) -> str:
        token = m.group(0)
        anterior = None
        while anterior != token:
            anterior, token = token, _O_ENTRE_CIFRAS.sub("0", token)
        return token
    return corregir_porcentajes(_L_ENTRE_CIFRAS.sub("1", _CODIGO.sub(arreglar, texto)))


def _servicio(imagen) -> dict:
    r = requests.post(f"{SERVICIO}/ocr", data=_png(imagen), headers={"Content-Type": "image/png"}, timeout=TIEMPO_SERVICIO)
    r.raise_for_status()
    return r.json()


def paddle(imagen) -> str:
    return corregir_digitos(_servicio(imagen)["texto"])


def lineas_paddle(imagen) -> list[tuple[str, tuple[int, int, int, int]]]:
    """(texto, caja) de cada línea que detecta PaddleOCR, en píxeles de la imagen."""
    return [(corregir_digitos(x["texto"]), tuple(x["caja"])) for x in _servicio(imagen)["lineas"]]


def leer(imagen, psm: str | None = None, timeout: int = 90) -> str:
    """Texto de la imagen con el motor configurado. `psm` es el modo de
    Tesseract («6» por bloques); PaddleOCR siempre entrega renglones en orden
    de lectura, con cada fila de tabla junta."""
    if usa_paddle():
        try:
            return paddle(imagen)
        except (requests.RequestException, KeyError, ValueError) as exc:
            log.error("El servicio de OCR (PaddleOCR) no respondió en %s: %s. Se lee con Tesseract.", SERVICIO, exc)
    return tesseract(imagen, psm, timeout)


def salud() -> dict:
    if not usa_paddle():
        return {"motor": "tesseract", "ok": True}
    try:
        return {"motor": "paddle", **requests.get(f"{SERVICIO}/salud", timeout=5).json()}
    except (requests.RequestException, ValueError) as exc:
        return {"motor": "paddle", "ok": False, "error": str(exc)}
