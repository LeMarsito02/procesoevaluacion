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
    # Lo que la experiencia específica exige del objeto por encima de la
    # general ("…DE EDIFICACIONES, DECLARADAS COMO BIENES DE INTERÉS
    # CULTURAL"): no se puede dar por cumplido sin ver los documentos.
    condicion_objeto: str = ""


@dataclass
class ParametrosTecnicos:
    smmlv: float
    lotes: list[LoteTecnico] = field(default_factory=list)
    # Factores de puntaje que el pliego nombra (los que no, no se evalúan).
    factores_nombrados: set[str] = field(default_factory=set)
    # Parámetros que solo leyó la IA del pliego, o en los que la IA y las
    # reglas no coinciden. Mientras una persona no los confirme, ningún lote
    # se aprueba solo: ver motor/pliego/fusion.py.
    sin_confirmar: list[str] = field(default_factory=list)
    # Códigos UNSPSC a nivel de clase ("721410").
    clases_unspsc: set[str] = field(default_factory=set)
    tabla_valor: list[tuple[int, int, float]] = field(default_factory=lambda: list(TABLA_VALOR_DOCUMENTO_TIPO))
    max_contratos: int = 5
    # 3.5.3 D: en plurales, uno aporta al menos el 50 %, los demás al menos
    # el 5 %, y solo uno puede no aportar si su participación es ≤ 10 %.
    plural_principal: float = 0.50
    plural_demas: float = 0.05
    plural_sin_experiencia_max: float = 0.10
    # Puntaje de cada factor leído del capítulo IV: {clave: puntos}, None si
    # el pliego dice "NO APLICA". Lo que falta no se leyó (se usa el del
    # documento tipo y se avisa).
    puntajes: dict[str, float | None] = field(default_factory=dict)

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
# "por lo menos el 70% del valor del presupuesto oficial" (licitación) y
# "debe corresponder mínimo al 30% del presupuesto oficial" (menor cuantía).
_FRACCION_VALOR_RE = re.compile(
    r"POR\s+LO\s+MENOS\s+UNO\s*\(\s*1\s*\)\s+DE\s+LOS\s+CONTRATOS[^.]{0,400}?"
    r"(?:POR\s+LO\s+MENOS|MINIMO\s+AL|CORRESPONDIENTE\s+A)\s+(?:EL\s+)?(\d{1,3})\s*%\s*DEL\s+(?:VALOR\s+DE(?:L)?\s+)?PRESUPUESTO\s+OFICIAL"
)
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


def _experiencia_en_filas(filas) -> tuple[str, str] | None:
    """Proceso de un solo lote (menor cuantía): la tabla no tiene columna de
    lote, sino los títulos en su propia fila — "EXPERIENCIA GENERAL" y
    debajo el texto, luego "EXPERIENCIA ESPECÍFICA" y debajo el suyo."""
    textos: dict[str, list[str]] = {"general": [], "especifica": []}
    actual: str | None = None
    for fila in filas:
        celdas = [c for c in fila if c and c.strip()]
        if not celdas:
            continue
        titulo = normalizar(" ".join(celdas))
        if re.fullmatch(r"EXPERIENCIA\s+GENERAL\s*:?", titulo):
            actual = "general"
        elif re.fullmatch(r"EXPERIENCIA\s+(?:ESPECIFICA|ESPECIFICA\s*:)\s*:?", titulo):
            actual = "especifica"
        elif actual:
            textos[actual].append(" ".join(celdas))
    if not textos["general"]:
        return None
    return " ".join(textos["general"]), " ".join(textos["especifica"])


def _experiencia_por_lote(tablas) -> dict[str, tuple[str, str]]:
    """{"1": (general, específica)} de la tabla "Lote | Experiencia General |
    Experiencia Especifica" (3.5.2 A)."""
    por_lote: dict[str, tuple[str, str]] = {}
    sin_lote: tuple[str, str] | None = None
    for _, filas in tablas:
        encabezado = next((f for f in filas if any("EXPERIENCIA GENERAL" in normalizar(c) for c in f)), None)
        if encabezado is None:
            continue
        antes = len(por_lote)
        for fila in filas:
            celdas = [c for c in fila if c]
            if len(celdas) < 3 or not re.fullmatch(r"\d{1,2}", celdas[0]):
                continue
            por_lote[celdas[0]] = (celdas[1], " ".join(celdas[2:]))
        if len(por_lote) == antes and sin_lote is None:
            sin_lote = _experiencia_en_filas(filas)
    if not por_lote and sin_lote:
        por_lote["1"] = sin_lote
    return por_lote


