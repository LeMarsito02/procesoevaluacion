from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.evaluacion.formato1 import (
    _clave_cache,
    _guardar_cache,
    _leer_cache,
    _norm,
    _nombres_coinciden,
    obtener_tipo_proponente,
)
from app.evaluacion.proponente_plural import obtener_personas_a_verificar
from app.integrations.drive import download_file_bytes, get_file_metadata
from app.models.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from app.procesamiento.pdf_utils import extraer_texto
from app.procesamiento.zip_utils import extraer_pdfs

# Cuántas páginas de cada PDF candidato se revisan: estos certificados son
# de una sola página casi siempre, pero se deja el mismo margen que COPNIA
# por si vienen fusionados con otros documentos del proponente.
PAGINAS_A_REVISAR = 4


def _solo_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


# Identidad = (nombre-o-None, cédula-o-None), extraídos del texto normalizado
# del propio certificado. Cada entidad tiene su propia redacción, así que no
# hay un único regex universal — pero la orquestación (buscar, emparejar con
# las personas requeridas, decidir cumple/no cumple) sí es compartida.
ExtractorIdentidad = Callable[[str], tuple[str | None, str | None]]


@dataclass(frozen=True)
class AntecedenteConfig:
    requisito: int
    entidad: str  # nombre para mensajes, ej. "REDAM", "Contraloría"
    titulo_re: re.Pattern[str]
    pistas_nombre: tuple[str, ...]
    frase_cumple_re: re.Pattern[str]
    extraer_identidad: ExtractorIdentidad


def _orden_busqueda_generico(nombres: list[str], pistas: tuple[str, ...]) -> list[str]:
    def pista(nombre: str) -> int:
        base = _norm(nombre.rsplit("/", 1)[-1])
        return 0 if any(p.upper() in base for p in pistas) else 1

    return sorted(nombres, key=pista)


def encontrar_documentos_antecedente(pdfs: dict[str, bytes], config: AntecedenteConfig) -> list[tuple[str, str]]:
    """A diferencia de encontrar_formato1/encontrar_copnia (que devuelven solo
    el primer PDF que calza), aquí se devuelven TODOS los que calzan con el
    título: es común que un proponente aporte un certificado por cada
    integrante o por cada persona (representante + suplente), y hay que
    revisarlos todos para saber si cubren a las personas requeridas."""
    encontrados = []
    for nombre in _orden_busqueda_generico(list(pdfs.keys()), config.pistas_nombre):
        contenido = pdfs[nombre]
        try:
            texto = extraer_texto(contenido, max_paginas=PAGINAS_A_REVISAR)
        except Exception:  # noqa: BLE001
            continue
        if config.titulo_re.search(_norm(texto)):
            encontrados.append((nombre, texto))
    return encontrados


class ResultadoEvaluacionAntecedente:
    def __init__(self, cumple: bool, motivo: str | None, archivo: str | None) -> None:
        self.cumple = cumple
        self.motivo = motivo
        self.archivo = archivo


def evaluar_antecedente(
    pdfs: dict[str, bytes], config: AntecedenteConfig, personas: list[tuple[str, str | None]]
) -> ResultadoEvaluacionAntecedente:
    """Verifica que se haya aportado el certificado de `config.entidad` para
    cada persona en `personas` (representante legal, o representante +
    suplente del consorcio/UT), y que ninguno reporte novedades."""
    if not personas:
        return ResultadoEvaluacionAntecedente(
            cumple=False,
            motivo=(
                "No se pudo identificar al representante legal (ni al del consorcio/unión temporal) para "
                f"verificar su {config.entidad} — revisa manualmente."
            ),
            archivo=None,
        )

    candidatos = encontrar_documentos_antecedente(pdfs, config)
    if not candidatos:
        return ResultadoEvaluacionAntecedente(
            cumple=False,
            motivo=f"No se encontró el certificado de {config.entidad} por título dentro de los documentos del proponente.",
            archivo=None,
        )

    identidades = [(nombre, texto, *config.extraer_identidad(_norm(texto))) for nombre, texto in candidatos]

    faltantes: list[str] = []
    archivo_evaluado: str | None = None
    for nombre_persona, cedula_persona in personas:
        cedula_persona_digitos = _solo_digitos(cedula_persona) if cedula_persona else None
        encontrado = None
        for archivo, texto, nombre_doc, cedula_doc in identidades:
            coincide_cedula = (
                cedula_persona_digitos is not None
                and cedula_doc is not None
                and _solo_digitos(cedula_doc) == cedula_persona_digitos
            )
            coincide_nombre = nombre_doc is not None and _nombres_coinciden(nombre_doc, nombre_persona)
            if coincide_cedula or (cedula_persona_digitos is None and coincide_nombre):
                encontrado = (archivo, texto)
                break
        if encontrado is None:
            faltantes.append(f"no se aportó el certificado de {config.entidad} de {nombre_persona}")
            continue
        archivo, texto = encontrado
        if archivo_evaluado is None:
            archivo_evaluado = archivo
        if not config.frase_cumple_re.search(_norm(texto)):
            faltantes.append(
                f"el certificado de {config.entidad} de {nombre_persona} no confirma que esté libre de novedades"
            )

    cumple = not faltantes
    motivo = "; ".join(faltantes) if faltantes else None
    return ResultadoEvaluacionAntecedente(cumple=cumple, motivo=motivo, archivo=archivo_evaluado)


