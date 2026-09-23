"""Qué exige el pliego en lo técnico y lo financiero, y qué de eso sabe
verificar el motor.

El pliego manda: dice QUÉ se exige. Este catálogo solo dice qué de eso el
programa puede comprobar por su cuenta. Y, sobre todo, deja ver lo que NO
puede: un requisito del pliego que no calce con ninguna verificación queda
señalado y **el lote no se aprueba solo**.

Esa es la garantía que hace al sistema compatible con cualquier pliego: no
hace falta que el motor sepa verificarlo todo, hace falta que nunca dé por
cumplido lo que no verificó. Cuando aparece un requisito nuevo (el área
intervenida en edificaciones, por ejemplo), el proceso sigue evaluándose y
ese punto va a revisión, con su cita, hasta que se programe su verificación.
"""
from __future__ import annotations

import re
import unicodedata

# Lo que el motor sabe verificar hoy. La clave es el nombre interno; el texto,
# cómo se le explica a quien lee el informe.
VERIFICACIONES: dict[str, str] = {
    "tecnica.experiencia_general": "las actividades y el tipo de obra de los contratos aportados",
    "tecnica.experiencia_valor": "que los contratos sumen el valor exigido en SMMLV",
    "tecnica.un_contrato_valor": "que un contrato alcance el porcentaje exigido del presupuesto",
    "tecnica.longitud": "la longitud intervenida que acredita un contrato",
    "tecnica.area": "el área intervenida o construida que acredita un contrato",
    "tecnica.unspsc": "la clasificación de los contratos en los códigos del pliego",
    "tecnica.max_contratos": "el número máximo de contratos que se tienen en cuenta",
    "tecnica.rup_experiencia": "que los contratos estén inscritos en el RUP con su consecutivo",
    "tecnica.soporte": "el acta de recibo o la certificación de cada contrato",
    "tecnica.formato3": "el Formato 3 y el integrante que aporta cada contrato",
    "tecnica.plural": "las condiciones de aporte de cada integrante del proponente plural",
    "tecnica.socio": "la experiencia aportada por un socio o accionista",
    "tecnica.obras_inconclusas": "la reducción de puntaje por obras civiles inconclusas",
    "tecnica.puntaje": "los factores de calidad, industria nacional, mujeres, mipyme y discapacidad",
    "financiera.indicadores": "liquidez, endeudamiento y razón de cobertura de intereses",
    "financiera.organizacional": "rentabilidad del activo y del patrimonio",
    "financiera.capital_trabajo": "el capital de trabajo demandado",
    "financiera.capacidad_residual": "la capacidad residual del proponente",
    "financiera.patrimonio": "el patrimonio mínimo exigido",
    "financiera.validez_estados": "que los estados financieros estén firmados y sus contadores vigentes",
    "financiera.rup_financiero": "la información financiera inscrita en el RUP",
}