# Palabras que no distinguen nada al comparar la experiencia específica con
# la general.
_VACIAS_CONDICION = {
    "DE", "DEL", "LA", "LAS", "EL", "LOS", "Y", "O", "U", "EN", "QUE", "SE", "SU", "CON", "POR", "PARA", "AL",
    "UNO", "UNA", "COMO", "DEBE", "DEBEN", "SER", "CONTRATO", "CONTRATOS", "VALIDOS", "APORTADOS", "MENOS",
    "EXPERIENCIA", "GENERAL", "ESPECIFICA", "CORRESPONDER", "CONTEMPLAR", "PRESENTE", "PROCESO", "SELECCION",
}


def _condicion_objeto(general: str, especifica: str) -> str:
    """Lo que la experiencia específica pide del objeto y la general no.

    El documento tipo repite en la específica toda la lista de actividades de
    la general y le añade la exigencia propia del proceso ("… DE
    EDIFICACIONES, DECLARADAS COMO BIENES DE INTERÉS CULTURAL Y/O
    CONSERVACIÓN PATRIMONIAL"). Esa cola es lo que se devuelve; si la
    específica solo habla de valor o de longitud, no hay condición de objeto."""
    gen, esp = normalizar(general), normalizar(especifica)
    if not gen or not esp:
        return ""
    materia = re.split(r"\s+(?:EN|DE)\s+", gen, maxsplit=1)
    ultima = materia[1].split(" O ")[0].strip(" .,") if len(materia) > 1 else ""
    if not ultima or ultima not in esp:
        return ""
    cola = esp[esp.rindex(ultima) + len(ultima):].split(".")[0].strip(" ,;:")
    nuevas = {p for p in re.findall(r"[A-ZÑ]{4,}", cola) if p not in _VACIAS_CONDICION and p not in gen}
    return cola if len(nuevas) >= 2 else ""


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
    """Las clases del clasificador de Naciones Unidas en las que deben estar
    los contratos de experiencia. El pliego las escribe de varias formas:
    "72 14 10 Servicios…" (licitación, a veces partida en dos renglones) y
    "72000000 72120000 72121400" o "72121400" pegado a su descripción (menor
    cuantía). De un segmento/familia/clase solo cuenta la clase.

    El mismo pliego puede traer dos tablas (la del capítulo 1 y la de la
    experiencia): se toman los códigos de todas, porque son los que la
    entidad aceptó."""
    clases: set[str] = set()
    for titulo in ("CLASIFICACION DE LA EXPERIENCIA EN EL", "CLASIFICADOR DE BIENES Y SERVICIOS DE NACIONES UNIDAS"):
        for encontrado in re.finditer(re.escape(titulo), texto_norm):
            seccion = texto_norm[encontrado.start(): encontrado.start() + 2500]
            # Hasta donde empieza lo siguiente: el título que sigue en la
            # licitación, o el número de la próxima sección ("1.5. RECURSOS…").
            fin = re.search(r"\n\s*(?:\d+(?:\.\d+)+\.?\s*)?ACREDITACION DE LA EXPERIENCIA REQUERIDA\s*\n"
                            r"|\n\s*\d+\.\d+\.?\s+[A-ZÑ]", seccion[100:])
            seccion = seccion[: 100 + fin.start() if fin else None]
            clases |= _clases_de_la_tabla(seccion)
    return clases


def _clases_de_la_tabla(seccion: str) -> set[str]:
    clases: set[str] = set()
    # "72121400": los dígitos 5 y 6 en "00" son la familia ("72120000") o el
    # segmento ("72000000"), que no sirven para comparar con el RUP.
    for codigo in re.findall(r"\b(\d{4})(\d{2})00\b", seccion):
        if codigo[1] != "00":
            clases.add("".join(codigo))
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


