from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

import pdfplumber
from dateutil.relativedelta import relativedelta

from motor.esquemas.proceso import GarantiaSeriedad, Lote, ProcesoDocumentoBase

MONEY_RE = re.compile(r"\$\s*([\d.,]+)")
MONTHS_RE = re.compile(r"\((\d+)\)\s*MES", re.IGNORECASE)
PERCENT_RE = re.compile(r"\((\d+(?:[.,]\d+)?)\s*%\)")
# "Lote 1", "Lote No. 1", "Lote N° 1", "Segmento 2". Sin el "No." de por medio,
# un proceso de dos lotes se leía como uno solo y su presupuesto salía siendo el
# del primer lote.
LOTE_ROW_RE = re.compile(r"^(LOTE|SEGMENTO)\s*(?:N[O°ºª]?\s*\.?\s*)?\d+", re.IGNORECASE)

DEFAULT_VIGENCIA_MESES = 3
DEFAULT_PORCENTAJE = 0.10


def _norm(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _parse_money(text: str | None) -> float | None:
    if not text:
        return None
    match = MONEY_RE.search(text)
    if not match:
        return None
    raw = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


_MESES_EN_LETRAS = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7,
    "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}
# "HASTA EL 31 DE DICIEMBRE DE 2026": el plazo dicho como la fecha en que termina.
_FECHA_LIMITE_RE = re.compile(
    r"HASTA\s+EL\s+(\d{1,2})\s+DE\s+(" + "|".join(_MESES_EN_LETRAS) + r")\s+DE\s+(\d{4})",
    re.IGNORECASE)


def _fecha_limite(texto: str | None) -> date | None:
    """La fecha en que termina el contrato, cuando el pliego la da en vez de los
    meses de plazo."""
    if not texto:
        return None
    m = _FECHA_LIMITE_RE.search(re.sub(r"\s+", " ", _strip_accents(texto.upper())))
    if m is None:
        return None
    try:
        return date(int(m.group(3)), _MESES_EN_LETRAS[m.group(2).upper()], int(m.group(1)))
    except ValueError:
        return None


def _parse_months(text: str | None) -> int | None:
    if not text:
        return None
    match = MONTHS_RE.search(text)
    return int(match.group(1)) if match else None


@dataclass
class ParsedLote:
    numero: str
    objeto: str
    plazo_meses: int | None
    valor_presupuesto: float | None
    lugar_ejecucion: str | None
    # Hay pliegos que no dan el plazo en meses sino la fecha en que termina
    # ("HASTA EL 31 DE DICIEMBRE DE 2026"). Los meses se calculan después, que es
    # cuando se sabe la fecha de cierre del proceso.
    plazo_hasta: date | None = None


@dataclass
class ParsedGarantia:
    vigencia_meses: int | None
    porcentaje: float | None
    base_calculo: str
    raw_vigencia: str = ""
    raw_valor: str = ""
    # Página (desde 1) del numeral, para poder abrir el pliego ahí.
    pagina: int | None = None


@dataclass
class ParseResult:
    objeto_general: str
    lotes: list[ParsedLote] = field(default_factory=list)
    garantia: ParsedGarantia | None = None
    modalidad: str | None = None
    tarjeta_suplible: bool = False
    tarjeta_exigida: bool = False
    # Páginas (desde 1) donde se encontró cada cosa, para poder abrir el pliego
    # ahí y comprobarlo.
    pagina_objeto: int | None = None
    pagina_garantia: int | None = None


# "El requisito de la tarjeta profesional se puede suplir con el registro de
# que trata el artículo 18 del Decreto-Ley 2106 de 2019."
TARJETA_SUPLIBLE_RE = re.compile(r"tarjeta profesional se (?:puede|podr[áa]) suplir con el registro", re.IGNORECASE)

# Sección del aval: "…la oferta tendrá que ser avalada por un ingeniero, para
# lo cual adjuntará…" hasta "El aval del ingeniero… hace parte integral". Unos
# pliegos piden ahí solo el certificado COPNIA; otros, además, la copia de la
# tarjeta profesional.
_AVAL_RE = re.compile(r"avalada por un ingeniero(.{0,1500}?)(?:hace parte integral|$)", re.IGNORECASE | re.S)


def _aval_pide_tarjeta(texto: str) -> bool:
    """La sección del aval del ingeniero pide copia de la tarjeta profesional
    y no dice que se pueda suplir con el registro."""
    for m in _AVAL_RE.finditer(texto):
        seccion = m.group(1)
        if re.search(r"tarjeta profesional", seccion, re.IGNORECASE) and not TARJETA_SUPLIBLE_RE.search(seccion):
            return True
    return False


# ---------------------------------------------------------------- escaneados
#
# Hay entidades que publican el Documento Base escaneado: el PDF solo trae como
# texto el encabezado y el pie, y todo el cuerpo es una imagen. Ahí
# extract_text() devuelve el mismo encabezado en las 95 páginas y no se
# encuentra ni la tabla de objeto y presupuesto ni el numeral de la garantía, así
# que el proceso se crea sin lotes y con la garantía por defecto —que es
# exactamente el aviso que veía el usuario—.
#
# El motor ya sabe leer páginas escaneadas (motor/procesamiento/pdf_utils, con
# tesseract y caché por página); lo que faltaba era usarlo aquí. Como cada página
# cuesta unos dos segundos la primera vez, se hace OCR solo si el documento lo
# necesita y solo en las páginas donde puede estar lo que se busca.

# Cuántas páginas del principio se miran para decidir si está escaneado, y
# cuánto texto propio debería traer una página que no lo esté.
_PAGINAS_DE_MUESTRA = 6
_TEXTO_MINIMO_POR_PAGINA = 400
# Hasta dónde se busca la tabla de objeto y presupuesto en un escaneado: es el
# numeral 1.1, siempre al principio.
_MAX_PAGINAS_ENCABEZADO = 25


def _es_escaneado(pdf: pdfplumber.PDF) -> bool:
    """Si el cuerpo del documento es una imagen. Se mide con las primeras
    páginas: si apenas traen texto y sí traen imágenes, está escaneado."""
    paginas = pdf.pages[:_PAGINAS_DE_MUESTRA]
    if not paginas:
        return False
    textos, con_imagen = [], 0
    for page in paginas:
        textos.append(len((page.extract_text() or "").strip()))
        con_imagen += bool(page.images)
    return sum(textos) / len(textos) < _TEXTO_MINIMO_POR_PAGINA and con_imagen >= len(paginas) / 2


def _texto(page, escaneado: bool) -> str:
    """El texto de la página, con OCR si esa página lo necesita.

    La decisión es por página, no por documento: hay pliegos con la portada y el
    índice en texto y el cuerpo escaneado, y mirando solo el principio se
    concluiría que no hace falta OCR justo en las páginas que sí. De eso ya se
    encarga `texto_pagina_tabla`, que usa el texto propio de la página cuando lo
    tiene y solo hace OCR —fila por fila, que es como hay que leer una tabla—
    cuando la página es una imagen. `escaneado` no cambia lo que se lee: solo
    acota dónde se busca, porque el OCR cuesta.
    """
    from motor.procesamiento.pdf_utils import texto_pagina_tabla

    return texto_pagina_tabla(page)


# El encabezado y el pie del documento tipo, que se repiten en cada página.
_ENCABEZADO_RE = re.compile(
    r"DOCUMENTOS?\s+(?:BASE|TIPO)|VERSION\s*\d|CCE-EICP|PAGINA\s*\d|CODIGO\s+CCE")


# Las palabras con que un pliego escribe una cifra en letras. Sirven para
# separar el objeto del valor cuando el OCR los pega.
_CIFRA_EN_LETRAS_RE = re.compile(
    r"\b(?:UNO|DOS|TRES|CUATRO|CINCO|SEIS|SIETE|OCHO|NUEVE|DIEZ|ONCE|DOCE|TRECE|CATORCE|QUINCE|DIECISEIS"
    r"|DIECISIETE|DIECIOCHO|DIECINUEVE|VEINTE|TREINTA|CUARENTA|CINCUENTA|SESENTA|SETENTA|OCHENTA|NOVENTA"
    r"|CIEN|CIENTO|DOSCIENTOS|TRESCIENTOS|CUATROCIENTOS|QUINIENTOS|SEISCIENTOS|SETECIENTOS|OCHOCIENTOS"
    r"|NOVECIENTOS|MIL|MILLON|MILLONES|PESOS|M/?CTE)\b",
    re.IGNORECASE,
)


def _orden_de_busqueda(pdf: pdfplumber.PDF, titulo: str, escaneado: bool):
    """Las páginas en el orden en que conviene buscar un numeral.

    Sin OCR, de la primera a la última, como siempre. Con OCR, el orden importa
    porque cada página cuesta: el propio documento dice dónde está lo que se
    busca —su índice trae el numeral y el número de página—, así que se empieza
    por ahí y se sigue con las de alrededor. Si el índice no ayuda, se recorre
    normal. En ningún caso se deja de mirar una página: solo cambia el orden."""
    if not escaneado:
        return list(pdf.pages)
    total = len(pdf.pages)
    pistas: list[int] = []
    # El índice está en las primeras páginas y ya se le hizo OCR al detectar el
    # tipo de documento, así que mirarlo es gratis.
    for page in pdf.pages[:_PAGINAS_DE_MUESTRA]:
        texto = _strip_accents(_texto(page, True).upper())
        for m in re.finditer(re.escape(titulo) + r"[^\n\d]{0,90}?(\d{1,3})", texto):
            pagina = int(m.group(1))
            if 1 <= pagina <= total:
                pistas.append(pagina - 1)
    orden: list[int] = []
    for p in pistas:
        # El número del índice es el del pie de página, que puede ir corrido
        # respecto al del PDF por las portadas: se mira alrededor.
        for i in range(max(0, p - 3), min(total, p + 4)):
            if i not in orden:
                orden.append(i)
    orden += [i for i in range(total) if i not in orden]
    return [pdf.pages[i] for i in orden]


# El presupuesto escrito sin el signo de pesos. Un escaneo pierde el "$" a menudo
# (o lo lee como "S" o "5"), así que la cifra se reconoce por su forma: al menos
# millones, con separadores de miles. En un Documento Base no hay otro número así.
_CIFRA_GRANDE_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3}){2,}(?:[.,]\d{1,2})?)(?![\d])")

