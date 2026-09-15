from __future__ import annotations

import io
import re
from datetime import date

import pdfplumber
from dateutil.relativedelta import relativedelta

from app.evaluacion.formato1 import (
    _clave_cache,
    _guardar_cache,
    _leer_cache,
    _norm,
    _tokens_significativos,
    obtener_tipo_proponente,
)
from app.integrations.drive import download_file_bytes, get_file_metadata
from app.models.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from app.procesamiento.zip_utils import extraer_pdfs

# El título se repite como encabezado en cada página, así que basta revisar
# la primera para identificar el documento — el contenido completo (objeto
# social, facultades) se lee aparte, ya en las páginas que hagan falta.
PAGINAS_PARA_TITULO = 1

VIGENCIA_MAXIMA_MESES = 1

# Título con variantes reales confirmadas entre Cámaras de Comercio: Bogotá
# dice "...REGISTRO UNICO DE PROPONENTES" (sin "EN EL"), Valledupar dice
# "...EN EL REGISTRO DE PROPONENTES", Medellín solo dice "CERTIFICADO DE
# PROPONENTES". El ".{0,20}" tolera esas variaciones entre "CLASIFICACION"
# y "PROPONENTES" sin depender de una redacción exacta.
TITULO_EXISTENCIA_RE = re.compile(r"CERTIFICADO DE EXISTENCIA Y REPRESENTACION LEGAL")
TITULO_RUP_RE = re.compile(r"CERTIFICADO DE (?:INSCRIPCION Y CLASIFICACION.{0,20})?PROPONENTES")

PISTAS_EXISTENCIA = ("existencia", "camara de comercio", "camara comercio", "rep legal", "representacion legal")
PISTAS_RUP = ("rup",)

MESES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}

# Confirmado con documentos reales de al menos 4 Cámaras de Comercio
# distintas, cada una con su propio formato:
#   - "FECHA EXPEDICION: 08/07/2026 - ..." (DD/MM/AAAA, Valledupar)
#   - "FECHA EXPEDICION: 2026/07/06 - ..." (AAAA/MM/DD, Barrancabermeja)
#   - "FECHA EXPEDICION: 20 DE JULIO DE 2026 HORA: ..." (Bogotá, Certificado
#     de Existencia)
#   - "CODIGO VERIFICACION: <codigo> 20 DE JULIO DE 2026 HORA ..." (Bogotá,
#     portada del RUP — sin ninguna etiqueta "fecha expedición")
# Se prueban en orden hasta que uno calce.
_FECHA_NUMERICA_RE = re.compile(r"FECHA(?:\s+DE)?\s+EXPEDICION:\s*(\d{2,4})/(\d{2})/(\d{2,4})")
_FECHA_MES_TEXTO_RE = re.compile(r"FECHA(?:\s+DE)?\s+EXPEDICION:\s*(\d{1,2})\s+DE\s+([A-Z]+)\s+DE\s+(\d{4})")
_FECHA_TRAS_CODIGO_VERIFICACION_RE = re.compile(
    r"CODIGO VERIFICACION:?\s*\S+\s+(\d{1,2})\s+DE\s+([A-Z]+)\s+DE\s+(\d{4})\s+HORA"
)


def _tiene_fecha_expedicion(texto_norm: str) -> bool:
    return bool(
        _FECHA_NUMERICA_RE.search(texto_norm)
        or _FECHA_MES_TEXTO_RE.search(texto_norm)
        or _FECHA_TRAS_CODIGO_VERIFICACION_RE.search(texto_norm)
    )


def _parsear_fecha_expedicion(texto_norm: str) -> date | None:
    match = _FECHA_NUMERICA_RE.search(texto_norm)
    if match:
        g1, g2, g3 = match.groups()
        try:
            if len(g1) == 4:
                return date(int(g1), int(g2), int(g3))
            return date(int(g3), int(g2), int(g1))
        except ValueError:
            return None

    for patron in (_FECHA_MES_TEXTO_RE, _FECHA_TRAS_CODIGO_VERIFICACION_RE):
        match = patron.search(texto_norm)
        if not match:
            continue
        dia_str, mes_texto, anio_str = match.groups()
        mes = MESES.get(mes_texto)
        if mes is None:
            continue
        try:
            return date(int(anio_str), mes, int(dia_str))
        except ValueError:
            return None
    return None


def _orden_busqueda(nombres: list[str], pistas: tuple[str, ...]) -> list[str]:
    def pista(nombre: str) -> int:
        base = _norm(nombre.rsplit("/", 1)[-1])
        return 0 if any(p.upper() in base for p in pistas) else 1

    return sorted(nombres, key=pista)


