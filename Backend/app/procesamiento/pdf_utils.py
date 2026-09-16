from __future__ import annotations

import io
from collections.abc import Iterator
from contextlib import contextmanager

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
            partes.append(page.extract_text() or "")
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
            partes.append(page.extract_text() or "")
            page.flush_cache()
            acumulado = "\n".join(partes)
            if coincide(acumulado):
                return acumulado
    return None
