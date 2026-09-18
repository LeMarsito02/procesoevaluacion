from __future__ import annotations

import re
from datetime import date
from itertools import product

from motor import criterios
from motor.procesamiento.memoria_proponente import memo_por_pdfs
from motor.evaluacion.formato1 import _clave_cache, _guardar_cache, _leer_cache, _norm, encontrar_formato1
from motor.integrations.drive import download_file_bytes, get_file_metadata
from motor.llm.cliente import aparece_en_texto, consultar_json
from motor.esquemas.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from motor.procesamiento.pdf_utils import extraer_texto, texto_ocr_reforzado
from motor.procesamiento.zip_utils import extraer_pdfs

PAGINAS_A_REVISAR = 2
PISTAS_POLIZA = ("poliza", "garantia", "seriedad")

# El texto plano de la póliza sale con el encabezado/logo desordenado (letras
# sueltas del logo de la aseguradora), pero el cuerpo con los datos del
# certificado (fechas, valores, beneficiario) suele extraerse en orden
# legible. Solo se exige el título genérico: no se exige además "SERIEDAD DE
# LA OFERTA" porque se confirmó con una póliza real (Seguros de Estado) que
# no siempre aparece ese texto literal en la extracción, y en esta etapa
# (documentos de la propuesta, antes de la adjudicación) no existe todavía
# ninguna póliza de cumplimiento del contrato con la que pueda confundirse.
#
# Variantes de título confirmadas: "POLIZA DE SEGURO DE CUMPLIMIENTO ENTIDAD
# ESTATAL" (Seguros del Estado, Mundial) y "POLIZA DE GARANTIA UNICA DE
# CUMPLIMIENTO EN FAVOR DE ENTIDADES ESTATALES" (Confianza). Como la frase
# "póliza de cumplimiento" puede citarse en otros documentos, se exige además
# el campo de vigencia propio de la carátula de una póliza.
# Otras variantes reales: SURA ("NUMERO POLIZA: 1234567 SEGURO DE
# CUMPLIMIENTO"), Liberty con el texto sin espacios ("POLIZADECUMPLIMIENTO
# AFAVORDEENTIDADESESTATALES") y escaneadas donde el OCR pierde la tilde
# ("P LIZA DE SEGURO DE CUMPLIMIENTO"). Zurich no trae "VIGENCIA HASTA" sino
# otros nombres de campo, así que la guarda acepta vigencia + valor asegurado.
# Más variantes del proceso ICCU-LP-027-2026: Solidaria parte el título en
# columnas ("POLIZA DE SEGURO DE POLIZA / ENDOSO <tomador> CUMPLIMIENTO EN
# FAVOR DE ENTIDADES ESTATALES"), Chubb ("GARANTIA UNICA DE CUMPLIMIENTO EN
# FAVOR DE ENTIDADES ESTATALES") y "GARANTIA UNICA DE SEGUROS DE CUMPLIMIENTO".
TITULO_POLIZA_RE = re.compile(
    r"P\s?O?\s?LIZA\s*DE\s*(?:SEGURO\s*DE\s*|GARANTIA\s*UNICA\s*DE\s*)?CUMPLIMIENTO"
    r"|NUMERO\s+(?:DE\s+)?POLIZA:?\s*\S+\s+SEGURO\s+DE\s+CUMPLIMIENTO"
    r"|GARANTIA\s*UNICA\s*DE\s*(?:SEGUROS?\s*DE\s*)?CUMPLIMIENTO"
    r"|CUMPLIMIENTO\s*(?:EN|A)\s*FAVOR\s*DE\s*(?:LAS\s*)?ENTIDADES\s*ESTATALES"
)
CAMPO_VIGENCIA_RE = re.compile(
    r"VIGENC\S{0,3}\s*\S{0,3}\s*HASTA"
    r"|VIGENCIA\s*DE\s*TERMINACION"
    r"|VIGENCIA.{0,400}?(?:VALOR|SUMA)\s*ASEGURAD"
    r"|(?:VALOR|SUMA)\s*ASEGURAD.{0,800}?VIGENCIA",
    re.DOTALL,
)

_MESES_ABREVIADOS = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12}


