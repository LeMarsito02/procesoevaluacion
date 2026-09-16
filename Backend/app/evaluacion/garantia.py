from __future__ import annotations

import re
from datetime import date

from app.evaluacion.formato1 import _clave_cache, _guardar_cache, _leer_cache, _norm
from app.integrations.drive import download_file_bytes, get_file_metadata
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
TITULO_POLIZA_RE = re.compile(r"POLIZA DE (?:SEGURO DE |GARANTIA UNICA DE )?CUMPLIMIENTO")
CAMPO_VIGENCIA_RE = re.compile(r"VIGENCIA\s+HASTA")

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

    motivos = []

    if not BENEFICIARIO_RE.search(texto_norm):
        motivos.append("no se pudo confirmar que el beneficiario de la póliza sea la entidad (ICCU)")

    fecha_hasta_texto, valor_texto = _leer_vigencia_y_valor(texto_norm)
    if fecha_hasta_texto is None or valor_texto is None:
        motivos.append(
            "no se pudieron leer la vigencia y el valor asegurado del amparo de seriedad de la oferta — confirma manualmente"
        )
    else:
        fecha_hasta = _parsear_fecha_ddmmyyyy(fecha_hasta_texto)
        if fecha_hasta is None:
            motivos.append("no se pudo leer la fecha de vencimiento de la vigencia de la póliza")
        elif fecha_hasta < garantia.fecha_vencimiento:
            motivos.append(
                f"la póliza vence el {fecha_hasta.strftime('%d/%m/%Y')}, antes de la fecha mínima requerida "
                f"({garantia.fecha_vencimiento.strftime('%d/%m/%Y')})"
            )

        valor_asegurado_poliza = _parsear_valor_pesos(valor_texto)
        if valor_asegurado_poliza is None:
            motivos.append("no se pudo leer el valor asegurado de la póliza")
        elif valor_asegurado_poliza < garantia.valor_asegurado:
            motivos.append(
                f"la póliza asegura ${valor_asegurado_poliza:,.2f}, menos del valor mínimo requerido "
                f"(${garantia.valor_asegurado:,.2f})"
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
