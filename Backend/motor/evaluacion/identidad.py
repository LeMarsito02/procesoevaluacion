"""Copia del documento de identidad de los representantes (requisito que
agrega el pliego: "fotocopia del documento de identificación del
representante legal").

Se exige la cédula de cada representante a quien se le verifican
antecedentes (el del proponente o los del consorcio) y, si el parámetro
`identidad_suplente` está activo, también la del suplente que figure en el
certificado de existencia: un abogado rechazó una oferta porque "no fue
posible validar los antecedentes de la representante legal suplente ya que
no se aportó copia de la cédula".

La cédula suele venir escaneada: se reconoce por sus marcas (identificación
personal, índice derecho, NUIP, Registraduría) y se empareja con la persona
por su número (tolerando un dígito mal leído por el OCR) o por su nombre.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date

from motor import criterios
from motor.evaluacion.camara_comercio import (
    PISTAS_EXISTENCIA,
    TITULO_EXISTENCIA_RE,
    _evaluar_proponente_camara,
    _texto_completo,
    encontrar_documentos,
)
from motor.evaluacion.formato1 import _nombres_coinciden, _norm
from motor.evaluacion.proponente_plural import obtener_personas_a_verificar
from motor.esquemas.proceso import PersonaAntecedente, ProcesoDocumentoBase, Proponente, ResultadoRequisito
from motor.procesamiento.memoria_proponente import memo_por_pdfs
from motor.llm.vision import LecturaVision
from motor.procesamiento.pdf_utils import abrir_pdf, paginas_ocr_reforzado, texto_ocr_reforzado, texto_pagina

MARCAS_CEDULA_RE = re.compile(
    r"IDENTIFICACION\s+PERSONAL|INDICE\s+DERECHO|\bNUIP\b|REGISTRADUR[IA]A?\s+NACIONAL|REGISTRADOR\s+NACIONAL"
    r"|FECHA\s+Y\s+LUGAR\s+DE\s+NACIMIENTO|LUGAR\s+DE\s+NACIMIENTO|ESTATURA|G\.?\s?S\.?\s+RH"
)
# Documentos que citan cédulas sin ser la cédula.
NO_ES_CEDULA_RE = re.compile(
    r"CERTIFICA|PROCURADURIA|CONTRALORIA|POLICIA NACIONAL|MEDIDAS CORRECTIVAS|DEUDORES ALIMENTARIOS|CAMARA DE COMERCIO"
    r"|FORMATO\s+\d|CARTA DE PRESENTACION|SENORES"
)
PISTAS_CEDULA = ("cedula", "cc", "c.c", "identidad", "documento", "rl", "representante", "ci ", "id")
PAGINAS_CON_PISTA = 20
PAGINAS_SIN_PISTA = 6
PAGINAS_REFORZADAS = 4

# Suplente en el certificado de existencia: "REPRESENTANTE LEGAL SUPLENTE
# SANDRA STELLA MORENO BUITRAGO C.C. NO. 35.254.078", "GERENTE SUPLENTE
# CAROLINA CUELLAR PASTRANA C.C. NO. 1.075.303.013".
SUPLENTE_RE = re.compile(
    r"(?:REPRESENTANTE\s+LEGAL\s+SUPLENTE|SUPLENTE\s+DEL\s+(?:REPRESENTANTE\s+LEGAL|GERENTE)|GERENTE\s+SUPLENTE|SUBGERENTE)"
    r"\s+([A-ZÑ][A-ZÑ ]{5,60}?)\s+(?:C\.?\s?C\.?|CEDULA\s+DE\s+CIUDADANIA)\s*(?:NO\.?\s*)?(\d[\d.]{5,})"
)


def _digitos(texto: str) -> str:
    """Solo los dígitos, sin ceros a la izquierda: la Cámara de Comercio
    escribe las cédulas rellenas con ceros ("C.C. 000000079939017")."""
    return re.sub(r"\D", "", texto).lstrip("0")


@memo_por_pdfs
def paginas_cedula(pdfs: dict[str, bytes]) -> list[tuple[str, str]]:
    """(archivo, texto) de las páginas que parecen una cédula."""
    return [(archivo, texto) for archivo, _, texto in paginas_cedula_numeradas(pdfs)]


@memo_por_pdfs
def paginas_cedula_numeradas(pdfs: dict[str, bytes]) -> list[tuple[str, int, str]]:
    """(archivo, número de página, texto) de las páginas que parecen una
    cédula. El número importa para mostrarle a la IA la página correcta: en un
    paquete de 30 páginas la cédula puede estar en la 7."""
    paginas = []
    for nombre, contenido in pdfs.items():
        base = nombre.rsplit("/", 1)[-1].lower()
        limite = PAGINAS_CON_PISTA if any(p in base for p in PISTAS_CEDULA) else PAGINAS_SIN_PISTA
        try:
            with abrir_pdf(contenido) as pdf:
                for page in pdf.pages[:limite]:
                    texto = texto_pagina(page)
                    numero = page.page_number
                    page.flush_cache()
                    texto_norm = _norm(texto)
                    if MARCAS_CEDULA_RE.search(texto_norm) and not NO_ES_CEDULA_RE.search(texto_norm):
                        paginas.append((nombre, numero, texto_norm))
        except Exception:  # noqa: BLE001
            continue
    return paginas


def _numero_en(numero: str, texto_norm: str, exacto: bool = False) -> bool:
    """El número de cédula está en el texto, con a lo sumo un dígito mal
    leído (el OCR confunde 1/7, 0/8, 5/6…)."""
    if len(numero) < 6:
        return False
    for candidato in re.findall(r"\d[\d.,\s]{5,16}\d", texto_norm):
        d = _digitos(candidato)
        if d == numero:
            return True
        if not exacto and len(d) == len(numero) and sum(a != b for a, b in zip(d, numero)) <= 1:
            return True
    return False


_ARCHIVO_CEDULA_RE = re.compile(r"CEDULA|\bC\.?\s?C\b|DOCUMENTO\s+DE\s+IDENTIDAD|\bDI\b|\bDCTO\b|\bDOC\b|IDENTIFICACION")


# Archivo de la cédula del representante legal: "CEDULA REPRESENTANTE
# LEGAL", "2. CEDULA REP LEGAL", "acedula-rl-consorcio", "Dcto Representante
# Legal".
# "LEGAL" solo no basta: "DOC LEGAL MEGB" es la carpeta de documentos legales
# de otra persona (así se le asignó la cédula de la suplente a la
# representante, una aprobación indebida).
_ARCHIVO_DEL_REPRESENTANTE_RE = re.compile(r"REPRESENTANTE|REP\.?\s*LEGAL|\bR\.?\s?L\b|\bRL\b")


_PALABRAS_DE_LA_CEDULA = {
    "REPUBLICA", "COLOMBIA", "IDENTIFICACION", "PERSONAL", "CEDULA", "CIUDADANIA", "NUMERO", "APELLIDOS", "NOMBRES",
    "FIRMA", "FECHA", "LUGAR", "NACIMIENTO", "EXPEDICION", "ESTATURA", "SEXO", "INDICE", "DERECHO", "REGISTRADOR",
    "NACIONAL", "DE", "DEL", "LA", "Y",
}


def _nombre_completo_en(nombre: str, texto: str) -> bool:
    """Todas las palabras del nombre (salvo una, si tiene cuatro o más) están
    en la página. Con dos en común no basta: «MARTA EUGENIA GARCÍA BETANCUR»
    y «EUGENIA GARCÍA LÓPEZ» comparten dos y son personas distintas."""
    partes = [p for p in re.findall(r"[A-ZÑ]{2,}", _norm(nombre)) if p not in _PALABRAS_DE_LA_CEDULA]
    if len(partes) < 2:
        return False
    en_pagina = set(re.findall(r"[A-ZÑ]{2,}", texto))
    faltan = sum(1 for p in partes if p not in en_pagina)
    return faltan == 0 or (len(partes) >= 4 and faltan == 1)


def _es_suyo(nombre: str, numero: str, texto: str) -> bool:
    """La página es de esta persona: trae su número exacto, o su nombre
    completo y ninguna otra cédula legible.

    Un número con un dígito distinto puede ser un error del OCR… o la cédula
    de un hermano: dos cédulas expedidas el mismo día son consecutivas
    (1.020.304.050 y 1.020.304.051). Por eso con un dígito distinto se exige
    además el nombre completo."""
    if numero and _numero_en(numero, texto, exacto=True):
        return True
    if numero and _numero_en(numero, texto):
        return _nombre_completo_en(nombre, texto)
    if numero and _de_otra_persona(numero, texto):
        return False
    return _nombre_completo_en(nombre, texto)


def _de_otra_persona(numero: str, texto_norm: str) -> bool:
    """La página trae una cédula legible que no es la de esta persona. El
    reverso de la cédula repite el número en su código ("…-F-0043001767-…"):
    si hay números con forma de cédula y ninguno es el suyo, es de otro."""
    if len(numero) < 6:
        return False
    candidatos = {d.lstrip("0") for d in re.findall(r"\d{7,11}", re.sub(r"[.\s]", "", texto_norm))}
    candidatos = {d for d in candidatos if 6 <= len(d) <= 10}
    return bool(candidatos) and not any(_numero_en(numero, d) for d in candidatos)


def cedula_de(pdfs: dict[str, bytes], nombre: str, cedula: str | None, principal: bool = False) -> str | None:
    """Archivo con la copia de la cédula de la persona, o None: una página de
    cédula con su número o su nombre (releída con el OCR reforzado si el
    normal no alcanza), o que está en un archivo llamado "cédula <su
    nombre>" o, si es el representante principal, "cédula representante
    legal" (el reverso de la cédula no trae ni nombre ni número)."""
    numero = _digitos(cedula or "")
    paginas = paginas_cedula(pdfs)
    for archivo, texto in paginas:
        if _es_suyo(nombre, numero, texto):
            return archivo
        # Si la página muestra la cédula de otra persona, el nombre del
        # archivo no la vuelve suya.
        if _de_otra_persona(numero, texto):
            continue
        base = _norm(archivo.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        if _ARCHIVO_CEDULA_RE.search(base) and _nombre_en_archivo(nombre, base):
            return archivo
        # La página ya es una cédula: si el archivo es "del representante
        # legal" ("Dcto Representante Legal", "EXISTENCIA Y RL"), es la suya.
        if principal and _ARCHIVO_DEL_REPRESENTANTE_RE.search(base):
            return archivo
    for archivo in dict.fromkeys(a for a, _ in paginas):
        try:
            reforzado = _norm(texto_ocr_reforzado(pdfs[archivo], max_paginas=PAGINAS_REFORZADAS))
        except Exception:  # noqa: BLE001
            continue
        if reforzado and _es_suyo(nombre, numero, reforzado):
            return archivo
    return None


PAGINAS_MAXIMAS_ARCHIVO_CEDULA = 3


def archivo_cedula_por_nombre(pdfs: dict[str, bytes], nombre: str, cedula: str | None, principal: bool = False) -> str | None:
    """Archivo corto llamado como la cédula de la persona ("CC ADRIANA ROJAS
    RL", "CEDULA CEGG") cuyo escaneo es tan malo que el OCR no reconoce la
    página como cédula. Solo sirve para buscar ahí la fecha de expedición (la
    IA tiene que leer el mismo número de cédula) y para mostrárselo a quien
    la escribe a mano; no cuenta como copia de la cédula en el requisito de
    identidad."""
    numero = _digitos(cedula or "")
    bases = {a: _norm(a.rsplit("/", 1)[-1].rsplit(".", 1)[0]) for a in sorted(pdfs)}
    candidatos = [a for a, b in bases.items() if _ARCHIVO_CEDULA_RE.search(b) and _nombre_en_archivo(nombre, b)]
    if not candidatos and principal:
        # "CC R.L.", "CEDULA REPRESENTANTE LEGAL": sirve para el representante
        # legal solo si hay uno solo así.
        del_representante = [a for a, b in bases.items()
                             if _ARCHIVO_CEDULA_RE.search(b) and _ARCHIVO_DEL_REPRESENTANTE_RE.search(b)]
        candidatos = del_representante if len(del_representante) == 1 else []
    for archivo in candidatos:
        try:
            with abrir_pdf(pdfs[archivo]) as pdf:
                if len(pdf.pages) > PAGINAS_MAXIMAS_ARCHIVO_CEDULA:
                    continue
            texto = _norm(texto_ocr_reforzado(pdfs[archivo], max_paginas=PAGINAS_MAXIMAS_ARCHIVO_CEDULA))
        except Exception:  # noqa: BLE001
            continue
        if not _de_otra_persona(numero, texto):
            return archivo
    return None


_NO_SON_INICIALES = {"DOC", "DOCS", "RUT", "RUP", "CED", "CCO", "RLS", "TPS", "PDF", "ACT", "COP", "CAM", "EXP", "ANT", "SEG"}


def _nombre_en_archivo(nombre: str, base: str) -> bool:
    """El archivo (ya reconocido como cédula) es de esta persona: trae su
    nombre ("CEDULA JUAN JOSE ARAQUE"), su primer nombre ("CEDULA Y TARJETA
    DANIELA") o sus iniciales ("C.C., T.P. Y COPNIA JAL" = Juan Amado Lizarazo)."""
    palabras = set(re.findall(r"[A-ZÑ]{2,}", base))
    partes = [p for p in re.findall(r"[A-ZÑ]+", _norm(nombre)) if p not in {"DE", "DEL", "LA", "LOS", "Y"}]
    if not partes:
        return False
    if _nombres_coinciden(nombre, " ".join(palabras)):
        return True
    if len(partes[0]) >= 4 and partes[0] in palabras:
        return True
    iniciales = {"".join(p[0] for p in partes), "".join(p[0] for p in partes[:3]), partes[0][0] + "".join(p[0] for p in partes[-2:])}
    # "DOC", "RUT", "RUP"… son palabras de nombres de archivo, no iniciales.
    return any(len(i) >= 3 and i in palabras and i not in _NO_SON_INICIALES for i in iniciales)


def suplentes_del_certificado(pdfs: dict[str, bytes]) -> list[tuple[str, str]]:
    suplentes = []
    for nombre in encontrar_documentos(pdfs, TITULO_EXISTENCIA_RE, PISTAS_EXISTENCIA):
        texto = re.sub(r"\s+", " ", _norm(_texto_completo(pdfs, nombre)))
        for m in SUPLENTE_RE.finditer(texto):
            persona = (re.sub(r"\s+", " ", m.group(1)).strip(), _digitos(m.group(2)))
            if not any(_nombres_coinciden(persona[0], s[0]) for s in suplentes):
                suplentes.append(persona)
    return suplentes


# En el reverso de la cédula: "05-JUN-2001 CARTAGENA FECHA Y LUGAR DE
# EXPEDICION". La fecha viene antes de la etiqueta, con la ciudad en medio, y
# el OCR daña la etiqueta con frecuencia ("FECHA Y LUEGAR", "EXPEDICIONF.20").
MESES_CEDULA = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
                "JUL": 7, "AGO": 8, "SEP": 9, "SET": 9, "OCT": 10, "NOV": 11, "DIC": 12}