def _fecha_en_texto(fecha_ddmmaaaa: str, texto: str) -> bool:
    """La fecha extraída (dd/mm/aaaa) está escrita en el documento, con
    números ("29/11/2026", "29 11 2026") o con el mes abreviado como la
    escribe SURA ("29-ENE-2027")."""
    if aparece_en_texto(fecha_ddmmaaaa, texto, numerico=True):
        return True
    dia, mes, anio = fecha_ddmmaaaa.split("/")
    abreviado = next((k for k, v in _MESES_ABREVIADOS.items() if v == int(mes)), None)
    return abreviado is not None and re.search(rf"\b{int(dia):02d}[-/ ]{abreviado}[A-Z]*[-/ ]{anio}\b", _norm(texto)) is not None

# "BENEFICIARIO <NOMBRE DE LA ENTIDAD> - <SIGLA> NO. DOC. IDENTIDAD ..." — se
# exige la sigla (o el nombre) de la entidad cerca de la palabra
# "BENEFICIARIO", sin depender del nombre completo, que suele venir con leves
# variaciones de redacción. Las claves las define cada entidad en su plantilla
# (parámetro "beneficiario_claves").


def _beneficiario_re() -> re.Pattern[str] | None:
    """Beneficiario según la entidad (parámetro "beneficiario_claves"). Sin
    claves configuradas no se puede confirmar: el requisito va a revisión."""
    claves = [re.escape(_norm(c)) for c in criterios.valor("beneficiario_claves") if c.strip()]
    if not claves:
        return None
    # En una póliza a favor de entidades estatales el asegurado y el
    # beneficiario son la entidad; hay aseguradoras que solo rotulan
    # "ASEGURADO" (o cuyo OCR pierde la etiqueta BENEFICIARIO). A "ASEGURADO"
    # se le exige el nombre casi pegado, para no tomar frases del clausulado
    # ("el tomador y/o asegurado según corresponda…").
    return re.compile(r"(?:BENEFICIARIO.{0,150}?|ASEGURAD[OA]\W{0,4}(?:N\b)?.{0,40}?)(?:" + "|".join(claves) + ")")

# El separador decimal cambia según la aseguradora (ver _parsear_valor_pesos).
VALOR_PESOS_RE = r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?"

# Seguros del Estado a veces no deja la fila del amparo como texto (queda en
# una capa no extraíble) pero sí la carátula: "TIPO MOVIMIENTO 24 07 2026
# 29 07 2026 00:00 29 12 2026 23:59" (expedición, vigencia desde, vigencia
# hasta) y "VALOR ASEGURADO TOTAL PLAN DE PAGO $ ***prima $ ***gastos $ ***iva
# $ ***total $ ***valor asegurado". Una póliza de seriedad de la oferta solo
# tiene ese amparo, así que la vigencia y el valor total de la póliza son los
# del amparo; se usa solo cuando no se encontró la fila del amparo.
_FECHA_ESPACIOS = r"(\d{2})\s+(\d{2})\s+(\d{4})"
VIGENCIA_CARATULA_RE = re.compile(
    rf"TIPO MOVIMIENTO\s+{_FECHA_ESPACIOS}\s+{_FECHA_ESPACIOS}\s+\d{{2}}:\d{{2}}\s+{_FECHA_ESPACIOS}\s+\d{{2}}:\d{{2}}"
)
VALOR_CARATULA_RE = re.compile(
    rf"VALOR ASEGURADO TOTAL PLAN DE PAGO(?:\s*\$\s*\**{VALOR_PESOS_RE}){{4}}\s*\$\s*\**({VALOR_PESOS_RE})"
)


def _parsear_valor_pesos(texto: str) -> float | None:
    """Distintas aseguradoras usan distinto separador decimal en los mismos
    documentos (formato colombiano '1.234.567,89' vs. formato con coma de
    miles '1,234,567.89') — se asume que el separador decimal es el que
    aparece más a la derecha."""
    # Solo cuenta como decimal un separador final seguido de 1 o 2 cifras;
    # los demás separadores son de miles. Así también se leen valores con
    # los separadores mezclados o duplicados por el OCR ("545.,895.454,50").
    limpio = re.sub(r"[^\d.,]", "", texto)
    decimal = re.fullmatch(r"(.*\d)[.,](\d{1,2})", limpio)
    entero, centavos = (decimal.group(1), decimal.group(2)) if decimal else (limpio, "0")
    entero = re.sub(r"\D", "", entero)
    if not entero:
        return None
    return float(f"{entero}.{centavos}")


