"""Lectura del Formato 3 – Experiencia.

El Formato 3 no acredita la experiencia (lo dice el propio formato): es el
índice de los contratos que el proponente aporta, con el número consecutivo
de cada uno en el RUP y el integrante que lo aporta. Los valores oficiales
salen del RUP (ver rup.py); los del formato solo sirven para cotejar.

Se pide "preferiblemente en Excel", pero muchos lo traen solo en PDF. Las
dos formas se leen igual: una lista de filas de celdas (del Excel, o de la
tabla que pdfplumber reconoce en el PDF). Las columnas se ubican por el
texto del encabezado, no por posición: cada versión del formato las mueve.

Los proponentes llenan las celdas a su manera; se vio, por ejemplo, una sola
celda con los consecutivos de dos integrantes ("ISAIAS VARGAS GONZALEZ
CONSECUTIVO - 204 / V&M CONSECUTIVO - 065") y otra con el texto copiado del
RUP ("*** EXPERIENCIA No.88 : NÚMERO CONSECUTIVO DEL CONTRATO:490").
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from motor.tecnica.rup import normalizar, numero

# Columnas por palabras de su encabezado (normalizado). El orden importa:
# se prueba cada columna contra la primera clave que la describe.
_COLUMNAS: list[tuple[str, re.Pattern]] = [
    ("orden", re.compile(r"^NO\.? DE ORDEN|^ORDEN\b|^NO\.?\s*$")),
    ("consecutivo", re.compile(r"CONSECUTIVO")),
    ("tipo_experiencia", re.compile(r"EXPERIENCIA REQUERIDA")),
    ("contratante", re.compile(r"ENTIDAD CONTRATANTE|^CONTRATANTE")),
    ("contrato", re.compile(r"CONTRATO O RESOLUCION")),
    ("codigos", re.compile(r"CLASIFICADOR")),
    ("forma", re.compile(r"FORMAS? DE EJECUCION")),
    ("integrante", re.compile(r"INTEGRANTE")),
    ("inicio", re.compile(r"INICIACION|FECHA DE INICIO")),
    ("terminacion", re.compile(r"TERMINACION")),
    ("valor_afectado", re.compile(r"AFECTADO POR")),
    ("valor_rup", re.compile(r"REPORTADO EN EL RUP")),
    ("valor_smmlv", re.compile(r"VALOR TOTAL DEL CONTRATO EN SMMLV")),
    ("lotes", re.compile(r"LOTES?\b")),
]
_FIN_RE = re.compile(r"^(LA INFORMACION INCLUIDA|NOTA\b|CARACTERISTICAS DEL FORMATO)")
_CONSECUTIVO_RE = re.compile(r"CONSECUTIVO[^\d\n]{0,40}(\d{1,6})")
_NUMERO_SUELTO_RE = re.compile(r"(?<![\d.,])(\d{1,6})(?:\.0)?(?![\d.,])")
_PORCENTAJE_RE = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%")


@dataclass
class ContratoFormato3:
    orden: int
    consecutivos: list[str] = field(default_factory=list)
    texto_consecutivo: str = ""
    tipo_experiencia: str = ""
    contratante: str = ""
    numero_contrato: str = ""
    objeto: str = ""
    codigos: str = ""
    forma: str = ""
    porcentaje: str = ""
    integrante: str = ""
    inicio: date | None = None
    terminacion: date | None = None
    valor_rup: float | None = None
    valor_smmlv: float | None = None
    valor_afectado: float | None = None
    lotes: str = ""


@dataclass
class Formato3:
    archivo: str
    contratos: list[ContratoFormato3] = field(default_factory=list)


def _texto(celda) -> str:
    if celda is None:
        return ""
    if isinstance(celda, float) and celda.is_integer():
        celda = int(celda)
    return " ".join(str(celda).split())


def _fecha(celda) -> date | None:
    if isinstance(celda, datetime):
        return celda.date()
    if isinstance(celda, date):
        return celda
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", _texto(celda))
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def _valor(celda) -> float | None:
    if isinstance(celda, (int, float)):
        return float(celda)
    m = re.search(r"[\d][\d.,]*", _texto(celda).replace("$", ""))
    return numero(m.group(0)) if m else None


def consecutivos_de(texto: str) -> list[str]:
    """Los consecutivos del RUP escritos en una celda. Si la celda dice
    "CONSECUTIVO", solo cuentan los números que lo siguen (el "EXPERIENCIA
    No.88" copiado del RUP no es el consecutivo)."""
    norm = normalizar(texto)
    encontrados = _CONSECUTIVO_RE.findall(norm) if "CONSECUTIVO" in norm else _NUMERO_SUELTO_RE.findall(norm)
    vistos: list[str] = []
    for n in encontrados:
        n = n.lstrip("0") or "0"
        if n not in vistos:
            vistos.append(n)
    return vistos


def _mapa_de_columnas(filas: list[list]) -> tuple[int, dict[str, int]] | None:
    """La fila donde empieza el encabezado y la columna de cada campo. El
    encabezado ocupa dos filas (la segunda tiene "No." / "Objeto" del
    contrato, "I,C,UT" / "%" de la forma de ejecución y los dos valores)."""
    for i, fila in enumerate(filas):
        textos = [normalizar(_texto(c)) for c in fila]
        if not any("CONSECUTIVO" in t for t in textos) or not any("CONTRATANTE" in t for t in textos):
            continue
        columnas: dict[str, int] = {}
        for j, t in enumerate(textos):
            for campo, patron in _COLUMNAS:
                if campo not in columnas and t and patron.search(t):
                    columnas[campo] = j
                    break
        siguiente = [normalizar(_texto(c)) for c in filas[i + 1]] if i + 1 < len(filas) else []
        for j, t in enumerate(siguiente):
            if t in ("NO.", "NO", "NUMERO") and "contrato" in columnas:
                columnas["numero_contrato"] = j
            elif t.startswith("OBJETO"):
                columnas["objeto"] = j
            elif t.startswith("I,C") or t.startswith("I, C"):
                columnas["forma"] = j
            elif t == "%":
                columnas["porcentaje"] = j
            elif "REPORTADO EN EL RUP" in t:
                columnas["valor_rup"] = j
            elif "VALOR TOTAL DEL CONTRATO EN SMMLV" in t:
                columnas["valor_smmlv"] = j
        if "numero_contrato" not in columnas and "contrato" in columnas:
            columnas["numero_contrato"] = columnas["contrato"]
        if "objeto" not in columnas and "contrato" in columnas:
            columnas["objeto"] = columnas["contrato"] + 1
        return i, columnas
    return None


def leer_filas(filas: list[list], archivo: str) -> Formato3 | None:
    ubicado = _mapa_de_columnas(filas)
    if ubicado is None:
        return None
    inicio, col = ubicado
    formato = Formato3(archivo=archivo)

    def celda(fila, campo):
        j = col.get(campo)
        return fila[j] if j is not None and j < len(fila) else None

    for fila in filas[inicio + 1:]:
        primero = next((normalizar(_texto(c)) for c in fila if _texto(c)), "")
        if _FIN_RE.match(primero):
            break
        texto_consecutivo = _texto(celda(fila, "consecutivo"))
        contratante = _texto(celda(fila, "contratante"))
        if not (texto_consecutivo or contratante):
            continue
        orden = _valor(celda(fila, "orden"))
        if orden is None:
            # Filas del encabezado o de títulos intermedios, sin número de orden.
            if not re.search(r"\d", texto_consecutivo):
                continue
            orden = len(formato.contratos) + 1
        formato.contratos.append(ContratoFormato3(
            orden=int(orden),
            consecutivos=consecutivos_de(texto_consecutivo),
            texto_consecutivo=texto_consecutivo,
            tipo_experiencia=_texto(celda(fila, "tipo_experiencia")),
            contratante=contratante,
            numero_contrato=_texto(celda(fila, "numero_contrato")),
            objeto=_texto(celda(fila, "objeto")),
            codigos=_texto(celda(fila, "codigos")),
            forma=_texto(celda(fila, "forma")),
            porcentaje=_texto(celda(fila, "porcentaje")),
            integrante=_texto(celda(fila, "integrante")),
            inicio=_fecha(celda(fila, "inicio")),
            terminacion=_fecha(celda(fila, "terminacion")),
            valor_rup=_valor(celda(fila, "valor_rup")),
            valor_smmlv=_valor(celda(fila, "valor_smmlv")),
            valor_afectado=_valor(celda(fila, "valor_afectado")),
            lotes=_texto(celda(fila, "lotes")),
        ))
    return formato if formato.contratos else None


def leer_excel(contenido: bytes, archivo: str) -> Formato3 | None:
    import openpyxl

    try:
        libro = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
    except Exception:  # noqa: BLE001
        return None
    for hoja in libro.worksheets:
        filas = [list(f) for f in hoja.iter_rows(values_only=True, max_row=200)]
        if formato := leer_filas(filas, f"{archivo} ({hoja.title})"):
            return formato
    return None


def _filas_de_tabla(page, tabla) -> list[list]:
    """Filas de la tabla; las que pdfplumber junta (varias filas sin línea
    divisoria: "1 2 3" en la columna del orden) se parten por la altura de
    cada número de orden, con las coordenadas de las palabras."""
    textos = tabla.extract()
    filas: list[list] = []
    for r, fila in enumerate(tabla.rows):
        celdas = fila.cells
        orden = " ".join((textos[r][0] or "").split())
        if not re.fullmatch(r"\d{1,2}(?: \d{1,2})+", orden) or not celdas or celdas[0] is None:
            filas.append(textos[r])
            continue
        x0, arriba, x1, abajo = celdas[0]
        palabras = page.within_bbox(fila.bbox).extract_words()
        alturas = sorted(w["top"] for w in palabras if x0 - 1 <= w["x0"] and w["x1"] <= x1 + 1 and re.fullmatch(r"\d{1,2}", w["text"]))
        # El texto de cada fila va centrado alrededor de su número de orden:
        # el corte entre dos filas es la mitad entre sus números.
        cortes = [arriba] + [(a + b) / 2 for a, b in zip(alturas, alturas[1:])] + [abajo]
        for k in range(len(alturas)):
            nueva = []
            for c in celdas:
                if c is None:
                    nueva.append(None)
                    continue
                try:
                    recorte = page.crop((c[0], max(c[1], cortes[k]), c[2], min(c[3], cortes[k + 1])), strict=False)
                    nueva.append(recorte.extract_text() or "")
                except ValueError:
                    nueva.append("")
            filas.append(nueva)
    return filas


def leer_pdf(contenido: bytes, archivo: str) -> Formato3 | None:
    """La tabla del Formato 3 en PDF: la página del encabezado y las
    siguientes mientras sigan con una tabla del mismo número de columnas (el
    mismo archivo suele traer después los soportes de cada contrato)."""
    from motor.procesamiento.pdf_utils import abrir_pdf

    filas: list[list] = []
    columnas: int | None = None
    try:
        with abrir_pdf(contenido) as pdf:
            for page in pdf.pages[:10]:
                tablas = page.find_tables()
                if columnas is None:
                    for tabla in tablas:
                        extraida = tabla.extract()
                        if any("CONSECUTIVO" in normalizar(_texto(c)) for f in extraida for c in f):
                            columnas = max(len(f) for f in extraida)
                            filas.extend(_filas_de_tabla(page, tabla))
                else:
                    seguidas = [t for t in tablas if max((len(f) for f in t.extract()), default=0) == columnas]
                    if not seguidas:
                        break
                    for tabla in seguidas:
                        filas.extend(_filas_de_tabla(page, tabla))
                page.flush_cache()
    except Exception:  # noqa: BLE001
        return None
    return leer_filas(filas, archivo) if filas else None


def porcentajes_de(texto: str) -> list[float]:
    return [v / 100 for p in _PORCENTAJE_RE.findall(texto) if (v := numero(p)) is not None]
