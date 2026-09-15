from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pdfplumber

from app.evaluacion.formato1 import (
    _clave_cache,
    _guardar_cache,
    _leer_cache,
    _norm,
    obtener_tipo_proponente,
)
from app.integrations.drive import download_file_bytes, get_file_metadata
from app.models.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from app.procesamiento.zip_utils import extraer_pdfs

# El título interno es siempre este, sin importar el nombre del archivo
# ("Formato 2 - Conformación...", "Acuerdo Consorcial...", "4. Conformación
# Consorcio...", etc. son solo nombres de archivo distintos para el mismo
# documento).
TITULO_FORMATO2_RE = re.compile(r"FORMATO\s*2\b.{0,15}CONFORMACION DE PROPONENTE PLURAL")

PISTAS_NOMBRE_FORMATO2 = (
    "formato 2",
    "formato2",
    "conformacion de proponente plural",
    "conformacion consorcio",
    "conformacion union temporal",
    "acuerdo consorcial",
    "acuerdo union temporal",
    "documento consorcial",
)

# Los documentos reales revisados son cortos (2 páginas), pero se deja margen
# por si vienen fusionados con otro documento antes.
PAGINAS_A_REVISAR = 6

# "5. EL REPRESENTANTE DEL CONSORCIO ES ADRIANA MARCELA ROJAS PRIETO
# IDENTIFICADA CON CEDULA DE CIUDADANIA 52.371.321 DE BOGOTA D.C., QUIEN..."
# También se vieron variantes reales sin coma antes de "IDENTIFICADO" y sin
# la palabra "IDENTIFICADO" (solo "CON CEDULA DE CIUDADANIA # ...").
REPRESENTANTE_RE = re.compile(
    r"REPRESENTANTE(?:\s+PRINCIPAL)? (?:DEL CONSORCIO|DE LA UNION TEMPORAL) ES:?\s+"
    r"([A-ZÑ][A-ZÑ .]+?),?\s*(?:IDENTIFICAD[OA]\s+)?CON CEDULA DE CIUDADANIA\s*(?:#|NO\.?)?\s*([\d.,]+)"
)
REPRESENTANTE_SUPLENTE_RE = re.compile(
    r"REPRESENTANTE SUPLENTE (?:DEL CONSORCIO|DE LA UNION TEMPORAL) ES:?\s+"
    r"([A-ZÑ][A-ZÑ .]+?),?\s*(?:IDENTIFICAD[OA]\s+)?CON CEDULA DE CIUDADANIA\s*(?:#|NO\.?)?\s*([\d.,]+)"
)

# La tabla de integrantes sale desordenada en texto plano (nombres partidos
# en varias líneas), pero los porcentajes siempre quedan entre el
# encabezado "Compromiso (%)" y la nota al pie "El total de la columna...".
TABLA_INTEGRANTES_RE = re.compile(
    r"NOMBRE DEL INTEGRANTE.*?COMPROMISO\s*\(%\)\s*(?:\(1\)\s*)?(.*?)"
    r"(?:EL TOTAL DE LA COLUMNA|\d+\.\s*(?:EL CONSORCIO|LA UNION TEMPORAL) SE DENOMINA)",
    re.DOTALL,
)
PORCENTAJE_RE = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%")

TOLERANCIA_SUMA_PORCENTAJES = 1.5


def _orden_busqueda_formato2(nombres: list[str]) -> list[str]:
    def pista(nombre: str) -> int:
        base = _norm(nombre.rsplit("/", 1)[-1])
        return 0 if any(p.upper() in base for p in PISTAS_NOMBRE_FORMATO2) else 1

    return sorted(nombres, key=pista)


def encontrar_formato2(pdfs: dict[str, bytes]) -> tuple[str, str] | None:
    """Busca, entre los PDF del proponente, el Formato 2 (Conformación de
    Proponente Plural) por su título interno. Devuelve (nombre_archivo,
    texto_completo) o None."""
    for nombre in _orden_busqueda_formato2(list(pdfs.keys())):
        contenido = pdfs[nombre]
        try:
            with pdfplumber.open(io.BytesIO(contenido)) as pdf:
                texto = "\n".join((page.extract_text() or "") for page in pdf.pages[:PAGINAS_A_REVISAR])
        except Exception:  # noqa: BLE001
            continue
        if TITULO_FORMATO2_RE.search(_norm(texto)):
            return nombre, texto
    return None


@dataclass
class DatosProponentePlural:
    porcentajes: list[float]
    representante_principal: tuple[str, str] | None  # (nombre, cédula)
    representante_suplente: tuple[str, str] | None  # (nombre, cédula)


