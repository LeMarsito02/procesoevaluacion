"""Parámetros de la evaluación técnica que salen del pliego.

Todo sale del pliego (documento tipo de Colombia Compra Eficiente para obra
pública de infraestructura de transporte): la experiencia general y la
específica de cada lote (3.5.2), los códigos UNSPSC válidos (3.5.4) y la
tabla de valor mínimo a certificar según el número de contratos (3.5.9). El
presupuesto de cada lote ya lo lee el análisis del documento base.

Lo que el pliego no permita leer queda en None: el evaluador lo pide como
revisión en vez de suponerlo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from motor.tecnica.rup import normalizar, numero

# Tabla 3.5.9 del documento tipo, por si no se puede leer la del pliego.
TABLA_VALOR_DOCUMENTO_TIPO: list[tuple[int, int, float]] = [(1, 2, 0.75), (3, 4, 1.20), (5, 5, 1.50)]


@dataclass
class LoteTecnico:
    nombre: str
    presupuesto: float | None
    experiencia_general: str = ""
    experiencia_especifica: str = ""
    # Un contrato debe valer al menos esta fracción del presupuesto del lote.
    fraccion_un_contrato: float | None = None
    # Un contrato debe acreditar al menos esta longitud intervenida (km).
    longitud_minima_km: float | None = None
    longitud_total_km: float | None = None
    fraccion_longitud: float | None = None


@dataclass
class ParametrosTecnicos:
    smmlv: float
    lotes: list[LoteTecnico] = field(default_factory=list)
    # Códigos UNSPSC a nivel de clase ("721410").
    clases_unspsc: set[str] = field(default_factory=set)
    tabla_valor: list[tuple[int, int, float]] = field(default_factory=lambda: list(TABLA_VALOR_DOCUMENTO_TIPO))
    max_contratos: int = 5
    # 3.5.3 D: en plurales, uno aporta al menos el 50 %, los demás al menos
    # el 5 %, y solo uno puede no aportar si su participación es ≤ 10 %.
    plural_principal: float = 0.50
    plural_demas: float = 0.05
    plural_sin_experiencia_max: float = 0.10

    def presupuesto_smmlv(self, lote: LoteTecnico) -> float | None:
        return None if lote.presupuesto is None else lote.presupuesto / self.smmlv

    def factor(self, contratos: int) -> float | None:
        for desde, hasta, factor in self.tabla_valor:
            if desde <= contratos <= hasta:
                return factor
        return self.tabla_valor[-1][2] if contratos > self.tabla_valor[-1][1] else None


_CODIGO_RE = re.compile(r"\b(\d{2})\s+(\d{2})\s+(\d{2})\b")
_LONGITUD_TOTAL_RE = re.compile(r"LONGITUD DE LA (?:VIA|CARRETERA)[^.]{0,40}?ES DE\s*([\d.,]+)\s*(KM|KILOMETROS|M|ML|METROS)\b")
_FRACCION_LONGITUD_RE = re.compile(r"LONGITUD\s+INTERVENIDA\s+CORRESPONDIENTE\s+A\s+POR\s+LO\s+MENOS\s+EL\s+(\d{1,3})\s*%")
_FRACCION_VALOR_RE = re.compile(r"POR\s+LO\s+MENOS\s+EL\s+(\d{1,3})\s*%\s*DEL\s+VALOR\s+DE(?:L)?\s+PRESUPUESTO\s+OFICIAL")
_FILA_TABLA_VALOR_RE = re.compile(r"(?:DE\s+(\d+)\s+HASTA\s+(\d+)|HASTA\s+(\d+))\D{0,20}?(\d{2,3})\s*%")


def _texto_celda(c) -> str:
    return " ".join(str(c or "").split())


def _tablas(pdf) -> list[tuple[int, list[list[str]]]]:
    tablas = []
    for n, page in enumerate(pdf.pages, 1):
        texto = normalizar(page.extract_text() or "")
        if not re.search(r"EXPERIENCIA GENERAL|VALOR MINIMO A CERTIFICAR|CLASIFICADOR DE BIENES", texto):
            continue
        for tabla in page.extract_tables():
            tablas.append((n, [[_texto_celda(c) for c in fila] for fila in tabla]))
        page.flush_cache()
    return tablas


def _experiencia_por_lote(tablas) -> dict[str, tuple[str, str]]:
    """{"1": (general, específica)} de la tabla "Lote | Experiencia General |
    Experiencia Especifica" (3.5.2 A)."""
    por_lote: dict[str, tuple[str, str]] = {}
    for _, filas in tablas:
        encabezado = next((f for f in filas if any("EXPERIENCIA GENERAL" in normalizar(c) for c in f)), None)
        if encabezado is None:
            continue
        for fila in filas:
            celdas = [c for c in fila if c]
            if len(celdas) < 3 or not re.fullmatch(r"\d{1,2}", celdas[0]):
                continue
            por_lote[celdas[0]] = (celdas[1], " ".join(celdas[2:]))
    return por_lote


def _tabla_valor(tablas) -> list[tuple[int, int, float]] | None:
    for _, filas in tablas:
        if not any("VALOR MINIMO A CERTIFICAR" in normalizar(" ".join(f)) for f in filas):
            continue
        tabla = []
        for fila in filas:
            m = _FILA_TABLA_VALOR_RE.search(normalizar(" ".join(fila)))
            if not m:
                continue
            if m.group(3):
                desde = tabla[-1][1] + 1 if tabla else 1
                tabla.append((desde, int(m.group(3)), int(m.group(4)) / 100))
            else:
                tabla.append((int(m.group(1)), int(m.group(2)), int(m.group(4)) / 100))
        if tabla:
            return tabla
    return None