def encontrar_documentos(pdfs: dict[str, bytes], titulo_re: re.Pattern[str], pistas: tuple[str, ...]) -> list[str]:
    """Devuelve los nombres de TODOS los PDF cuyo título calza — puede haber
    más de uno en un proponente plural (uno por cada integrante persona
    jurídica). Exige, además del título, que también aparezca 'FECHA
    EXPEDICION': se encontraron documentos reales (respuestas a preguntas
    del SECOP, cartas de composición accionaria) que solo MENCIONAN de
    pasada "el certificado de existencia y representación legal..." sin ser
    el certificado real — un certificado real siempre trae ese campo de
    fecha en el encabezado, esos otros documentos no."""
    encontrados = []
    for nombre in _orden_busqueda(list(pdfs.keys()), pistas):
        contenido = pdfs[nombre]
        try:
            with pdfplumber.open(io.BytesIO(contenido)) as pdf:
                texto = "\n".join((page.extract_text() or "") for page in pdf.pages[:PAGINAS_PARA_TITULO])
        except Exception:  # noqa: BLE001
            continue
        texto_norm = _norm(texto)
        if titulo_re.search(texto_norm) and _tiene_fecha_expedicion(texto_norm):
            encontrados.append(nombre)
    return encontrados


def _texto_completo(pdfs: dict[str, bytes], nombre: str) -> str:
    with pdfplumber.open(io.BytesIO(pdfs[nombre])) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


class ResultadoEvaluacionCamara:
    def __init__(self, cumple: bool, motivo: str | None, archivo: str | None) -> None:
        self.cumple = cumple
        self.motivo = motivo
        self.archivo = archivo


def _evaluar_vigencia_documentos(
    pdfs: dict[str, bytes], titulo_re: re.Pattern[str], pistas: tuple[str, ...], nombre_doc: str, fecha_cierre: date
) -> ResultadoEvaluacionCamara:
    """Patrón compartido por los Requisitos 6 (Certificado de Existencia) y 9
    (RUP): ambos exigen vigencia máxima de 1 mes contada desde el cierre, y
    ambos comparten el mismo formato de 'FECHA EXPEDICION'."""
    encontrados = encontrar_documentos(pdfs, titulo_re, pistas)
    if not encontrados:
        return ResultadoEvaluacionCamara(
            cumple=False,
            motivo=f"No se encontró el {nombre_doc} por título dentro de los documentos del proponente.",
            archivo=None,
        )

    motivos = []
    for nombre in encontrados:
        texto_norm = _norm(_texto_completo(pdfs, nombre))
        fecha = _parsear_fecha_expedicion(texto_norm)
        if fecha is None:
            motivos.append(f"no se pudo leer la fecha de expedición de '{nombre}' — confirma manualmente que no supere 1 mes")
        elif fecha < fecha_cierre - relativedelta(months=VIGENCIA_MAXIMA_MESES):
            motivos.append(
                f"'{nombre}' fue expedido el {fecha.strftime('%d/%m/%Y')}, hace más de {VIGENCIA_MAXIMA_MESES} mes "
                f"contado desde la fecha de cierre ({fecha_cierre.strftime('%d/%m/%Y')})"
            )

    cumple = not motivos
    return ResultadoEvaluacionCamara(cumple=cumple, motivo="; ".join(motivos) if motivos else None, archivo=encontrados[0])


def evaluar_requisito6(pdfs: dict[str, bytes], fecha_cierre: date, tipo_proponente: str | None) -> ResultadoEvaluacionCamara:
    """Requisito 6: Certificado de Existencia y Representación Legal,
    expedido máximo 1 mes antes de la fecha de cierre. N.A. si el
    proponente es persona natural (no tiene Certificado de Existencia). Si
    es plural, se evalúan todos los certificados encontrados (uno por cada
    integrante persona jurídica)."""
    if tipo_proponente == "persona_natural":
        return ResultadoEvaluacionCamara(
            cumple=True, motivo="N.A. — persona natural, no aplica Certificado de Existencia y Representación Legal", archivo=None
        )
    return _evaluar_vigencia_documentos(
        pdfs, TITULO_EXISTENCIA_RE, PISTAS_EXISTENCIA, "Certificado de Existencia y Representación Legal", fecha_cierre
    )


def evaluar_requisito9(pdfs: dict[str, bytes], fecha_cierre: date) -> ResultadoEvaluacionCamara:
    """Requisito 9: RUP (Registro Único de Proponentes), expedido máximo 1
    mes antes de la fecha de cierre. Aplica a todos los tipos de
    proponente."""
    return _evaluar_vigencia_documentos(pdfs, TITULO_RUP_RE, PISTAS_RUP, "RUP", fecha_cierre)