# Una fila de lote leída del texto: "LOTE 1 <objeto> <cifra> <N> MESES".
_LOTE_EN_TEXTO_RE = re.compile(r"\b(LOTE|SEGMENTO)\s*(?:N[O°.]?\s*)?(\d{1,2})\b", re.IGNORECASE)


def _cifra_del_texto(texto: str) -> float | None:
    """El presupuesto de una fila: con el signo de pesos si está, y si no, la
    cifra más grande con forma de dinero. Se toma la mayor porque en la fila
    también puede quedar el número del lote o el plazo."""
    con_signo = _DINERO_CELDA_RE.search(texto)
    if con_signo is not None:
        valor = _parse_money(con_signo.group(0))
        if valor:
            return valor
    valores = []
    for m in _CIFRA_GRANDE_RE.finditer(texto):
        crudo = m.group(1)
        if crudo.count(".") + crudo.count(",") < 2:
            continue  # "1,23" no es un presupuesto
        # El punto separa los miles y la coma los decimales (como en el país):
        # "337.867.316,00" son trescientos treinta y siete millones, no treinta
        # y tres mil. Confundirlos multiplica el presupuesto por cien.
        entero = crudo.split(",")[0].replace(".", "")
        if entero.isdigit() and len(entero) >= 7:
            valores.append(float(f"{entero}.{(crudo.split(',') + ['0'])[1][:2] or 0}"))
    return max(valores) if valores else None