def extraer_datos_plural(texto: str) -> DatosProponentePlural:
    texto_norm = _norm(texto)

    porcentajes: list[float] = []
    tabla_match = TABLA_INTEGRANTES_RE.search(texto_norm)
    if tabla_match:
        porcentajes = [float(p.replace(",", ".")) for p in PORCENTAJE_RE.findall(tabla_match.group(1))]

    principal_match = REPRESENTANTE_RE.search(texto_norm)
    representante_principal = None
    if principal_match:
        nombre = re.sub(r"\s+", " ", principal_match.group(1)).strip(" .")
        representante_principal = (nombre, principal_match.group(2))

    suplente_match = REPRESENTANTE_SUPLENTE_RE.search(texto_norm)
    representante_suplente = None
    if suplente_match:
        nombre = re.sub(r"\s+", " ", suplente_match.group(1)).strip(" .")
        representante_suplente = (nombre, suplente_match.group(2))

    return DatosProponentePlural(
        porcentajes=porcentajes,
        representante_principal=representante_principal,
        representante_suplente=representante_suplente,
    )


class ResultadoEvaluacionPlural:
    def __init__(
        self,
        cumple: bool,
        motivo: str | None,
        datos: DatosProponentePlural | None,
        archivo_formato2: str | None,
    ) -> None:
        self.cumple = cumple
        self.motivo = motivo
        self.datos = datos
        self.archivo_formato2 = archivo_formato2


def evaluar_requisito4(pdfs: dict[str, bytes], tipo_proponente: str | None) -> ResultadoEvaluacionPlural:
    """Requisito 4: Conformación de Proponente Plural (Formato 2). N.A. si el
    proponente es individual (persona natural o jurídica); si es Consorcio o
    Unión Temporal, debe aportar el Formato 2 con los integrantes y sus
    porcentajes de participación (deben sumar 100%) y el representante legal
    designado para el consorcio/UT."""
    if tipo_proponente not in ("consorcio", "union_temporal"):
        return ResultadoEvaluacionPlural(
            cumple=True,
            motivo="N.A. — persona natural o jurídica individual",
            datos=None,
            archivo_formato2=None,
        )

    encontrado = encontrar_formato2(pdfs)
    if encontrado is None:
        return ResultadoEvaluacionPlural(
            cumple=False,
            motivo=(
                "El proponente es Consorcio/Unión Temporal pero no se encontró el Formato 2 (Conformación de "
                "Proponente Plural) por título dentro de sus documentos. Revisa manualmente."
            ),
            datos=None,
            archivo_formato2=None,
        )

    archivo_formato2, texto = encontrado
    datos = extraer_datos_plural(texto)

    motivos = []
    if not datos.porcentajes:
        motivos.append(
            "no se pudieron leer los porcentajes de participación de los integrantes en el Formato 2 — "
            "confirma manualmente que sumen 100%"
        )
    elif abs(sum(datos.porcentajes) - 100) > TOLERANCIA_SUMA_PORCENTAJES:
        motivos.append(
            f"los porcentajes de participación de los integrantes suman {sum(datos.porcentajes):g}%, no 100%"
        )

    if datos.representante_principal is None:
        motivos.append(
            "no se pudo identificar en el Formato 2 quién es el representante legal designado del "
            "consorcio/unión temporal — revisa manualmente"
        )

    cumple = not motivos
    motivo = "; ".join(motivos) if motivos else None

    return ResultadoEvaluacionPlural(cumple=cumple, motivo=motivo, datos=datos, archivo_formato2=archivo_formato2)


def obtener_personas_a_verificar(
    pdfs: dict[str, bytes], tipo_proponente: str | None, representante_individual: str | None
) -> list[tuple[str, str | None]]:
    """Devuelve la lista de personas cuyos antecedentes (REDAM, Contraloría,
    Procuraduría, Policía, RNMC) hay que verificar: el representante legal
    declarado en el Formato 1 si el proponente es individual, o el
    representante + suplente del consorcio/UT (Formato 2) si es plural — el
    abogado aclaró que en ese caso se revisan estas 2 personas, no cada
    integrante. Cada elemento es (nombre, cédula-o-None); si no se pudo
    identificar a nadie, devuelve una lista vacía."""
    if tipo_proponente not in ("consorcio", "union_temporal"):
        if representante_individual:
            return [(representante_individual, None)]
        return []

    encontrado = encontrar_formato2(pdfs)
    if encontrado is None:
        return []
    _, texto = encontrado
    datos = extraer_datos_plural(texto)
    personas: list[tuple[str, str | None]] = []
    if datos.representante_principal:
        personas.append(datos.representante_principal)
    if datos.representante_suplente:
        personas.append(datos.representante_suplente)
    return personas


def evaluar_proponente_requisito4(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    base = {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
        "requisito": 4,
    }

    try:
        metadata = get_file_metadata(proponente.drive_file_id)
    except Exception:  # noqa: BLE001
        metadata = None

    md5 = metadata.get("md5Checksum") if metadata else None
    clave_cache = _clave_cache(proponente, proceso, md5, requisito=4)
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
    resultado = evaluar_requisito4(pdfs, tipo_proponente)

    return finalizar(
        ResultadoRequisito(
            **base,
            cumple=resultado.cumple,
            motivo=resultado.motivo,
            archivo_evaluado=resultado.archivo_formato2,
            archivos_disponibles=sorted(pdfs.keys()) if resultado.archivo_formato2 is None else [],
            tipo_proponente=tipo_proponente,
        ),
        cacheable=True,
    )
