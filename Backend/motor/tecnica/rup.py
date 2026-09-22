"""Lectura del RUP (Registro Único de Proponentes) para la evaluación técnica.

El RUP es la fuente oficial de la experiencia (pliego, 3.5: "La evaluación
de los proponentes se efectuará de acuerdo con la experiencia contenida en
el RUP"). Cada contrato reportado trae un número consecutivo (el que el
proponente cita en el Formato 3), quién lo celebró, el contratante, el valor
en SMMLV, el porcentaje de participación si fue en consorcio o unión
temporal y los códigos UNSPSC. También trae el tamaño de la empresa, que da
el puntaje MIPYME.

Hay RUP de más de 1.500 páginas (casi todo son listas de códigos UNSPSC):
el texto se saca con pdfium, que lee mil páginas en un segundo; pdfplumber
tardaría minutos.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

import pypdfium2

# Encabezado que se repite en cada página del certificado: se quita para que
# un bloque de experiencia partido entre dos páginas se lea seguido. Formato
# de Confecámaras (la mayoría de cámaras) y de la Cámara de Comercio de Bogotá.
_ENCABEZADO_RE = re.compile(
    r"^\s*(?:CAMARA DE COMERCIO\b.*|CERTIFICADO DE INSCRIPCION Y CLASIFICACION.*|FECHA EXPEDICION\s*:.*"
    r"|RECIBO NO\..*|CODIGO (?:DE )?VERIFICACION.*|VERIFIQUE EL CONTENIDO.*|VISUALICE LA IMAGEN.*"
    r"|CONTADOS A PARTIR DE LA FECHA.*|PAGINA\s+[\d.]+\s+DE\s+[\d.]+\s*"
    r"|SEDE VIRTUAL\s*|\d{1,2} DE [A-Z]+ DE \d{4} HORA .*|\S*\s*PAGINA\s*:\s*\d+\s+DE\s+\d+\s*|(?:\*\s*){5,})$"
)
# Inicio de cada contrato: "*** EXPERIENCIA No.88 :" (Confecámaras) o
# "NUMERO CONSECUTIVO DEL REPORTE DEL CONTRATO EJECUTADO: 66" (Bogotá).
_EXPERIENCIA_RE = re.compile(
    r"\*{2,}\s*EXPERIENCIA\s+NO\.?\s*(\d+)\s*:?|(?=NUMERO CONSECUTIVO DEL REPORTE DEL CONTRATO EJECUTADO\s*:)"
)
_CONSECUTIVO_RE = re.compile(r"NUMERO CONSECUTIVO DEL (?:REPORTE DEL )?CONTRATO(?: EJECUTADO)?\s*:\s*([\w-]+)")
# Los campos pueden seguir en el renglón siguiente (Bogotá parte los nombres largos).
_CELEBRADO_RE = re.compile(r"CONTRATO CELEBRADO POR\s*:\s*(?:\d+\s*-\s*)?(.+?)(?=\n\s*NOMBRE DEL CONTRATISTA)", re.S)
_CONTRATISTA_RE = re.compile(r"NOMBRE DEL CONTRATISTA\s*:\s*(.+?)(?=\n\s*NOMBRE DEL CONTRATANTE)", re.S)
_CONTRATANTE_RE = re.compile(r"NOMBRE DEL CONTRATANTE\s*:\s*(.+?)(?=\n\s*VALOR)", re.S)
_VALOR_RE = re.compile(r"VALOR (?:CONTRATADO|DEL CONTRATO EJECUTADO EXPRESADO) EN SMMLV\s*:\s*([\d.,]+)")
_PARTICIPACION_RE = re.compile(r"PORCENTAJE DE PARTICIPACION[^:]*:\s*([\d.,]+)\s*%?")
_CODIGO_RE = re.compile(r"^\s*(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*:|\|\s*(\d{2})\s*\|\s*(\d{2})\s*\|\s*(\d{2})\s*\|\s*(\d{2})\s*\|", re.M)
_TAMANO_RE = re.compile(
    r"TAMANO DE (?:LA )?EMPRESA\s*:\s*([A-Z ]+?)\s*$|CLASIFICACION POR TAMANO DE LA EMPRESA\s*\n(?:.*SE CLASIFICO COMO\s*:?\s*\n)?\s*([A-Z ]+?)\s*$",
    re.M,
)
_NIT_RE = re.compile(r"\bNIT\s*:\s*([\d.\- ]+)")
_NOMBRE_RE = re.compile(r"^(?:NOMBRE|QUE)\s*:\s*([^\n]+)", re.M)
_FECHA_EXPEDICION_RE = re.compile(r"FECHA EXPEDICION\s*:\s*(\d{1,2})/(\d{1,2})/(\d{4})")
_FECHA_BOGOTA_RE = re.compile(r"(\d{1,2}) DE ([A-Z]+) DE (\d{4}) HORA")
_CONSTITUCION_RE = re.compile(r"FECHA DE CONSTITUCION\s*:\s*(\d{1,2})/(\d{1,2})/(\d{4})")
_CONSTITUCION_ISO_RE = re.compile(r"FECHA DE ADQUISICION DE LA PERSONERIA JURIDICA\s*:\s*(\d{4})/(\d{1,2})/(\d{1,2})")
# Códigos sueltos en la tabla del clasificador (Bucaramanga: "72 14 10 00 72 14 11 00").
_CODIGO_SUELTO_RE = re.compile(r"(?<![\d/.,])(\d{2}) (\d{2}) (\d{2}) (\d{2})(?![\d/.,])")
_FECHA_ISO_EXPEDICION_RE = re.compile(r"FECHA DE EXPEDICION\s*:[^\n]*?(\d{4})/(\d{1,2})/(\d{1,2})")
# Inicio de cada certificado (hay PDF con los RUP de varios integrantes seguidos).
_IDENTIFICACION_RE = re.compile(r"\n\s*IDENTIFICACION\s*\n\s*(?:QUE|NOMBRE)\s*:")
_CONSTITUCION_BOGOTA_RE = re.compile(r"INFORMACION CONSTITUCION\.?\s*(?:POR|MEDIANTE)[^\n]*?\bDEL?\s+(\d{1,2})\s+DE\s+([A-Z]+)\s+DE\s+(\d{4})", re.S)
_MESES = {m: i for i, m in enumerate(
    "ENERO FEBRERO MARZO ABRIL MAYO JUNIO JULIO AGOSTO SEPTIEMBRE OCTUBRE NOVIEMBRE DICIEMBRE".split(), 1)}


_EQUIVALENTES = str.maketrans({"—": " - ", "–": " - ", "“": '"', "”": '"', "‘": "'", "’": "'", "\u00a0": " "})


def normalizar(texto: str) -> str:
    texto = texto.translate(_EQUIVALENTES)
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.upper()


def numero(texto: str) -> float | None:
    """Número escrito a la colombiana ("15.525,61", "15525,61") o con punto
    decimal ("15525.61")."""
    t = texto.strip().rstrip(".,")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1 or re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


@dataclass
class ExperienciaRup:
    consecutivo: str
    numero: int
    celebrado_por: str = ""
    contratista: str = ""
    contratante: str = ""
    valor_smmlv: float | None = None
    # Participación del inscrito en el consorcio o unión temporal (0 a 1);
    # None si lo ejecutó solo.
    participacion: float | None = None
    # Códigos UNSPSC a nivel de clase: "721410" (segmento, familia, clase).
    clases: set[str] = field(default_factory=set)

    @property
    def en_consorcio(self) -> bool:
        return "CONSORCIO" in self.celebrado_por or "UNION TEMPORAL" in self.celebrado_por

    @property
    def de_un_socio(self) -> bool:
        """Experiencia de un socio, accionista o constituyente (sociedades de
        menos de tres años, pliego 3.5.2 E)."""
        return "SOCIO" in self.celebrado_por or "ACCIONISTA" in self.celebrado_por

    @property
    def valor_aportado(self) -> float | None:
        """Valor que le cuenta al inscrito: el total por su participación
        (pliego 3.5.3 F)."""
        if self.valor_smmlv is None:
            return None
        if self.en_consorcio:
            return None if self.participacion is None else self.valor_smmlv * self.participacion
        return self.valor_smmlv


@dataclass
class InformacionFinanciera:
    """Lo que el RUP certifica de los estados financieros del inscrito (la
    evaluación financiera se hace con esto: pliego 3.10.1)."""
    fecha_corte: date | None = None
    activo_corriente: float | None = None
    activo_total: float | None = None
    pasivo_corriente: float | None = None
    pasivo_total: float | None = None
    patrimonio: float | None = None
    utilidad_operacional: float | None = None
    gastos_intereses: float | None = None

    @property
    def completa(self) -> bool:
        return None not in (self.activo_corriente, self.activo_total, self.pasivo_corriente, self.pasivo_total,
                            self.patrimonio, self.utilidad_operacional, self.gastos_intereses)


@dataclass
class Rup:
    nombre: str = ""
    nit: str = ""
    fecha_expedicion: date | None = None
    fecha_constitucion: date | None = None
    tamano_empresa: str = ""
    # Primeras líneas del certificado (para reconocer siglas del nombre).
    encabezado: str = ""
    financiera: InformacionFinanciera | None = None
    experiencias: dict[str, ExperienciaRup] = field(default_factory=dict)

    @property
    def es_mipyme(self) -> bool | None:
        if not self.tamano_empresa:
            return None
        return any(t in self.tamano_empresa for t in ("MICRO", "PEQUENA", "MEDIANA"))


def texto_del_pdf(contenido: bytes) -> str:
    documento = pypdfium2.PdfDocument(contenido)
    try:
        paginas = []
        for i in range(len(documento)):
            pagina = documento[i]
            textpage = pagina.get_textpage()
            paginas.append(textpage.get_text_range())
            textpage.close()
            pagina.close()
        return "\n".join(paginas)
    finally:
        documento.close()


def _sin_encabezados(texto_norm: str) -> str:
    return "\n".join(linea for linea in texto_norm.splitlines() if not _ENCABEZADO_RE.match(linea))


def _campo(patron: re.Pattern, bloque: str) -> str:
    m = patron.search(bloque)
    return " ".join(m.group(1).split()) if m else ""


_VALOR_PESOS = r"\$?\s*(-?\s*\(?[\d.,]+\)?)"
_CAMPOS_FINANCIEROS = {
    "activo_corriente": rf"ACTIVO\s+CORRIENTE\s*:\s*{_VALOR_PESOS}",
    "activo_total": rf"ACTIVO\s+TOTAL\s*:\s*{_VALOR_PESOS}",
    "pasivo_corriente": rf"PASIVO\s+CORRIENTE\s*:\s*{_VALOR_PESOS}",
    "pasivo_total": rf"PASIVO\s+TOTAL\s*:\s*{_VALOR_PESOS}",
    "patrimonio": rf"PATRIMONIO(?:\s+NETO)?\s*:\s*{_VALOR_PESOS}",
    "utilidad_operacional": rf"UTILIDAD(?:/PERDIDA)?\s+OPERACIONAL\s*:\s*{_VALOR_PESOS}",
    "gastos_intereses": rf"GASTOS?\s+DE\s+INTERESES\s*:\s*{_VALOR_PESOS}",
}
_CORTE_RE = re.compile(r"FECHA\s+(?:DE\s+)?CORTE\s+DE\s+LA\s+INFORMACION\s+FINANCIERA\s*:\s*(\d{1,4})[/-](\d{1,2})[/-](\d{1,4})")


def _pesos(texto: str) -> float | None:
    negativo = "-" in texto or "(" in texto
    valor = numero(re.sub(r"[^\d.,]", "", texto))
    return None if valor is None else (-valor if negativo else valor)


def leer_financiera(cuerpo: str) -> InformacionFinanciera | None:
    """La sección "INFORMACIÓN FINANCIERA" más reciente del certificado
    (algunos traen varios años; el primero es el último corte)."""
    inicio = cuerpo.find("INFORMACION FINANCIERA")
    while inicio >= 0 and not re.search(r"ACTIVO\s+CORRIENTE", cuerpo[inicio:inicio + 1500]):
        inicio = cuerpo.find("INFORMACION FINANCIERA", inicio + 10)
    if inicio < 0:
        return None
    seccion = cuerpo[inicio:inicio + 2500]
    info = InformacionFinanciera()
    if m := _CORTE_RE.search(seccion):
        a, b, c = (int(x) for x in m.groups())
        try:
            info.fecha_corte = date(a, b, c) if a > 31 else date(c, b, a)
        except ValueError:
            pass
    for campo, patron in _CAMPOS_FINANCIEROS.items():
        if m := re.search(patron, seccion):
            setattr(info, campo, _pesos(m.group(1)))
    return info


def _clases(bloque: str) -> set[str]:
    clases = {"".join(g[0:3]) or "".join(g[4:7]) for g in _CODIGO_RE.findall(bloque)}
    tabla = bloque.find("CLASIFICADOR DE BIENES")
    if tabla >= 0:
        clases |= {a + b + c for a, b, c, _ in _CODIGO_SUELTO_RE.findall(bloque[tabla:])}
    return clases


def leer_rups(texto: str) -> list[Rup]:
    """Todos los certificados del texto: algunos proponentes juntan los RUP
    de sus integrantes en un solo PDF."""
    norm = normalizar(texto.replace("\r", ""))
    inicios = [m.start() for m in _IDENTIFICACION_RE.finditer(norm)]
    if len(inicios) <= 1:
        return [leer_rup(texto)]
    rups = []
    for i, inicio in enumerate(inicios):
        # El encabezado (fecha de expedición) va antes de la identificación.
        desde = max(inicios[i - 1] if i else 0, inicio - 2500) if i else 0
        hasta = inicios[i + 1] - 2500 if i + 1 < len(inicios) else len(norm)
        rups.append(leer_rup(norm[desde:max(hasta, inicio + 1)]))
    return rups


def leer_rup(texto: str) -> Rup:
    norm = normalizar(texto.replace("\r", ""))
    rup = Rup()
    try:
        if m := _FECHA_EXPEDICION_RE.search(norm):
            rup.fecha_expedicion = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        elif m := _FECHA_ISO_EXPEDICION_RE.search(norm):
            rup.fecha_expedicion = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        elif (m := _FECHA_BOGOTA_RE.search(norm)) and m.group(2) in _MESES:
            rup.fecha_expedicion = date(int(m.group(3)), _MESES[m.group(2)], int(m.group(1)))
    except ValueError:
        pass
    cuerpo = _sin_encabezados(norm)
    try:
        if m := _CONSTITUCION_RE.search(cuerpo):
            rup.fecha_constitucion = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        elif m := _CONSTITUCION_ISO_RE.search(cuerpo):
            rup.fecha_constitucion = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        elif (m := _CONSTITUCION_BOGOTA_RE.search(cuerpo[:20000])) and m.group(2) in _MESES:
            rup.fecha_constitucion = date(int(m.group(3)), _MESES[m.group(2)], int(m.group(1)))
    except ValueError:
        pass
    rup.nombre = _campo(_NOMBRE_RE, cuerpo)
    rup.encabezado = cuerpo[:4000]
    rup.financiera = leer_financiera(cuerpo)
    rup.nit = re.sub(r"\s", "", _campo(_NIT_RE, cuerpo))
    if m := _TAMANO_RE.search(cuerpo):
        rup.tamano_empresa = " ".join((m.group(1) or m.group(2) or "").split())

    marcas = list(_EXPERIENCIA_RE.finditer(cuerpo))
    for i, marca in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(cuerpo)
        bloque = cuerpo[marca.end() if marca.group(1) else marca.start():fin]
        consecutivo = _campo(_CONSECUTIVO_RE, bloque)
        if not consecutivo:
            continue
        # Lo que viene después del último código ya es otra sección del
        # certificado (sanciones, etc.): no importa, solo se leen campos.
        participacion = numero(_campo(_PARTICIPACION_RE, bloque))
        experiencia = ExperienciaRup(
            consecutivo=consecutivo.lstrip("0") or "0",
            numero=int(marca.group(1)) if marca.group(1) else i + 1,
            celebrado_por=_campo(_CELEBRADO_RE, bloque),
            contratista=_campo(_CONTRATISTA_RE, bloque),
            contratante=_campo(_CONTRATANTE_RE, bloque),
            valor_smmlv=numero(_campo(_VALOR_RE, bloque)),
            participacion=None if participacion is None else participacion / 100,
            clases=_clases(bloque),
        )
        rup.experiencias[experiencia.consecutivo] = experiencia
    return rup