FECHA_CEDULA_RE = re.compile(r"(\d{1,2})\s?[-/.]\s?([A-Z]{3})\s?[-/.]\s?(\d{4})")
# Cédula digital (desde 2020): la fecha va después de la etiqueta y con
# espacios: "FECHA Y LUGAR DE EXPEDICION 26 ENE 2000, BUCARAMANGA".
FECHA_CEDULA_DIGITAL_RE = re.compile(r"(\d{1,2})\s?[-/. ]\s?([A-Z]{3})\s?[-/. ]\s?(\d{4})")
DESPUES_DE_LA_ETIQUETA = 36
# Basta el comienzo: el OCR daña el final de la palabra con frecuencia
# ("EXPED&CION", "EXPEDIC|ON") aunque la fecha de al lado salga bien.
ETIQUETA_EXPEDICION_RE = re.compile(r"EXPED")
# Distancia máxima entre la fecha y la etiqueta (en medio va la ciudad).
CERCA_DE_LA_ETIQUETA = 70


def _fecha_de(match: re.Match[str]) -> date | None:
    mes = MESES_CEDULA.get(match.group(2))
    if not mes:
        return None
    try:
        fecha = date(int(match.group(3)), mes, int(match.group(1)))
    except ValueError:
        return None
    # Una cédula no se expide antes de 1960 ni después de hoy.
    return fecha if date(1960, 1, 1) <= fecha <= date.today() else None


