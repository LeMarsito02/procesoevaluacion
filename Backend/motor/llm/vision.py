"""Leer una cédula escaneada con la IA local cuando el OCR no alcanza.

El reverso de la cédula trae la fecha de expedición, que la Policía pide para
consultar el RNMC. Muchas copias vienen torcidas, con sombras o en fotos de
mala calidad, y el OCR devuelve basura ("FECHA Y LUEGAR", "O8=JUL:"). En esos
casos se le muestra la imagen de la página a un modelo de visión local.

Reglas para no equivocarse:
- El modelo debe devolver también el número de la cédula: si no es el de la
  persona que se está buscando, no se usa la fecha.
- Fecha imposible (futura o anterior a 1960) se descarta.
- Sin modelo de visión disponible, todo sigue como antes: la persona escribe
  la fecha a mano.

Igual que el resto, la IA es local: la imagen no sale del servidor.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from datetime import date

import requests

log = logging.getLogger(__name__)

URL = os.environ.get("LLM_URL", "http://localhost:11434")
MODELO = os.environ.get("VISION_MODELO", "qwen2.5vl:3b")
HABILITADO = os.environ.get("VISION_HABILITADO", "1") == "1"
TIEMPO_MAXIMO = float(os.environ.get("VISION_TIMEOUT", "180"))
RESOLUCION = int(os.environ.get("VISION_RESOLUCION", "220"))
PAGINAS_MAXIMAS = 4

INSTRUCCION = (
    "Eres un lector de documentos de identidad colombianos. En la imagen hay una cédula de ciudadanía "
    "(anverso o reverso). Devuelve SOLO un JSON con lo que se lee literalmente, sin inventar nada:\n"
    '{"numero": "número de la cédula sin puntos, o null", '
    '"fecha_expedicion": "AAAA-MM-DD de la FECHA Y LUGAR DE EXPEDICIÓN, o null", '
    '"fecha_nacimiento": "AAAA-MM-DD, o null", "nombre": "nombre completo, o null"}\n'
    "Ojo: la fecha de nacimiento y la de expedición son distintas. Si un dato no se ve con claridad, ponlo en null."
)


def disponible() -> bool:
    if not HABILITADO:
        return False
    try:
        respuesta = requests.get(f"{URL}/api/tags", timeout=5)
        return respuesta.ok and any(m.get("name") == MODELO for m in respuesta.json().get("models", []))
    except requests.RequestException:
        return False


def _imagenes(contenido: bytes, max_paginas: int) -> list[bytes]:
    """Las páginas del PDF como PNG (solo las que el OCR ya consideró imagen)."""
    from motor.procesamiento.pdf_utils import abrir_pdf

    imagenes = []
    with abrir_pdf(contenido) as pdf:
        for page in pdf.pages[:max_paginas]:
            try:
                imagen = page.to_image(resolution=RESOLUCION).original
                buffer = io.BytesIO()
                imagen.save(buffer, format="PNG")
                imagenes.append(buffer.getvalue())
                del imagen
            except Exception:  # noqa: BLE001
                continue
            finally:
                page.flush_cache()
    return imagenes


def _preguntar(imagen: bytes) -> dict:
    respuesta = requests.post(
        f"{URL}/api/chat",
        timeout=TIEMPO_MAXIMO,
        json={
            "model": MODELO,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [{"role": "user", "content": INSTRUCCION, "images": [base64.b64encode(imagen).decode()]}],
        },
    )
    respuesta.raise_for_status()
    contenido = respuesta.json()["message"]["content"]
    encontrado = re.search(r"\{.*\}", contenido, re.S)
    return json.loads(encontrado.group(0)) if encontrado else {}


def _fecha(valor) -> date | None:
    try:
        fecha = date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None
    return fecha if date(1960, 1, 1) <= fecha <= date.today() else None


def leer_cedula(contenido: bytes, cedula: str | None = None, max_paginas: int = PAGINAS_MAXIMAS) -> date | None:
    """La fecha de expedición que la IA lee en la cédula escaneada, o None.

    Con `cedula`, solo se acepta la fecha si el modelo leyó ese mismo número:
    una carpeta puede traer las cédulas de varias personas."""
    if not disponible():
        return None
    numero = re.sub(r"\D", "", cedula or "")
    for imagen in _imagenes(contenido, max_paginas):
        try:
            datos = _preguntar(imagen)
        except (requests.RequestException, ValueError) as exc:
            log.warning("La IA no pudo leer la cédula: %s", exc)
            continue
        fecha = _fecha(datos.get("fecha_expedicion"))
        if fecha is None:
            continue
        leido = re.sub(r"\D", "", str(datos.get("numero") or ""))
        if numero and leido and leido != numero:
            continue  # es la cédula de otra persona
        if numero and not leido:
            continue  # sin número no se puede afirmar de quién es
        # La expedición nunca puede ser anterior a los 18 años de vida.
        nacimiento = _fecha(datos.get("fecha_nacimiento"))
        if nacimiento and fecha <= nacimiento:
            continue
        return fecha
    return None