# --- Fila del amparo de seriedad, sea cual sea la aseguradora ---------------
# "SERIEDAD DE LA OFERTA" seguido, en la misma fila, de las fechas de
# vigencia (desde, hasta) y de la suma asegurada. Formatos reales:
#   Solidaria: "SERIEDAD DE LA OFERTA ---- COP 545.895.454,50 VIGENCIA DE LA COBERTURA : DESDE LAS 0 HS DEL 24/07/2026, HASTA LAS 0 HS DEL 24/11/2026"
#   Chubb (OCR): "SERTEDAD OFERTA CO 2026/07/24 2026/11/24 545,895,454.50"
#   Otra:      "SERIEDAD DE LA OFERTA 24-07-2026 11-11-2026 545,895,455.00"
#   Mundial (OCR reforzado): "SERIEDAD DE LA OFERTA 00:00 Horas Del 24/07/2026 24:00 Horas Del 24/11/2026 545.895.454,50"
#   Mundial (digital): "SERIEDAD DE LA OFERTA 00:00 HORAS DEL 29/07/2026 24:00 HORAS DEL 10/11/2026 129.970.022,40"
#   Seguros del Estado: "SERIEDAD DE LA OFERTA 29/07/2026 13/11/2026 $129,970,022.40"
#   Confianza: "SERIEDAD DE LA OFERTA 29/07/2026 10/11/2026 129,971,000.00"
# Los días, meses y años pueden traer errores del OCR (ver _fechas_posibles).
SERIEDAD_FILA_RE = re.compile(r"SER[IT1L]EDAD\s*(?:DE\s*(?:LA\s*)?)?OFERTA")
FECHA_FILA_RE = re.compile(
    r"(?<!\d)(\d{4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})(?!\d)"  # aaaa/mm/dd
    r"|(?<![\d:])(\d{1,3})\s*[/;-]\s*(\d{1,3})\s*[/;-]\s*(\d{4,5})(?!\d)"  # dd/mm/aaaa (";": OCR)
)
VALOR_FILA_RE = re.compile(r"(?<![\d.,])\d{1,3}(?:[.,]{1,2}\s?\d{3}){2,}(?:[.,]\d{1,2})?(?![\d])")
VENTANA_FILA = 260


# Cifra leída por el OCR → cifras que pudo ser en realidad.
_CONFUSIONES_OCR = {"8": "0", "6": "0", "7": "2"}


def _fechas_posibles(dia: str, mes: str, anio: str, anio_cierre: int) -> set[date]:
    """Fechas que puede ser "dia/mes/anio" leído de la póliza. Si se lee tal
    cual y el año es razonable, es esa. Si no, es un error de OCR (la fuente
    monoespaciada de algunas pólizas hace leer 0 como 8 o 6 y 2 como 7:
    "24/11/2826", "31/18/2826", "24/11/28726", "24/11/7076") y se devuelven
    TODAS las lecturas posibles deshaciendo esas confusiones o quitando una
    cifra de más; quien las usa solo da por buena la vigencia si todas la
    cumplen."""
    def valida(d: str, m: str, a: str) -> date | None:
        try:
            fecha = date(int(a), int(m), int(d))
        except ValueError:
            return None
        return fecha if anio_cierre <= fecha.year <= anio_cierre + 2 else None

    directa = valida(dia, mes, anio)
    if directa is not None:
        return {directa}

    def variantes(texto: str, largo: int) -> set[str]:
        if len(texto) <= largo:
            recortes = {texto}
        elif len(texto) == largo + 1:  # una cifra de más ("28726")
            recortes = {texto[:i] + texto[i + 1 :] for i in range(len(texto))}
        else:
            return set()
        salida: set[str] = set()
        for r in recortes:
            salida.update("".join(p) for p in product(*[(c, *_CONFUSIONES_OCR.get(c, "")) for c in r]))
        return salida

    return {
        f
        for d in variantes(dia, 2)
        for m in variantes(mes, 2)
        for a in variantes(anio, 4)
        if (f := valida(d, m, a)) is not None
    }


