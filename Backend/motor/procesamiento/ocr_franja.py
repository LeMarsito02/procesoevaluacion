"""Leer una fila concreta de una tabla escaneada, recortándola de la página.

El OCR de una página completa a veces pierde justo la celda que importa: la letra
es pequeña, la tabla tiene líneas y el resultado deja «Asegurado Contratación» sin
el dato del medio. Recortar la fila y leerla sola, a varios tamaños, la recupera
—es el mismo camino que ya se usa con la fecha de expedición de las cédulas
(motor/procesamiento/ocr_cedula.py)—.

Cada tamaño es una lectura independiente, así que quien llama recibe varias y
puede quedarse con lo que coincida entre ellas en vez de fiarse de una sola.
"""
from __future__ import annotations

import io
import re
import subprocess
import os

from motor.procesamiento.pdf_utils import OCR_CACHE_DIR, OCR_HABILITADO, OCR_TIMEOUT_SEGUNDOS

# Resolución con la que se rasteriza la página para ubicar la fila, y tamaños a
# los que se lee la franja recortada (el OCR es muy sensible al tamaño).
RESOLUCION_PAGINA = 200
LADOS_PARA_UBICAR = (2000, 2600)
LADOS_DE_LA_FRANJA = (1800, 2400, 3000)


def textos_de_la_franja(page, etiqueta: re.Pattern[str]) -> list[str]:
    """Lecturas de la fila de la tabla cuya primera columna calza `etiqueta`.

    Devuelve una lista (una por tamaño probado), o vacía si no se encontró la
    etiqueta o si el OCR no está disponible. La franja va desde la etiqueta hasta
    el borde derecho de la página, que es donde está el dato de la fila."""
    if not OCR_HABILITADO:
        return []
    try:
        from PIL import ImageOps

        from motor.procesamiento.ocr_cedula import _escalada, _lineas
    except Exception:  # noqa: BLE001
        return []
    cache = _archivo_de_cache(page, etiqueta)
    if cache is not None and cache.exists():
        return [t for t in cache.read_text(encoding="utf-8").split("\f") if t.strip()]
    try:
        base = page.to_image(resolution=RESOLUCION_PAGINA).original.convert("L")
    except Exception:  # noqa: BLE001
        return []
    franja = None
    for lado in LADOS_PARA_UBICAR:
        escalada, factor = _escalada(base, lado)
        for texto, (x0, y0, x1, y1) in _lineas(ImageOps.autocontrast(escalada, cutoff=2)):
            if not etiqueta.search(texto.upper()):
                continue
            alto, ancho = y1 - y0, x1 - x0
            recorte = (
                max(0, int((x0 - 0.2 * ancho) / factor)),
                max(0, int((y0 - 1.2 * alto) / factor)),
                base.width,
                min(base.height, int((y1 + 2.5 * alto) / factor)),
            )
            candidata = base.crop(recorte)
            if candidata.height >= 10 and candidata.width >= 30:
                franja = candidata
            break
        if franja is not None:
            break
    if franja is None:
        return []
    lecturas = []
    for lado in LADOS_DE_LA_FRANJA:
        escalada, _ = _escalada(franja, lado)
        texto = _leer(ImageOps.autocontrast(escalada, cutoff=2))
        if texto.strip():
            lecturas.append(re.sub(r"\s+", " ", texto).strip())
    if cache is not None and lecturas:
        try:
            OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text("\f".join(lecturas), encoding="utf-8")
        except OSError:
            pass
    return lecturas


def _archivo_de_cache(page, etiqueta: re.Pattern[str]):
    import hashlib

    huella = getattr(page.pdf, "_huella_contenido", None)
    if not huella:
        return None
    marca = hashlib.sha1(etiqueta.pattern.encode()).hexdigest()[:8]
    return OCR_CACHE_DIR / f"{huella}_{page.page_number}_franja_{marca}.txt"


def _leer(imagen) -> str:
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    try:
        salida = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "spa", "--psm", "6"],
            input=buffer.getvalue(), capture_output=True, timeout=OCR_TIMEOUT_SEGUNDOS,
            env={**os.environ, "OMP_THREAD_LIMIT": "2"},
        )
        return salida.stdout.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return ""