def _evaluar_proponente_antecedente(
    config: AntecedenteConfig, proponente: Proponente, proceso: ProcesoDocumentoBase
) -> ResultadoRequisito:
    """Lógica compartida por los 5 evaluadores de antecedentes. No se expone
    directamente como evaluador de un requisito: cada uno de
    `evaluar_proponente_requisitoN` de más abajo es una función de módulo
    (no un closure) que la llama con su propio config, porque
    ProcessPoolExecutor necesita poder *picklear* la función por su nombre
    calificado — un closure generado dinámicamente no se puede serializar y
    revienta con PicklingError al enviarlo al pool de procesos."""
    base = {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
        "requisito": config.requisito,
    }

    try:
        metadata = get_file_metadata(proponente.drive_file_id)
    except Exception:  # noqa: BLE001
        metadata = None

    md5 = metadata.get("md5Checksum") if metadata else None
    clave_cache = _clave_cache(proponente, proceso, md5, requisito=config.requisito)
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
    personas = obtener_personas_a_verificar(pdfs, tipo_proponente)
    resultado = evaluar_antecedente(pdfs, config, personas)

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


# ---------------------------------------------------------------------------
# Configuraciones por entidad, confirmadas contra documentos reales de varios
# proponentes de este proceso (no contra el Segundo Informe).
# ---------------------------------------------------------------------------

# REDAM (Requisito 5): "...con número de identificación CC 52371321 NO SE
# ENCUENTRA INSCRITO EN EL REGISTRO DE DEUDORES ALIMENTARIOS MOROSOS" — solo
# trae cédula, no nombre.
_CEDULA_CC_RE = re.compile(r"\bCC\s*(\d[\d.]*)")


def _identidad_redam(texto_norm: str) -> tuple[str | None, str | None]:
    match = _CEDULA_CC_RE.search(texto_norm)
    return None, match.group(1) if match else None


CONFIG_REDAM = AntecedenteConfig(
    requisito=5,
    entidad="REDAM (Registro de Deudores Alimentarios Morosos)",
    titulo_re=re.compile(r"DEUDORES ALIMENTARIOS MOROSOS"),
    pistas_nombre=("redam",),
    frase_cumple_re=re.compile(r"NO SE ENCUENTRA INSCRITO EN EL REGISTRO DE DEUDORES ALIMENTARIOS MOROSOS"),
    extraer_identidad=_identidad_redam,
)

# Contraloría (Requisito 14): "...No. Identificación 77031208...NO SE
# ENCUENTRA REPORTADO COMO RESPONSABLE FISCAL" — igual que REDAM, solo cédula.
_CEDULA_IDENTIFICACION_RE = re.compile(r"NO\.?\s*IDENTIFICACION\s*(\d[\d.]*)")


def _identidad_contraloria(texto_norm: str) -> tuple[str | None, str | None]:
    match = _CEDULA_IDENTIFICACION_RE.search(texto_norm)
    return None, match.group(1) if match else None


CONFIG_CONTRALORIA = AntecedenteConfig(
    requisito=14,
    entidad="Contraloría (Boletín de Responsables Fiscales)",
    titulo_re=re.compile(r"BOLETIN DE RESPONSABLES FISCALES|CONTRALORIA DELEGADA PARA RESPONSABILIDAD FISCAL"),
    pistas_nombre=("contraloria",),
    frase_cumple_re=re.compile(r"NO SE ENCUENTRA REPORTADO COMO RESPONSABLE FISCAL"),
    extraer_identidad=_identidad_contraloria,
)

# Procuraduría (Requisito 15): "...el(la) señor(a) ADRIANA MARCELA ROJAS
# PRIETO identificado(a) con Cédula de ciudadanía número 52371321...NO
# REGISTRA SANCIONES NI INHABILIDADES VIGENTES" — trae nombre y cédula, pero
# solo cuando el certificado es de una PERSONA (el de la empresa dice
# "la persona <razón social> identificado(a) con NIT número...", que este
# patrón ignora a propósito al exigir "CEDULA DE CIUDADANIA").
_PROCURADURIA_PERSONA_RE = re.compile(
    r"SE[ÑN]OR\(A\)\s+([A-ZÑ][A-ZÑ .]+?)\s+IDENTIFICAD[OA]\(A\)\s+CON C[EÉ]DULA DE CIUDADAN[IÍ]A N[UÚ]MERO\s*(\d[\d.]*)"
)