# La etiqueta completa y sin daños del OCR: si está así, lo leído es de fiar.
ETIQUETA_LIMPIA_RE = re.compile(r"FECHA\s+Y\s+LUGAR\s+DE\s+EXPEDICION")


class LecturaFecha:
    """Qué fecha se leyó, de dónde y si se puede confiar en ella. Una fecha
    dudosa no sirve: consultar la página de la Policía con ella la rechaza y
    se gasta una consulta a una plataforma del Estado para nada."""

    def __init__(self, fecha: date | None, confiable: bool, fuente: str) -> None:
        self.fecha = fecha
        self.confiable = confiable
        self.fuente = fuente  # "ocr" | "ia" | "ninguna"

    def __repr__(self) -> str:  # pragma: no cover - ayuda al depurar
        return f"LecturaFecha({self.fecha}, confiable={self.confiable}, fuente={self.fuente!r})"


def lectura_ocr(texto_norm: str) -> LecturaFecha:
    """Lo que el OCR alcanzó a leer. Es de fiar solo si la etiqueta salió
    completa ("FECHA Y LUGAR DE EXPEDICION") y hay una sola fecha pegada a
    ella; con la etiqueta rota ("FECHA Y LUEGAR", "EXPEDICIONF.20") los
    dígitos de al lado también suelen venir mal leídos."""
    fecha = fecha_expedicion_en(texto_norm)
    if fecha is None:
        return LecturaFecha(None, False, "ninguna")
    limpia = bool(ETIQUETA_LIMPIA_RE.search(re.sub(r"\s+", " ", texto_norm)))
    return LecturaFecha(fecha, limpia, "ocr")


