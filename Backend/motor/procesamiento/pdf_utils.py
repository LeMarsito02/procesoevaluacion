from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException


def _reparar_pdf(contenido: bytes) -> bytes | None:
    """Reescribe el PDF con pikepdf (qpdf), que quita el cifrado de solo
    permisos y normaliza la estructura. Se confirmó con un Formato 1 real
    (P-79) cifrado con un valor de permisos negativo que pdfminer no sabe
    leer ("'L' format requires 0 <= number <= 4294967295"): tras reescribirlo
    el texto sale completo."""
    try:
        import pikepdf

        with pikepdf.open(io.BytesIO(contenido)) as pdf:
            salida = io.BytesIO()
            pdf.save(salida)
            return salida.getvalue()
    except Exception:  # noqa: BLE001
        return None


# --- OCR para páginas escaneadas -------------------------------------------
# Varios proponentes aportan documentos escaneados (pólizas, COPNIA, cartas
# consorciales) que no tienen capa de texto: sin OCR quedaban como "no
# encontrado". Solo se aplica a páginas SIN texto útil que además traen una
# imagen, así que los PDF digitales siguen leyéndose igual que antes. El
# resultado se guarda en disco por (contenido del PDF, página), porque el OCR
# cuesta segundos por página y cada requisito vuelve a leer los mismos
# documentos.
OCR_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "ocr"
OCR_RESOLUCION = 250
OCR_MINIMO_CARACTERES = 40
OCR_TIMEOUT_SEGUNDOS = 90
OCR_HABILITADO = os.environ.get("OCR_HABILITADO", "1") == "1" and shutil.which("tesseract") is not None
# Las firmas digitales dejan una estampa de texto sobre páginas escaneadas
# ("Digitally signed by ... Date: ...") que no es contenido del documento.
_ESTAMPA_FIRMA_RE = re.compile(r"digitally signed by.*?(?:date:[^\n]*)?$", re.IGNORECASE | re.MULTILINE)


# OCR reforzado, para documentos cuyas tablas pierde el OCR normal: la
# imagen en gris y binarizada (se van los fondos de color de las celdas y las
# líneas claras) y leída como un solo bloque (--psm 6), que conserva las filas
# de las tablas. Se confirmó con pólizas escaneadas de Seguros Mundial: el OCR
# normal perdía las etiquetas ASEGURADO/BENEFICIARIO y la fila del amparo
# (fechas y suma asegurada); el reforzado las lee. Cuesta unos 3 s por página,
# por eso solo se usa donde hace falta (ver `texto_ocr_reforzado`).
OCR_REFORZADO_RESOLUCION = 300
OCR_REFORZADO_UMBRAL = 120


def _ocr_pagina(page, reforzado: bool = False, filas: bool = False) -> str:
    """`filas`: tesseract en modo bloque uniforme (--psm 6), que conserva cada
    fila de una tabla (etiqueta y cifras juntas) en vez de leer columna por
    columna; lo usan los estados financieros escaneados."""
    if reforzado:
        imagen = page.to_image(resolution=OCR_REFORZADO_RESOLUCION).original.convert("L")
        imagen = imagen.point(lambda v: 255 if v > OCR_REFORZADO_UMBRAL else 0)
    else:
        imagen = page.to_image(resolution=OCR_RESOLUCION).original
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    del imagen
    entorno = {**os.environ, "OMP_THREAD_LIMIT": "2"}
    salida = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", "spa", *(["--psm", "6"] if reforzado or filas else [])],
        input=buffer.getvalue(),
        capture_output=True,
        timeout=OCR_TIMEOUT_SEGUNDOS,
        env=entorno,
    )
    return salida.stdout.decode("utf-8", errors="ignore")


def texto_pagina_tabla(page) -> str:
    """Texto de la página pensado para tablas: si es escaneada (imagen con
    poco o ningún texto), se lee con OCR fila por fila (--psm 6), de modo que
    la etiqueta de cada renglón quede junto a sus cifras. Cacheado aparte del
    OCR general."""
    crudo = page.extract_text() or ""
    if len(crudo.strip()) >= 300 or not page.images or not OCR_HABILITADO:
        return texto_pagina(page)
    huella = getattr(page.pdf, "_huella_contenido", None)
    cache = OCR_CACHE_DIR / f"{huella}_{page.page_number}_filas.txt" if huella else None
    try:
        if cache is not None and cache.exists():
            return cache.read_text(encoding="utf-8") or crudo
        ocr = _ocr_pagina(page, filas=True)
        if cache is not None:
            OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(ocr, encoding="utf-8")
        return ocr if len(ocr.strip()) > len(crudo.strip()) else crudo
    except Exception:  # noqa: BLE001
        return texto_pagina(page)