class LecturaAmparo:
    """Vigencia final (todas las fechas posibles si el OCR la dejó ambigua) y
    suma asegurada leídas de la póliza."""

    def __init__(self, hasta: set[date], valor: float | None) -> None:
        self.hasta = hasta
        self.valor = valor


# La fila termina donde empiezan otros campos con fecha propia ("FECHA
# ADJUDICACION : 13/08/2026", fecha de pago): se vio con pólizas reales en
# las que el OCR dañó una fecha de la fila y la de adjudicación ocupaba su
# lugar.
FIN_FILA_RE = re.compile(r"FECHA|ADJUDICACION|PAGO")


def _fechas_de_fila(ventana: str, anio_cierre: int) -> list[set[date]]:
    """Las fechas de la fila EN SU POSICIÓN (desde, hasta): una que no se
    pueda leer queda como conjunto vacío, no se salta."""
    fechas = []
    for m in FECHA_FILA_RE.finditer(ventana):
        if m.group(1):
            fechas.append(_fechas_posibles(m.group(3), m.group(2), m.group(1), anio_cierre))
        else:
            fechas.append(_fechas_posibles(m.group(4), m.group(5), m.group(6), anio_cierre))
    return fechas


def _leer_fila_seriedad(texto_norm: str, anio_cierre: int, valor_exigido: float) -> LecturaAmparo | None:
    """La fila del amparo de seriedad con dos fechas (desde, hasta) y una
    suma asegurada razonable (entre 1/100 y 20 veces el valor exigido: así
    no se toma la prima ni el presupuesto). Si la fila aparece varias veces
    (dos lecturas de OCR), se toma la lectura más exigente: todas las fechas
    posibles y el valor más bajo."""
    lecturas = []
    for m in SERIEDAD_FILA_RE.finditer(texto_norm):
        ventana = texto_norm[m.end() : m.end() + VENTANA_FILA]
        fin = FIN_FILA_RE.search(ventana)
        if fin is not None:
            ventana = ventana[: fin.start()]
        fechas = _fechas_de_fila(ventana, anio_cierre)
        valores = [
            v
            for v in (_parsear_valor_pesos(x.group(0)) for x in VALOR_FILA_RE.finditer(ventana))
            if v is not None and valor_exigido / 100 <= v <= valor_exigido * 20
        ]
        if len(fechas) >= 2 and fechas[1] and valores:
            lecturas.append(LecturaAmparo(fechas[1], max(valores)))
    if not lecturas:
        return None
    return LecturaAmparo(set().union(*(l.hasta for l in lecturas)), min(l.valor for l in lecturas))


def _con_pista(nombre: str) -> bool:
    base = _norm(nombre.rsplit("/", 1)[-1])
    return any(p.upper() in base for p in PISTAS_POLIZA)


def _orden_busqueda(nombres: list[str]) -> list[str]:
    return sorted(nombres, key=lambda nombre: 0 if _con_pista(nombre) else 1)


def _tiene_fila_seriedad(texto_norm: str) -> bool:
    """Hay una fila del amparo de seriedad con sus dos fechas (sin validar
    aún los valores: eso lo hace _leer_fila_seriedad)."""
    return any(
        len(FECHA_FILA_RE.findall(texto_norm[m.end() : m.end() + VENTANA_FILA])) >= 2
        for m in SERIEDAD_FILA_RE.finditer(texto_norm)
    )


def _es_poliza(texto_norm: str) -> bool:
    return bool(TITULO_POLIZA_RE.search(texto_norm)) and (
        bool(CAMPO_VIGENCIA_RE.search(texto_norm)) or _tiene_fila_seriedad(texto_norm)
    )