# "OBJETO SOCIAL OBJETO SOCIAL. POR ACTA...LA SOCIEDAD TENDRA COMO OBJETO
# PRINCIPAL..." — se toma el texto que sigue al encabezado, igual que
# _extraer_objeto_carta hace con el objeto de la carta de presentación.
def _extraer_objeto_social(texto_norm: str) -> str | None:
    idx = texto_norm.find("OBJETO SOCIAL")
    if idx == -1:
        return None
    inicio = idx + len("OBJETO SOCIAL")
    return texto_norm[inicio : inicio + 1200].strip()


# Comparación por raíz de palabra (los primeros 3 caracteres), no por
# palabra exacta: un objeto social real (Cámara de Comercio de Bogotá)
# describía "...EL DISEÑO Y LA CONSTRUCCION DE REDES VIALES, CARRETERAS..."
# — relacionado de sobra con un proceso de interventoría de VÍAS, pero con
# comparación de palabras exactas la superposición daba 0 (“VIALES” ≠
# “VIAS”). Con raíces de 3 caracteres, "VIA" cubre "VIAS"/"VIAL"/"VIALES".
def _raiz(palabra: str) -> str:
    return palabra[:3]


def _proporcion_objeto_relacionado_laxo(objeto_social: str, objeto_base: str) -> float:
    raices_base = {_raiz(t) for t in _tokens_significativos(objeto_base)}
    if not raices_base:
        return 1.0
    raices_social = {_raiz(t) for t in _tokens_significativos(objeto_social)}
    comunes = raices_social & raices_base
    return len(comunes) / len(raices_base)


# Umbral mucho más bajo que el 0.5 del Requisito 1: ahí se compara el
# objeto de la CARTA (que normalmente copia casi textual el objeto del
# proceso) contra el objeto del proceso. Aquí se compara el objeto SOCIAL
# de la empresa (una descripción amplia y genérica de todas las
# actividades que puede realizar, redactada años antes de este proceso)
# contra el objeto específico del proceso — nunca van a compartir la
# mayoría de las palabras. Confirmado con proponentes reales del sector
# construcción/ingeniería (ya con la comparación por raíz): entre 0.14 y
# 0.43; un objeto social sintético claramente NO relacionado (venta de
# alimentos y ropa) dio 0.0 — el umbral solo necesita distinguir "algo" de
# "nada" en común.
PROPORCION_MINIMA_OBJETO_SOCIAL = 0.1


def evaluar_requisito7(
    pdfs: dict[str, bytes], objeto_base: str, tipo_proponente: str | None
) -> ResultadoEvaluacionCamara:
    """Requisito 7: el objeto social del Certificado de Existencia debe
    relacionarse con el objeto del proceso — reutiliza la comparación de
    palabras clave del Requisito 1 (Carta de presentación), pero con un
    umbral mucho más permisivo (ver PROPORCION_MINIMA_OBJETO_SOCIAL). N.A.
    si es persona natural."""
    if tipo_proponente == "persona_natural":
        return ResultadoEvaluacionCamara(
            cumple=True, motivo="N.A. — persona natural, no aplica objeto social", archivo=None
        )

    encontrados = encontrar_documentos(pdfs, TITULO_EXISTENCIA_RE, PISTAS_EXISTENCIA)
    if not encontrados:
        return ResultadoEvaluacionCamara(
            cumple=False,
            motivo="No se encontró el Certificado de Existencia y Representación Legal por título dentro de los documentos del proponente.",
            archivo=None,
        )

    motivos = []
    for nombre in encontrados:
        texto_norm = _norm(_texto_completo(pdfs, nombre))
        objeto_social = _extraer_objeto_social(texto_norm)
        proporcion = _proporcion_objeto_relacionado_laxo(objeto_social or "", objeto_base)
        if proporcion < PROPORCION_MINIMA_OBJETO_SOCIAL:
            motivos.append(f"el objeto social de '{nombre}' no se relaciona claramente con el objeto del proceso")

    cumple = not motivos
    return ResultadoEvaluacionCamara(cumple=cumple, motivo="; ".join(motivos) if motivos else None, archivo=encontrados[0])


