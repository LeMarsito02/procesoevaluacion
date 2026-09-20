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
RESOLUCION = int(os.environ.get("VISION_RESOLUCION", "200"))
# Lado mayor de la imagen que se le manda al modelo: una página a 200 ppp es
# enorme, el servicio la rechaza y además cada píxel cuesta tiempo de GPU.
LADO_MAXIMO = int(os.environ.get("VISION_LADO_MAXIMO", "1100"))
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


def _imagenes(contenido: bytes, max_paginas: int, paginas: list[int] | None = None) -> list[bytes]:
    """Las páginas del PDF como JPEG, del tamaño que el modelo acepta. Con
    `paginas` (números de página, desde 1) solo esas."""
    from motor.procesamiento.pdf_utils import abrir_pdf

    imagenes = []
    with abrir_pdf(contenido) as pdf:
        elegidas = [p for p in pdf.pages if p.page_number in paginas] if paginas else list(pdf.pages)
        for page in elegidas[:max_paginas]:
            try:
                imagen = page.to_image(resolution=RESOLUCION).original.convert("RGB")
                mayor = max(imagen.size)
                if mayor > LADO_MAXIMO:
                    escala = LADO_MAXIMO / mayor
                    imagen = imagen.resize((int(imagen.width * escala), int(imagen.height * escala)))
                # Primero el recorte de la zona de la fecha (se lee mucho
                # mejor); la página completa queda de respaldo.
                for version in (_recorte_de_la_fecha(imagen), imagen):
                    if version is None:
                        continue
                    buffer = io.BytesIO()
                    version.save(buffer, format="JPEG", quality=90)
                    imagenes.append(buffer.getvalue())
                del imagen
            except Exception:  # noqa: BLE001
                continue
            finally:
                page.flush_cache()
    return imagenes


def _recorte_de_la_fecha(imagen):
    """El pedazo de la cédula donde está la fecha de expedición, ampliado.

    En una página completa los dígitos de la fecha ocupan poquísimos píxeles y
    el modelo no los distingue. Tesseract sí sabe *dónde* está la etiqueta
    "EXPEDICION" (aunque lea mal los números de al lado), así que se recorta
    esa zona —la fecha va a su izquierda y arriba— y se le muestra grande.
    Devuelve None si no se encuentra la etiqueta."""
    import subprocess

    from PIL import Image

    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    try:
        salida = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "spa", "tsv"],
            input=buffer.getvalue(), capture_output=True, timeout=120,
            env={**os.environ, "OMP_THREAD_LIMIT": "2"},
        ).stdout.decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return None
    for linea in salida.splitlines()[1:]:
        partes = linea.split("\t")
        if len(partes) < 12 or "EXPEDI" not in partes[11].upper():
            continue
        x, y, ancho, alto = (int(partes[i]) for i in (6, 7, 8, 9))
        # La fecha está a la izquierda de la etiqueta y un poco más arriba.
        caja = (
            max(0, x - int(ancho * 1.2)),
            max(0, y - int(alto * 4.5)),
            min(imagen.width, x + int(ancho * 2.2)),
            min(imagen.height, y + int(alto * 2.0)),
        )
        recorte = imagen.crop(caja)
        if recorte.width < 40 or recorte.height < 20:
            return None
        escala = min(4.0, 900 / max(recorte.width, 1))
        if escala > 1:
            recorte = recorte.resize((int(recorte.width * escala), int(recorte.height * escala)), Image.LANCZOS)
        return recorte
    return None


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


class LecturaVision:
    """Lo que la IA leyó y cuántas veces vio lo mismo. Una sola lectura no
    basta: en una prueba real el modelo leyó "24" donde decía "13", y con una
    fecha equivocada la página de la Policía rechaza la consulta."""

    def __init__(self, fecha: date | None, veces: int = 0) -> None:
        self.fecha = fecha
        self.veces = veces

    @property
    def confirmada(self) -> bool:
        """Dos miradas distintas a la cédula (el recorte de la fecha y la
        página completa) dijeron lo mismo."""
        return self.fecha is not None and self.veces >= 2


def leer_cedula_detallado(
    contenido: bytes, cedula: str | None = None, max_paginas: int = PAGINAS_MAXIMAS, paginas: list[int] | None = None
) -> LecturaVision:
    """Lo que la IA lee en la cédula escaneada: la fecha más repetida y cuántas
    veces salió. Con `cedula`, solo cuenta si el modelo leyó ese mismo número:
    una carpeta puede traer las cédulas de varias personas."""
    if not disponible():
        return LecturaVision(None)
    numero = re.sub(r"\D", "", cedula or "")
    leidas: list[date] = []
    for imagen in _imagenes(contenido, max_paginas, paginas):
        try:
            datos = _preguntar(imagen)
        except (requests.RequestException, ValueError) as exc:
            detalle = getattr(getattr(exc, "response", None), "text", "")
            log.warning("La IA no pudo leer la cédula: %s %s", exc, detalle[:200])
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
        leidas.append(fecha)
    if not leidas:
        return LecturaVision(None)
    fecha = max(set(leidas), key=leidas.count)
    return LecturaVision(fecha, leidas.count(fecha))


def leer_cedula(
    contenido: bytes, cedula: str | None = None, max_paginas: int = PAGINAS_MAXIMAS, paginas: list[int] | None = None
) -> date | None:
    """Solo la fecha que la IA vio dos veces igual (la que se puede usar sin
    que nadie la confirme)."""
    lectura = leer_cedula_detallado(contenido, cedula, max_paginas, paginas)
    return lectura.fecha if lectura.confirmada else None
