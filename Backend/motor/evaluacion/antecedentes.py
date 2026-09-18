from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from motor.procesamiento.memoria_proponente import memo_por_pdfs
from motor.evaluacion.formato1 import (
    _clave_cache,
    _guardar_cache,
    _leer_cache,
    _norm,
    _nombres_coinciden,
    obtener_tipo_proponente,
)
from motor.evaluacion.proponente_plural import obtener_personas_a_verificar
from motor.integrations.drive import download_file_bytes, get_file_metadata
from motor.esquemas.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from motor.procesamiento.pdf_utils import abrir_pdf, texto_pagina
from motor.procesamiento.zip_utils import extraer_pdfs

# Se leen al menos estas páginas de cada PDF buscando algún certificado de
# antecedentes. Si aparece alguno, se sigue leyendo hasta
# PAGINAS_MAXIMAS_FUSIONADOS: hay proponentes que fusionan todos sus
# certificados en un solo PDF (se confirmó uno real de 10 páginas con
# Contraloría, Procuraduría, Policía, RNMC y REDAM de la empresa y del
# representante, con el de Policía en la página 5). Los PDF sin ningún
# certificado en sus primeras páginas (RUP, experiencia...) se dejan de leer
# ahí, para no recorrer documentos de cientos de páginas.
# Marca del formulario de preguntas del SECOP II (archivos CO1_OTLCNTNR_*),
# que se detectaba como certificado RNMC por mencionar el registro.
FORMULARIO_SECOP_RE = re.compile(r"THIS QUESTION REQUIRES|ESTA PREGUNTA REQUIERE ANEXAR|SOBRE UNICO")

PAGINAS_MINIMAS = 4
# Paquetes de antecedentes con portada, índice y cédula antes del primer
# certificado (se vio uno real de 22 páginas con Contraloría en la página 6):
# si el archivo o sus primeras páginas hablan de antecedentes, se sigue leyendo.
PISTA_PAQUETE_ANTECEDENTES_RE = re.compile(r"ANTECEDENTE|CONTRALOR|PROCURADUR|POLICIA|JUDICIAL|RNMC|REDAM")
# Se midió un paquete real con el RNMC en la página 21, que el límite anterior
# de 20 dejaba fuera: solo aplica a archivos que ya se ven como paquete de
# antecedentes, así que no obliga a recorrer documentos largos de otro tipo.
PAGINAS_MAXIMAS_FUSIONADOS = 32


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


@dataclass(frozen=True)
class Certificado:
    archivo: str
    texto: str  # texto de la(s) página(s) de ESTE certificado, no del PDF entero
    requisitos: frozenset[int]  # a qué entidad(es) corresponde, por título


def _configs() -> tuple[AntecedenteConfig, ...]:
    return (CONFIG_REDAM, CONFIG_CONTRALORIA, CONFIG_PROCURADURIA, CONFIG_POLICIA, CONFIG_RNMC)


@memo_por_pdfs
def leer_certificados(pdfs: dict[str, bytes]) -> list[Certificado]:
    """Recorre los PDF del proponente página por página y separa cada
    certificado de antecedentes que encuentre (de cualquier entidad), aunque
    vengan varios fusionados en un mismo archivo. Un certificado empieza en
    una página con título reconocible y puede seguir en la página siguiente
    si esta no trae título propio (ej. la frase de "sin novedades" o el pie
    quedan en la hoja 2)."""
    certificados: list[Certificado] = []
    for nombre, contenido in pdfs.items():
        try:
            with abrir_pdf(contenido) as pdf:
                actual: tuple[frozenset[int], list[str]] | None = None
                encontro_alguno = False
                es_paquete_antecedentes = bool(PISTA_PAQUETE_ANTECEDENTES_RE.search(_norm(nombre.rsplit("/", 1)[-1])))
                for indice, page in enumerate(pdf.pages[:PAGINAS_MAXIMAS_FUSIONADOS]):
                    if indice >= PAGINAS_MINIMAS and not encontro_alguno and not es_paquete_antecedentes:
                        break
                    texto = texto_pagina(page)
                    page.flush_cache()
                    texto_norm = _norm(texto)
                    if indice < PAGINAS_MINIMAS and PISTA_PAQUETE_ANTECEDENTES_RE.search(texto_norm):
                        es_paquete_antecedentes = True
                    requisitos = frozenset(c.requisito for c in _configs() if c.titulo_re.search(texto_norm))
                    if requisitos and FORMULARIO_SECOP_RE.search(texto_norm):
                        # El formulario de preguntas del SECOP cita los
                        # nombres de todos los certificados; no es uno.
                        requisitos = frozenset()
                    if requisitos:
                        if actual is not None:
                            certificados.append(Certificado(nombre, "\n".join(actual[1]), actual[0]))
                        actual = (requisitos, [texto])
                        encontro_alguno = True
                    elif actual is not None and len(actual[1]) == 1:
                        actual[1].append(texto)
                    elif actual is not None:
                        certificados.append(Certificado(nombre, "\n".join(actual[1]), actual[0]))
                        actual = None
                if actual is not None:
                    certificados.append(Certificado(nombre, "\n".join(actual[1]), actual[0]))
        except Exception:  # noqa: BLE001
            continue
    return certificados