# Confirmado con dos redacciones reales distintas para "sin restricción de
# cuantía": "SIN LIMITE DE CUANTIA" (Cámara de Valledupar) y "NO TENDRA
# RESTRICCIONES DE CONTRATACION POR RAZON DE LA NATURALEZA NI DE LA CUANTIA"
# (Cámara de Barrancabermeja). Si no calza ninguna, no se asume que SÍ hay
# límite — solo que no se pudo confirmar que no lo haya, y en cualquiera de
# los dos casos el abogado indicó que debe quedar para revisión humana (un
# límite requeriría cruzar el valor del proceso contra un acta de
# autorización, algo que no es automatizable con certeza).
FACULTADES_SIN_LIMITE_PATRONES = [
    re.compile(r"SIN LIMITE(?:S)? DE CUANTIA"),
    re.compile(r"NO TENDR[AÁ]?\S* RESTRICCION(?:ES)?\s+DE\s+CONTRATACION.{0,80}CUANTIA"),
    re.compile(r"SIN RESTRICCION(?:ES)?.{0,40}CUANTIA"),
]


def evaluar_requisito8(pdfs: dict[str, bytes], tipo_proponente: str | None) -> ResultadoEvaluacionCamara:
    """Requisito 8: Facultades del representante legal — cumple solo cuando
    el certificado indica expresamente que no hay restricción de cuantía
    para contratar. Cualquier otro caso (hay un límite mencionado, o no se
    pudo confirmar) queda para revisión humana. N.A. si es persona natural."""
    if tipo_proponente == "persona_natural":
        return ResultadoEvaluacionCamara(
            cumple=True, motivo="N.A. — persona natural, no aplica certificado de facultades", archivo=None
        )

    encontrados = encontrar_documentos(pdfs, TITULO_EXISTENCIA_RE, PISTAS_EXISTENCIA)
    if not encontrados:
        return ResultadoEvaluacionCamara(
            cumple=False,
            motivo="No se encontró el Certificado de Existencia y Representación Legal por título dentro de los documentos del proponente.",
            archivo=None,
        )

    motivos = []
    for nombre in encontrados:
        texto_norm = _norm(_texto_completo(pdfs, nombre))
        if not any(patron.search(texto_norm) for patron in FACULTADES_SIN_LIMITE_PATRONES):
            motivos.append(
                f"'{nombre}' no confirma expresamente que el representante legal no tenga restricción de cuantía "
                "para contratar — revisa manualmente si menciona un límite y si el proceso lo supera"
            )

    cumple = not motivos
    return ResultadoEvaluacionCamara(cumple=cumple, motivo="; ".join(motivos) if motivos else None, archivo=encontrados[0])


def evaluar_requisito10(pdfs: dict[str, bytes]) -> ResultadoEvaluacionCamara:
    """Requisito 10: Sanciones dentro del RUP. Limitación conocida: se
    revisó el RUP real de un proponente (32 páginas) y no existe una
    sección de 'sanciones' o 'multas' identificable por texto — el
    documento no la incluye cuando no hay novedades, así que no hay una
    frase de 'sin novedad' que buscar (a diferencia de los certificados de
    antecedentes). Por eso este requisito siempre se deja para revisión
    humana en vez de arriesgar una confirmación automática sin base real."""
    encontrados = encontrar_documentos(pdfs, TITULO_RUP_RE, PISTAS_RUP)
    if not encontrados:
        return ResultadoEvaluacionCamara(
            cumple=False, motivo="No se encontró el RUP por título dentro de los documentos del proponente.", archivo=None
        )
    return ResultadoEvaluacionCamara(
        cumple=False,
        motivo=(
            "El RUP no trae una sección de sanciones/multas identificable automáticamente — confirma manualmente "
            "revisando el documento completo."
        ),
        archivo=encontrados[0],
    )


def _evaluar_proponente_camara(
    requisito: int, evaluador, proponente: Proponente, proceso: ProcesoDocumentoBase
) -> ResultadoRequisito:
    """Descarga+cachea el zip del proponente y delega en `evaluador`, que
    recibe (pdfs, tipo_proponente) y devuelve un ResultadoEvaluacionCamara.
    Función de módulo (no closure) para que sea picklable por
    ProcessPoolExecutor — el mismo bug que ya rompió los evaluadores de
    antecedentes con un closure similar."""
    base = {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
        "requisito": requisito,
    }

    try:
        metadata = get_file_metadata(proponente.drive_file_id)
    except Exception:  # noqa: BLE001
        metadata = None

    md5 = metadata.get("md5Checksum") if metadata else None
    clave_cache = _clave_cache(proponente, proceso, md5, requisito=requisito)
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

    tipo_proponente = obtener_tipo_proponente(pdfs)
    resultado = evaluador(pdfs, proceso, tipo_proponente)

    return finalizar(
        ResultadoRequisito(
            **base,
            cumple=resultado.cumple,
            motivo=resultado.motivo,
            archivo_evaluado=resultado.archivo,
            archivos_disponibles=sorted(pdfs.keys()) if resultado.archivo is None else [],
            tipo_proponente=tipo_proponente,
        ),
        cacheable=True,
    )


