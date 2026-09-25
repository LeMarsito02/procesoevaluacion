"""Texto de los documentos que no son PDF.

Los anexos del pliego llegan en Word o Excel tan a menudo como en PDF (la
Matriz 2 de indicadores financieros, por ejemplo, casi siempre es un .docx).
Se leen sin dependencias nuevas: un .docx y un .xlsx son archivos zip con XML
adentro.
"""
from __future__ import annotations

import io
import re
import zipfile


def _texto_de_xml(xml: bytes) -> str:
    """El texto de un XML de Office, respetando los saltos de párrafo y de
    celda para que las tablas no queden pegadas en una sola línea."""
    import html

    texto = xml.decode("utf-8", "ignore")
    texto = re.sub(r"</(?:w:p|w:tr|a:p|row)>", "\n", texto)
    texto = re.sub(r"</(?:w:tc|c)>", " ", texto)
    # En el XML los símbolos van escapados, así que sin esto los rangos de la
    # Matriz 2 ("&gt;0 &lt;4.000 SMMLV") llegan sin sus comparadores y no se
    # puede saber a qué presupuesto aplica cada columna.
    return html.unescape(re.sub(r"<[^>]+>", "", texto))


def es_zip_de_office(contenido: bytes) -> bool:
    return contenido[:2] == b"PK"


def texto_de_docx(contenido: bytes) -> str:
    """El texto de un Word, incluido el de sus tablas."""
    partes = []
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        for nombre in ("word/document.xml", *sorted(n for n in z.namelist() if n.startswith("word/header"))):
            if nombre in z.namelist():
                partes.append(_texto_de_xml(z.read(nombre)))
    return "\n".join(partes)


def texto_de_xlsx(contenido: bytes) -> str:
    """El texto de un Excel: las cadenas compartidas y el valor de cada celda."""
    from openpyxl import load_workbook

    libro = load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
    partes = []
    try:
        for hoja in libro.worksheets:
            for fila in hoja.iter_rows(values_only=True):
                celdas = [str(c) for c in fila if c is not None and str(c).strip()]
                if celdas:
                    partes.append(" ".join(celdas))
    finally:
        libro.close()
    return "\n".join(partes)


def texto_de_documento(contenido: bytes, nombre: str = "") -> str:
    """El texto de un PDF, un Word o un Excel, según lo que sea de verdad (no
    según su extensión, que a veces miente)."""
    from motor.procesamiento.pdf_utils import abrir_pdf

    if contenido[:5] == b"%PDF-":
        with abrir_pdf(contenido) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    if es_zip_de_office(contenido):
        try:
            with zipfile.ZipFile(io.BytesIO(contenido)) as z:
                nombres = z.namelist()
            if "word/document.xml" in nombres:
                return texto_de_docx(contenido)
            if any(n.startswith("xl/") for n in nombres):
                return texto_de_xlsx(contenido)
        except zipfile.BadZipFile:
            return ""
    return ""
