from __future__ import annotations

import io
import re

import pdfplumber

from app.evaluacion.formato1 import (
    _clave_cache,
    _extraer_nombre_apertura,
    _extraer_representante_legal,
    _guardar_cache,
    _leer_cache,
    _norm,
    _tokens_nombre,
    encontrar_formato1,
    obtener_tipo_proponente,
)
from app.integrations.drive import download_file_bytes, get_file_metadata
from app.models.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from app.procesamiento.zip_utils import extraer_pdfs

PAGINAS_A_REVISAR = 2

# "FORMATO 5 – PAGOS AL SISTEMA DE SEGURIDAD SOCIAL Y APORTES LEGALES" — se
# vio en un documento real con el espacio entre "SEGURIDAD" y "SOCIAL"
# comido por la extracción ("SEGURIDADSOCIAL"), así que el espacio es
# opcional.
TITULO_FORMATO5_RE = re.compile(r"FORMATO\s*5\b.{0,15}PAGOS?\s+AL\s+SISTEMA\s+DE\s+SEGURIDAD\s*SOCIAL")
PISTAS_FORMATO5 = ("formato 5", "seguridad social", "seg social", "parafiscales")


def _orden_busqueda(nombres: list[str]) -> list[str]:
    def pista(nombre: str) -> int:
        base = _norm(nombre.rsplit("/", 1)[-1])
        return 0 if any(p.upper() in base for p in PISTAS_FORMATO5) else 1

    return sorted(nombres, key=pista)


def encontrar_formato5(pdfs: dict[str, bytes]) -> tuple[str, str] | None:
    for nombre in _orden_busqueda(list(pdfs.keys())):
        contenido = pdfs[nombre]
        try:
            with pdfplumber.open(io.BytesIO(contenido)) as pdf:
                texto = "\n".join((page.extract_text() or "") for page in pdf.pages[:PAGINAS_A_REVISAR])
        except Exception:  # noqa: BLE001
            continue
        if TITULO_FORMATO5_RE.search(_norm(texto)):
            return nombre, texto
    return None


def _nombre_aparece_en_texto(nombre: str, texto_norm: str) -> bool:
    """Verifica que al menos 2 palabras del nombre (o todas, si tiene menos
    de 2) aparezcan literalmente en el texto — mismo criterio de
    coincidencia por palabras ya usado para cruzar nombres en otros
    requisitos, aplicado aquí para saber si la persona firmó/certificó este
    documento."""
    tokens = _tokens_nombre(nombre)
    if not tokens:
        return False
    minimo = min(2, len(tokens))
    encontrados = sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", texto_norm))
    return encontrados >= minimo


class ResultadoEvaluacionSegSocial:
    def __init__(self, cumple: bool, motivo: str | None, archivo: str | None) -> None:
        self.cumple = cumple
        self.motivo = motivo
        self.archivo = archivo


def _representante_legal_individual(pdfs: dict[str, bytes]) -> str | None:
    encontrado = encontrar_formato1(pdfs)
    if encontrado is None:
        return None
    _, contenido = encontrado
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        texto = "\n".join((page.extract_text() or "") for page in pdf.pages)
    texto_norm = _norm(texto)
    return _extraer_representante_legal(texto_norm) or _extraer_nombre_apertura(texto_norm)


def evaluar_requisito12(pdfs: dict[str, bytes], tipo_proponente: str | None) -> ResultadoEvaluacionSegSocial:
    """Requisito 12: Formato de pago de seguridad social y aportes legales.
    El abogado indicó que debe ir firmado por el representante legal (y por
    el revisor fiscal, si el certificado de existencia indica que la
    sociedad tiene uno), y que si es plural cada integrante aporta su
    propio Formato 5 firmado por SU PROPIO representante legal (no por el
    representante elegido del consorcio/UT — esa regla es específica de los
    antecedentes de REDAM/Contraloría/etc., no de este requisito).

    Limitaciones conocidas, ambas quedan para revisión humana en vez de una
    confirmación automática sin base real: (1) no se verifica la firma del
    revisor fiscal — requeriría cruzar con el Requisito 6 si el certificado
    de existencia menciona uno, y esa extracción no está implementada; (2)
    para proponentes plurales no se determina el representante legal propio
    de cada integrante, así que el caso plural siempre se deja para
    revisión humana."""
    encontrado = encontrar_formato5(pdfs)
    if encontrado is None:
        return ResultadoEvaluacionSegSocial(
            cumple=False,
            motivo="No se encontró el Formato 5 (Pagos de Seguridad Social y Aportes Legales) por título dentro de los documentos del proponente.",
            archivo=None,
        )

    archivo, texto = encontrado
    texto_norm = _norm(texto)

    if tipo_proponente in ("consorcio", "union_temporal"):
        return ResultadoEvaluacionSegSocial(
            cumple=False,
            motivo=(
                "Es un proponente plural: cada integrante debe aportar su propio Formato 5 firmado por su propio "
                "representante legal — confirma manualmente que estén completos y correctamente firmados."
            ),
            archivo=archivo,
        )

    representante = _representante_legal_individual(pdfs)
    if representante is None:
        return ResultadoEvaluacionSegSocial(
            cumple=False,
            motivo="Se encontró el Formato 5, pero no se pudo identificar al representante legal (Formato 1) para confirmar su firma — revisa manualmente.",
            archivo=archivo,
        )

    if not _nombre_aparece_en_texto(representante, texto_norm):
        return ResultadoEvaluacionSegSocial(
            cumple=False,
            motivo=(
                f"El Formato 5 no menciona a '{representante}' (el representante legal identificado en el "
                "Formato 1) — confirma manualmente quién lo firmó (y si falta la firma del revisor fiscal, cuando "
                "aplique, que este requisito no valida automáticamente)"
            ),
            archivo=archivo,
        )

    return ResultadoEvaluacionSegSocial(cumple=True, motivo=None, archivo=archivo)


def evaluar_proponente_requisito12(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    base = {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
        "requisito": 12,
    }

    try:
        metadata = get_file_metadata(proponente.drive_file_id)
    except Exception:  # noqa: BLE001
        metadata = None

    md5 = metadata.get("md5Checksum") if metadata else None
    clave_cache = _clave_cache(proponente, proceso, md5, requisito=12)
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
    resultado = evaluar_requisito12(pdfs, tipo_proponente)

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
