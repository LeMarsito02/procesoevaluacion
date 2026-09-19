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
    ("juridica.seguridad_social", r"SEGURIDAD SOCIAL|APORTES (?:LEGALES|PARAFISCALES)|PARAFISCAL|LEY 789|ARTICULO 50"
                                  r"|COTIZACION|PENSION DE VEJEZ"),
    ("juridica.garantia", r"GARANTIA DE SERIEDAD|POLIZA DE SERIEDAD|SERIEDAD DE LA OFERTA"),
    ("juridica.carta", r"CARTA DE PRESENTACION|FORMATO 1\b"),
)
_REGLAS = tuple((clave, re.compile(patron)) for clave, patron in REGLAS)


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").upper())
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c)))


# Requisitos que solo aplican en un caso ("si la oferta la firma un
# apoderado", "la persona natural que reúna los requisitos para la pensión",
# "quienes no estén obligados a cotizar"): no se le exigen a todos.
_CONDICIONAL_RE = re.compile(
    r"^(?:SI |EN CASO|CUANDO |QUIENES |LA PERSONA NATURAL QUE |LAS PERSONAS QUE |EN EL EVENTO)|APODERAD|\bPODER\b"
)


def es_condicional(req) -> bool:
    return bool(_CONDICIONAL_RE.search(_norm(req.requisito)))


def temas_en(texto: str) -> list[str]:
    """Verificaciones cuyo tema aparece en el texto (sin importar quién lo
    aporta o consulta)."""
    t = _norm(texto)
    return sorted({clave for clave, patron in _REGLAS if clave in criterios.VERIFICACIONES and patron.search(t)})


def _clave_de(texto: str) -> str | None:
    t = _norm(texto)
    for clave, patron in _REGLAS:
        if patron.search(t) and clave in criterios.VERIFICACIONES:
            return clave
    return None


def verificacion_de(req) -> str | None:
    """La verificación del motor para lo que el pliego exige, o None si el
    motor no la tiene. Manda el requisito, no el documento: la IA a veces
    nombra un documento que no corresponde ("garantía de seriedad… documento:
    certificado de existencia")."""
    # Lo propio se decide por lo que se exige (los títulos del documento a
    # veces traen formatos vecinos: "Carta de presentación", "Acreditación de Mipyme").
    propio = _norm(f"{req.requisito} {req.documento or ''}")
    if _PROPIOS_RE.search(propio) or re.search(r"MIPYME|EMPRENDIMIENTO", propio):
        return None
    return _clave_de(req.requisito) or _clave_de(f"{req.documento or ''} {' '.join(req.titulo_documento)}")


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
    # El documento que nombró la IA debe corresponder a lo que se exige: si
    # apunta a otra cosa (garantía de seriedad "acreditada" con el certificado
    # de existencia), no se busca nada y lo revisa una persona.
    del_documento = _clave_de(f"{req.documento or ''} {' '.join(req.titulo_documento)}")
    if del_documento is not None and del_documento != _clave_de(req.requisito):
        return None
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
    # Lo que leyó la IA nunca aprueba solo: encontrar un documento con ese
    # título no prueba que diga lo que el pliego exige, así que siempre queda
    # una confirmación de la persona (el contenido lo lee ella).
    if not any(b["tipo"] == "confirmar" for b in bloques):
        bloques.append({"tipo": "confirmar", "frases": [req.requisito[:200]]})
    return {"frases_documento": frases[:4], "paginas": 3, "bloques": bloques, "aplica_a": aplica_a_de(req)}


# A quién se le exige, solo si el mismo pliego lo dice: el modelo tiende a
# poner "persona jurídica" a todo, y restringir de más deja a otros como "no
# aplica" sin revisar.
_TIPO_EN_TEXTO = {
    "persona_natural": (re.compile(r"PERSONAS? (?:JURIDICAS? (?:O|Y) )?NATURAL"), ["persona_natural"]),
    "persona_juridica": (re.compile(r"PERSONAS? (?:NATURAL(?:ES)? (?:O|Y) )?JURIDICA"), ["persona_juridica"]),
    "plural": (re.compile(r"PLURAL|CONSORCIO|UNION TEMPORAL|INTEGRANTE"), ["consorcio", "union_temporal"]),
}


def tipos_del_pliego(req) -> list[str]:
    """El tipo de proponente al que se restringe el requisito, si el pliego
    lo nombra y es uno solo ("el proponente persona natural debe…"); vacío =
    a todos."""
    texto = _norm(f"{req.requisito} {req.cita}")
    tipos = [t for t in dict.fromkeys(req.aplica_a) if t in _TIPO_EN_TEXTO and _TIPO_EN_TEXTO[t][0].search(texto)]
    return tipos if len(tipos) == 1 else []


def aplica_a_de(req) -> list[str]:
    return sorted({x for t in tipos_del_pliego(req) for x in _TIPO_EN_TEXTO[t][1]})