# Zona de lectura mecánica de la cédula digital, segunda línea:
# "7903270M3209136COL72007216<<<7" = nacimiento AAMMDD + control, sexo,
# vencimiento AAMMDD + control, "COL" y el número de cédula.
MRZ_RE = re.compile(r"(\d{6})(\d)([MF<])(\d{6})(\d)C[O0]L(\d{6,10})<")
# Fechas de la cédula digital con el mes dañado por el OCR ("31 00T 2012",
# "07 MAYO 1997", "13 SEPT 2032").
FECHA_DIGITAL_LAXA_RE = re.compile(r"\b(\d{1,2})\s?[-/. ]\s?([A-Z0-9]{3,4})\s?[-/. ]\s?((?:19|20)\d{2})\b")


def _digito_control(datos: str) -> int:
    """Dígito de control ICAO 9303 (pesos 7, 3, 1)."""
    valores = [int(c) if c.isdigit() else (ord(c) - 55 if c.isalpha() else 0) for c in datos]
    return sum(v * (7, 3, 1)[i % 3] for i, v in enumerate(valores)) % 10


def _fecha_mrz(aammdd: str, futuro: bool) -> date | None:
    anio, mes, dia = int(aammdd[:2]), int(aammdd[2:4]), int(aammdd[4:])
    siglo = 2000 if (futuro or anio <= date.today().year % 100) else 1900
    try:
        return date(siglo + anio, mes, dia)
    except ValueError:
        return None


def _mes_laxo(token: str) -> int | None:
    token = token.replace("0", "O").replace("1", "I")[:3]
    if token in MESES_CEDULA:
        return MESES_CEDULA[token]
    # Una sola letra dañada ("OOT" -> OCT), si no hay dos meses posibles.
    parecidos = {m for k, m in MESES_CEDULA.items() if sum(a != b for a, b in zip(k, token)) == 1}
    return parecidos.pop() if len(parecidos) == 1 else None


