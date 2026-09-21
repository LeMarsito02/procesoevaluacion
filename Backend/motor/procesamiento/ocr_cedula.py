"""Lectura a fondo de una página con una cédula escaneada o fotografiada.

El OCR de la página completa falla con las cédulas reales más comunes:
fotos de la tarjeta con fondo de colores y hologramas, pequeñas dentro de la
hoja, o incrustadas giradas 90° (el visor las muestra derechas, pero la imagen
guardada no lo está). Aquí se toma cada imagen incrustada a su resolución
original, se pone derecha, se aclara el fondo de color y se lee con varios
tratamientos. Quien use estas lecturas debe exigir que varias coincidan: un
solo tratamiento puede leer un 8 como 0.

Todo queda en caché en disco por página, porque es lento (varios segundos).
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess

from PIL import Image, ImageChops, ImageOps

from motor.procesamiento.pdf_utils import OCR_CACHE_DIR, OCR_HABILITADO, abrir_pdf

VERSION = 3
LADO_MINIMO_IMAGEN = 250
TIEMPO_MAXIMO = 60
# Palabras impresas en la cédula: la orientación correcta es la que más lee.
_PALABRAS_CEDULA_RE = re.compile(
    r"FECHA|NACIMIENTO|ESTATURA|EXPEDI|REPUBLICA|COLOMBIA|CEDULA|NOMBRES|APELLIDOS|REGISTRADOR|INDICE|DERECHO|SEXO|LUGAR"
)


def _tesseract(imagen: Image.Image) -> str:
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    try:
        salida = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "spa", "--psm", "6"],
            input=buffer.getvalue(), capture_output=True, timeout=TIEMPO_MAXIMO,
            env={**os.environ, "OMP_THREAD_LIMIT": "2"},
        )
    except Exception:  # noqa: BLE001
        return ""
    return salida.stdout.decode("utf-8", errors="ignore")


def _canal_mas_claro(imagen: Image.Image) -> Image.Image:
    """En cada píxel, el canal de color más claro: el fondo amarillo, rosado
    o verde de la cédula queda casi blanco y el texto negro sigue negro."""
    r, g, b = imagen.convert("RGB").split()
    return ImageChops.lighter(ImageChops.lighter(r, g), b)


def _orientacion(gris: Image.Image) -> tuple[int, str]:
    """Los grados a girar para que se lean más palabras de cédula, y ese
    texto."""
    mejor, texto_mejor, puntos_mejor = 0, "", -1
    for giro in (0, 90, 270, 180):
        texto = _tesseract(gris.rotate(giro, expand=True) if giro else gris)
        puntos = len(_PALABRAS_CEDULA_RE.findall(texto.upper()))
        if puntos > puntos_mejor:
            mejor, texto_mejor, puntos_mejor = giro, texto, puntos
        if giro == 0 and puntos >= 4:
            break  # ya estaba derecha
    return mejor, texto_mejor


def _imagenes_de_la_pagina(page) -> list[Image.Image]:
    """Las imágenes incrustadas que se pueden abrir (JPEG casi siempre), a su
    resolución original; si no hay, la página renderizada."""
    imagenes = []
    for datos in page.images:
        try:
            ancho, alto = datos.get("srcsize") or (0, 0)
            if min(ancho, alto) < LADO_MINIMO_IMAGEN:
                continue
            imagen = Image.open(io.BytesIO(datos["stream"].get_data()))
            imagen.load()
            imagenes.append(imagen.convert("RGB"))
        except Exception:  # noqa: BLE001
            continue
    if not imagenes:
        imagenes.append(page.to_image(resolution=300).original.convert("RGB"))
    return imagenes


# La etiqueta "FECHA Y LUGAR DE EXPEDICION", aunque el OCR la dañe.
_ETIQUETA_RE = re.compile(r"EXP[EFR]?D|XPEDI|PEDIC|EDICI|LUGAR\s*DE\s*E")
# Lados mayores a los que se busca la etiqueta, y alturas a las que se lee la
# franja: el OCR es muy sensible al tamaño de la letra, así que cada tamaño
# es una lectura independiente (un voto).
LADOS_PARA_UBICAR = (1600, 1200, 2000, 2400)
ALTURAS_FRANJA = (140, 160, 200, 260, 300)


def _lineas(imagen: Image.Image) -> list[tuple[str, tuple[int, int, int, int]]]:
    """(texto, caja) de cada línea que lee tesseract."""
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    try:
        salida = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "spa", "--psm", "6", "tsv"],
            input=buffer.getvalue(), capture_output=True, timeout=TIEMPO_MAXIMO,
            env={**os.environ, "OMP_THREAD_LIMIT": "2"},
        ).stdout.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return []
    lineas: dict[tuple[str, str, str], tuple[str, tuple[int, int, int, int]]] = {}
    for fila in salida.splitlines()[1:]:
        p = fila.split("\t")
        if len(p) < 12 or not p[11].strip():
            continue
        x, y, w, h = (int(p[i]) for i in (6, 7, 8, 9))
        texto, (x0, y0, x1, y1) = lineas.get((p[2], p[3], p[4]), ("", (10**9, 10**9, 0, 0)))
        lineas[(p[2], p[3], p[4])] = (f"{texto} {p[11]}", (min(x0, x), min(y0, y), max(x1, x + w), max(y1, y + h)))
    return list(lineas.values())


def _escalada(imagen: Image.Image, lado: int) -> tuple[Image.Image, float]:
    factor = lado / max(imagen.size)
    return imagen.resize((max(1, int(imagen.width * factor)), max(1, int(imagen.height * factor))), Image.LANCZOS), factor


def _franja_de_la_fecha(derecha: Image.Image) -> Image.Image | None:
    """La franja de la cédula antigua con la fecha de expedición: la línea de
    la etiqueta y las que tiene encima (ahí va "17-OCT-1995 BOGOTA D.C.")."""
    for lado in LADOS_PARA_UBICAR:
        escalada, factor = _escalada(derecha, lado)
        for texto, (x0, y0, x1, y1) in _lineas(ImageOps.autocontrast(escalada, cutoff=2)):
            if not _ETIQUETA_RE.search(texto.upper()):
                continue
            alto, ancho = y1 - y0, x1 - x0
            caja = (x0 - 0.1 * ancho, y0 - 2.8 * alto, x1 + 0.4 * ancho, y1 + 0.6 * alto)
            x0, y0, x1, y1 = (int(v / factor) for v in caja)
            franja = derecha.crop((max(0, x0), max(0, y0), min(derecha.width, x1), min(derecha.height, y1)))
            return franja if franja.height >= 10 and franja.width >= 30 else None
    return None


def lecturas_a_fondo(contenido: bytes, pagina: int) -> dict[str, list[str]]:
    """Lecturas a fondo de la página (número desde 1): "paginas", el texto de
    cada imagen ya derecha (sirve para saber de quién es), y "franjas", la
    franja de la fecha de expedición leída a varios tamaños y tratamientos
    (cada una es un voto)."""
    vacio: dict[str, list[str]] = {"paginas": [], "franjas": []}
    if not OCR_HABILITADO:
        return vacio
    try:
        with abrir_pdf(contenido) as pdf:
            if pagina > len(pdf.pages):
                return vacio
            page = pdf.pages[pagina - 1]
            cache = OCR_CACHE_DIR / f"{pdf._huella_contenido}_{pagina}_cedula_v{VERSION}.json"
            if cache.exists():
                return json.loads(cache.read_text(encoding="utf-8"))
            lecturas: dict[str, list[str]] = {"paginas": [], "franjas": []}
            for imagen in _imagenes_de_la_pagina(page):
                clara = _canal_mas_claro(imagen)
                giro, texto = _orientacion(_escalada(clara, 1600)[0])
                lecturas["paginas"].append(texto)
                derecha = clara.rotate(giro, expand=True) if giro else clara
                franja = _franja_de_la_fecha(derecha)
                if franja is None:
                    # A veces la etiqueta solo aparece al leer media imagen
                    # (pasó con una foto del reverso con mucho fondo).
                    mitades = (
                        derecha.crop((0, 0, derecha.width, derecha.height // 2)),
                        derecha.crop((0, derecha.height // 2, derecha.width, derecha.height)),
                    )
                    franja = next((f for m in mitades if (f := _franja_de_la_fecha(m)) is not None), None)
                if franja is None:
                    continue
                for alto in ALTURAS_FRANJA:
                    tamano = franja.resize((max(1, int(franja.width * alto / franja.height)), alto), Image.LANCZOS)
                    lecturas["franjas"].append(_tesseract(tamano))
                    lecturas["franjas"].append(_tesseract(ImageOps.autocontrast(tamano, cutoff=2)))
            page.flush_cache()
    except Exception:  # noqa: BLE001
        return vacio
    OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(lecturas, ensure_ascii=False), encoding="utf-8")
    return lecturas

