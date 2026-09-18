"""Lectura completa del pliego y división en secciones numeradas.

Los pliegos son documentos tipo (Colombia Compra Eficiente): capítulos en
romanos y secciones numeradas ("3.3.2 PERSONAS JURÍDICAS"), un índice al
comienzo y un encabezado y pie que se repiten en cada página. Se lee todo el
documento —con OCR donde no hay capa de texto— porque cualquier exigencia que
se pase por alto puede terminar en una mala evaluación.
"""
from __future__ import annotations

import collections
import hashlib
import re
import unicodedata
from dataclasses import dataclass

from motor.procesamiento.pdf_utils import abrir_pdf, texto_pagina


@dataclass(frozen=True)
class Pagina:
    numero: int  # desde 1
    texto: str


@dataclass(frozen=True)
class Seccion:
    numero: str  # "3.3.2", "III" para capítulos
    titulo: str
    pagina: int
    texto: str  # cuerpo, sin el título

    @property
    def capitulo(self) -> str:
        return self.numero.split(".")[0]

    @property
    def encabezado(self) -> str:
        return f"{self.numero} {self.titulo}".strip()


def norm(texto: str) -> str:
    """Mayúsculas y sin tildes (la Ñ se conserva), para buscar con patrones."""
    texto = unicodedata.normalize("NFD", texto.upper().replace("Ñ", "\0"))
    return "".join(c for c in texto if unicodedata.category(c) != "Mn").replace("\0", "Ñ")


def huella(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def leer_paginas(contenido: bytes) -> list[Pagina]:
    paginas = []
    with abrir_pdf(contenido) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            paginas.append(Pagina(i, texto_pagina(page) or ""))
            page.flush_cache()
    return paginas


# Líneas del índice: "CAPÍTULO III. REQUISITOS HABILITANTES ........ 25".
_LINEA_INDICE_RE = re.compile(r"\.{4,}\s*\d+\s*$")
_NUMERO_PAGINA_RE = re.compile(r"^\s*(?:P[AÁ]GINA\s+)?(\d{1,4})(?:\s+DE\s+(\d{1,4}))?\s*$", re.IGNORECASE)


def _es_numero_de_pagina(linea: str, total: int) -> bool:
    """"21", "Página 21 de 96" o "21 de 96" — pero no "2097 de 2021", que es
    parte de "Ley 2097 de 2021" partida en dos líneas."""
    m = _NUMERO_PAGINA_RE.match(linea)
    if not m:
        return False
    if m.group(2) is not None:
        return int(m.group(2)) == total and int(m.group(1)) <= total
    return int(m.group(1)) <= total
_CAPITULO_RE = re.compile(r"^CAP[IÍ]TULO\s+([IVXLC]+)\.?\s*(.*)$", re.IGNORECASE)
# "3.3.2 PERSONAS JURÍDICAS", "3.4. CERTIFICACIÓN DE PAGOS…", "1.15. CAUSALES DE RECHAZO".
_SECCION_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){1,3})\.?\s+([A-ZÁÉÍÓÚÑÜ][^a-záéíóúñ]{3,})$")


def _lineas_repetidas(paginas: list[Pagina]) -> set[str]:
    """Encabezados y pies: líneas que aparecen en más de un tercio de las
    páginas (el número de página se ignora al compararlas)."""
    conteo: collections.Counter[str] = collections.Counter()
    for p in paginas:
        # Solo el número de esta página se vuelve comodín ("Página 21 de 96"):
        # así no se confunden con encabezados las líneas de contenido que
        # también tienen números ("Ley 2097 de 2021").
        vistas = {re.sub(rf"\b{p.numero}\b", "#", l.strip()) for l in p.texto.splitlines() if l.strip()}
        conteo.update(vistas)
    minimo = max(3, len(paginas) // 3)
    return {l for l, n in conteo.items() if n >= minimo}


def _es_titulo(linea: str) -> re.Match[str] | None:
    return _CAPITULO_RE.match(linea) or _SECCION_RE.match(linea)


def secciones(paginas: list[Pagina]) -> list[Seccion]:
    repetidas = _lineas_repetidas(paginas)
    lineas: list[tuple[int, str]] = []
    for p in paginas:
        propias = [l.strip() for l in p.texto.splitlines()]
        propias = [
            l for l in propias
            if l and re.sub(rf"\b{p.numero}\b", "#", l) not in repetidas and not _es_numero_de_pagina(l, len(paginas))
        ]
        # Página de índice: la mayoría de sus títulos terminan en "..... 25".
        if sum(bool(_LINEA_INDICE_RE.search(l)) for l in propias) >= 5:
            continue
        lineas.extend((p.numero, l) for l in propias if not _LINEA_INDICE_RE.search(l))

    resultado: list[Seccion] = []
    actual: tuple[str, str, int] | None = None
    cuerpo: list[str] = []

    def cerrar() -> None:
        if actual is not None:
            resultado.append(Seccion(actual[0], actual[1], actual[2], "\n".join(cuerpo).strip()))

    i = 0
    while i < len(lineas):
        pagina, linea = lineas[i]
        m = _es_titulo(linea)
        if m:
            cerrar()
            if m.re is _CAPITULO_RE:
                numero, titulo = m.group(1).upper(), m.group(2).strip()
            else:
                numero, titulo = m.group(1), m.group(2).strip()
            # Títulos largos que siguen en la línea de abajo (también en mayúsculas).
            while i + 1 < len(lineas) and not _es_titulo(lineas[i + 1][1]) and re.fullmatch(
                r"[A-ZÁÉÍÓÚÑÜ0-9 ,.;:()\-–/]{3,}", lineas[i + 1][1]
            ) and not re.search(r"[.:]$", titulo):
                i += 1
                titulo = f"{titulo} {lineas[i][1]}"
            actual, cuerpo = (numero, titulo.strip(" .:"), pagina), []
        elif actual is not None:
            cuerpo.append(linea)
        i += 1
    cerrar()
    return resultado


def codigo_documento_tipo(paginas: list[Pagina]) -> str | None:
    """Código del documento tipo de Colombia Compra Eficiente, ej. CCE-EICP-GI-11."""
    for p in paginas[:5]:
        m = re.search(r"C[oó]digo\s+(CCE-[A-Z0-9\-]+)", p.texto)
        if m:
            return m.group(1)
    return None