def fecha_expedicion_por_mrz(texto_norm: str, numero: str) -> date | None:
    """Cédula digital sin etiquetas legibles: la MRZ (con sus dígitos de
    control) dice cuáles son la fecha de nacimiento y la de vencimiento; si en
    la página queda exactamente otra fecha, es la de expedición. Solo si la
    MRZ trae el número de esta persona."""
    compacto = re.sub(r"\s+", "", texto_norm)
    for m in MRZ_RE.finditer(compacto):
        nacimiento_txt, c1, _, vence_txt, c2, cedula = m.groups()
        if numero and _digitos(cedula) != _digitos(numero):
            continue
        if _digito_control(nacimiento_txt) != int(c1) or _digito_control(vence_txt) != int(c2):
            continue
        nacimiento, vence = _fecha_mrz(nacimiento_txt, False), _fecha_mrz(vence_txt, True)
        if nacimiento is None or vence is None:
            continue
        otras = set()
        for f in FECHA_DIGITAL_LAXA_RE.finditer(re.sub(r"\s+", " ", texto_norm)):
            mes = _mes_laxo(f.group(2))
            if not mes:
                continue
            try:
                fecha = date(int(f.group(3)), mes, int(f.group(1)))
            except ValueError:
                continue
            # Fuera la de nacimiento y la de vencimiento (tolerando que el OCR
            # dañe un dígito del año o del día) y lo imposible.
            if any((fecha.month, fecha.day) == (d.month, d.day) or abs((fecha - d).days) < 400 for d in (nacimiento, vence)):
                continue
            if nacimiento < fecha <= date.today():
                otras.add(fecha)
        if len(otras) == 1:
            return otras.pop()
    return None


def fecha_expedicion_en(texto_norm: str) -> date | None:
    """La fecha de expedición que dice el reverso de la cédula, o None si no
    está clara. Se toma la fecha que está pegada a la etiqueta "FECHA Y LUGAR
    DE EXPEDICION"; la de nacimiento queda descartada porque está junto a su
    propia etiqueta, lejos de esta."""
    texto = re.sub(r"\s+", " ", texto_norm)
    candidatas: list[date] = []
    for etiqueta in ETIQUETA_EXPEDICION_RE.finditer(texto):
        trozo = texto[max(0, etiqueta.start() - CERCA_DE_LA_ETIQUETA) : etiqueta.start()]
        encontradas = [f for m in FECHA_CEDULA_RE.finditer(trozo) if (f := _fecha_de(m))]
        # Se queda con la más pegada a la etiqueta; si hay dos distintas igual
        # de cerca no se afirma nada.
        if encontradas:
            candidatas.append(encontradas[-1])
        despues = texto[etiqueta.end() : etiqueta.end() + DESPUES_DE_LA_ETIQUETA]
        siguiente = next((f for m in FECHA_CEDULA_DIGITAL_RE.finditer(despues) if (f := _fecha_de(m))), None)
        if siguiente:
            candidatas.append(siguiente)
    distintas = set(candidatas)
    return candidatas[0] if len(distintas) == 1 else None


VOTOS_MINIMOS = 3
# Fecha de la cédula con el OCR dañando letras y dígitos: "OB-FEB-2013",
# "19-AG0-1976", "03-0CT-1997", "2013VALLEDUPAR" (año pegado a la ciudad).
_FECHA_CON_MES_DANADO_RE = re.compile(
    r"(?<![A-Z0-9])([0-9OBISZ]{1,2})(\s?[-/. ]\s?)([A-Z0-9]{3})(\s?[-/. ]\s?)((?:19|20|I9|2O)[0-9OBISZ]{2})(?!\d)"
)
_LETRA_POR_DIGITO = str.maketrans("OBISZ", "08152")
_ABREVIATURA = {m: k for k, m in MESES_CEDULA.items() if k != "SET"}


def _arreglar_fechas(texto: str) -> str:
    """Pasa las fechas dañadas por el OCR a "DD-MMM-AAAA" limpio."""
    def arreglar(m: re.Match[str]) -> str:
        mes = _mes_laxo(m.group(3))
        if mes is None:
            return m.group(0)
        dia = m.group(1).translate(_LETRA_POR_DIGITO)
        anio = m.group(5).translate(_LETRA_POR_DIGITO)
        return f"{dia}-{_ABREVIATURA[mes]}-{anio} "

    return _FECHA_CON_MES_DANADO_RE.sub(arreglar, texto)


def _fecha_votada(texto_norm: str, numero: str) -> date | None:
    """La fecha de expedición que da una lectura: junto a la etiqueta (con el
    mes arreglado si el OCR lo dañó, "0CT" -> "OCT") o, en la cédula digital,
    por la MRZ."""
    texto = _arreglar_fechas(texto_norm)
    return fecha_expedicion_en(texto) or fecha_expedicion_por_mrz(texto, numero)


_NACIMIENTO_RE = re.compile(r"NAC\w{0,8}\W{0,12}(\d{1,2})\s?[-/. ]\s?([A-Z0-9]{3})\s?[-/. ]\s?((?:19|20)\d{2})")


def _nacimientos(textos: list[str]) -> set[date]:
    """Fechas de nacimiento que se leen junto a su etiqueta."""
    fechas = set()
    for texto in textos:
        for m in _NACIMIENTO_RE.finditer(re.sub(r"\s+", " ", texto)):
            mes = _mes_laxo(m.group(2))
            try:
                fecha = date(int(m.group(3)), mes, int(m.group(1))) if mes else None
            except ValueError:
                fecha = None
            if fecha and date(1900, 1, 1) < fecha < date.today():
                fechas.add(fecha)
    return fechas