def _plazo_del_texto(texto: str) -> int | None:
    """El plazo en meses. El OCR separa el número de la palabra porque entre
    ellos se cuela la columna de al lado."""
    plano = re.sub(r"\s+", " ", _strip_accents(texto.upper()))
    m = (re.search(r"\((\d{1,3})\)[^()]{0,70}?MES(?:ES)?", plano)
         or re.search(r"MES(?:ES)?[^()]{0,70}?\((\d{1,3})\)", plano)
         or re.search(r"(\d{1,3})\s+MES(?:ES)?", plano))
    return int(m.group(1)) if m else None


def _lotes_del_texto(texto: str) -> list[ParsedLote]:
    """Las filas de lote reconocidas en el texto, para cuando la tabla es una
    imagen. Cada fila empieza donde se nombra el lote y termina donde empieza el
    siguiente; de ese tramo se saca el presupuesto, el plazo y el objeto."""
    marcas = list(_LOTE_EN_TEXTO_RE.finditer(texto))
    if len(marcas) < 2:
        return []
    lotes: list[ParsedLote] = []
    vistos: set[str] = set()
    for i, m in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        tramo = texto[m.start():fin]
        numero = f"{m.group(1).upper()} {int(m.group(2))}"
        if numero in vistos:
            continue
        valor = _cifra_del_texto(tramo)
        if valor is None:
            continue
        vistos.add(numero)
        lotes.append(ParsedLote(
            numero=numero,
            objeto=_objeto_de_las_lineas(tramo) or _norm(tramo[:200]),
            plazo_meses=_plazo_del_texto(tramo),
            valor_presupuesto=valor,
            lugar_ejecucion=None,
        ))
    return lotes if len(lotes) >= 2 else []


def _zona_de_la_tabla(texto: str, largo: int = 1400) -> str:
    """El tramo del texto donde está la tabla de objeto y presupuesto."""
    plano = _strip_accents(texto.upper())
    desde = (re.search(r"SIGUIENTE\s+TABLA\s*:?", plano)
             or re.search(r"OBJETO\s+DEL\s+PROYECTO", plano)
             or re.search(r"PRESUPUESTO\s+OFICIAL", plano))
    inicio = desde.end() if desde else 0
    return texto[inicio: inicio + largo]


def _objeto_de_las_lineas(texto: str) -> str:
    """El objeto del proyecto, reconstruido renglón por renglón.

    En una tabla escaneada el OCR lee cada renglón completo, así que en una misma
    línea queda el pedazo del objeto junto al pedazo del valor en letras y del
    lugar: «ADMINISTRATIVA, FINANCIERA, TRESCIENTOS TREINTA Y». El objeto es la
    primera columna, así que de cada línea se toma lo que va antes de que empiece
    otra: la cifra en letras, el plazo en meses, el signo $ o el nombre del lugar
    (que va en minúsculas)."""
    plano = _strip_accents(texto.upper())
    # Por orden de precisión: la frase que presenta la tabla, luego su fila de
    # encabezados. El título del numeral («1.1 OBJETO, PRESUPUESTO OFICIAL…») no
    # sirve como ancla: dejaría dentro su propio texto.
    desde = (re.search(r"SIGUIENTE\s+TABLA\s*:?", plano)
             or re.search(r"OBJETO\s+DEL\s+PROYECTO[^\n]*\n", plano))
    cuerpo = texto[desde.end():] if desde else texto
    partes: list[str] = []
    for linea in cuerpo.splitlines():
        linea = linea.strip()
        if not linea:
            if partes:
                break  # la tabla terminó
            continue
        sin_tildes = _strip_accents(linea.upper())
        if _ENCABEZADO_RE.search(sin_tildes):
            continue
        # La fila de encabezados de la propia tabla.
        if "OBJETO DEL PROYECTO" in sin_tildes or ("PLAZO" in sin_tildes and "PRESUPUESTO" in sin_tildes):
            continue
        # Solo la parte en mayúsculas del principio de la línea.
        m = re.match(r"[\"“”'(]?[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9\s,.\-\"“”'()]*", linea)
        if m is None:
            if partes:
                break
            continue
        tramo = _CIFRA_EN_LETRAS_RE.split(m.group(0), maxsplit=1)[0]
        tramo = re.split(r"\bMES(?:ES)?\b|\$|\(\d", tramo, maxsplit=1)[0].strip(" ,.-")
        if len(tramo) >= 3:
            partes.append(tramo)
        if len(partes) >= 12:
            break
    return _norm(" ".join(partes))


