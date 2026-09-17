from __future__ import annotations

import re
from datetime import date

from app.procesamiento.memoria_proponente import memo_por_pdfs
from app.evaluacion.formato1 import _clave_cache, _guardar_cache, _leer_cache, _norm, encontrar_formato1
from app.integrations.drive import download_file_bytes, get_file_metadata
from app.llm.cliente import aparece_en_texto, consultar_json
from app.models.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from app.procesamiento.pdf_utils import extraer_texto
from app.procesamiento.zip_utils import extraer_pdfs

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
TITULO_POLIZA_RE = re.compile(
    r"P\s?O?\s?LIZA\s*DE\s*(?:SEGURO\s*DE\s*|GARANTIA\s*UNICA\s*DE\s*)?CUMPLIMIENTO"
    r"|NUMERO\s+(?:DE\s+)?POLIZA:?\s*\S+\s+SEGURO\s+DE\s+CUMPLIMIENTO"
)
CAMPO_VIGENCIA_RE = re.compile(
    r"VIGENC\S{0,3}\s*\S{0,3}\s*HASTA"
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

# "BENEFICIARIO INSTITUTO DE CAMINOS Y CONSTRUCCIONES DE CUNDINAMARCA - ICCU
# NO. DOC. IDENTIDAD ..." — se exige la sigla de la entidad cerca de la
# palabra "BENEFICIARIO", sin depender del nombre completo (que podría venir
# con leves variaciones de redacción).
BENEFICIARIO_RE = re.compile(r"BENEFICIARIO.{0,150}ICCU")

# Fila del amparo específico de seriedad de la oferta, con sus propias fechas
# de vigencia y la suma asegurada. Formatos confirmados:
#   Mundial:            "SERIEDAD DE LA OFERTA 00:00 HORAS DEL 29/07/2026 24:00 HORAS DEL 10/11/2026 129.970.022,40"
#   Seguros del Estado: "SERIEDAD DE LA OFERTA 29/07/2026 13/11/2026 $129,970,022.40"
#   Confianza:          "SERIEDAD DE LA OFERTA 29/07/2026 10/11/2026 129,971,000.00"
# El separador decimal cambia según la aseguradora (ver _parsear_valor_pesos).
VALOR_PESOS_RE = r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?"
AMPARO_SERIEDAD_RE = re.compile(
    r"SERIEDAD DE LA OFERTA\s+(?:00:00\s*HORAS\s*DEL\s*)?(\d{2}/\d{2}/\d{4})\s+"
    rf"(?:24:00\s*HORAS\s*DEL\s*)?(\d{{2}}/\d{{2}}/\d{{4}})\s+\$?\s*({VALOR_PESOS_RE})"
)

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


def _parsear_fecha_ddmmyyyy(texto: str) -> date | None:
    match = re.match(r"(\d{2})/(\d{2})/(\d{4})", texto)
    if not match:
        return None
    dia, mes, anio = match.groups()
    try:
        return date(int(anio), int(mes), int(dia))
    except ValueError:
        return None


def _parsear_valor_pesos(texto: str) -> float | None:
    """Distintas aseguradoras usan distinto separador decimal en los mismos
    documentos (formato colombiano '1.234.567,89' vs. formato con coma de
    miles '1,234,567.89') — se asume que el separador decimal es el que
    aparece más a la derecha."""
    texto = texto.strip()
    if texto.rfind(",") > texto.rfind("."):
        limpio = texto.replace(".", "").replace(",", ".")
    else:
        limpio = texto.replace(",", "")
    try:
        return float(limpio)
    except ValueError:
        return None


def _orden_busqueda(nombres: list[str]) -> list[str]:
    def pista(nombre: str) -> int:
        base = _norm(nombre.rsplit("/", 1)[-1])
        return 0 if any(p.upper() in base for p in PISTAS_POLIZA) else 1

    return sorted(nombres, key=pista)


@memo_por_pdfs
def encontrar_poliza(pdfs: dict[str, bytes]) -> tuple[str, str] | None:
    """Busca la póliza de garantía de seriedad de la oferta por su título
    interno, sin importar el nombre del archivo. Devuelve (nombre_archivo,
    texto) o None."""
    for nombre in _orden_busqueda(list(pdfs.keys())):
        contenido = pdfs[nombre]
        try:
            texto = extraer_texto(contenido, max_paginas=PAGINAS_A_REVISAR)
        except Exception:  # noqa: BLE001
            continue
        texto_norm = _norm(texto)
        if TITULO_POLIZA_RE.search(texto_norm) and CAMPO_VIGENCIA_RE.search(texto_norm):
            return nombre, texto
    return None


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
        if "ICCU" in beneficiario_norm or "INSTITUTO DE CAMINOS" in beneficiario_norm:
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


def _leer_vigencia_y_valor(texto_norm: str) -> tuple[str | None, str | None]:
    """Devuelve (vigencia_hasta 'dd/mm/aaaa', valor asegurado) leídos de la
    fila del amparo de seriedad o, si no está, de la carátula de la póliza."""
    amparo = AMPARO_SERIEDAD_RE.search(texto_norm)
    if amparo is not None:
        return amparo.group(2), amparo.group(3)
    vigencia = VIGENCIA_CARATULA_RE.search(texto_norm)
    valor = VALOR_CARATULA_RE.search(texto_norm)
    if vigencia is None or valor is None:
        return None, None
    dia, mes, anio = vigencia.groups()[6:9]
    return f"{dia}/{mes}/{anio}", valor.group(1)


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
    beneficiario a la entidad (ICCU), cubrir al menos hasta la fecha de
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

    beneficiario_ok = bool(BENEFICIARIO_RE.search(texto_norm))
    fecha_hasta_texto, valor_texto = _leer_vigencia_y_valor(texto_norm)
    if valor_texto is not None:
        valor_leido = _parsear_valor_pesos(valor_texto)
        if valor_leido is None or not (
            valor_exigido / 100 <= valor_leido <= valor_exigido * 20
        ):
            # Un valor absurdo (ej. "$522" en una póliza leída con OCR) es otro
            # campo o un error de lectura: se trata como no leído.
            fecha_hasta_texto, valor_texto = None, None
    datos_con_ia = False
    if not beneficiario_ok or fecha_hasta_texto is None or valor_texto is None:
        # Formato no reconocido por las reglas (otra aseguradora, póliza
        # escaneada): el modelo local extrae los datos que falten, y cada uno
        # se acepta solo si aparece en el documento.
        extraidos = _extraer_poliza_con_ia(texto)
        if not beneficiario_ok and extraidos.get("beneficiario"):
            beneficiario_ok = datos_con_ia = True
        if (fecha_hasta_texto is None or valor_texto is None) and extraidos.get("vigencia_hasta") and extraidos.get("valor"):
            fecha_hasta_texto, valor_texto = extraidos["vigencia_hasta"], extraidos["valor"]
            datos_con_ia = True

    if not beneficiario_ok:
        motivos.append("no se pudo confirmar que el beneficiario de la póliza sea la entidad (ICCU)")

    if fecha_hasta_texto is None or valor_texto is None:
        motivos.append(
            "no se pudieron leer la vigencia y el valor asegurado del amparo de seriedad de la oferta — confirma manualmente"
        )
    else:
        fecha_hasta = _parsear_fecha_ddmmyyyy(fecha_hasta_texto)
        # Pólizas escaneadas se leen con OCR, que puede confundir dígitos
        # ("29/07/2026" -> "15/11/2826"): una fecha fuera de un rango
        # razonable se trata como ilegible en vez de darla por buena.
        if fecha_hasta is not None and not (
            garantia.fecha_cierre.year <= fecha_hasta.year <= garantia.fecha_cierre.year + 2
        ):
            fecha_hasta = None
        if fecha_hasta is None:
            motivos.append("no se pudo leer la fecha de vencimiento de la vigencia de la póliza")
        elif fecha_hasta < garantia.fecha_vencimiento:
            motivos.append(
                f"la póliza vence el {fecha_hasta.strftime('%d/%m/%Y')}, antes de la fecha mínima requerida "
                f"({garantia.fecha_vencimiento.strftime('%d/%m/%Y')})"
            )

        valor_asegurado_poliza = _parsear_valor_pesos(valor_texto)
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