# Línea de abajo del reverso de la cédula antigua:
# "A-1500150-01172910-F-0052371321-20201023" (sexo, número con ceros a la
# izquierda y fecha de impresión).
_NUMERO_DEL_REVERSO_RE = re.compile(r"[MF]\W{0,2}(\d{10})\W{0,2}(?:19|20)\d{6}")


def _reverso_es_suyo(numero: str, texto_norm: str) -> bool | None:
    """Según el número de la línea de abajo del reverso: True si es el suyo
    (con hasta dos dígitos mal leídos), False si es claramente otro y None
    si no se leyó."""
    leidos = [_digitos(m.group(1)) for m in _NUMERO_DEL_REVERSO_RE.finditer(re.sub(r"[\s.]", "", texto_norm))]
    if not leidos or len(numero) < 6:
        return None
    return any(len(d) == len(numero) and sum(a != b for a, b in zip(d, numero)) <= 2 for d in leidos)


def _ediciones(a: str, b: str) -> int:
    """Distancia de edición entre dos cadenas cortas de dígitos."""
    fila = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        anterior, fila[0] = fila[0], i
        for j, cb in enumerate(b, 1):
            anterior, fila[j] = fila[j], min(fila[j] + 1, fila[j - 1] + 1, anterior + (ca != cb))
    return fila[-1]


def _numero_parecido(numero: str, texto_norm: str) -> bool:
    """El número está en el texto con a lo sumo dos dígitos cambiados,
    sobrantes o faltantes ("00192715138" por 19275138). Solo se usa cuando el
    archivo ya se llama como la cédula de la persona."""
    if len(numero) < 6:
        return False
    compacto = re.sub(r"(?<=\d)[\s.,](?=\d)", "", texto_norm)
    return any(
        abs(len(d) - len(numero)) <= 2 and _ediciones(d, numero) <= 2
        for d in (c.lstrip("0") for c in re.findall(r"(?<!\d)\d{6,13}(?!\d)", compacto))
    )


def _archivo_con_su_nombre(archivo: str, nombre: str) -> bool:
    """El nombre del archivo trae su nombre y al menos un apellido ("CC
    ADRIANA ROJAS RL"), no solo iniciales."""
    base = set(re.findall(r"[A-ZÑ]{3,}", _norm(archivo.rsplit("/", 1)[-1].rsplit(".", 1)[0])))
    partes = [p for p in re.findall(r"[A-ZÑ]{3,}", _norm(nombre)) if p not in {"DEL", "LOS", "LAS"}]
    return len(partes) >= 3 and partes[0] in base and any(p in base for p in partes[-2:])


def _fecha_de_la_franja(texto_norm: str) -> date | None:
    """En la franja recortada ("…SEXO 17-OCT-1995 BOGOTA D.C. FECHA Y LUGAR DE
    EXPEDICION"), la fecha más cercana antes de la etiqueta; si la etiqueta no
    salió, la última fecha de la franja."""
    texto = _arreglar_fechas(re.sub(r"\s+", " ", texto_norm))
    etiqueta = ETIQUETA_EXPEDICION_RE.search(texto)
    antes = texto[: etiqueta.start()] if etiqueta else texto
    fechas = [f for m in FECHA_CEDULA_RE.finditer(antes) if (f := _fecha_de(m))]
    return fechas[-1] if fechas else None


def lecturas_de_paginas(contenido: bytes, ademas: frozenset[int] = frozenset()) -> tuple[dict[int, str], dict[int, str]]:
    """Texto normal y OCR reforzado (normalizados) de las primeras páginas
    del archivo de la cédula y de las páginas `ademas` (las que ya se vieron
    como cédula más adentro, p. ej. anexa al final del Formato 1)."""
    normales: dict[int, str] = {}
    try:
        with abrir_pdf(contenido) as pdf:
            for page in pdf.pages[:max([PAGINAS_REFORZADAS, *ademas])]:
                if page.page_number <= PAGINAS_REFORZADAS or page.page_number in ademas:
                    normales[page.page_number] = _norm(texto_pagina(page))
                page.flush_cache()
    except Exception:  # noqa: BLE001
        pass
    try:
        reforzadas = {
            n: _norm(t) for n, t in paginas_ocr_reforzado(contenido, max_paginas=PAGINAS_REFORZADAS, ademas=ademas)
        }
    except Exception:  # noqa: BLE001
        reforzadas = {}
    return normales, reforzadas


