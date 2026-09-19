"""Catálogo jurídico: qué verificación del motor corresponde a cada requisito
que el pliego exige, y qué parámetros del pliego la ajustan.

El pliego decide QUÉ se exige; este catálogo solo dice CÓMO se verifica lo que
el motor ya sabe verificar (con las reglas de las guías de Colombia Compra
Eficiente: manual de requisitos habilitantes CCE-EICP-MA-04, guías de
asuntos corporativos, garantías y proveedores extranjeros). Lo que no está
aquí se verifica con una configuración armada desde el mismo pliego
(`config_desde_pliego`) o queda para revisión.
"""
from __future__ import annotations

import re
import unicodedata

from motor import criterios

# Orden importa: la primera regla que calza gana (las más específicas arriba).
# Lo que calza aquí no es una verificación del motor aunque nombre otra cosa
# (ej. "el apoderado que firma la oferta de un proponente plural").
_PROPIOS_RE = re.compile(r"APODERAD|PODER (?:ESPECIAL|GENERAL|OTORGADO)|\bPODER\b")
REGLAS: tuple[tuple[str, str], ...] = (
    # Declaraciones que el proponente hace en la carta (Formato 1) y que la
    # consulta de antecedentes completa: no son un documento aparte.
    ("juridica.carta", r"INHABILIDAD|INCOMPATIBILIDAD|CONFLICTO DE INTERES|TENER CAPACIDAD JURIDICA|DEBE SER PERSONA NATURAL O JURIDICA"
                       r"|MANIFESTAR CON CLARIDAD"),
    ("juridica.copnia_antecedentes", r"ANTECEDENTES\s+DISCIPLINARIOS?\s+(?:PROFESIONAL|DEL\s+(?:INGENIERO|ARQUITECTO))|CONSEJO PROFESIONAL.*ANTECEDENTES|VIGENCIA Y ANTECEDENTES"),
    ("juridica.aval_ingeniero", r"\bAVAL|AVALAD|MATRICULA PROFESIONAL|TARJETA PROFESIONAL|COPNIA|LEY 842|INGENIERO|ARQUITECTO"),
    ("juridica.sanciones_rup", r"MULTAS?|SANCION(?:ES)?\s+(?:INSCRITAS|EN EL RUP|IMPUESTAS)|CLAUSULA PENAL|INCUMPLIMIENTO"),
    ("juridica.rup", r"INSCRITOS? EN EL REGISTRO UNICO DE PROPONENTES|CERTIFICADO (?:DEL|DE) (?:REGISTRO UNICO DE PROPONENTES|RUP)|\bRUP\b.{0,60}(?:VIGENTE|EN FIRME|EXPEDI)|REGISTRO UNICO DE PROPONENTES"),
    ("juridica.redam", r"REDAM|DEUDORES ALIMENTARIOS"),
    ("juridica.contraloria", r"CONTRALORIA|RESPONSABLES FISCALES|RESPONSABILIDAD FISCAL"),
    ("juridica.procuraduria", r"PROCURADURIA|ANTECEDENTES DISCIPLINARIOS"),
    ("juridica.rnmc", r"MEDIDAS CORRECTIVAS|RNMC|CODIGO NACIONAL DE (?:POLICIA|SEGURIDAD)"),
    ("juridica.policia", r"ANTECEDENTES (?:JUDICIALES|PENALES)|POLICIA NACIONAL"),
    ("juridica.revisor_fiscal", r"ABIERTA O CERRADA|SOCIEDAD ANONIMA"),
    ("juridica.duracion", r"DURACION|TERMINO DE DURACION|VIGENCIA DE LA (?:SOCIEDAD|PERSONA JURIDICA)"),
    ("juridica.identidad", r"DOCUMENTO DE IDENTIFICACION|DOCUMENTO DE IDENTIDAD|CEDULA DE CIUDADANIA|FOTOCOPIA DE LA CEDULA|COPIA DE LA CEDULA"),
    ("juridica.plural", r"PROPONENTE PLURAL|CONSORCIO|UNION TEMPORAL|FORMATO 2\b|CONFORMACION|PORCENTAJE DE PARTICIPACION"),
    ("juridica.facultades", r"FACULTADES|AUTORIZACION (?:DEL|DE LA) (?:ORGANO|JUNTA|ASAMBLEA)|LIMITACION(?:ES)? (?:DEL|AL) REPRESENTANTE"),
    ("juridica.objeto_social", r"OBJETO SOCIAL"),
    ("juridica.existencia", r"EXISTENCIA Y REPRESENTACION|CAMARA DE COMERCIO|CERTIFICADO DE EXISTENCIA"),
    ("juridica.seguridad_social", r"SEGURIDAD SOCIAL|APORTES (?:LEGALES|PARAFISCALES)|PARAFISCAL|LEY 789|ARTICULO 50"),
    ("juridica.garantia", r"GARANTIA DE SERIEDAD|POLIZA DE SERIEDAD|SERIEDAD DE LA OFERTA"),
    ("juridica.carta", r"CARTA DE PRESENTACION|FORMATO 1\b"),
)
_REGLAS = tuple((clave, re.compile(patron)) for clave, patron in REGLAS)


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").upper())
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c)))