# Orden importa: la primera regla que calza gana (las más específicas arriba).
REGLAS: tuple[tuple[str, str], ...] = (
    ("tecnica.area", r"AREA\s+(?:INTERVENIDA|CONSTRUIDA|DISENADA)|METROS\s+CUADRADOS|\bM2\b"),
    ("tecnica.longitud", r"LONGITUD\s+(?:INTERVENIDA|DE\s+LA\s+VIA)|KILOMETROS\s+INTERVENIDOS"),
    ("tecnica.un_contrato_valor", r"(?:UNO|1)\s*\(?1?\)?\s+DE\s+LOS\s+CONTRATOS[^.]{0,120}(?:PORCENTAJE|%|VALOR)"
                                  r"|POR\s+LO\s+MENOS\s+EL\s+\d+\s*%\s*DEL\s+(?:VALOR|PRESUPUESTO)"),
    ("tecnica.unspsc", r"CLASIFICAD|UNSPSC|CLASIFICADOR\s+DE\s+BIENES"),
    ("tecnica.max_contratos", r"MAXIMO\s+(?:DE\s+)?\w+\s*\(?\d+\)?\s*CONTRATOS|MINIMO\s+UNO.{0,40}MAXIMO"),
    ("tecnica.soporte", r"ACTA\s+DE\s+(?:RECIBO|LIQUIDACION|TERMINACION)|CERTIFICACION\s+(?:DEL|DE\s+LA)\s+CONTRAT"
                        r"|DOCUMENTOS\s+VALIDOS\s+PARA\s+LA\s+ACREDITACION"),
    ("tecnica.formato3", r"FORMATO\s*3\b|NUMERO\s+CONSECUTIVO\s+DEL\s+CONTRATO"),
    ("tecnica.socio", r"SOCIO|ACCIONISTA|MENOS\s+DE\s+TRES\s+\(?3\)?\s+ANOS"),
    ("tecnica.plural", r"PROPONENTE\s+PLURAL|CONSORCIO|UNION\s+TEMPORAL|CADA\s+INTEGRANTE|PORCENTAJE\s+DE\s+PARTICIPACION"),
    ("tecnica.obras_inconclusas", r"OBRAS?\s+(?:CIVILES\s+)?INCONCLUSAS"),
    ("tecnica.puntaje", r"PUNTAJE|PUNTOS|FACTOR\s+DE\s+CALIDAD|INDUSTRIA\s+NACIONAL|EMPRENDIMIENTO|MIPYME|DISCAPACIDAD"
                        r"|CRITERIOS?\s+AMBIENTAL|PLAN\s+DE\s+CALIDAD|GERENCIA\s+DE\s+PROYECTOS|DESEMPATE"),
    ("tecnica.rup_experiencia", r"INSCRIT\w+\s+EN\s+EL\s+RUP|EXPERIENCIA\s+CONTENIDA\s+EN\s+EL\s+(?:REGISTRO|RUP)"),
    ("financiera.capacidad_residual", r"CAPACIDAD\s+RESIDUAL|\bCRP\b|SALDO\s+DE\s+(?:LOS\s+)?CONTRATOS\s+EN\s+EJECUCION"),
    ("financiera.capital_trabajo", r"CAPITAL\s+DE\s+TRABAJO"),
    ("financiera.patrimonio", r"PATRIMONIO\s+(?:MINIMO|EXIGIDO|REQUERIDO)"),
    ("financiera.organizacional", r"RENTABILIDAD\s+(?:DEL|SOBRE)|CAPACIDAD\s+ORGANIZACIONAL"),
    ("financiera.indicadores", r"LIQUIDEZ|ENDEUDAMIENTO|COBERTURA\s+DE\s+INTERESES|CAPACIDAD\s+FINANCIERA|INDICADOR"),
    ("financiera.validez_estados", r"ESTADOS\s+FINANCIEROS|CONTADOR|REVISOR\s+FISCAL|DICTAMEN|JUNTA\s+CENTRAL"),
    ("financiera.rup_financiero", r"INFORMACION\s+FINANCIERA\s+(?:DEL|INSCRITA\s+EN\s+EL)\s+RUP"),
    ("tecnica.experiencia_valor", r"VALOR\s+(?:MINIMO\s+)?A\s+CERTIFICAR|SMMLV|SALARIOS\s+MINIMOS"),
    ("tecnica.experiencia_general", r"EXPERIENCIA\s+GENERAL|CONTRATOS?\s+(?:APORTADOS|PRESENTADOS|VALIDOS)|EXPERIENCIA\s+ESPECIFICA"),
)
_REGLAS = tuple((clave, re.compile(patron)) for clave, patron in REGLAS)

# Lo que no es una exigencia al proponente: trámite de la entidad, reglas de
# desempate, definiciones. No cuenta como requisito sin verificar.
_NO_ES_EXIGENCIA_RE = re.compile(
    r"LA\s+ENTIDAD\s+(?:VERIFICARA|CONSULTARA|REVISARA|PUBLICARA|SOLICITARA|PODRA|SE\s+RESERVA)"
    r"|SUBSANAC|SE\s+ENTIENDE\s+POR|PARA\s+EFECTOS\s+DE\s+ESTE|DEFINICION|GLOSARIO"
    r"|INFORME\s+DE\s+EVALUACION|CRONOGRAMA|AUDIENCIA|ADJUDICA|SECOP|PLATAFORMA"
    r"|CAUSAL(?:ES)?\s+DE\s+RECHAZO|OFERTA\s+ECONOMICA|PRECIO\s+ARTIFICIALMENTE"
)


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").upper())
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip()


def verificacion_de(requisito: str, cita: str = "") -> str | None:
    """La verificación del motor que corresponde a lo que el pliego exige, o
    None si el motor no sabe comprobarlo (entonces va a revisión)."""
    texto = _norm(f"{requisito} {cita}")
    if _NO_ES_EXIGENCIA_RE.search(texto):
        return ""  # no es una exigencia al proponente: ni se verifica ni falta
    for clave, patron in _REGLAS:
        if patron.search(texto):
            return clave
    return None


def cobertura(requisitos: list[tuple[str, str]]) -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    """(lo que el motor cubre, lo que no). `requisitos` son (requisito, cita)
    tal como los leyó la IA del pliego."""
    cubiertos: dict[str, list[str]] = {}
    sin_cubrir: list[tuple[str, str]] = []
    for requisito, cita in requisitos:
        clave = verificacion_de(requisito, cita)
        if clave is None:
            sin_cubrir.append((requisito, cita))
        elif clave:
            cubiertos.setdefault(clave, []).append(requisito)
    return cubiertos, sin_cubrir