def _cedulas_por_nombre(certificados: list[Certificado]) -> list[tuple[str, str]]:
    """Pares (nombre, cédula) de los certificados que traen ambos datos
    (Procuraduría, Policía, RNMC). Sirven para emparejar los certificados
    que solo traen cédula (REDAM, Contraloría) cuando la carta de
    presentación no declara la cédula del representante."""
    pares = []
    for certificado in certificados:
        texto_norm = _norm(certificado.texto)
        for config in _configs():
            if config.requisito not in certificado.requisitos:
                continue
            nombre, cedula = config.extraer_identidad(texto_norm)
            if nombre and cedula:
                pares.append((nombre, cedula))
    return pares


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

    certificados = leer_certificados(pdfs)
    candidatos = [c for c in certificados if config.requisito in c.requisitos]
    if not candidatos:
        return ResultadoEvaluacionAntecedente(
            cumple=False,
            motivo=f"No se encontró el certificado de {config.entidad} por título dentro de los documentos del proponente.",
            archivo=None,
        )

    identidades = [(c.archivo, c.texto, *config.extraer_identidad(_norm(c.texto))) for c in candidatos]
    pares_conocidos = _cedulas_por_nombre(certificados)

    faltantes: list[str] = []
    archivo_evaluado: str | None = None
    for nombre_persona, cedula_persona in personas:
        if not cedula_persona:
            cedula_persona = next(
                (cedula for nombre, cedula in pares_conocidos if _nombres_coinciden(nombre, nombre_persona)), None
            )
        cedula_persona_digitos = _solo_digitos(cedula_persona) if cedula_persona else None
        encontrado = None
        for archivo, texto, nombre_doc, cedula_doc in identidades:
            if cedula_persona_digitos and cedula_doc:
                # Con ambas cédulas manda la cédula: dos personas pueden
                # compartir nombre y apellido, no número de documento.
                coincide = _solo_digitos(cedula_doc) == cedula_persona_digitos
            else:
                coincide = nombre_doc is not None and _nombres_coinciden(nombre_doc, nombre_persona)
            if coincide:
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
    personas = obtener_personas_a_verificar(pdfs, tipo_proponente, proceso.codigo_proceso)
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

# REDAM (Requisito 5): "...con número de identificación CC 12345678 NO SE
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

# Contraloría (Requisito 14): "...No. Identificación 11223344...NO SE
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

# Procuraduría (Requisito 15): "...el(la) señor(a) MARIA FERNANDA GOMEZ
# PEREZ identificado(a) con Cédula de ciudadanía número 12345678...NO
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
# identificado con: Cédula de Ciudadanía Nº 12345678 Apellidos y Nombres:
# GOMEZ PEREZ MARIA FERNANDA NO TIENE ASUNTOS PENDIENTES CON LAS
# AUTORIDADES JUDICIALES". En escaneados el OCR cambia "Nº" por "N*" u otro
# signo, así que se acepta cualquier signo corto después de la N.
_POLICIA_JUDICIAL_RE = re.compile(
    r"CEDULA DE CIUDADAN[IÍ]A N(?:[^\d\s]{0,3}|9\.)\s*(\d[\d.]*)\s*APELLIDOS Y NOMBRES:?\s*([A-ZÑ][A-ZÑ .]+?)\s+NO TIENE"
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
# Cédula de Ciudadanía Nº. 12345678 y Nombre: MARIA FERNANDA GOMEZ PEREZ.
# NO TIENE MEDIDAS CORRECTIVAS PENDIENTES POR CUMPLIR" (otra versión omite
# "y Nombre:": "...Nº. 87654321 ANA LUCIA TORRES DIAZ. NO TIENE...") — el de la empresa
# dice "...para - NIT, sin digito de verificación: N. ...", que este patrón
# ignora a propósito al exigir "CEDULA DE CIUDADANIA".
# El RNMC tiene dos redacciones para persona natural: con el nombre junto a la
# cédula, y otra que solo trae la cédula ("EL CIUDADANO CON CEDULA DE
# CIUDADANIA NO. 12345 . NO TIENE MEDIDAS..."). En la segunda el nombre no
# aparece, pero la cédula sola basta para saber de quién es el certificado.
_RNMC_PERSONA_RE = re.compile(
    r"CIUDADANO CON C[EÉ]DULA DE CIUDADAN[IÍ]A N(?:[^\d\s]{0,3}|9\.)\s*(\d[\d.]*)\s*\.?\s*"
    r"(?:Y NOMBRE:?\s*([A-ZÑ][A-ZÑ .]+?)\.|([A-ZÑ][A-ZÑ .]+?)\.\s*NO TIENE)?"
)


def _identidad_rnmc(texto_norm: str) -> tuple[str | None, str | None]:
    match = _RNMC_PERSONA_RE.search(texto_norm)
    if not match:
        return None, None
    crudo = match.group(2) or match.group(3)
    nombre = re.sub(r"\s+", " ", crudo).strip(" .") if crudo else None
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