@memo_por_pdfs
def encontrar_poliza(pdfs: dict[str, bytes]) -> tuple[str, str] | None:
    """Busca la póliza de garantía de seriedad de la oferta por su título
    interno, sin importar el nombre del archivo. Devuelve (nombre_archivo,
    texto) o None.

    Si la póliza es escaneada, a su texto se le suma el del OCR reforzado
    (el normal pierde las tablas de varias aseguradoras). Entre varios
    documentos con título de póliza (la carátula y el clausulado, por
    ejemplo) se prefiere el que trae la fila del amparo de seriedad."""
    mejor, puntaje_mejor = None, (-1, -1, -1)
    patron_beneficiario = _beneficiario_re()
    for nombre in _orden_busqueda(list(pdfs.keys())):
        contenido = pdfs[nombre]
        try:
            texto = extraer_texto(contenido, max_paginas=PAGINAS_A_REVISAR)
        except Exception:  # noqa: BLE001
            continue
        texto_norm = _norm(texto)
        es_poliza = _es_poliza(texto_norm)
        if not es_poliza and not (_con_pista(nombre) or SERIEDAD_FILA_RE.search(texto_norm)):
            continue
        try:
            reforzado = texto_ocr_reforzado(contenido, max_paginas=PAGINAS_A_REVISAR)
        except Exception:  # noqa: BLE001
            reforzado = ""
        if reforzado:
            texto = f"{texto}\n{reforzado}"
            texto_norm = _norm(texto)
            es_poliza = es_poliza or _es_poliza(texto_norm)
        if not es_poliza:
            continue
        # La carátula trae la fila del amparo (o sus campos) y a la entidad
        # como beneficiaria; el clausulado, ninguno de los dos.
        puntaje = (
            int(_tiene_fila_seriedad(texto_norm)),
            int(bool(patron_beneficiario and patron_beneficiario.search(texto_norm))),
            int(bool(VIGENCIA_CARATULA_RE.search(texto_norm) or VALOR_CARATULA_RE.search(texto_norm))),
        )
        if puntaje[:2] == (1, 1):
            return nombre, texto
        if puntaje > puntaje_mejor:
            mejor, puntaje_mejor = (nombre, texto), puntaje
    return mejor


VALOR_MAXIMO_RAZONABLE_IA = 3

_INSTRUCCION_POLIZA = (
    "Esta es una póliza de garantía de seriedad de la oferta. Extrae: el beneficiario/asegurado; la fecha final de "
    "vigencia (VIGENCIA HASTA) del amparo de seriedad de la oferta; y el VALOR ASEGURADO (suma asegurada) de ese "
    "amparo. Ojo: el valor asegurado NO es la prima, ni el IVA, ni el total a pagar, ni el presupuesto del proceso. "
    'Responde JSON: {"beneficiario": str|null, "vigencia_hasta": "dd/mm/aaaa"|null, "valor_asegurado": str|null}'
)


def _extraer_poliza_con_ia(texto: str) -> dict[str, str]:
    """Datos de la póliza extraídos por el modelo local que pasaron la
    verificación contra el texto. Claves posibles: beneficiario,
    vigencia_hasta (dd/mm/aaaa), valor."""
    respuesta = consultar_json(_INSTRUCCION_POLIZA, texto)
    if not respuesta:
        return {}
    verificados: dict[str, str] = {}

    beneficiario = respuesta.get("beneficiario")
    if isinstance(beneficiario, str) and aparece_en_texto(beneficiario, texto):
        beneficiario_norm = _norm(beneficiario)
        if any(_norm(c) in beneficiario_norm for c in criterios.valor("beneficiario_claves") if c.strip()):
            verificados["beneficiario"] = beneficiario

    vigencia = respuesta.get("vigencia_hasta")
    if isinstance(vigencia, str) and re.fullmatch(r"\d{2}/\d{2}/\d{4}", vigencia.strip()):
        # Los dígitos de la fecha deben estar en el texto: descarta fechas
        # "corregidas" por el modelo sobre un OCR ilegible.
        if _fecha_en_texto(vigencia.strip(), texto):
            verificados["vigencia_hasta"] = vigencia.strip()

    valor = respuesta.get("valor_asegurado")
    if isinstance(valor, str) and aparece_en_texto(valor, texto, numerico=True):
        verificados["valor"] = re.sub(r"[^\d.,]", "", valor)
    return verificados


def _leer_caratula(texto_norm: str, anio_cierre: int, valor_exigido: float) -> LecturaAmparo | None:
    """Vigencia y valor total de la carátula (Seguros del Estado), para
    cuando no se encontró la fila del amparo."""
    vigencia = VIGENCIA_CARATULA_RE.search(texto_norm)
    valor = VALOR_CARATULA_RE.search(texto_norm)
    if vigencia is None or valor is None:
        return None
    dia, mes, anio = vigencia.groups()[6:9]
    leido = _parsear_valor_pesos(valor.group(1))
    if leido is None or not (valor_exigido / 100 <= leido <= valor_exigido * 20):
        # Un valor absurdo (ej. "$522" en una póliza leída con OCR) es otro
        # campo o un error de lectura: se trata como no leído.
        return None
    return LecturaAmparo(_fechas_posibles(dia, mes, anio, anio_cierre), leido)