def leer_fecha_expedicion(
    pdfs: dict[str, bytes], nombre: str, cedula: str | None, principal: bool = False, con_ia: bool = True
) -> LecturaFecha:
    """La fecha de expedición de la cédula de esa persona, leída de la copia
    que viene en la oferta (los proponentes la escanean por ambos lados). La
    pide el RNMC para consultar sus antecedentes.

    Primero el texto del PDF, luego el OCR reforzado y, si alguno de los dos
    quedó dudoso (o no leyó nada), la IA local mira la imagen: está mejor
    preparada para escaneos torcidos o con sombras, y una fecha mal leída
    significa una consulta perdida a la página del Estado.

    Solo se lee de una página que sea demostrablemente suya (trae su número o
    su nombre): una carpeta puede traer las cédulas de varias personas y una
    fecha de otro no sirve para consultar nada."""
    archivo = cedula_de(pdfs, nombre, cedula, principal=principal)
    por_nombre = archivo is None
    archivo = archivo or archivo_cedula_por_nombre(pdfs, nombre, cedula, principal=principal)
    if archivo is None:
        return LecturaFecha(None, False, "ninguna")
    numero = _digitos(cedula or "")
    # Dos lecturas de cada página: el texto normal y el OCR reforzado (otro
    # tratamiento de la imagen). Página por página: un PDF puede traer las
    # cédulas de dos personas, y leerlo entero le asignaba a una la fecha de
    # la otra (pasó en un consorcio real).
    de_cedula = frozenset(n for a, n, _ in paginas_cedula_numeradas(pdfs) if a == archivo)
    normales, reforzadas = lecturas_de_paginas(pdfs[archivo], de_cedula)
    # Una página es suya si cualquiera de las dos lecturas trae su número o su
    # nombre (el reverso de la cédula a veces solo lo trae en una de ellas).
    suyas = sorted(
        n for n in set(normales) | set(reforzadas)
        if _es_suyo(nombre, numero, normales.get(n, "")) or _es_suyo(nombre, numero, reforzadas.get(n, ""))
    )
    # fecha -> (en cuántas lecturas salió, si alguna tenía la etiqueta limpia)
    vistas: dict[date, list[int | bool]] = {}
    for n in suyas:
        for texto in (normales.get(n, ""), reforzadas.get(n, "")):
            if not texto:
                continue
            lectura = lectura_ocr(texto)
            fecha, limpia = lectura.fecha, lectura.confiable
            if fecha is None:
                # Cédula digital sin etiquetas legibles: la MRZ dice cuáles
                # son el nacimiento y el vencimiento.
                fecha, limpia = fecha_expedicion_por_mrz(texto, numero), True
            if fecha is not None:
                visto = vistas.setdefault(fecha, [0, False])
                visto[0] += 1
                visto[1] = visto[1] or limpia
    dudosa = LecturaFecha(None, False, "ninguna")
    if len(vistas) == 1:
        # Una sola fecha: se usa si las dos lecturas la vieron o si al lado
        # estaba la etiqueta completa.
        fecha, (veces, limpia) = next(iter(vistas.items()))
        if veces >= 2 or limpia:
            return LecturaFecha(fecha, True, "ocr")
        dudosa = LecturaFecha(fecha, False, "ocr")
    elif vistas:
        # Las lecturas no coinciden (un 8 leído como 0, pasó con una cédula
        # real): ninguna se usa sola. Se sugiere la más repetida.
        fecha = max(vistas, key=lambda f: (vistas[f][0], vistas[f][1]))
        dudosa = LecturaFecha(fecha, False, "ocr")

    # Lectura a fondo: cada imagen incrustada derecha, sin el fondo de color y
    # con varios tratamientos (fotos de la cédula, imágenes giradas). Cada
    # lectura es un voto; se usa la fecha solo si al menos tres coinciden y
    # ninguna otra tiene más de un voto.
    from motor.procesamiento.ocr_cedula import lecturas_a_fondo

    votos: Counter[date] = Counter({f: v[0] for f, v in vistas.items()})
    nacimientos: set[date] = set()
    for n in suyas or sorted(normales)[:PAGINAS_MAXIMAS_ARCHIVO_CEDULA]:
        lecturas = lecturas_a_fondo(pdfs[archivo], n)
        paginas = [_norm(t) for t in lecturas.get("paginas", [])]
        franjas = [_norm(t) for t in lecturas.get("franjas", [])]
        todo = " ".join(paginas + franjas)
        # Suya si alguna lectura trae su número o su nombre; o si el archivo
        # se llama como su cédula y el número sale con a lo sumo un dígito
        # dañado (el reverso solo lo trae en el código de abajo).
        if n not in suyas and not _es_suyo(nombre, numero, todo) and not (
            por_nombre and _reverso_es_suyo(numero, todo) is not False
            and (_numero_parecido(numero, todo) or _reverso_es_suyo(numero, todo) or _archivo_con_su_nombre(archivo, nombre))
        ):
            continue
        nacimientos |= _nacimientos(paginas + franjas + list(normales.values()) + list(reforzadas.values()))
        for texto in paginas:
            fecha = _fecha_votada(texto, numero)
            if fecha:
                votos[fecha] += 1
        for texto in franjas:
            fecha = _fecha_de_la_franja(texto)
            if fecha:
                votos[fecha] += 1
    # La franja a veces toma la línea del nacimiento: esa fecha (y sus
    # variantes con el año mal leído) no es la de expedición, y nadie recibe
    # la cédula antes de los 17 años.
    for fecha in list(votos):
        if any((fecha.month, fecha.day) == (d.month, d.day) or fecha < d.replace(year=d.year + 17) for d in nacimientos):
            del votos[fecha]
    if votos:
        (fecha, veces), *resto = votos.most_common()
        segundo = resto[0][1] if resto else 0
        if veces >= VOTOS_MINIMOS and veces >= 3 * segundo:
            return LecturaFecha(fecha, True, "ocr")
        dudosa = LecturaFecha(fecha, False, "ocr")

    if not con_ia:
        return dudosa

    from motor.llm.vision import leer_cedula_detallado

    # Solo las páginas que parecen cédula, no las primeras del archivo: en un
    # paquete de documentos la cédula puede estar en cualquier página.
    paginas = [n for a, n, _ in paginas_cedula_numeradas(pdfs) if a == archivo]
    try:
        de_la_ia = leer_cedula_detallado(pdfs[archivo], cedula, paginas=paginas)
    except Exception:  # noqa: BLE001
        de_la_ia = LecturaVision(None)
    if de_la_ia.fecha is None:
        return dudosa
    # Se da por buena cuando dos miradas coinciden, o cuando la IA confirma lo
    # que el OCR había leído a medias. Una sola lectura se sugiere, no se usa.
    segura = de_la_ia.confirmada or de_la_ia.fecha in votos
    return LecturaFecha(de_la_ia.fecha, segura, "ia")