def _lote_unico_del_texto(texto: str) -> ParsedLote | None:
    """La fila de objeto y presupuesto leída del texto, cuando no hay tabla que
    extraer porque la página es una imagen. Cada dato se reconoce por su forma,
    igual que en la tabla: el valor por el signo $, el plazo por los meses y el
    objeto por ser la parte larga en mayúsculas."""
    valor = _cifra_del_texto(texto)
    if not valor:
        return None

    # El objeto: el tramo largo en mayúsculas de la tabla (los pliegos lo
    # escriben así), sin los números ni el encabezado de las columnas.
    objeto = _objeto_de_las_lineas(texto)
    return ParsedLote(
        numero="ÚNICO",
        objeto=_norm(objeto),
        plazo_meses=_plazo_del_texto(texto),
        valor_presupuesto=valor,
        lugar_ejecucion=None,
    )


_SOLO_NUMERO_RE = re.compile(r"^\(?(\d{1,2})\)?$")


def _filas_numeradas_con_dinero(table: list[list[str | None]]) -> set[str]:
    """Las celdas de la primera columna que son solo un número y cuya fila trae
    una cifra de dinero. Devuelve el conjunto vacío si hay menos de dos: una
    fila sola no distingue una tabla de lotes de una lista numerada."""
    candidatas: dict[str, float] = {}
    for row in table:
        if not row or row[0] is None:
            continue
        primera = _norm(row[0])
        if not _SOLO_NUMERO_RE.match(primera):
            continue
        resto = " ".join(_norm(c) for c in row[1:] if c)
        if _cifra_del_texto(resto):
            candidatas[primera] = 1
    return set(candidatas) if len(candidatas) >= 2 else set()


def _find_budget_rows(pdf: pdfplumber.PDF, escaneado: bool = False) -> tuple[str, list[ParsedLote], int | None]:
    objeto_general = ""
    lotes: list[ParsedLote] = []
    heading_page_idx = None
    fallback_page_idx = None

    # A table-of-contents entry also contains the heading text (with a dot
    # leader and page number), so prefer a page where the "OBJETO:" paragraph
    # itself can be found; only fall back to the first heading match otherwise.
    # En un escaneado cada página cuesta un OCR, así que se para en el numeral
    # 1.1, que está siempre al principio.
    hasta = min(_MAX_PAGINAS_ENCABEZADO, len(pdf.pages)) if escaneado else len(pdf.pages)
    for i, page in enumerate(pdf.pages[:hasta]):
        text = _texto(page, escaneado)
        sin_tildes = _strip_accents(text.upper())
        # El OCR deforma el título ("OBJETO, PRESUPUESTO OFICTAL"), así que
        # también vale que la página nombre la tabla o sus columnas.
        if not (("OBJETO" in sin_tildes and "PRESUPUESTO" in sin_tildes)
                or "OBJETO DEL PROYECTO" in sin_tildes):
            continue
        if fallback_page_idx is None:
            fallback_page_idx = i
        match = re.search(r"OBJETO:\s*(.*?)\n\s*N[uú]mero", text, re.DOTALL)
        if match:
            heading_page_idx = i
            objeto_general = _norm(match.group(1))
            break

    if heading_page_idx is None:
        heading_page_idx = fallback_page_idx

    if heading_page_idx is None:
        return objeto_general, lotes, None

    pagina_tabla: int | None = None
    for i in range(heading_page_idx, min(heading_page_idx + 6, len(pdf.pages))):
        page = pdf.pages[i]
        for table in page.extract_tables():
            # Hay pliegos cuya columna de lote trae solo el número ("1", "2"),
            # sin la palabra: se aceptan si hay al menos dos filas así con su
            # cifra de dinero, que es lo que hace que sea una tabla de lotes y no
            # una lista numerada cualquiera.
            solo_numero = _filas_numeradas_con_dinero(table)
            for row in table:
                if not row or row[0] is None:
                    continue
                first_cell = _norm(row[0])
                if not LOTE_ROW_RE.match(first_cell) and first_cell not in solo_numero:
                    continue
                if first_cell in solo_numero:
                    first_cell = f"LOTE {int(first_cell)}"
                # Cada dato se reconoce por su forma, no por su posición: hay
                # pliegos con una columna de más (o de menos) y con el orden
                # cambiado, y tomando la posición el presupuesto salía en cero.
                celdas = [_norm(c) for c in row[1:] if c and _norm(c)]
                valor = next((c for c in celdas if _cifra_del_texto(c)), None)
                plazo = next((c for c in celdas if re.search(r"\bMES", _strip_accents(c.upper()))), None)
                resto = [c for c in celdas if c not in (valor, plazo)]
                objeto = max(resto, key=len) if resto else ""
                lugar = next((c for c in resto if c != objeto), None)
                pagina_tabla = pagina_tabla if pagina_tabla is not None else i
                lotes.append(
                    ParsedLote(
                        numero=first_cell,
                        objeto=objeto,
                        plazo_meses=_parse_months(plazo) or _plazo_del_texto(" ".join(celdas)),
                        valor_presupuesto=_cifra_del_texto(valor) if valor else None,
                        lugar_ejecucion=lugar,
                        plazo_hasta=_fecha_limite(" ".join(celdas)),
                    )
                )
        if i > heading_page_idx and re.search(
            r"1\.2\.?\s+DOCUMENTOS DEL PROCESO", _texto(page, escaneado), re.IGNORECASE
        ):
            break

    if not lotes:
        # La tabla puede ser una imagen (o venir vacía): sus filas se reconocen
        # en el texto. Primero los lotes, porque un pliego por lotes leído como
        # un solo objeto daría un presupuesto y un plazo equivocados.
        for i in range(heading_page_idx, min(heading_page_idx + 8, len(pdf.pages))):
            texto = _texto(pdf.pages[i], escaneado)
            sin_tildes = _strip_accents(texto.upper())
            if "PRESUPUESTO" not in sin_tildes:
                continue
            del_texto = _lotes_del_texto(texto)
            if del_texto:
                lotes.extend(del_texto)
                pagina_tabla = i
                break
    if not lotes:
        vista: list[int] = []
        unico = _objeto_unico(pdf, heading_page_idx, escaneado, vista)
        if vista:
            pagina_tabla = vista[0]
        if unico is not None:
            lotes.append(unico)
            objeto_general = objeto_general or unico.objeto

    # El plazo suele estar en su propia celda, pero cuando la tabla lo parte (o la
    # página es una imagen) queda sin leer, y sin plazo no se puede calcular el
    # capital de trabajo ni saber si el pliego exige patrimonio mínimo. Se busca
    # entonces en el texto de la página de la tabla.
    if lotes and all(l.plazo_meses is None for l in lotes) and heading_page_idx is not None:
        # La página donde se nombra la sección puede ser la del índice, con la
        # tabla varias páginas más allá: la de verdad es la que trae la cifra del
        # presupuesto que ya se leyó.
        cifras = {l.valor_presupuesto for l in lotes if l.valor_presupuesto}
        for i in range(heading_page_idx, min(heading_page_idx + 10, len(pdf.pages))):
            texto = _texto(pdf.pages[i], escaneado)
            if cifras and _cifra_del_texto(texto) not in cifras:
                continue
            # Solo en la zona de la tabla: más allá está la vigencia de la
            # garantía, que también se cuenta en meses y pondría un plazo falso.
            plazo = _plazo_del_texto(_zona_de_la_tabla(texto))
            if plazo:
                for lote in lotes:
                    lote.plazo_meses = plazo
                break

    for lote in lotes:
        lote.lugar_ejecucion = lote.lugar_ejecucion or None

    return objeto_general, lotes, (pagina_tabla or heading_page_idx) + 1