# Encabezado de la carátula de Mundial, que repite la vigencia de la póliza:
# "VIGENCIA DESDE VIGENCIA HASTA ... 00:00 HORAS DEL | 24/07/2026 |24:00
# HORAS DEL | 01/12/2026", con el valor en "TOTAL ASEGURADO $ 545.895.454,50".
# Una póliza de seriedad solo tiene ese amparo, así que es su vigencia.
VIGENCIA_HORAS_RE = re.compile(
    r"VIGENCIA\s*DESDE\s*VIGENCIA\s*HASTA.{0,200}?HORAS\s*DEL\W{0,4}(\S{1,3}[/;-]\S{1,3}[/;-]\d{4,5})"
    r".{0,30}?HORAS\s*DEL\W{0,4}(\S{1,3}[/;-]\S{1,3}[/;-]\d{4,5})"
)
TOTAL_ASEGURADO_RE = re.compile(r"TOTAL\s*ASEGURADO\W{0,4}(" + VALOR_FILA_RE.pattern + ")")


def _leer_encabezado_horas(texto_norm: str, anio_cierre: int, valor_exigido: float) -> LecturaAmparo | None:
    hasta: set[date] = set()
    for m in VIGENCIA_HORAS_RE.finditer(texto_norm):
        fechas = _fechas_de_fila(m.group(2), anio_cierre)
        if fechas and fechas[0]:  # una lectura ilegible (otra pasada de OCR) no cuenta
            hasta |= fechas[0]
    valores = [
        v
        for v in (_parsear_valor_pesos(m.group(1)) for m in TOTAL_ASEGURADO_RE.finditer(texto_norm))
        if v is not None and valor_exigido / 100 <= v <= valor_exigido * 20
    ]
    if not hasta or not valores:
        return None
    return LecturaAmparo(hasta, min(valores))


def leer_vigencia_y_valor(texto_norm: str, anio_cierre: int, valor_exigido: float) -> LecturaAmparo | None:
    """La vigencia final y la suma asegurada del amparo de seriedad: de su
    fila en la póliza o, si no está, de la carátula."""
    return (
        _leer_fila_seriedad(texto_norm, anio_cierre, valor_exigido)
        or _leer_caratula(texto_norm, anio_cierre, valor_exigido)
        or _leer_encabezado_horas(texto_norm, anio_cierre, valor_exigido)
    )


class ResultadoEvaluacionGarantia:
    def __init__(self, cumple: bool, motivo: str | None, archivo: str | None) -> None:
        self.cumple = cumple
        self.motivo = motivo
        self.archivo = archivo


# "LOTE 2", "LOTE NO. 1", "LOTES 1 Y 2", "LOTES: 1, 2".
_LOTE_NUMERO_RE = re.compile(r"\bLOTE\s*(?:NO\.?\s*)?(\d+)\b")
_LOTES_LISTA_RE = re.compile(r"\bLOTES\s*:?\s*((?:\d+\s*(?:,|Y)\s*)+\d+)")


def _numeros_de_lote(texto_norm: str) -> set[str]:
    numeros = set(_LOTE_NUMERO_RE.findall(texto_norm))
    for lista in _LOTES_LISTA_RE.findall(texto_norm):
        numeros.update(re.findall(r"\d+", lista))
    return numeros