def texto_de_tablas(contenido: bytes, max_paginas: int = 15) -> str:
    """Texto del PDF leyendo cada página como tabla (ver `texto_pagina_tabla`)."""
    with abrir_pdf(contenido) as pdf:
        partes = []
        for page in pdf.pages[:max_paginas]:
            partes.append(texto_pagina_tabla(page))
            page.flush_cache()
    return " ".join(partes)


def texto_completo(contenido: bytes, max_paginas: int = 15) -> str:
    """Las dos lecturas del PDF, una detrás de la otra: la normal y la de
    tablas (OCR fila por fila). Cada una rescata lo que la otra pierde en los
    escaneados, y ambas quedan cacheadas."""
    normal = extraer_texto(contenido, max_paginas=max_paginas)
    tablas = texto_de_tablas(contenido, max_paginas=max_paginas)
    return f"{normal}\n{tablas}" if tablas.strip() != normal.strip() else normal


def paginas_ocr_reforzado(
    contenido: bytes, max_paginas: int = 2, ademas: set[int] | frozenset[int] = frozenset()
) -> list[tuple[int, str]]:
    """(número de página, texto) de las páginas escaneadas del PDF leídas con
    el OCR reforzado (cacheado en disco): las primeras `max_paginas` y las de
    `ademas`. Las páginas digitales no se leen."""
    if not OCR_HABILITADO:
        return []
    partes: list[tuple[int, str]] = []
    with abrir_pdf(contenido) as pdf:
        huella = pdf._huella_contenido
        for page in pdf.pages[:max([max_paginas, *ademas])]:
            if page.page_number > max_paginas and page.page_number not in ademas:
                continue
            try:
                if not _necesita_ocr(page, page.extract_text() or ""):
                    continue
                archivo_cache = OCR_CACHE_DIR / f"{huella}_{page.page_number}_reforzado.txt"
                if archivo_cache.exists():
                    partes.append((page.page_number, archivo_cache.read_text(encoding="utf-8")))
                    continue
                texto = _ocr_pagina(page, reforzado=True)
                OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                archivo_cache.write_text(texto, encoding="utf-8")
                partes.append((page.page_number, texto))
            except Exception:  # noqa: BLE001
                continue
            finally:
                page.flush_cache()
    return partes


def texto_ocr_reforzado(contenido: bytes, max_paginas: int = 2) -> str:
    """Texto de las páginas escaneadas del PDF leído con el OCR reforzado. Si
    ninguna página es escaneada devuelve ""."""
    return "\n".join(texto for _, texto in paginas_ocr_reforzado(contenido, max_paginas))


# Texto ya extraído en este worker para el proponente en curso, por
# (huella del PDF, número de página): los 18 requisitos leen muchas veces
# las mismas páginas y extract_text es lo más caro. Se vacía al cambiar de
# proponente (ver `limpiar_memoria_texto`).
_TEXTO_POR_PAGINA: dict[tuple[str, int], str] = {}
_HUELLAS: dict[int, tuple[bytes, str]] = {}


def limpiar_memoria_texto() -> None:
    _TEXTO_POR_PAGINA.clear()
    _HUELLAS.clear()


def _huella(contenido: bytes) -> str:
    # Se guarda también la referencia al objeto: así su id no puede
    # reutilizarse por otro PDF mientras la entrada exista.
    guardada = _HUELLAS.get(id(contenido))
    if guardada is not None and guardada[0] is contenido:
        return guardada[1]
    huella = hashlib.md5(contenido).hexdigest()
    _HUELLAS[id(contenido)] = (contenido, huella)
    return huella


def texto_pagina(page) -> str:
    """Texto de una página de pdfplumber; si la página es escaneada (sin
    texto útil pero con imagen), se obtiene con OCR (tesseract), cacheado."""
    huella = getattr(page.pdf, "_huella_contenido", None)
    clave = (huella, page.page_number) if huella else None
    if clave is not None and clave in _TEXTO_POR_PAGINA:
        return _TEXTO_POR_PAGINA[clave]
    texto = _texto_pagina_sin_memoria(page)
    if clave is not None:
        _TEXTO_POR_PAGINA[clave] = texto
    return texto


# Algunas aseguradoras generan la póliza con el texto de los datos
# convertido en trazos vectoriales: solo queda como texto la plantilla
# (~300 caracteres de etiquetas) y el resto son miles de curvas. Se
# confirmó en 7 pólizas reales de Seguros del Estado. Esas páginas también
# se leen con OCR.
OCR_MAXIMO_CARACTERES_TEXTO_DIBUJADO = 1000
OCR_MINIMO_CURVAS_TEXTO_DIBUJADO = 1000