_DINERO_CELDA_RE = re.compile(r"\$\s*\d[\d.,]*")


def _objeto_unico(pdf: pdfplumber.PDF, desde: int, escaneado: bool = False,
                  donde: list[int] | None = None) -> ParsedLote | None:
    """Pliegos de un solo objeto (sin lotes), como los de obra pública: una
    tabla "Objeto del proyecto | Plazo | Valor presupuesto oficial | Lugar".
    Las columnas de los datos no siempre calzan con las del encabezado, así
    que cada dato se reconoce por su forma: el valor por el signo $, el plazo
    por los meses, el objeto como el texto más largo y el lugar, lo que queda."""
    # Se empieza en la primera página que nombra la sección (puede ser el índice).
    for i in range(desde, min(desde + 8, len(pdf.pages))):
        for table in pdf.pages[i].extract_tables():
            texto = _strip_accents(" ".join(c or "" for fila in table for c in fila).upper())
            if "OBJETO" not in texto or "PRESUPUESTO" not in texto:
                continue
            for row in table:
                celdas = [_norm(c) for c in row if c and _norm(c)]
                valor = next((c for c in celdas if _DINERO_CELDA_RE.search(c)), None)
                if valor is None:
                    continue
                plazo = next((c for c in celdas if re.search(r"\bMES", _strip_accents(c.upper()))), None)
                resto = [c for c in celdas if c not in (valor, plazo)]
                objeto = max(resto, key=len) if resto else ""
                lugar = next((c for c in resto if c != objeto), None)
                if donde is not None:
                    donde.append(i)
                return ParsedLote(
                    numero="ÚNICO",
                    objeto=objeto,
                    plazo_meses=_parse_months(plazo),
                    valor_presupuesto=_parse_money(_DINERO_CELDA_RE.search(valor).group(0)),
                    lugar_ejecucion=lugar,
                    plazo_hasta=_fecha_limite(" ".join(celdas)),
                )
    # Las tablas no dieron la fila: o la página es una imagen (y no hay tabla que
    # extraer) o la tabla existe y viene vacía. En ambos casos la fila se reconoce
    # en el texto, que con OCR llega con las columnas entremezcladas.
    for i in range(desde, min(desde + 8, len(pdf.pages))):
        texto = _texto(pdf.pages[i], escaneado)
        sin_tildes = _strip_accents(texto.upper())
        if "OBJETO" not in sin_tildes or "PRESUPUESTO" not in sin_tildes:
            continue
        unico = _lote_unico_del_texto(texto)
        if unico is not None:
            if donde is not None:
                donde.append(i)
            return unico
    return None


def _row_condicion(row: list[str | None]) -> str:
    non_empty = [c for c in row[1:] if c]
    return _norm(non_empty[0]) if non_empty else ""


# El porcentaje del valor asegurado escrito en letras. Importa porque en un
# escaneo el número se lee mal ("(107)", "¿1U70)") y la palabra, bien: de seis
# lecturas de la misma franja, "Diez por ciento" salió igual en las seis.
_EN_LETRAS = {
    "UNO": 1, "DOS": 2, "TRES": 3, "CUATRO": 4, "CINCO": 5, "SEIS": 6, "SIETE": 7, "OCHO": 8,
    "NUEVE": 9, "DIEZ": 10, "ONCE": 11, "DOCE": 12, "QUINCE": 15, "VEINTE": 20, "TREINTA": 30,
    "CUARENTA": 40, "CINCUENTA": 50,
}
# Las alternativas van de la palabra más larga a la más corta, y sin exigir
# límite de palabra al principio: el OCR pega letras sueltas delante ("VDiez por
# ciento"), y con \b esa lectura se perdía.
_PALABRAS_DE_NUMERO = "|".join(sorted(_EN_LETRAS, key=len, reverse=True))
_PORCENTAJE_EN_LETRAS_RE = re.compile(
    r"(" + _PALABRAS_DE_NUMERO + r")\b[^)]{0,16}?\)?\s*POR\s*CIENTO", re.IGNORECASE)