def _identidad_procuraduria(texto_norm: str) -> tuple[str | None, str | None]:
    match = _PROCURADURIA_PERSONA_RE.search(texto_norm)
    if not match:
        return None, None
    nombre = re.sub(r"\s+", " ", match.group(1)).strip(" .")
    return nombre or None, match.group(2)


CONFIG_PROCURADURIA = AntecedenteConfig(
    requisito=15,
    entidad="Procuraduría (Registro de Sanciones e Inhabilidades - SIRI)",
    titulo_re=re.compile(r"REGISTRO DE SANCIONES E INHABILIDADES|PROCURADURIA GENERAL DE LA NACION"),
    pistas_nombre=("procuradur",),
    frase_cumple_re=re.compile(r"NO REGISTRA SANCIONES NI INHABILIDADES VIGENTES"),
    extraer_identidad=_identidad_procuraduria,
)

# Policía Nacional — antecedentes judiciales (Requisito 16): "...el ciudadano
# identificado con: Cédula de Ciudadanía Nº 52371321 Apellidos y Nombres:
# ROJAS PRIETO ADRIANA MARCELA NO TIENE ASUNTOS PENDIENTES CON LAS
# AUTORIDADES JUDICIALES".
_POLICIA_JUDICIAL_RE = re.compile(
    r"CEDULA DE CIUDADAN[IÍ]A N[º°O.]*\s*(\d[\d.]*)\s*APELLIDOS Y NOMBRES:?\s*([A-ZÑ][A-ZÑ .]+?)\s+NO TIENE"
)


def _identidad_policia_judicial(texto_norm: str) -> tuple[str | None, str | None]:
    match = _POLICIA_JUDICIAL_RE.search(texto_norm)
    if not match:
        return None, None
    nombre = re.sub(r"\s+", " ", match.group(2)).strip(" .")
    return nombre or None, match.group(1)


CONFIG_POLICIA = AntecedenteConfig(
    requisito=16,
    entidad="Policía Nacional (antecedentes judiciales)",
    titulo_re=re.compile(r"CONSULTA EN LINEA DE ANTECEDENTES PENALES Y REQUERIMIENTOS JUDICIALES"),
    pistas_nombre=("policia", "antecedentes penales", "antecedentes judiciales"),
    frase_cumple_re=re.compile(r"NO TIENE ASUNTOS PENDIENTES CON LAS AUTORIDADES JUDICIALES"),
    extraer_identidad=_identidad_policia_judicial,
)

# RNMC — multas / medidas correctivas (Requisito 17): "...el ciudadano con
# Cédula de Ciudadanía Nº. 52371321 y Nombre: ADRIANA MARCELA ROJAS PRIETO.
# NO TIENE MEDIDAS CORRECTIVAS PENDIENTES POR CUMPLIR" — el de la empresa
# dice "...para - NIT, sin digito de verificación: N. ...", que este patrón
# ignora a propósito al exigir "CEDULA DE CIUDADANIA".
_RNMC_PERSONA_RE = re.compile(
    r"CIUDADANO CON C[EÉ]DULA DE CIUDADAN[IÍ]A N[º°O.]*\s*(\d[\d.]*)\s*Y NOMBRE:?\s*([A-ZÑ][A-ZÑ .]+?)\."
)


def _identidad_rnmc(texto_norm: str) -> tuple[str | None, str | None]:
    match = _RNMC_PERSONA_RE.search(texto_norm)
    if not match:
        return None, None
    nombre = re.sub(r"\s+", " ", match.group(2)).strip(" .")
    return nombre or None, match.group(1)


CONFIG_RNMC = AntecedenteConfig(
    requisito=17,
    entidad="RNMC (Registro Nacional de Medidas Correctivas)",
    titulo_re=re.compile(r"SISTEMA REGISTRO NACIONAL DE MEDIDAS CORRECTIVAS|REGISTRO NACIONAL DE MEDIDAS CORRECTIVAS\s*RNMC"),
    pistas_nombre=("rnmc", "medidas correctivas"),
    frase_cumple_re=re.compile(r"NO TIENE MEDIDAS CORRECTIVAS PENDIENTES POR CUMPLIR"),
    extraer_identidad=_identidad_rnmc,
)

def evaluar_proponente_requisito5(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_antecedente(CONFIG_REDAM, proponente, proceso)


def evaluar_proponente_requisito14(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_antecedente(CONFIG_CONTRALORIA, proponente, proceso)


def evaluar_proponente_requisito15(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_antecedente(CONFIG_PROCURADURIA, proponente, proceso)


def evaluar_proponente_requisito16(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_antecedente(CONFIG_POLICIA, proponente, proceso)


def evaluar_proponente_requisito17(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_antecedente(CONFIG_RNMC, proponente, proceso)