# Factores de puntaje por el título de su sección (el numeral cambia entre pliegos).
_TITULOS_PUNTAJE: dict[str, str] = {
    "gerencia_proyectos": r"PROGRAMA\s+DE\s+GERENCIA\s+DE\s+PROYECTOS",
    "maquinaria": r"CONDICIONES\s+FUNCIONALES\s+DE\s+LA\s+MAQUINARIA",
    "plan_calidad": r"PRESENTACION\s+DE\s+UN\s+PLAN\s+DE\s+CALIDAD",
    "criterios_ambientales": r"CRITERIOS\s+AMBIENTALES\s+Y\s+SOCIALES",
    "industria_nacional": r"ACREDITACION\s+DEL\s+PUNTAJE\s+POR\s+SERVICIOS\s+NACIONALES",
    "discapacidad": r"VINCULACION\s+DE\s+PERSONAS\s+CON\s+DISCAPACIDAD",
    "mujeres": r"EMPRENDIMIENTOS\s+Y\s+EMPRESAS\s+DE\s+MUJERES",
    "mipyme": r"MIPYME\s+DOMICILIADA\s+EN\s+COLOMBIA",
}
_PUNTOS_RE = re.compile(
    r"(?:ASIGNAR|OTORGAR)[A-Z]*\s+(?:HASTA\s+)?(?:UN\s+PUNTAJE\s+DE\s+)?[A-Z ]{0,60}?\(\s*(\d+(?:[.,]\d+)?)\s*\)\s*PUNTOS?"
)


def _puntajes(texto_norm: str) -> tuple[dict[str, float | None], set[str]]:
    """Puntos de cada factor, en el cuerpo del capítulo IV (no en el índice:
    ahí el título va seguido de puntos suspensivos y la página). None cuando
    el factor no hace parte del proceso: el pliego lo dice con "NO APLICA" o
    con "N/A." debajo del título, o sencillamente no lo nombra."""
    puntajes: dict[str, float | None] = {}
    nombrados: set[str] = set()
    for clave, titulo in _TITULOS_PUNTAJE.items():
        apariciones = [
            m for m in re.finditer(titulo, texto_norm)
            if "...." not in texto_norm[texto_norm.rfind("\n", 0, m.start()) + 1: texto_norm.find("\n", m.end())]
        ]
        if not apariciones:
            # El pliego no nombra el factor: no se evalúa en este proceso.
            puntajes[clave] = None
            continue
        nombrados.add(clave)
        # El encabezado de la sección ("4.2.3. PRESENTACIÓN DE UN PLAN…") vale
        # más que una mención suelta en otra parte del pliego.
        encabezados = [
            m for m in apariciones
            if re.match(r"\s*4(?:\.\d+){1,2}\.?\s", texto_norm[texto_norm.rfind("\n", 0, m.start()) + 1: m.start()] or " ")
        ]
        m = (encabezados or apariciones)[-1]
        cuerpo = texto_norm[m.end():m.end() + 1500]
        siguiente = re.search(r"\n\s*4(?:\.\d+){1,2}\.?\s+[A-Z]", cuerpo)
        cuerpo = cuerpo[: siguiente.start() if siguiente else None]
        # "N/A." va pegado al título, que a veces sigue en el renglón de abajo
        # ("…DE LA MAQUINARIA DE\nOBRA N/A.").
        if re.match(r"[^.]{0,60}?(?:NO\s+APLICA|N\s*/\s*A)\b", cuerpo):
            puntajes[clave] = None
        elif p := _PUNTOS_RE.search(cuerpo):
            puntajes[clave] = float(p.group(1).replace(",", "."))
    return puntajes, nombrados


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
    parametros.puntajes, parametros.factores_nombrados = _puntajes(texto_norm)
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
        # La tabla a veces parte la experiencia específica en dos páginas: si
        # el porcentaje no quedó en ella, se busca en el texto del pliego.
        fraccion_valor = _FRACCION_VALOR_RE.search(esp) or (
            _FRACCION_VALOR_RE.search(texto_norm) if len(lotes) == 1 else None
        )
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
            condicion_objeto=_condicion_objeto(general, especifica),
        ))
    return parametros