# La etiqueta de la fila, aunque el OCR la dañe ("Vvalor Asegurado").
_ETIQUETA_ASEGURADO_RE = re.compile(r"ASEGURAD")


def _porcentaje_en_letras(texto: str) -> float | None:
    """El porcentaje dicho en letras («diez por ciento» → 0.10)."""
    m = _PORCENTAJE_EN_LETRAS_RE.search(_strip_accents(texto.upper()))
    if m is None:
        return None
    palabra = (m.group(1) or m.group(2) or "").upper()
    valor = _EN_LETRAS.get(palabra)
    return valor / 100 if valor else None


def _porcentaje_a_fondo(page) -> tuple[float | None, str]:
    """(porcentaje, la frase que lo dice) leyendo la fila del valor asegurado
    recortada de la página.

    Es el último recurso, para cuando el OCR de la página completa perdió esa
    celda. Se lee la misma franja a varios tamaños y se exige que coincidan al
    menos dos: una sola lectura de un escaneo no basta para fijar el valor
    asegurado que después se le exige al proponente."""
    from motor.procesamiento.ocr_franja import textos_de_la_franja

    votos: dict[float, str] = {}
    cuenta: dict[float, int] = {}
    for lectura in textos_de_la_franja(page, _ETIQUETA_ASEGURADO_RE):
        porcentaje = _porcentaje_en_letras(lectura)
        if porcentaje is None:
            continue
        cuenta[porcentaje] = cuenta.get(porcentaje, 0) + 1
        votos.setdefault(porcentaje, _norm(lectura[:160]))
    if not cuenta:
        return None, ""
    mejor = max(cuenta, key=lambda p: cuenta[p])
    if cuenta[mejor] < 2:
        return None, ""
    return mejor, votos[mejor]


def _porcentaje_del_presupuesto(texto: str) -> tuple[float | None, str]:
    """Un porcentaje dicho sobre el Presupuesto Oficial, en cifra o en letras.

    Tiene que ser del presupuesto: las garantías del contrato (cumplimiento,
    salarios, estabilidad) traen sus propios 20 % y 30 % "del valor del
    contrato", y tomar uno de esos pondría un valor asegurado equivocado."""
    plano = re.sub(r"\s+", " ", _strip_accents(texto))
    for m in re.finditer(r"(\d{1,3}(?:[.,]\d+)?)\s*%[^.]{0,60}?PRESUPUESTO\s+OFICIAL", plano, re.IGNORECASE):
        valor = float(m.group(1).replace(",", ".")) / 100
        if 0 < valor <= 1:
            return valor, _norm(plano[max(0, m.start() - 60): m.end() + 20])
    for m in re.finditer(r"POR\s*CIENTO[^.]{0,60}?PRESUPUESTO\s+OFICIAL", plano, re.IGNORECASE):
        valor = _porcentaje_en_letras(plano[max(0, m.start() - 40): m.end()])
        if valor is not None:
            return valor, _norm(plano[max(0, m.start() - 40): m.end() + 20])
    return None, ""


def _garantia_del_texto(texto: str) -> tuple[int | None, str, float | None, str]:
    """(vigencia en meses, su frase, porcentaje, su frase) leídos del texto de la
    tabla de características de la garantía, para cuando esa tabla es una imagen.

    Se busca por la etiqueta de cada fila, como en la tabla, pero admitiendo que
    el OCR mezcle las columnas: entre la etiqueta y su dato puede colarse texto
    del renglón de al lado."""
    plano = re.sub(r"\s+", " ", _strip_accents(texto))
    vigencia = porcentaje = None
    raw_vigencia = raw_valor = ""
    m = re.search(r"VIGENCIA[^.]{0,120}?(\d{1,2})\s*MES", plano, re.IGNORECASE)
    if m is None:
        # También al revés: "3 meses contados a partir del cierre" en la fila de
        # vigencia, con la etiqueta antes de lo que el OCR pegó del lado.
        m = re.search(r"(\d{1,2})\s*MESES?\s+CONTADOS", plano, re.IGNORECASE)
    if m is not None:
        vigencia = int(m.group(1))
        raw_vigencia = _norm(plano[max(0, m.start() - 40): m.end() + 80])
    v = re.search(r"VALOR\s+ASEGURADO[^.]{0,200}?(\d{1,3}(?:[.,]\d+)?)\s*%", plano, re.IGNORECASE)
    if v is None:
        v = re.search(r"(\d{1,3}(?:[.,]\d+)?)\s*%\s*DEL\s+(?:VALOR\s+DEL\s+)?PRESUPUESTO", plano, re.IGNORECASE)
    if v is not None:
        porcentaje = float(v.group(1).replace(",", ".")) / 100
        raw_valor = _norm(plano[max(0, v.start() - 60): v.end() + 60])
    if porcentaje is None:
        # En letras: el escaneo daña el número y no la palabra. Tiene que ser del
        # PRESUPUESTO: las garantías del contrato (cumplimiento, salarios,
        # estabilidad) traen sus propios porcentajes "del valor del contrato" en
        # las páginas siguientes, y tomar uno de esos pondría un valor asegurado
        # equivocado.
        m = re.search(r"POR\s*CIENTO[^.]{0,80}?PRESUPUESTO", plano, re.IGNORECASE)
        if m is not None:
            porcentaje = _porcentaje_en_letras(plano[max(0, m.start() - 40): m.end()])
            if porcentaje is not None:
                raw_valor = _norm(plano[max(0, m.start() - 40): m.end() + 40])
    return vigencia, raw_vigencia, porcentaje, raw_valor