def _clases_unspsc(texto_norm: str) -> set[str]:
    """Códigos de la tabla de 3.5.4 (segmento, familia y clase). La tabla a
    veces sale partida: "72 14 10 Servicios..." en un renglón, y en otro "72
    Servicios de construcción..." con "14 11" en el renglón siguiente."""
    # El índice del pliego también tiene el título: se toma la última aparición.
    inicio = texto_norm.rfind("CLASIFICACION DE LA EXPERIENCIA EN EL")
    if inicio < 0:
        return set()
    seccion = texto_norm[inicio:inicio + 2500]
    fin = re.search(r"\n\s*(?:\d+(?:\.\d+)+\.?\s*)?ACREDITACION DE LA EXPERIENCIA REQUERIDA\s*\n", seccion)
    seccion = seccion[: fin.start() if fin else None]
    clases: set[str] = set()
    segmento = None
    for linea in seccion.splitlines():
        linea = linea.strip()
        if m := re.match(r"(\d{2})\s+(\d{2})\s+(\d{2})\b", linea):
            clases.add("".join(m.groups()))
            segmento = m.group(1)
        elif m := re.match(r"(\d{2})\b(?!\s+\d)", linea):
            segmento = m.group(1)
        elif (m := re.fullmatch(r"(\d{2})\s+(\d{2})", linea)) and segmento:
            clases.add(segmento + m.group(1) + m.group(2))
    return clases


_LOTE_SECCION_RE = re.compile(r"OBJETO, PRESUPUESTO OFICIAL, PLAZO Y UBICACION(.{0,6000}?)\n\s*1\.2\.?\s", re.S)
_VALOR_ENTRE_PARENTESIS_RE = re.compile(r"\(\s*\$\s*([\d.,]+)\s*\)")


def lotes_del_pliego(texto_norm: str, lotes_de_la_tabla: list[str]) -> list[tuple[str, float | None]]:
    """Presupuesto de cada lote leído de la tabla de la sección 1.1, donde el
    valor viene en letras seguido de "($3.664.560.000,00)"; se emparejan en
    orden con los lotes de la tabla de experiencia."""
    secciones = list(_LOTE_SECCION_RE.finditer(texto_norm))
    if not secciones:
        return []
    valores = [numero(v) for v in _VALOR_ENTRE_PARENTESIS_RE.findall(secciones[-1].group(1))]
    if len(valores) != len(lotes_de_la_tabla):
        return []
    return [(f"LOTE {n}", v) for n, v in zip(lotes_de_la_tabla, valores)]


def _longitud(especifica_norm: str) -> tuple[float | None, float | None, float | None]:
    total = fraccion = None
    if m := _LONGITUD_TOTAL_RE.search(especifica_norm):
        valor = numero(m.group(1))
        if valor is not None:
            total = valor if m.group(2).startswith("K") else valor / 1000
    if m := _FRACCION_LONGITUD_RE.search(especifica_norm):
        fraccion = int(m.group(1)) / 100
    minima = total * fraccion if total is not None and fraccion is not None else None
    return minima, total, fraccion


def leer_parametros(contenido_pliego: bytes, lotes: list[tuple[str, float | None]], smmlv: float) -> ParametrosTecnicos:
    """`lotes`: [(nombre, presupuesto en pesos)] como los leyó el análisis del
    documento base."""
    from motor.procesamiento.pdf_utils import abrir_pdf

    with abrir_pdf(contenido_pliego) as pdf:
        tablas = _tablas(pdf)
        texto_norm = normalizar("\n".join(page.extract_text() or "" for page in pdf.pages))
    parametros = ParametrosTecnicos(smmlv=smmlv)
    parametros.clases_unspsc = _clases_unspsc(texto_norm)
    parametros.tabla_valor = _tabla_valor(tablas) or list(TABLA_VALOR_DOCUMENTO_TIPO)
    experiencia = _experiencia_por_lote(tablas)
    if len(experiencia) > 1 and len(lotes) < len(experiencia):
        # El análisis del documento base no separó los lotes (presupuesto en letras).
        lotes = lotes_del_pliego(texto_norm, sorted(experiencia, key=int)) or lotes
    for nombre, presupuesto in lotes:
        numero_lote = re.search(r"\d+", nombre)
        general, especifica = experiencia.get(numero_lote.group(0) if numero_lote else "1", ("", ""))
        if not general and len(experiencia) == 1:
            general, especifica = next(iter(experiencia.values()))
        esp = normalizar(especifica)
        fraccion_valor = _FRACCION_VALOR_RE.search(esp)
        minima, total, fraccion = _longitud(esp)
        parametros.lotes.append(LoteTecnico(
            nombre=nombre,
            presupuesto=presupuesto,
            experiencia_general=general,
            experiencia_especifica=especifica,
            fraccion_un_contrato=int(fraccion_valor.group(1)) / 100 if fraccion_valor else None,
            longitud_minima_km=minima,
            longitud_total_km=total,
            fraccion_longitud=fraccion,
        ))
    return parametros
