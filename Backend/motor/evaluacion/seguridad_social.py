from __future__ import annotations

import re

from motor.evaluacion.camara_comercio import revisores_fiscales
from motor.evaluacion.formato1 import (
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
from motor.integrations.drive import download_file_bytes, get_file_metadata
from motor.esquemas.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from motor.evaluacion.proponente_plural import datos_formato2, encontrar_formato2
from motor.llm.cliente import solo_digitos
from motor import criterios
from motor.evaluacion.antecedentes import FORMULARIO_SECOP_RE
from motor.procesamiento.memoria_proponente import memo_por_pdfs
from motor.procesamiento.pdf_utils import abrir_pdf, extraer_texto, texto_pagina
from motor.procesamiento.zip_utils import extraer_pdfs, pdfs_con_aportados

PAGINAS_A_REVISAR = 2

# "FORMATO 5 – PAGOS AL SISTEMA DE SEGURIDAD SOCIAL Y APORTES LEGALES" — se
# vio en un documento real con el espacio entre "SEGURIDAD" y "SOCIAL"
# comido por la extracción ("SEGURIDADSOCIAL"), así que el espacio es
# opcional.
# Variantes reales: "FORMATO 5 - PAGOS DE SEGURIDAD SOCIAL Y APORTES
# LEGALES" (sin "AL SISTEMA") y "FORMATO NO. 5 – CERTIFICACION DE PAGOS DE
# SEGURIDAD SOCIAL".
# El número cambia según el pliego tipo: es el Formato 5 en el de
# interventoría y el Formato 6 en el de obra pública (allí el 5 es "Capacidad
# residual"). Se reconoce por el título, con cualquier número.
TITULO_FORMATO5_RE = re.compile(
    r"FORMATO\s*(?:NO\.?\s*)?\d{1,2}\b.{0,40}?PAGOS?\s+(?:AL\s+SISTEMA\s+)?DE\s+SEGURIDAD\s*SOCIAL"
)
PISTAS_FORMATO5 = ("seguridad social", "seg social", "parafiscales", "formato 5", "formato 6")


def _orden_busqueda(nombres: list[str]) -> list[str]:
    def pista(nombre: str) -> int:
        base = _norm(nombre.rsplit("/", 1)[-1])
        return 0 if any(p.upper() in base for p in PISTAS_FORMATO5) else 1

    return sorted(nombres, key=pista)


def encontrar_formato5(pdfs: dict[str, bytes]) -> tuple[str, str] | None:
    for nombre in _orden_busqueda(list(pdfs.keys())):
        contenido = pdfs[nombre]
        try:
            texto = extraer_texto(contenido, max_paginas=PAGINAS_A_REVISAR)
        except Exception:  # noqa: BLE001
            continue
        if _es_certificado(_norm(texto)):
            return nombre, texto
    return None


def _es_certificado(texto_norm: str) -> bool:
    """El formato del pliego o, si el pliego lo permite ("bastará el
    certificado suscrito por el revisor fiscal o el representante legal"),
    una certificación propia con el mismo contenido."""
    if FORMULARIO_SECOP_RE.search(texto_norm):
        return False
    if TITULO_FORMATO5_RE.search(texto_norm):
        return True
    return bool(criterios.valor("seguridad_social_certificado")) and bool(CERTIFICACION_PROPIA_RE.search(texto_norm))


# Hay proponentes que no usan el formato del pliego sino una certificación
# propia con el mismo contenido: "CERTIFICACION DE PAGOS DE SEGURIDAD SOCIAL Y
# APORTES PARAFISCALES - ARTICULO 50 DE LA LEY 789 DE 2002".
CERTIFICACION_PROPIA_RE = re.compile(
    r"CERTIFICACION\s+(?:DE\s+)?(?:PAGOS?|CUMPLIMIENTO)\s+(?:AL\s+SISTEMA\s+)?(?:DE\s+)?(?:APORTES\s+(?:AL\s+SISTEMA\s+)?(?:DE\s+)?)?"
    r"SEGURIDAD\s*SOCIAL|ARTICULO\s+50\s+DE\s+LA\s+LEY\s+789"
)


def _certificacion_propia(pdfs: dict[str, bytes]) -> str | None:
    for nombre in _orden_busqueda(list(pdfs.keys())):
        try:
            texto_norm = _norm(extraer_texto(pdfs[nombre], max_paginas=PAGINAS_A_REVISAR))
        except Exception:  # noqa: BLE001
            continue
        if CERTIFICACION_PROPIA_RE.search(texto_norm) and not FORMULARIO_SECOP_RE.search(texto_norm):
            return nombre
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


PAGINAS_MAXIMAS_FORMATO5 = 8
# Paquetes jurídicos: un solo PDF con Formato 2, separadores ("PARAFISCALES
# EMPRESAS"), los Formatos 6 de cada integrante, antecedentes y cámara de
# comercio (se vio uno real de 55 páginas con los formatos en las páginas 6 y
# 10). Si el nombre del archivo o sus primeras páginas lo delatan, se lee más.
PISTA_PAQUETE_JURIDICO_RE = re.compile(
    r"PARAFISCAL|SEGURIDAD SOCIAL|APORTES|JURIDIC|HABILITANTE|CONFORMACION\s+(?:DE\s+)?PROPONENTE\s+PLURAL"
)
PAGINAS_MINIMAS_PAQUETE = 4
PAGINAS_MAXIMAS_PAQUETE = 32

REVISOR_FISCAL_CERTIFICA_RE = re.compile(r"EN (?:MI )?CALIDAD DE REVISOR(?:A)? FISCAL|EN MI CONDICION DE REVISOR(?:A)? FISCAL")

# NIT de la empresa que certifica: "MSING S.A.S. IDENTIFICADA CON NIT
# 900.574.741-7", "NIT NO. 900.709-306-8", "NIT.NO.901.950.937- 1". Se toman
# los 9 dígitos sin el de verificación.
NIT_RE = re.compile(r"\bNIT\.?\s*(?:NO\.?\s*)?:?\s*(\d{3})[.\s-]?(\d{3})[.\s-]?(\d{3})")
# Quién firma: el representante legal o el revisor fiscal de la sociedad, o
# la propia persona natural integrante (variante "(PERSONAS NATURALES)").
FIRMANTE_VALIDO_RE = re.compile(r"REPRESENTANTE LEGAL|REVISOR(?:A)? FISCAL|\(PERSONAS NATURALES\)")
# A qué integrante corresponde: "...REPRESENTANTE LEGAL DE MSING S.A.S.
# IDENTIFICADA CON NIT...", "...REVISOR FISCAL DE ESAO SAS IDENTIFICADA...",
# o la persona natural "...YO, MARTA EUGENIA GARCIA BETANCUR IDENTIFICADA CON
# CC...". Hay Formatos 2 que listan a los integrantes solo por nombre, sin NIT.
EMPRESA_CERTIFICA_RE = re.compile(
    r"(?:REPRESENTANTE LEGAL|REVISOR(?:A)? FISCAL(?: SUPLENTE)?|CONTADOR(?:A)?)\s+DE\s+(?:LA\s+(?:SOCIEDAD|EMPRESA)\s+)?"
    r"([A-Z0-9Ñ&][A-Z0-9Ñ&.,\s-]{2,80}?),?\s+(?:\(|IDENTIFICAD|CON\s+NIT|NIT\b)"
)
PERSONA_NATURAL_RE = re.compile(r"\bYO,?\s+([A-ZÑ][A-ZÑ\s]{5,60}?),?\s+IDENTIFICAD[OA]\s+CON\s+(?:CC|C\.\s*C\.|CEDULA)")
_PALABRAS_SOCIETARIAS = {"SAS", "S", "A", "LTDA", "SA", "E", "Y", "DE", "LA", "EL", "CIA", "SOCIEDAD"}


@memo_por_pdfs
def certificados_formato5(pdfs: dict[str, bytes], profundo: bool = False) -> list[tuple[str, str]]:
    """Todos los Formato 5 del proponente como (archivo, texto), separados
    por página aunque vengan varios en un mismo PDF (un proponente plural
    aporta uno por integrante, a veces juntos). Una página sin título se
    toma como continuación del Formato 5 anterior."""
    certificados: list[tuple[str, str]] = []
    for nombre in _orden_busqueda(list(pdfs.keys())):
        try:
            with abrir_pdf(pdfs[nombre]) as pdf:
                actual: list[str] | None = None
                es_paquete = profundo and bool(PISTA_PAQUETE_JURIDICO_RE.search(_norm(nombre.rsplit("/", 1)[-1])))
                for indice, page in enumerate(pdf.pages[:PAGINAS_MAXIMAS_PAQUETE]):
                    if indice >= (PAGINAS_MAXIMAS_PAQUETE if es_paquete else PAGINAS_MAXIMAS_FORMATO5):
                        break
                    texto = texto_pagina(page)
                    page.flush_cache()
                    if profundo and indice < PAGINAS_MINIMAS_PAQUETE and PISTA_PAQUETE_JURIDICO_RE.search(_norm(texto)):
                        es_paquete = True
                    # El formulario de preguntas del SECOP cita el nombre del
                    # formato en el enunciado; no es el formato.
                    if _es_certificado(_norm(texto)):
                        if actual is not None:
                            certificados.append((nombre, "\n".join(actual)))
                        actual = [texto]
                    elif actual is not None and len(actual) == 1:
                        actual.append(texto)
                    elif actual is None and indice >= PAGINAS_A_REVISAR and not es_paquete:
                        break
                if actual is not None:
                    certificados.append((nombre, "\n".join(actual)))
        except Exception:  # noqa: BLE001
            continue
    return certificados


def _nit(texto_norm: str) -> str | None:
    match = NIT_RE.search(texto_norm)
    return "".join(match.groups()) if match else None


def _integrante_del_formato5(texto_norm: str, texto_formato2_norm: str) -> str | None:
    """Clave del integrante al que corresponde un Formato 5 (su NIT o su
    nombre), solo si ese integrante aparece en el Formato 2; None si no se
    puede relacionar."""
    nit = _nit(texto_norm)
    if nit and nit in solo_digitos(texto_formato2_norm):
        return nit
    candidatos = [m.group(1) for m in EMPRESA_CERTIFICA_RE.finditer(texto_norm)]
    persona = PERSONA_NATURAL_RE.search(texto_norm)
    if persona:
        candidatos.append(persona.group(1))
    for nombre in candidatos:
        palabras = [p for p in re.findall(r"[A-Z0-9Ñ&]+", nombre) if p not in _PALABRAS_SOCIETARIAS]
        if palabras and all(re.search(rf"\b{re.escape(p)}\b", texto_formato2_norm) for p in palabras):
            return " ".join(palabras)
    return None


def _evaluar_formato5_plural(pdfs: dict[str, bytes], codigo_proceso: str | None) -> ResultadoEvaluacionSegSocial:
    """Plural: cada integrante debe aportar su propio Formato 5 firmado por
    su representante legal o revisor fiscal. Se cruza el NIT de cada Formato 5
    con el documento de conformación (Formato 2) y se exige uno por cada
    integrante; lo que no se pueda confirmar queda para revisión humana."""
    certificados = certificados_formato5(pdfs)
    archivo = certificados[0][0] if certificados else None
    formato2 = datos_formato2(pdfs, codigo_proceso)
    if formato2 is None or not formato2[1].porcentajes:
        return ResultadoEvaluacionSegSocial(
            cumple=False,
            motivo=(
                f"Es un proponente plural con {len(certificados)} Formato(s) 5, pero no se pudo leer cuántos integrantes "
                "tiene en el Formato 2 — confirma manualmente que cada integrante aporte el suyo firmado."
            ),
            archivo=archivo,
        )
    _, datos, _ = formato2
    texto_formato2_norm = _norm(encontrar_formato2(pdfs, codigo_proceso)[1])
    integrantes = len(datos.porcentajes)

    revisores = revisores_fiscales(pdfs)
    nits_validos: set[str] = set()
    problemas: list[str] = []
    for nombre_archivo, texto in certificados:
        texto_norm = _norm(texto)
        integrante = _integrante_del_formato5(texto_norm, texto_formato2_norm)
        if integrante is None:
            problemas.append(f"no se pudo relacionar '{nombre_archivo}' con un integrante del Formato 2")
            continue
        if not FIRMANTE_VALIDO_RE.search(texto_norm):
            problemas.append(f"'{nombre_archivo}' no indica que lo firme el representante legal o el revisor fiscal")
            continue
        persona_natural = PERSONA_NATURAL_RE.search(texto_norm) and not _nit(texto_norm)
        revisor = None if persona_natural else _falta_revisor_fiscal(texto_norm, _nit(texto_norm), revisores)
        if revisor:
            problemas.append(
                f"'{nombre_archivo}' no viene certificado por el revisor fiscal de la sociedad ({revisor}, según su "
                "certificado de existencia)"
            )
            continue
        nits_validos.add(integrante)

    if len(nits_validos) >= integrantes:
        return ResultadoEvaluacionSegSocial(cumple=True, motivo=None, archivo=archivo)
    motivo = (
        f"el consorcio/unión temporal tiene {integrantes} integrantes pero solo se confirmó el formato de seguridad social de "
        f"{len(nits_validos)}"
    )
    if problemas:
        motivo += " (" + "; ".join(problemas) + ")"
    return ResultadoEvaluacionSegSocial(cumple=False, motivo=motivo + " — revisa manualmente", archivo=archivo)


def _falta_revisor_fiscal(texto_norm: str, nit: str | None, revisores: dict[str, str]) -> str | None:
    """Si la sociedad tiene revisor fiscal (según su certificado de
    existencia), el formato debe venir certificado por él (art. 50 Ley 789
    de 2002): se exige "en calidad de revisor fiscal" o su nombre. Devuelve
    el nombre del revisor que falta, o None si no aplica o está."""
    if not revisores:
        return None
    if nit is not None:
        revisor = revisores.get(nit)
    elif len(revisores) == 1:
        revisor = next(iter(revisores.values()))
    else:
        # Sin NIT en el formato no se sabe de qué sociedad es: basta que lo
        # certifique alguno de los revisores; si no, a revisión.
        if any(_nombre_aparece_en_texto(r, texto_norm) for r in revisores.values()):
            return None
        revisor = " o ".join(revisores.values())
    if revisor is None or REVISOR_FISCAL_CERTIFICA_RE.search(texto_norm) or _nombre_aparece_en_texto(revisor, texto_norm):
        return None
    return revisor


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
    texto_norm = _norm(extraer_texto(contenido))
    return _extraer_representante_legal(texto_norm) or _extraer_nombre_apertura(texto_norm)


def evaluar_requisito12(
    pdfs: dict[str, bytes], tipo_proponente: str | None, codigo_proceso: str | None = None
) -> ResultadoEvaluacionSegSocial:
    """Requisito 12: Formato de pago de seguridad social y aportes legales.
    El abogado indicó que debe ir firmado por el representante legal (y por
    el revisor fiscal, si el certificado de existencia indica que la
    sociedad tiene uno), y que si es plural cada integrante aporta su
    propio Formato 5 firmado por SU PROPIO representante legal (no por el
    representante elegido del consorcio/UT — esa regla es específica de los
    antecedentes de REDAM/Contraloría/etc., no de este requisito).

    Si el certificado de existencia de la sociedad designa revisor fiscal, el
    formato debe venir certificado por él (se busca "en calidad de revisor
    fiscal" o su nombre); si no, va a revisión. Limitación conocida: en
    plurales se exige un Formato 5 por integrante (cruzado por NIT con el
    Formato 2), firmado por representante legal o revisor fiscal, sin
    verificar el nombre exacto de quien firma."""
    encontrado = encontrar_formato5(pdfs)
    if encontrado is None:
        propia = _certificacion_propia(pdfs)
        if propia is not None:
            # Si se acepta en lugar del formato del pliego es criterio jurídico:
            # queda para revisión, pero diciendo exactamente qué se encontró.
            return ResultadoEvaluacionSegSocial(
                cumple=False,
                motivo=(
                    f"aportó una certificación propia de pagos de seguridad social ('{propia}') en lugar del formato "
                    "del pliego — confirma si se acepta y quién la firma"
                ),
                archivo=propia,
            )
        # Dentro de un paquete de documentos (Formato 2, parafiscales,
        # antecedentes y cámara en un solo PDF) el formato puede estar en la
        # página 17. Encontrarlo ahí no basta para aprobar: hubo uno así,
        # firmado por la revisora fiscal, que el abogado rechazó.
        en_paquete = certificados_formato5(pdfs, True)
        if en_paquete:
            archivos = ", ".join(dict.fromkeys(f"'{a}'" for a, _ in en_paquete))
            return ResultadoEvaluacionSegSocial(
                cumple=False,
                motivo=(
                    f"el formato de seguridad social está dentro de un paquete de documentos ({archivos}, "
                    f"{len(en_paquete)} formato(s)) — revisa que esté completo, firmado por quien corresponde y, "
                    "si es plural, que haya uno por integrante"
                ),
                archivo=en_paquete[0][0],
            )
        return ResultadoEvaluacionSegSocial(
            cumple=False,
            motivo="No se encontró el formato de Pagos de Seguridad Social y Aportes Legales por título dentro de los documentos del proponente.",
            archivo=None,
        )

    archivo, texto = encontrado
    texto_norm = _norm(texto)

    if tipo_proponente in ("consorcio", "union_temporal"):
        return _evaluar_formato5_plural(pdfs, codigo_proceso)

    if REVISOR_FISCAL_CERTIFICA_RE.search(texto_norm):
        # La norma (art. 50 Ley 789 de 2002) pide que certifique el revisor
        # fiscal cuando la sociedad lo tiene: se confirmó en 5 proponentes
        # reales firmado así, sin el representante legal.
        return ResultadoEvaluacionSegSocial(
            cumple=True, motivo="certificado por el revisor fiscal de la sociedad", archivo=archivo
        )

    representante = _representante_legal_individual(pdfs)
    if representante is None:
        return ResultadoEvaluacionSegSocial(
            cumple=False,
            motivo="Se encontró el formato de seguridad social, pero no se pudo identificar al representante legal (Formato 1) para confirmar su firma — revisa manualmente.",
            archivo=archivo,
        )

    revisor = _falta_revisor_fiscal(texto_norm, _nit(texto_norm), revisores_fiscales(pdfs))
    if revisor:
        return ResultadoEvaluacionSegSocial(
            cumple=False,
            motivo=(
                f"la sociedad tiene revisor fiscal ({revisor}, según su certificado de existencia) y el formato de "
                "seguridad social no viene certificado por él — confirma quién lo firmó"
            ),
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

    pdfs = pdfs_con_aportados(zip_bytes, proponente)
    if not pdfs:
        return finalizar(
            ResultadoRequisito(**base, error="El archivo del proponente no contiene PDFs legibles (¿zip dañado?)."),
            cacheable=False,
        )

    tipo_proponente = obtener_tipo_proponente(pdfs)
    resultado = evaluar_requisito12(pdfs, tipo_proponente, proceso.codigo_proceso)

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