def _find_garantia_seriedad(pdf: pdfplumber.PDF, escaneado: bool = False) -> ParsedGarantia | None:
    # The heading text also shows up as a table-of-contents entry earlier in
    # the document, which has no characteristics table. Check every page
    # that mentions the heading and keep the first one that actually yields
    # a "Vigencia" and/or "Valor Asegurado" row.
    for i, page in enumerate(_orden_de_busqueda(pdf, "GARANTIA DE SERIEDAD DE LA OFERTA", escaneado)):
        text = _texto(page, escaneado)
        if "GARANTIA DE SERIEDAD DE LA OFERTA" not in _strip_accents(text.upper()):
            continue

        window_pages = [page]
        siguiente = page.page_number  # page_number es 1-based: esto es el índice del siguiente
        if siguiente < len(pdf.pages):
            window_pages.append(pdf.pages[siguiente])

        vigencia_meses: int | None = None
        raw_vigencia = ""
        porcentaje: float | None = None
        raw_valor = ""

        for p in window_pages:
            for table in p.extract_tables():
                for row in table:
                    if not row or row[0] is None:
                        continue
                    label = _strip_accents(_norm(row[0])).lower()
                    condicion = _row_condicion(row)

                    if vigencia_meses is None and label.startswith("vigencia"):
                        m = re.search(r"(\d+)\s*mes", condicion, re.IGNORECASE)
                        if m:
                            vigencia_meses = int(m.group(1))
                            raw_vigencia = condicion

                    if porcentaje is None and "valor" in label and "asegurado" in label:
                        m = PERCENT_RE.search(condicion)
                        if m:
                            porcentaje = float(m.group(1).replace(",", ".")) / 100
                            raw_valor = condicion

            if vigencia_meses is None or porcentaje is None:
                # La tabla de características puede ser una imagen, o venir vacía
                # aunque exista: sus filas también se leen del texto, que las trae
                # con la etiqueta delante.
                de_texto = _garantia_del_texto(_texto(p, escaneado))
                if vigencia_meses is None and de_texto[0] is not None:
                    vigencia_meses, raw_vigencia = de_texto[0], de_texto[1]
                if porcentaje is None and de_texto[2] is not None:
                    porcentaje, raw_valor = de_texto[2], de_texto[3]
            if porcentaje is None and escaneado:
                # Último recurso: la celda del valor asegurado recortada de la
                # página y leída sola, a varios tamaños. El OCR de la página
                # completa se la come a veces, y sin el porcentaje habría que
                # asumir el del documento tipo.
                porcentaje, dice = _porcentaje_a_fondo(p)
                if porcentaje is not None:
                    raw_valor = dice
            if vigencia_meses is not None and porcentaje is not None:
                break

        if porcentaje is None:
            # El numeral dice el porcentaje en su texto casi siempre, aunque la
            # tabla de características no se haya podido leer: "por una cuantía
            # equivalente al diez por ciento (10%) del Presupuesto Oficial". Se
            # busca en las dos páginas de la ventana, exigiendo que sea del
            # presupuesto y no "del valor del contrato", que es lo que dicen las
            # garantías del contrato.
            for p in window_pages:
                porcentaje, raw = _porcentaje_del_presupuesto(_texto(p, escaneado))
                if porcentaje is not None:
                    raw_valor = raw_valor or raw
                    break

        if vigencia_meses is None and porcentaje is None:
            # Likely the table-of-contents entry; keep looking.
            continue

        combined_text = _strip_accents("\n".join(_texto(p, escaneado) for p in window_pages)).lower()
        base_calculo = "lote_mayor_valor" if "mayor valor" in combined_text else "presupuesto_total"

        return ParsedGarantia(
            vigencia_meses=vigencia_meses,
            porcentaje=porcentaje,
            base_calculo=base_calculo,
            raw_vigencia=raw_vigencia,
            raw_valor=raw_valor,
            pagina=page.page_number,
        )

    return None


def parse_documento_base(pdf_bytes: bytes) -> ParseResult:
    from motor.evaluacion.formato1_contenido import modalidad_de

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        # Se decide una vez: el OCR cuesta, y solo hace falta si el cuerpo del
        # documento es una imagen.
        # La huella permite cachear el OCR de cada página entre corridas.
        pdf._huella_contenido = hashlib.sha256(pdf_bytes).hexdigest()
        # Esto no decide si se hace OCR (eso es por página): decide si conviene
        # acotar la búsqueda, porque en un documento escaneado cada página cuesta.
        escaneado = _es_escaneado(pdf)
        objeto_general, lotes, pagina_objeto = _find_budget_rows(pdf, escaneado)
        garantia = _find_garantia_seriedad(pdf, escaneado)
        pagina_garantia = getattr(garantia, "pagina", None) if garantia else None
        # La modalidad se lee del encabezado de las primeras páginas.
        primeras = [_texto(p, escaneado) for p in pdf.pages[:8]]
        modalidad = modalidad_de(" ".join(primeras[:3]), " ".join(primeras))
        paginas = []
        for page in pdf.pages:
            # El texto completo (para las cláusulas del aval) se lee sin OCR: son
            # 95 páginas y ya se hizo OCR de las que importan. Si el documento
            # está escaneado, lo que se pierde es una comprobación de detalle,
            # no los lotes ni la garantía.
            paginas.append(re.sub(r"\s+", " ", page.extract_text() or ""))
            page.flush_cache()
        texto = " ".join(paginas)
        tarjeta_suplible = bool(TARJETA_SUPLIBLE_RE.search(texto))
    return ParseResult(
        objeto_general=objeto_general, lotes=lotes, garantia=garantia, modalidad=modalidad,
        tarjeta_suplible=tarjeta_suplible, tarjeta_exigida=_aval_pide_tarjeta(texto),
        pagina_objeto=pagina_objeto, pagina_garantia=pagina_garantia,
    )