def verificacion_de(req) -> str | None:
    """La verificación del motor para un requisito del pliego (por lo que
    exige y el documento con que se acredita), o None si el motor no la
    tiene."""
    texto = _norm(f"{req.requisito} {req.documento or ''} {' '.join(req.titulo_documento)}")
    if _PROPIOS_RE.search(texto) or re.search(r"MIPYME|EMPRENDIMIENTO", texto):
        return None
    for clave, patron in _REGLAS:
        if patron.search(texto) and clave in criterios.VERIFICACIONES:
            return clave
    return None


# Parámetros del motor que el pliego fija con la vigencia de cada documento.
def parametros_de(req) -> dict[str, int]:
    """Parámetros que la vigencia exigida por el pliego ajusta (ej. existencia
    y RUP "no mayor a 30 días" → camara_dias = 30)."""
    from motor.pliego.lector_ia import es_de_extranjeros

    if es_de_extranjeros(req):  # la vigencia de los documentos extranjeros no es la general
        return {}
    v, dias, meses = req.verificacion, req.vigencia_dias, req.vigencia_meses
    if v in ("juridica.existencia", "juridica.rup") and (dias or meses):
        return {"camara_dias": dias} if dias else {"camara_meses": meses}
    if v in ("juridica.aval_ingeniero", "juridica.copnia_antecedentes") and meses:
        return {"copnia_meses": meses}
    if v in ("juridica.contraloria", "juridica.procuraduria", "juridica.policia", "juridica.rnmc") and (dias or meses):
        return {"antecedentes_meses": meses or max(1, round(dias / 30))}
    return {}


def config_desde_pliego(req) -> dict | None:
    """Configuración de verificación automática (requisito personalizado por
    bloques) para un requisito que el motor no tiene: se reconoce el
    documento por las frases con que se titula y se revisa su vigencia; las
    demás condiciones del pliego quedan para que una persona las confirme.
    None si el requisito no tiene un documento que buscar."""
    frases = [f for f in req.titulo_documento if len(f) >= 8]
    if not frases and req.documento and len(req.documento) >= 8:
        frases = [req.documento]
    if not frases:
        return None
    bloques = []
    if req.vigencia_meses or req.vigencia_dias:
        meses = req.vigencia_meses or max(1, -(-req.vigencia_dias // 30))
        bloques.append({"tipo": "vigencia_maxima", "meses": meses})
    for c in req.condiciones:
        bloques.append({"tipo": "confirmar", "frases": [c[:200]]})
    aplica = {
        "persona_natural": ["persona_natural"],
        "persona_juridica": ["persona_juridica"],
        "plural": ["consorcio", "union_temporal"],
    }
    aplica_a = sorted({t for a in req.aplica_a for t in aplica.get(a, [])})
    return {"frases_documento": frases[:4], "paginas": 3, "bloques": bloques, "aplica_a": aplica_a}
