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
    ("tecnica.soporte", r"ACTA\s+DE\s+(?:RECIBO|LIQUIDACION|TERMINACION|INICIO|ENTREGA)|CERTIFICACION\s+(?:DEL|DE\s+LA)\s+CONTRAT"
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
    ("financiera.organizacional", r"RENTABILIDAD\s+(?:DEL|SOBRE)|CAPACIDAD\s+ORGANIZACIONAL|\bROA\b|\bROE\b"),
    ("financiera.indicadores", r"LIQUIDEZ|ENDEUDAMIENTO|COBERTURA\s+DE\s+INTERESES|CAPACIDAD\s+FINANCIERA|INDICADOR"),
    ("financiera.validez_estados", r"ESTADOS?\s+FINANCIER|ESTADO\s+DE\s+SITUACION\s+FINANCIERA|BALANCE\s+GENERAL"
                                    r"|CONTADOR|REVISOR\s+FISCAL|DICTAMEN|JUNTA\s+CENTRAL"),
    ("financiera.rup_financiero", r"INFORMACION\s+FINANCIERA\s+(?:DEL|INSCRITA\s+EN\s+EL)\s+RUP"),
    ("tecnica.experiencia_valor", r"VALOR\s+(?:MINIMO\s+)?A\s+CERTIFICAR|SMMLV|SALARIOS\s+MINIMOS"),
    ("tecnica.experiencia_general", r"EXPERIENCIA\s+GENERAL|CONTRATOS?\s+(?:APORTADOS|PRESENTADOS|VALIDOS)|EXPERIENCIA\s+ESPECIFICA"
                                      # Cómo los pliegos encabezan las actividades exigidas: es justo lo
                                      # que el motor compara contra el objeto de cada contrato.
                                      r"|QUE\s+HAYAN\s+CONTENIDO\s+LA\s+EJECUCION|ACTIVIDAD(?:ES)?\s+PRINCIPAL"),
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


# ---------------------------------------------------------------- clases
#
# No todo lo que el pliego dice es una exigencia que se pueda incumplir, y no
# todo lo que el motor deje de mirar puede aprobar a quien no debe. La clase
# dice qué riesgo corre cada frase si el programa la ignora:
#
# - exclusión: el pliego dice qué NO sirve. Si el motor no lo aplica, cuenta un
#   contrato que no debía contar y aprueba de más. Es lo más peligroso.
# - exigencia: el pliego pide algo. Si el motor no lo mira, no puede darlo por
#   cumplido.
# - permiso: el pliego AMPLÍA lo aceptable ("podrá acreditarlo también con…").
#   Ignorarlo no aprueba a nadie de más; puede hacer que se rechace a quien sí
#   cumplía, que es el otro riesgo (se rechaza con evidencia, no por omisión).
#   Por eso no frena la aprobación, pero se muestra cuando el resultado es un
#   rechazo o una revisión.
# - regla de lectura: le dice a quien evalúa cómo contar ("en caso de
#   discrepancia se toma el menor valor"). Sale del pliego, es igual para todos
#   los proponentes y se resuelve una vez por proceso.
# - encabezado: un título, una celda de tabla o un dato suelto que la lectura
#   partió de su frase. No le exige nada a nadie.
EXCLUSION, EXIGENCIA, PERMISO, REGLA_LECTURA, ENCABEZADO = (
    "exclusion", "exigencia", "permiso", "regla_lectura", "encabezado")

# El pliego dice qué no sirve. Va primero: una prohibición escrita con "podrá"
# ("solo uno podrá haber iniciado antes de…") sigue siendo una prohibición.
_EXCLUSION_RE = re.compile(
    r"NO\s+(?:SERA[AN]?|SON|ES)\s+VALID|NO\s+SE\s+(?:ACEPTAR|TENDRA[AN]?\s+EN\s+CUENTA|RECONOCER|ADMITIR)"
    r"|NO\s+SERVIRAN?\s+PARA|NO\s+PUEDE\s+(?:UTILIZAR|ESTAR\s+RELACIONAD)|NO\s+PODRA[AN]?\s+"
    r"|SOLO\s+PUEDE\s+ACREDITAR|SOLO\s+SERAN\s+TENIDOS\s+EN\s+CUENTA|UNICAMENTE\s+SE\s+TENDRA"
    # "solo uno (1) de los contratos podrá…" limita, aunque esté escrito con
    # "podrá": ignorarlo dejaría pasar los que el pliego no admite.
    r"|SOLO\s+(?:UNO|UNA|UN|\(?\d)|UNICAMENTE\s+UNO|SOLO\s+PODRA|NO\s+LO\s+TENDRA\s+EN\s+CUENTA"
    r"|SALVO\s+QUE\s+EL\s+PROCESO|EXCLUSIVAMENTE\s+EN"
)

# El pliego amplía lo aceptable. "PODRA/PUEDE" de permiso, no de prohibición.
_PERMISO_RE = re.compile(
    r"\bPODRA[AN]?\b|\bPUEDEN?\b|ES\s+VALIDA?\s+PARA|SERA\s+VALIDA?\s+PARA|SI\s+ASI\s+LO\s+CONSIDERA"
    r"|NO\s+ESTAN\s+OBLIGADOS|NO\s+SERA\s+OBLIGATORIO|ES\s+OPCIONAL|A\s+ELECCION\s+DEL"
)

# Le dice a quien evalúa cómo leer o contar, no al proponente qué aportar.
_REGLA_LECTURA_RE = re.compile(
    r"\bSE\s+(?:TENDRA[AN]?\s+EN\s+CUENTA|TOMARA|ENTENDERA|CONTARA|COMPUTARA|APLICARA|PROCEDERA|ADMITIRA"
    r"|REALIZARA|EFECTUARA|EXPRESEN|CONSIDERAN)"
    r"|CONTABILIZACION\s+DE\s+LA\s+EXPERIENCIA"
    r"|LA\s+ENTIDAD\s+(?:TOMARA|CONTARA|NO\s+LO\s+TENDRA)|SERA[AN]?\s+EVALUADOS?"
    r"|ORDEN\s+DE\s+PREVALENCIA|EN\s+CASO\s+DE\s+(?:EXISTIR\s+)?DISCREPANCIA"
    r"|ENTIENDASE\s+POR|HARA\s+LAS\s+VECES\s+DE|CONSERVARA\s+ESTA\s+EXPERIENCIA"
)

# Formas verbales con las que un pliego le exige algo a alguien.
_OBLIGACION_RE = re.compile(
    r"\bDEBE[RN]?\b|\bDEBERA[NS]?\b|\bDEBEN\b|\bTIENE[N]?\s+QUE\b|\bACREDIT|\bAPORT|\bPRESENT"
    r"|\bALLEG|\bDILIGENCI|\bDEMOSTRA|\bDEMUESTR|\bCUMPLIR|\bCUMPLIRA|\bSUSCRIB|\bINFORMA|\bADVERT"
    r"|\bAVIS|\bEXIG|\bREQUIER|\bOBLIGA|\bSE\s+SOLICITA|\bCERTIFICAR\b"
)


# Un deber propiamente dicho, para distinguir "debe aportar" de "podrá aportar".
_DEBER_RE = re.compile(r"\bDEBE[RN]?\b|\bDEBERA[NS]?\b|\bDEBEN\b|\bTIENE[N]?\s+QUE\b|\bESTA[NS]?\s+OBLIGADO"
                       r"|\bOBLIGATORI|\bSE\s+EXIGE\b|\bES\s+REQUISITO\b")


# Nombres de documento: una frase sin verbo que nombra un documento es una
# exigencia con el verbo elidido ("Actas de liquidación…" dentro de una lista de
# lo que hay que aportar), no un encabezado.
_NOMBRA_DOCUMENTO_RE = re.compile(
    r"\bACTA\b|\bACTAS\b|CERTIFICAC|CERTIFICADO|COPIA|ESTADO\s+DE\s+SITUACION|ESTADOS?\s+FINANCIER"
    r"|BALANCE|RESOLUCION|LICENCIA|DIPLOMA|TARJETA\s+PROFESIONAL|MATRICULA|FORMATO|RUP\b"
    r"|INFORME\s+DE\s+AUDITORIA|DICTAMEN|HOJA\s+DE\s+VIDA|PENSUM|POSESION|NOMBRAMIENTO"
)


# Los pliegos listan exigencias en infinitivo: "Acreditar el objeto del
# contrato", "Aportar el Formato 8". Empezar así es exigir, aunque la frase no
# traiga un "debe".
_EXIGE_EN_INFINITIVO_RE = re.compile(
    r"^(?:ACREDITAR|ACREDITARSE|APORTAR|PRESENTAR|ALLEGAR|DILIGENCIAR|DEMOSTRAR|DEMOSTRARSE|SUSCRIBIR"
    r"|CERTIFICAR|ADJUNTAR|ENTREGAR|CUMPLIR|INFORMAR|ADVERTIR|AVISAR)\b"
)


def clase_de(requisito: str, cita: str = "") -> str:
    """Qué clase de frase del pliego es. El orden es por riesgo: primero lo que
    puede hacer que se apruebe a quien no debe.

    Se clasifica por el requisito, no por la cita: la cita es el pedazo de
    pliego de donde salió y suele arrastrar frases vecinas, así que usarla aquí
    convertiría una exigencia en una regla de lectura ajena. Solo se mira la
    cita para la exclusión, donde el riesgo de pasarla por alto es aprobar a
    quien no debe."""
    texto = _norm(requisito)
    if _EXCLUSION_RE.search(texto) or _EXCLUSION_RE.search(_norm(cita)):
        return EXCLUSION
    if _DEBER_RE.search(texto):
        # Un deber manda sobre todo lo demás: "debe acreditarlo y, en caso de
        # discrepancia, la Entidad tomará el menor" sigue siendo una exigencia.
        return EXIGENCIA
    if _EXIGE_EN_INFINITIVO_RE.match(texto):
        return EXIGENCIA
    if _REGLA_LECTURA_RE.search(texto):
        return REGLA_LECTURA
    if _PERMISO_RE.search(texto):
        # "podrá acreditarlo con…" es un permiso aunque diga "acreditar": lo que
        # lo convierte en exigencia es un deber, no el verbo de la acción.
        return PERMISO
    if not _OBLIGACION_RE.search(texto):
        if len(texto.split()) <= 6 and not _NOMBRA_DOCUMENTO_RE.search(texto):
            # Corta, sin verbo y sin nombrar un documento: es un título o una
            # celda de tabla. Una frase larga sin verbo, en cambio, es una
            # exigencia a la que la lectura le cortó el verbo, y se trata como
            # tal: en la duda, la lectura que no aprueba.
            return ENCABEZADO
        return EXIGENCIA
    return EXIGENCIA


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").upper())
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip()


# Un proponente extranjero sin domicilio ni sucursal en Colombia no tiene RUP y
# presenta sus estados financieros según la ley de su país, traducidos y
# apostillados. El motor no sabe verificar nada de eso, y sus reglas hablan de
# los mismos temas (estados financieros, códigos de clasificación), así que sin
# esto quedaría tapado por una verificación que en su caso no se hizo.
_EXTRANJERO_SIN_SUCURSAL_RE = re.compile(
    r"EXTRANJER\w+(?:[^.]{0,80}?)(?:SIN\s+DOMICILIO|SIN\s+SUCURSAL)|LEGISLACION\s+(?:PROPIA\s+)?DEL?\s+PAIS"
    r"|PAIS\s+DE\s+ORIGEN|APOSTILL|CONSULARIZ"
)


def verificacion_de(requisito: str, cita: str = "") -> str | None:
    """La verificación del motor que corresponde a lo que el pliego exige, o
    None si el motor no sabe comprobarlo (entonces va a revisión)."""
    texto = _norm(f"{requisito} {cita}")
    if _NO_ES_EXIGENCIA_RE.search(texto):
        return ""  # no es una exigencia al proponente: ni se verifica ni falta
    if _EXTRANJERO_SIN_SUCURSAL_RE.search(texto):
        return None  # el motor no verifica lo de los proponentes extranjeros
    for clave, patron in _REGLAS:
        if patron.search(texto):
            return clave
    return None


# El orden en que se revisa: primero lo que, si nadie lo mira, puede aprobar a
# quien no debía.
_PRIORIDAD = {EXCLUSION: 0, EXIGENCIA: 1, REGLA_LECTURA: 2}

# Lo que frena la aprobación automática mientras nadie lo revise. Un permiso no
# está aquí: ignorarlo no aprueba a nadie de más. Un encabezado tampoco: no le
# exige nada a nadie.
FRENAN = (EXCLUSION, EXIGENCIA, REGLA_LECTURA)


def cobertura(requisitos: list[tuple[str, str]]) -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    """(lo que el motor cubre, lo que no). `requisitos` son (requisito, cita)
    tal como los leyó la IA del pliego.

    Lo que no se cubre sale ordenado por riesgo: las exclusiones del pliego
    primero («no se aceptará experiencia en…»), porque son las que, si nadie las
    mira, cuentan un contrato que no debía contar."""
    cubiertos: dict[str, list[str]] = {}
    sin_cubrir: list[tuple[int, str, str]] = []
    for requisito, cita in requisitos:
        clave = verificacion_de(requisito, cita)
        if clave is None:
            clase = clase_de(requisito, cita)
            if clase in FRENAN:
                sin_cubrir.append((_PRIORIDAD[clase], requisito, cita))
        elif clave:
            cubiertos.setdefault(clave, []).append(requisito)
    return cubiertos, [(r, c) for _, r, c in sorted(sin_cubrir, key=lambda x: x[0])]


def permisos(requisitos: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Lo que el pliego permite y el programa no sabe aprovechar: acreditar algo
    con un documento alterno, experiencia de contratos con particulares, y
    demás. No frena ninguna aprobación —ignorarlo no aprueba a nadie de más—,
    pero sí puede hacer que se rechace a quien en realidad cumplía. Por eso se
    muestra cuando el resultado es un rechazo o una revisión: se aprueba con
    evidencia y se rechaza con evidencia."""
    return [(requisito, cita) for requisito, cita in requisitos
            if verificacion_de(requisito, cita) is None and clase_de(requisito, cita) == PERMISO]