# Fuentes sin tabla de caracteres: pdfminer devuelve "(cid:12)(cid:9)..." en
# vez de letras (póliza real de P-70). Esas páginas también se leen con OCR.
_CID_RE = re.compile(r"\(cid:\d+\)")
OCR_MINIMO_CIDS = 30


def _necesita_ocr(page, texto: str) -> bool:
    if len(_CID_RE.findall(texto)) >= OCR_MINIMO_CIDS:
        return True
    util = len(_ESTAMPA_FIRMA_RE.sub("", texto).strip())
    if util < OCR_MINIMO_CARACTERES:
        return bool(page.images)
    if util < OCR_MAXIMO_CARACTERES_TEXTO_DIBUJADO:
        return len(page.curves) >= OCR_MINIMO_CURVAS_TEXTO_DIBUJADO
    return False


def _texto_pagina_sin_memoria(page) -> str:
    texto = page.extract_text() or ""
    if not OCR_HABILITADO:
        return texto
    try:
        if not _necesita_ocr(page, texto):
            return texto
        huella = getattr(page.pdf, "_huella_contenido", None)
        archivo_cache = OCR_CACHE_DIR / f"{huella}_{page.page_number}.txt" if huella else None
        if archivo_cache is not None and archivo_cache.exists():
            return archivo_cache.read_text(encoding="utf-8")
        texto_ocr = _ocr_pagina(page)
        if archivo_cache is not None:
            OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            archivo_cache.write_text(texto_ocr, encoding="utf-8")
        return texto_ocr or texto
    except Exception:  # noqa: BLE001
        return texto


@contextmanager
def abrir_pdf(contenido: bytes) -> Iterator[pdfplumber.PDF]:
    """Igual que `pdfplumber.open`, pero si pdfminer no puede abrir el
    archivo se intenta una vez más con una copia reparada. Solo se repara
    cuando falla, para no alterar los PDF que ya se leen bien (ni sus firmas
    digitales)."""
    try:
        pdf = pdfplumber.open(io.BytesIO(contenido))
    except PdfminerException:
        reparado = _reparar_pdf(contenido)
        if reparado is None:
            raise
        pdf = pdfplumber.open(io.BytesIO(reparado))
    pdf._huella_contenido = _huella(contenido)
    with pdf:
        yield pdf


def extraer_texto(contenido: bytes, max_paginas: int | None = None) -> str:
    """Extrae el texto de un PDF liberando el caché pesado de cada página
    (curvas, rects, layout) apenas se usa, con `page.flush_cache()`.

    Sin esto, pdfplumber puede consumir cientos de MB extra en documentos
    con muchas páginas y gráficos vectoriales — muy común en certificados
    oficiales con marca de agua/fondo de seguridad (RUP, Cámara de
    Comercio, pólizas). Se confirmó con un RUP real de 52 páginas: sin
    `flush_cache()` el proceso subía +255MB solo por ese documento; con
    `flush_cache()` por página, +110MB — y esa memoria nunca se libera
    sola porque los workers se reutilizan entre peticiones, así que con
    varios proponentes grandes en la misma corrida el ahorro se
    multiplica en vez de perderse."""
    with abrir_pdf(contenido) as pdf:
        paginas = pdf.pages[:max_paginas] if max_paginas is not None else pdf.pages
        partes = []
        for page in paginas:
            partes.append(texto_pagina(page))
            page.flush_cache()
        return "\n".join(partes)


def buscar_pagina(contenido: bytes, coincide, max_paginas: int = 6) -> str | None:
    """Recorre las primeras páginas del PDF y devuelve el texto leído hasta
    la primera página en la que se cumple `coincide(texto)`, o None.

    Va página por página y corta apenas encuentra, en vez de leer todo el
    documento de una: así el caso común (el título en la página 1) sigue
    costando lo mismo que antes, pero se alcanzan también los documentos que
    traen una carátula con el membrete de la empresa antes del certificado
    —se confirmó con proponentes reales cuyo Certificado de Existencia
    empieza en la página 2 y antes quedaban como "no encontrado".

    La condición se evalúa sobre el texto ACUMULADO de las páginas leídas
    hasta ese momento, no sobre cada página suelta: hay certificados (RUP de
    Bucaramanga) con el título en la carátula y la fecha de expedición en la
    página siguiente."""
    partes: list[str] = []
    with abrir_pdf(contenido) as pdf:
        for page in pdf.pages[:max_paginas]:
            partes.append(texto_pagina(page))
            page.flush_cache()
            acumulado = "\n".join(partes)
            if coincide(acumulado):
                return acumulado
    return None