def _meses_hasta(desde: date, hasta: date) -> int | None:
    """Meses entre dos fechas, redondeando hacia arriba: un plazo de cinco meses
    y medio son seis, y así el capital de trabajo que se exige no queda corto."""
    if hasta <= desde:
        return None
    meses = (hasta.year - desde.year) * 12 + (hasta.month - desde.month)
    if hasta.day > desde.day:
        meses += 1
    return max(1, meses)


def build_proceso(codigo_proceso: str, fecha_cierre: date, pdf_bytes: bytes) -> ProcesoDocumentoBase:
    parsed = parse_documento_base(pdf_bytes)
    advertencias: list[str] = []

    if not parsed.lotes:
        advertencias.append(
            "No se pudieron identificar lotes/segmentos en la tabla de objeto y presupuesto del Documento Base. "
            "Revise el documento manualmente."
        )

    lotes: list[Lote] = []
    for pl in parsed.lotes:
        if pl.plazo_meses is None and pl.plazo_hasta is not None:
            # El pliego no da meses sino la fecha en que termina el contrato: los
            # meses se cuentan desde el cierre, que es lo más cercano que se sabe
            # (el plazo corre en realidad desde el acta de inicio). Se dice de
            # dónde salió para que quien evalúa lo confirme.
            pl.plazo_meses = _meses_hasta(fecha_cierre, pl.plazo_hasta)
            if pl.plazo_meses:
                advertencias.append(
                    f"El pliego no da el plazo de {pl.numero} en meses sino hasta el "
                    f"{pl.plazo_hasta.strftime('%d/%m/%Y')}: se contaron {pl.plazo_meses} meses desde el cierre. "
                    "Confírmelo, porque el plazo corre desde el acta de inicio."
                )
        if pl.valor_presupuesto is None:
            advertencias.append(f"No se pudo leer el valor del Presupuesto Oficial de {pl.numero}; revíselo manualmente.")
        if pl.plazo_meses is None:
            advertencias.append(f"No se pudo leer el plazo en meses de {pl.numero}; revíselo manualmente.")
        lotes.append(
            Lote(
                numero=pl.numero,
                objeto=pl.objeto,
                plazo_meses=pl.plazo_meses or 0,
                valor_presupuesto=pl.valor_presupuesto or 0.0,
                lugar_ejecucion=pl.lugar_ejecucion,
            )
        )

    if parsed.garantia is None:
        advertencias.append(
            "No se encontró el numeral de Garantía de Seriedad de la Oferta en el documento; "
            f"se usan valores por defecto ({DEFAULT_VIGENCIA_MESES} meses, {DEFAULT_PORCENTAJE:.0%})."
        )
        vigencia_meses = DEFAULT_VIGENCIA_MESES
        porcentaje = DEFAULT_PORCENTAJE
        base_calculo = "lote_mayor_valor" if len(lotes) > 1 else "presupuesto_total"
    else:
        vigencia_meses = parsed.garantia.vigencia_meses
        porcentaje = parsed.garantia.porcentaje
        base_calculo = parsed.garantia.base_calculo
        if vigencia_meses is None:
            advertencias.append(
                f"No se pudo leer la vigencia de la Garantía de Seriedad; se asumen {DEFAULT_VIGENCIA_MESES} meses."
            )
            vigencia_meses = DEFAULT_VIGENCIA_MESES
        if porcentaje is None:
            advertencias.append(
                f"No se pudo leer el porcentaje del valor asegurado de la Garantía de Seriedad; se asume {DEFAULT_PORCENTAJE:.0%}."
            )
            porcentaje = DEFAULT_PORCENTAJE

    presupuesto_total = sum(l.valor_presupuesto for l in lotes)

    if lotes:
        lote_mayor = max(lotes, key=lambda l: l.valor_presupuesto)
    else:
        lote_mayor = None

    if base_calculo == "lote_mayor_valor" and lote_mayor is not None:
        valor_base = lote_mayor.valor_presupuesto
        lote_base = lote_mayor.numero
    else:
        valor_base = presupuesto_total
        lote_base = None

    valor_asegurado = round(valor_base * porcentaje, 2)
    fecha_vencimiento = fecha_cierre + relativedelta(months=vigencia_meses)

    garantia_seriedad = GarantiaSeriedad(
        vigencia_meses=vigencia_meses,
        porcentaje=porcentaje,
        base_calculo=base_calculo,
        lote_base=lote_base,
        valor_base=valor_base,
        valor_asegurado=valor_asegurado,
        fecha_cierre=fecha_cierre,
        fecha_vencimiento=fecha_vencimiento,
    )

    return ProcesoDocumentoBase(
        codigo_proceso=codigo_proceso,
        fecha_cierre=fecha_cierre,
        modalidad=parsed.modalidad,
        pagina_objeto=parsed.pagina_objeto,
        pagina_garantia=parsed.pagina_garantia,
        tarjeta_suplible=parsed.tarjeta_suplible,
        tarjeta_exigida=parsed.tarjeta_exigida,
        objeto_general=parsed.objeto_general,
        lotes=lotes,
        lote_mayor_valor=lote_mayor.numero if lote_mayor else "",
        presupuesto_total=presupuesto_total,
        garantia_seriedad=garantia_seriedad,
        advertencias=advertencias,
    )