# Al evaluar un proceso completo la IA puede tardar mucho en una GPU pequeña:
# con 0 la evaluación usa solo el lector de texto y la IA queda para cuando se
# pide consultar. En producción (GPU de 24 GB) conviene 1.
VISION_EN_EVALUACION = __import__("os").environ.get("VISION_EN_EVALUACION", "0") == "1"


@memo_por_pdfs
def fecha_de_la_persona(pdfs: dict[str, bytes], nombre: str, cedula: str | None, principal: bool = False) -> date | None:
    """La fecha de expedición de su cédula, confiable, para dejarla en la
    ficha de la persona al evaluar (una sola vez por persona y oferta)."""
    try:
        lectura = leer_fecha_expedicion(pdfs, nombre, cedula, principal=principal, con_ia=VISION_EN_EVALUACION)
    except Exception:  # noqa: BLE001
        return None
    return lectura.fecha if lectura.confiable else None


def fecha_expedicion_cedula(pdfs: dict[str, bytes], nombre: str, cedula: str | None, principal: bool = False) -> date | None:
    """Solo la fecha cuando es de fiar (para guardarla sin que nadie la revise)."""
    lectura = leer_fecha_expedicion(pdfs, nombre, cedula, principal=principal)
    return lectura.fecha if lectura.confiable else None


class ResultadoIdentidad:
    def __init__(self, cumple: bool, motivo: str | None, archivo: str | None,
                 personas: list[PersonaAntecedente] | None = None) -> None:
        self.cumple = cumple
        self.motivo = motivo
        self.archivo = archivo
        # Cada persona a la que se le exige la copia de su documento, con la
        # fecha de expedición que dice el reverso (la pide el RNMC).
        self.personas = personas or []


def evaluar_identidad(pdfs: dict[str, bytes], proceso: ProcesoDocumentoBase, tipo_proponente: str | None) -> ResultadoIdentidad:
    personas = [(n, c) for n, c in obtener_personas_a_verificar(pdfs, tipo_proponente, proceso.codigo_proceso)]
    if not personas:
        return ResultadoIdentidad(
            cumple=False,
            motivo="no se pudo identificar al representante legal para buscar la copia de su documento de identidad — revisa manualmente",
            archivo=None,
        )
    if criterios.valor("identidad_suplente") and tipo_proponente not in ("consorcio", "union_temporal", "persona_natural"):
        for suplente in suplentes_del_certificado(pdfs):
            if not any(_nombres_coinciden(suplente[0], p[0]) for p in personas):
                personas.append(suplente)
    faltan, archivo = [], None
    detalle: list[PersonaAntecedente] = []
    rol = "proponente" if tipo_proponente == "persona_natural" else "representante_legal"
    for indice, (nombre, cedula) in enumerate(personas):
        encontrado = cedula_de(pdfs, nombre, cedula, principal=indice == 0)
        fecha = None
        if encontrado is None:
            faltan.append(nombre)
        else:
            archivo = archivo or encontrado
            # La fecha solo si la página es suya (trae su número o su nombre).
            fecha = next(
                (f for a, texto in paginas_cedula(pdfs)
                 if a == encontrado and _es_suyo(nombre, _digitos(cedula or ""), texto) and (f := fecha_expedicion_en(texto))),
                None,
            )
        detalle.append(PersonaAntecedente(
            nombre=nombre,
            documento=_digitos(cedula or "") or None,
            tipo="natural",
            rol=rol if indice == 0 else ("suplente" if indice == 1 else "integrante"),
            estado="cumple" if encontrado else "falta",
            archivo=encontrado,
            fecha_expedicion_documento=fecha,
        ))
    if faltan:
        return ResultadoIdentidad(
            cumple=False,
            motivo=(
                f"no se encontró la copia del documento de identidad de {', '.join(faltan)} — confirma si se aportó "
                "(la cédula escaneada puede no leerse)"
            ),
            archivo=archivo,
            personas=detalle,
        )
    return ResultadoIdentidad(cumple=True, motivo=None, archivo=archivo, personas=detalle)


def evaluar_proponente_identidad(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_camara(20, evaluar_identidad, proponente, proceso)