def evaluar_proponente_requisito6(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_camara(
        6, lambda pdfs, proceso, tipo: evaluar_requisito6(pdfs, proceso.fecha_cierre, tipo), proponente, proceso
    )


def evaluar_proponente_requisito7(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_camara(
        7, lambda pdfs, proceso, tipo: evaluar_requisito7(pdfs, proceso.objeto_general, tipo), proponente, proceso
    )


def evaluar_proponente_requisito8(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_camara(8, lambda pdfs, proceso, tipo: evaluar_requisito8(pdfs, tipo), proponente, proceso)


def evaluar_proponente_requisito9(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_camara(
        9, lambda pdfs, proceso, tipo: evaluar_requisito9(pdfs, proceso.fecha_cierre), proponente, proceso
    )


def evaluar_proponente_requisito10(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_camara(10, lambda pdfs, proceso, tipo: evaluar_requisito10(pdfs), proponente, proceso)


# "ORGANIZACION JURIDICA: SOCIEDAD POR ACCIONES SIMPLIFICADA CATEGORIA :
# PERSONA JURIDICA PRINCIPAL NIT :..." — confirmado con un Certificado de
# Existencia real (SIMO SAS). "SOCIEDAD ANONIMA" y "SOCIEDAD POR ACCIONES
# SIMPLIFICADA" (S.A.S.) son frases completamente distintas en español, así
# que basta buscar la primera literalmente sin riesgo de confundirla con
# S.A.S. No se encontró en los documentos reales revisados un proponente
# que sea efectivamente una S.A. (todos eran S.A.S.), así que esta parte no
# se pudo validar contra un caso real — queda como limitación conocida.
SOCIEDAD_ANONIMA_RE = re.compile(r"SOCIEDAD ANONIMA(?!\s*SIMPLIFICADA)")
SOCIEDAD_ABIERTA_RE = re.compile(r"\bABIERTA\b")
SOCIEDAD_CERRADA_RE = re.compile(r"\bCERRADA\b")


def evaluar_requisito18(pdfs: dict[str, bytes], tipo_proponente: str | None) -> ResultadoEvaluacionCamara:
    """Requisito 18: Certificado de Revisor Fiscal indicando si la sociedad
    es abierta o cerrada. N.A. si el proponente no es una Sociedad Anónima
    (S.A.) — incluye personas naturales y cualquier otro tipo societario
    (S.A.S., Ltda., etc.), que no están obligados a este certificado. No
    validado contra un proponente S.A. real (limitación conocida, ver
    comentario en SOCIEDAD_ANONIMA_RE)."""
    if tipo_proponente == "persona_natural":
        return ResultadoEvaluacionCamara(cumple=True, motivo="N.A. — persona natural", archivo=None)

    encontrados = encontrar_documentos(pdfs, TITULO_EXISTENCIA_RE, PISTAS_EXISTENCIA)
    if not encontrados:
        return ResultadoEvaluacionCamara(
            cumple=False,
            motivo="No se encontró el Certificado de Existencia y Representación Legal por título dentro de los documentos del proponente.",
            archivo=None,
        )

    es_sociedad_anonima = False
    for nombre in encontrados:
        texto_norm = _norm(_texto_completo(pdfs, nombre))
        if SOCIEDAD_ANONIMA_RE.search(texto_norm):
            es_sociedad_anonima = True
            if SOCIEDAD_ABIERTA_RE.search(texto_norm) or SOCIEDAD_CERRADA_RE.search(texto_norm):
                return ResultadoEvaluacionCamara(cumple=True, motivo=None, archivo=nombre)

    if not es_sociedad_anonima:
        return ResultadoEvaluacionCamara(
            cumple=True, motivo="N.A. — el proponente no es una Sociedad Anónima (S.A.)", archivo=None
        )

    return ResultadoEvaluacionCamara(
        cumple=False,
        motivo="El proponente es una Sociedad Anónima (S.A.), pero no se pudo confirmar si es abierta o cerrada — revisa manualmente el certificado de Revisor Fiscal.",
        archivo=encontrados[0],
    )


def evaluar_proponente_requisito18(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_camara(18, lambda pdfs, proceso, tipo: evaluar_requisito18(pdfs, tipo), proponente, proceso)