def lotes_presentados(pdfs: dict[str, bytes], texto_poliza_norm: str, proceso: ProcesoDocumentoBase) -> set[str]:
    """Números de los lotes a los que se presenta el proponente. Cada lote
    tiene su propia garantía y, si se presenta a varios, se exige la del más
    caro (indicación del abogado). Se leen del objeto que copia la carta de
    presentación (entre "OBJETO" y "SEÑORES"); si la póliza nombra otros
    lotes se usa la unión, para no bajar la exigencia por un error de lectura.
    Si no se identifica ninguno, se devuelven todos los del proceso."""
    del_proceso = {n for lote in proceso.lotes for n in re.findall(r"\d+", lote.numero)}
    carta: set[str] = set()
    encontrado = encontrar_formato1(pdfs)
    if encontrado is not None:
        texto = _norm(extraer_texto(encontrado[1], max_paginas=2))
        inicio = texto.find("OBJETO")
        if inicio >= 0:
            fin = texto.find("SENORES", inicio)
            carta = _numeros_de_lote(texto[inicio : fin if fin > inicio else inicio + 2500]) & del_proceso
    poliza = _numeros_de_lote(texto_poliza_norm) & del_proceso
    lotes = carta | poliza if carta else poliza
    return lotes or del_proceso


def valor_asegurado_exigido(proceso: ProcesoDocumentoBase, lotes: set[str]) -> tuple[float, str]:
    """(valor mínimo, descripción) para los lotes a los que se presenta."""
    garantia = proceso.garantia_seriedad
    if garantia.base_calculo != "lote_mayor_valor" or not proceso.lotes:
        return garantia.valor_asegurado, "el presupuesto total"
    candidatos = [lote for lote in proceso.lotes if set(re.findall(r"\d+", lote.numero)) & lotes] or proceso.lotes
    mayor = max(candidatos, key=lambda lote: lote.valor_presupuesto)
    return round(mayor.valor_presupuesto * garantia.porcentaje, 2), mayor.numero


def evaluar_requisito11(pdfs: dict[str, bytes], proceso: ProcesoDocumentoBase) -> ResultadoEvaluacionGarantia:
    """Requisito 11: la garantía de seriedad de la oferta debe tener como
    beneficiario a la entidad, cubrir al menos hasta la fecha de
    vencimiento ya calculada en el Documento Base (fecha_cierre +
    vigencia_meses) y asegurar al menos el valor ya calculado (10% del
    lote de mayor valor, o del presupuesto total)."""
    encontrado = encontrar_poliza(pdfs)
    if encontrado is None:
        return ResultadoEvaluacionGarantia(
            cumple=False,
            motivo="No se encontró la póliza de garantía de seriedad de la oferta por título dentro de los documentos del proponente.",
            archivo=None,
        )

    archivo, texto = encontrado
    texto_norm = _norm(texto)
    garantia = proceso.garantia_seriedad
    lotes = lotes_presentados(pdfs, texto_norm, proceso)
    valor_exigido, lote_referencia = valor_asegurado_exigido(proceso, lotes)
    lotes_texto = ", ".join(f"Lote {n}" for n in sorted(lotes, key=int))

    motivos = []
    anio_cierre = garantia.fecha_cierre.year

    patron_beneficiario = _beneficiario_re()
    beneficiario_ok = bool(patron_beneficiario.search(texto_norm)) if patron_beneficiario else False
    lectura = leer_vigencia_y_valor(texto_norm, anio_cierre, valor_exigido)
    datos_con_ia = False
    if not beneficiario_ok or lectura is None:
        # Formato no reconocido por las reglas (otra aseguradora, póliza
        # escaneada): el modelo local extrae los datos que falten, y cada uno
        # se acepta solo si aparece en el documento.
        extraidos = _extraer_poliza_con_ia(texto)
        if not beneficiario_ok and extraidos.get("beneficiario"):
            beneficiario_ok = datos_con_ia = True
        if lectura is None and extraidos.get("vigencia_hasta") and extraidos.get("valor"):
            dia, mes, anio = extraidos["vigencia_hasta"].split("/")
            lectura = LecturaAmparo(_fechas_posibles(dia, mes, anio, anio_cierre), _parsear_valor_pesos(extraidos["valor"]))
            datos_con_ia = True

    if not beneficiario_ok:
        claves = criterios.valor("beneficiario_claves")
        motivos.append(
            f"no se pudo confirmar que el beneficiario de la póliza sea la entidad ({claves[0]})"
            if claves
            else "no está configurado el beneficiario de la póliza de la entidad: confírmalo manualmente"
        )

    if lectura is None:
        motivos.append(
            "no se pudieron leer la vigencia y el valor asegurado del amparo de seriedad de la oferta — confirma manualmente"
        )
    else:
        minima = garantia.fecha_vencimiento
        if not lectura.hasta:
            # Pólizas escaneadas: una fecha fuera de un rango razonable
            # ("15/11/2826") se trata como ilegible en vez de darla por buena.
            motivos.append("no se pudo leer la fecha de vencimiento de la vigencia de la póliza")
        elif max(lectura.hasta) < minima:
            motivos.append(
                f"la póliza vence el {max(lectura.hasta).strftime('%d/%m/%Y')}, antes de la fecha mínima requerida "
                f"({minima.strftime('%d/%m/%Y')})"
            )
        elif min(lectura.hasta) < minima:
            # El OCR dejó la fecha ambigua y no todas sus lecturas cumplen.
            posibles = ", ".join(f.strftime("%d/%m/%Y") for f in sorted(lectura.hasta))
            motivos.append(
                f"no se pudo leer con certeza la fecha de vencimiento de la póliza (puede ser {posibles}; la mínima "
                f"requerida es {minima.strftime('%d/%m/%Y')}) — confirma manualmente"
            )

        valor_asegurado_poliza = lectura.valor
        # Con datos de IA el tope es más estricto: el modelo podría tomar otro
        # valor del documento (ej. el presupuesto del lote, 10 veces mayor).
        tope = VALOR_MAXIMO_RAZONABLE_IA if datos_con_ia else 20
        if valor_asegurado_poliza is None:
            motivos.append("no se pudo leer el valor asegurado de la póliza")
        elif valor_asegurado_poliza > valor_exigido * tope or (
            # Un valor absurdamente bajo casi siempre es otro campo (la prima,
            # el IVA) leído como valor asegurado: se vio con una póliza real.
            datos_con_ia and valor_asegurado_poliza < valor_exigido / 100
        ):
            motivos.append("el valor asegurado leído de la póliza no es razonable — confirma manualmente")
        elif valor_asegurado_poliza < valor_exigido:
            motivos.append(
                f"la póliza asegura ${valor_asegurado_poliza:,.2f}, menos del valor mínimo requerido "
                f"(${valor_exigido:,.2f}, {garantia.porcentaje:.0%} de {lote_referencia}; se presenta a: {lotes_texto})"
            )

    if datos_con_ia:
        motivos = [f"{m} (datos leídos con IA local — verifica en el documento)" for m in motivos]
        if not motivos:
            return ResultadoEvaluacionGarantia(
                cumple=True,
                motivo="datos de la póliza leídos con IA local y verificados contra el texto del documento",
                archivo=archivo,
            )

    cumple = not motivos
    return ResultadoEvaluacionGarantia(cumple=cumple, motivo="; ".join(motivos) if motivos else None, archivo=archivo)


def evaluar_proponente_requisito11(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    base = {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
        "requisito": 11,
    }

    try:
        metadata = get_file_metadata(proponente.drive_file_id)
    except Exception:  # noqa: BLE001
        metadata = None

    md5 = metadata.get("md5Checksum") if metadata else None
    clave_cache = _clave_cache(proponente, proceso, md5, requisito=11)
    if md5:
        cacheado = _leer_cache(clave_cache)
        if cacheado is not None:
            return cacheado

    def finalizar(resultado: ResultadoRequisito, *, cacheable: bool) -> ResultadoRequisito:
        if cacheable and md5:
            _guardar_cache(clave_cache, resultado)
        return resultado

    try:
        zip_bytes = download_file_bytes(proponente.drive_file_id, metadata=metadata)
    except Exception as exc:  # noqa: BLE001
        return ResultadoRequisito(**base, error=f"No se pudo descargar el archivo de Drive: {exc}")

    pdfs = extraer_pdfs(zip_bytes)
    if not pdfs:
        return finalizar(
            ResultadoRequisito(**base, error="El archivo del proponente no contiene PDFs legibles (¿zip dañado?)."),
            cacheable=False,
        )

    resultado = evaluar_requisito11(pdfs, proceso)

    return finalizar(
        ResultadoRequisito(
            **base,
            cumple=resultado.cumple,
            motivo=resultado.motivo,
            archivo_evaluado=resultado.archivo,
            archivos_disponibles=sorted(pdfs.keys()) if resultado.archivo is None else [],
        ),
        cacheable=True,
    )
