"""Qué exige el pliego y en qué se aparta de la evaluación de la entidad.

El análisis tiene dos partes:

1. `extraer(paginas)`: independiente de la entidad. Clasifica cada sección
   del pliego (jurídica, técnica, financiera, puntaje…), la cruza con las
   verificaciones del motor y aplica detectores sobre el texto. Es lo que se
   guarda en caché por la huella del PDF.
2. `comparar(extraccion, definicion)`: contra la definición de evaluación
   vigente de la entidad. Produce los hallazgos que una persona debe
   confirmar: parámetros que cambian, exigencias que la plantilla no evalúa,
   aclaraciones.

Cada hallazgo lleva la cita literal del pliego y su página. Ningún ajuste se
aplica sin que alguien lo acepte.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from motor import criterios
from motor.pliego.lectura import Pagina, Seccion, codigo_documento_tipo, norm, secciones

# Sube cuando cambian los detectores: los análisis guardados con otra versión
# se rehacen.
VERSION_ANALISIS = 4

Ambito = Literal["juridica", "tecnica", "financiera", "puntaje", "garantias", "general"]

# --- Ámbito de cada sección, por su título ---
_AMBITOS: tuple[tuple[Ambito, re.Pattern[str]], ...] = (
    ("financiera", re.compile(r"CAPACIDAD FINANCIERA|CAPITAL DE TRABAJO|CAPACIDAD ORGANIZACIONAL|INDICADORES FINANCIEROS")),
    ("tecnica", re.compile(r"EXPERIENCIA|FORMACION ACADEMICA|PERSONAL CLAVE|EQUIPO DE TRABAJO|ANEXO TECNICO")),
    ("puntaje", re.compile(
        r"PUNTAJE|DESEMPATE|INDUSTRIA NACIONAL|SERVICIOS NACIONALES|COMPONENTE NACIONAL|SOSTENIBILIDAD|"
        r"DISCAPACIDAD|EMPRENDIMIENTOS|EMPRESAS DE MUJERES|MIPYME DOMICILIADA|CRITERIOS DE EVALUACION|OFERTA ECONOMICA"
    )),
    ("garantias", re.compile(r"GARANTIA")),
    ("juridica", re.compile(
        r"REQUISITOS HABILITANTES|GENERALIDADES|CAPACIDAD JURIDICA|EXISTENCIA Y REPRESENTACION|PERSONAS (?:NATURALES|JURIDICAS)|"
        r"PROPONENTES PLURALES|SEGURIDAD SOCIAL|CARTA DE PRESENTACION|APODERADO|LIMITACION A MIPYME|CAUSALES DE RECHAZO|"
        r"CONFLICTO DE INTERES|DOCUMENTOS OTORGADOS EN EL EXTERIOR"
    )),
)


def ambito(seccion: Seccion, capitulo_titulo: str) -> Ambito:
    titulo = norm(seccion.titulo)
    for nombre, patron in _AMBITOS:
        if patron.search(titulo):
            # Las secciones de personas naturales/jurídicas del capítulo de
            # capacidad financiera o experiencia heredan ese ámbito.
            if nombre == "juridica" and re.search(r"PERSONAS (?:NATURALES|JURIDICAS)", titulo):
                heredado = ambito_de_capitulo(capitulo_titulo)
                if heredado != "general":
                    return heredado
            return nombre
    return "general"


def ambito_de_capitulo(titulo: str) -> Ambito:
    for nombre, patron in _AMBITOS:
        if patron.search(norm(titulo)):
            return nombre
    return "general"


# --- Qué verificación del motor cubre cada exigencia ---
# Palabras del pliego que corresponden a cada verificación jurídica.
PISTAS_PLIEGO: dict[str, tuple[str, ...]] = {
    "juridica.carta": ("CARTA DE PRESENTACION",),
    "juridica.aval_ingeniero": ("AVAL", "MATRICULA PROFESIONAL", "INGENIERO"),
    "juridica.copnia_antecedentes": ("COPNIA", "CONSEJO PROFESIONAL"),
    "juridica.plural": ("PROPONENTE PLURAL", "PROPONENTES PLURALES", "CONSORCIO", "UNION TEMPORAL"),
    "juridica.redam": ("REDAM", "DEUDORES ALIMENTARIOS"),
    "juridica.existencia": ("EXISTENCIA Y REPRESENTACION LEGAL",),
    "juridica.objeto_social": ("OBJETO DE LA SOCIEDAD", "OBJETO SOCIAL"),
    "juridica.facultades": ("RESTRICCIONES PARA CONTRAER", "LIMITACIONES PARA CONTRAER", "AUTORIZACION SUFICIENTE"),
    "juridica.rup": ("REGISTRO UNICO DE PROPONENTES", "(RUP)"),
    "juridica.sanciones_rup": ("MULTAS", "SANCIONES", "CLAUSULA PENAL", "INCUMPLIMIENTO"),
    "juridica.garantia": ("GARANTIA DE SERIEDAD",),
    "juridica.seguridad_social": ("SEGURIDAD SOCIAL", "APORTES PARAFISCALES", "APORTES LEGALES"),
    "juridica.contraloria": ("RESPONSABLES FISCALES", "ANTECEDENTES FISCALES", "CONTRALORIA"),
    "juridica.procuraduria": ("ANTECEDENTES DISCIPLINARIOS", "PROCURADURIA"),
    "juridica.policia": ("ANTECEDENTES JUDICIALES",),
    "juridica.rnmc": ("MEDIDAS CORRECTIVAS",),
    "juridica.revisor_fiscal": ("REVISOR FISCAL",),
}


def verificaciones_de(texto: str) -> list[str]:
    t = norm(texto)
    return [clave for clave, pistas in PISTAS_PLIEGO.items() if any(p in t for p in pistas)]


# --- Estructuras ---
class SeccionAnalizada(BaseModel):
    numero: str
    titulo: str
    pagina: int
    ambito: Ambito
    verificaciones: list[str] = Field(default_factory=list)


class Exigencia(BaseModel):
    """Algo que el pliego dice, con su prueba literal."""

    clave: str  # identifica al detector: "vigencia_existencia", "duracion_sociedad"…
    titulo: str
    seccion: str
    pagina: int
    cita: str
    valor: str | int | None = None


class Extraccion(BaseModel):
    version: int = VERSION_ANALISIS
    paginas: int
    documento_tipo: str | None
    secciones: list[SeccionAnalizada]
    exigencias: list[Exigencia]
    formatos: list[Exigencia] = Field(default_factory=list)
    # Toda oración de una sección jurídica que obliga al proponente: la red de
    # seguridad para exigencias que ningún detector conoce.
    obligaciones: list[Exigencia] = Field(default_factory=list)


TipoHallazgo = Literal["ajuste_parametro", "requisito_nuevo", "aclaracion", "informativo", "fuera_de_alcance", "obligacion"]


class Hallazgo(BaseModel):
    id: str
    tipo: TipoHallazgo
    titulo: str
    detalle: str
    seccion: str
    pagina: int
    cita: str
    verificacion: str | None = None
    parametro: str | None = None
    valor_plantilla: str | int | list[str] | None = None
    valor_pliego: str | int | list[str] | None = None
    # Cómo se lee el valor del pliego ("30 días"), para mostrarlo.
    valor_pliego_texto: str | None = None
    # Solo los que cambian la evaluación exigen que alguien los acepte o rechace.
    requiere_decision: bool = False
    # Si se acepta un requisito nuevo, así queda en la evaluación.
    requisito_propuesto: dict | None = None


# --- Citas ---
def _inicio_oracion(texto: str, inicio: int) -> int:
    """Donde empieza la oración o el literal que contiene `inicio`. Un salto de
    línea también separa oraciones cuando la línea anterior no sigue (termina
    en número, paréntesis o punto) y la siguiente empieza en mayúscula: así
    quedan separados los literales de una lista que no terminan en punto."""
    i = inicio
    while i > 0:
        c = texto[i - 1]
        if c in ".:;" and (i >= len(texto) or texto[i] in " \n"):
            return i
        if c == "\n" and i < len(texto) and texto[i].isupper() and texto[i - 2 : i - 1] and (
            texto[i - 2].isdigit() or texto[i - 2] in ").:;"
        ):
            return i
        i -= 1
    return 0


def _cita(seccion: Seccion, inicio: int, fin: int, paginas: list[Pagina]) -> tuple[str, int]:
    """La oración (o el literal) donde está la coincidencia, y su página."""
    texto = seccion.texto
    a = _inicio_oracion(texto, inicio)
    fin_oracion = re.compile(r"\.(?=\s|$)").search(texto, fin)
    b = fin_oracion.end() if fin_oracion else len(texto)
    cita = re.sub(r"\s+", " ", texto[a:b]).strip(" .\n")
    if len(cita) > 420:
        centro = inicio - a
        cita = "…" + cita[max(0, centro - 200) : centro + 220].strip() + "…"
    return cita, _pagina_de(cita, seccion.pagina, paginas)


def _pagina_de(cita: str, desde: int, paginas: list[Pagina]) -> int:
    muestra = norm(re.sub(r"[…\s]+", " ", cita).strip())[:60]
    for p in paginas[desde - 1 :]:
        if muestra and muestra in norm(re.sub(r"\s+", " ", p.texto)):
            return p.numero
    return desde


def _buscar(seccion: Seccion, patron: re.Pattern[str]) -> re.Match[str] | None:
    return patron.search(norm(seccion.texto))


# --- Detectores ---
_NUMEROS = {"UN": 1, "UNO": 1, "DOS": 2, "TRES": 3, "CUATRO": 4, "SEIS": 6, "QUINCE": 15, "TREINTA": 30,
            "SESENTA": 60, "NOVENTA": 90, "CIENTO VEINTE": 120}
_VIGENCIA_DIAS_RE = re.compile(
    r"(?:FECHA DE EXPEDICION|EXPEDIDO|EXPEDICION)[^.]{0,80}?NO MAYOR A\s+([A-Z ]+?)\s*\((\d+)\)\s*DIAS"
)
_VIGENCIA_MESES_RE = re.compile(r"(?:FECHA DE EXPEDICION|EXPEDIDO|EXPEDICION)[^.]{0,80}?NO MAYOR A\s+([A-Z ]+?)\s*\((\d+)\)\s*MES")


def _detectar_vigencias(sec: Seccion, paginas: list[Pagina]) -> list[Exigencia]:
    t = norm(sec.texto)
    salida = []
    for m in _VIGENCIA_DIAS_RE.finditer(t):
        contexto = t[max(0, m.start() - 400) : m.start()]
        if "REGISTRO UNICO DE PROPONENTES" in contexto or "(RUP)" in contexto:
            clave, titulo = "vigencia_rup", "Vigencia del RUP"
        elif "EXISTENCIA Y REPRESENTACION" in contexto or "EXISTENCIA" in norm(sec.titulo) or "JURIDICAS" in norm(sec.titulo):
            clave, titulo = "vigencia_existencia", "Vigencia del certificado de existencia y representación legal"
        else:
            continue
        cita, pagina = _cita(sec, m.start(), m.end(), paginas)
        salida.append(Exigencia(clave=clave, titulo=titulo, seccion=sec.encabezado, pagina=pagina, cita=cita, valor=int(m.group(2))))
    return salida


_FIJOS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("duracion_sociedad", "Duración de la sociedad",
     re.compile(r"DURACION\s+(?:NO SERA INFERIOR|SEA IGUAL|SEA POR LO MENOS|DEBERA SER POR LO MENOS)[^.]{0,80}PLAZO[^.]{0,60}(?:UN|1)\s*(?:\(1\))?\s*A[NÑ]O")),
    ("identidad_representante", "Documento de identidad del representante legal",
     re.compile(r"(?:FOTOCOPIA|COPIA)\s+DEL\s+DOCUMENTO\s+DE\s+IDENTIFICACION\s+DEL\s+REPRESENTANTE\s+LEGAL")),
    ("consulta_antecedentes_entidad", "La entidad consulta los antecedentes en línea",
     re.compile(r"LA ENTIDAD\s+(?:DEBE|DEBERA|VERIFICARA|CONSULTARA)[^.]{0,60}ANTECEDENTES")),
    ("certificacion_sa", "Certificación de sociedad anónima abierta o cerrada",
     re.compile(r"SOCIEDAD ANONIMA[^.]{0,80}ABIERTA O CERRADA")),
    ("apoderado", "Oferta presentada por apoderado",
     re.compile(r"(?:DEBEN|DEBERAN)\s+ANEXAR\s+EL\s+PODER")),
    ("redam", "Certificado del REDAM", re.compile(r"REDAM")),
    ("certificado_seguridad_social", "Certificado de pagos de seguridad social",
     re.compile(r"BASTARA\s+(?:CON\s+)?EL\s+CERTIFICADO\s+SUSCRITO\s+POR\s+EL\s+REVISOR\s+FISCAL")),
)

# "No limita" (sin "se") también cuenta: "LA ENTIDAD NO LIMITA EL PROCESO DE
# CONTRATACIÓN A LAS MIPYME…". Y el texto tipo que explica CÓMO pedir la
# limitación ("LOS INTERESADOS MANIFESTARÁN SU INTENCIÓN DE LIMITAR…") no dice
# que el proceso esté limitado: solo cuenta una afirmación de limitación.
_MIPYME_NO_RE = re.compile(r"NO\s+(?:ES\s+SUSCEPTIBLE|SE\s+LIMITA|LIMITA\b|SERA\s+LIMITAD)|PODRA\s+PARTICIPAR\s+CUALQUIER")
_MIPYME_SI_RE = re.compile(
    r"(?:EL\s+PRESENTE\s+PROCESO|LA\s+CONVOCATORIA|EL\s+PROCESO\s+DE\s+CONTRATACION)\s+(?:SE\s+LIMITA|(?:QUEDA|ESTA)\s+LIMITAD[OA])[^.]{0,80}MIPYME"
    r"|(?:SOLO|UNICAMENTE)\s+(?:PODRAN\s+PARTICIPAR|SE\s+ACEPTARAN)[^.]{0,80}MIPYME"
)


def _detectar_fijos(sec: Seccion, paginas: list[Pagina]) -> list[Exigencia]:
    salida = []
    for clave, titulo, patron in _FIJOS:
        m = _buscar(sec, patron)
        if m:
            cita, pagina = _cita(sec, m.start(), m.end(), paginas)
            salida.append(Exigencia(clave=clave, titulo=titulo, seccion=sec.encabezado, pagina=pagina, cita=cita))
    if "LIMITACION A MIPYME" in norm(sec.titulo) or "CONVOCATORIA LIMITADA" in norm(sec.titulo):
        t = norm(sec.texto)
        limitado = not _MIPYME_NO_RE.search(t) and bool(_MIPYME_SI_RE.search(t))
        cita = re.sub(r"\s+", " ", sec.texto).strip()[:420] or sec.titulo
        salida.append(Exigencia(
            clave="limitacion_mipyme", titulo="Limitación a MiPyme", seccion=sec.encabezado,
            pagina=_pagina_de(cita, sec.pagina, paginas), cita=cita, valor="si" if limitado else "no",
        ))
    return salida


_FORMATO_RE = re.compile(r"^\s*(?:\d+\.\s*)?(FORMATO\s+\d+[A-Z]?)\s*[–\-‒—]\s*(.+)$", re.MULTILINE | re.IGNORECASE)


def _detectar_formatos(sec: Seccion, paginas: list[Pagina]) -> list[Exigencia]:
    if not re.search(r"FORMATOS?", norm(sec.titulo)):
        return []
    salida = []
    for m in _FORMATO_RE.finditer(sec.texto):
        nombre = re.sub(r"\s+", " ", m.group(2)).strip()
        salida.append(Exigencia(
            clave="formato", titulo=f"{m.group(1).title()} – {nombre}", seccion=sec.encabezado,
            pagina=_pagina_de(m.group(0).strip(), sec.pagina, paginas), cita=m.group(0).strip(),
        ))
    return salida


_OBLIGA_RE = re.compile(
    r"\b(?:DEBE|DEBERA|DEBERAN|DEBEN|TENDRA QUE|TENDRAN QUE|ESTA OBLIGADO A|ESTAN OBLIGADOS A)\s+(?:\w+\s+){0,3}?"
    r"(?:PRESENTAR|APORTAR|ACREDITAR|ADJUNTAR|ALLEGAR|ANEXAR|DILIGENCIAR|ENTREGAR|CONTAR CON)\b"
)
# Encabezados de lista ("Deben presentar los siguientes documentos:"): lo que
# importa son los literales, que ya revisan los detectores.
_INTRODUCE_LISTA_RE = re.compile(r"SIGUIENTES?\s+(?:DOCUMENTOS|REQUISITOS|ASPECTOS|INFORMACION)|:\s*[A-Z]?$")


def _detectar_obligaciones(sec: Seccion, paginas: list[Pagina]) -> list[Exigencia]:
    salida = []
    for m in _OBLIGA_RE.finditer(norm(sec.texto)):
        cita, pagina = _cita(sec, m.start(), m.end(), paginas)
        if len(cita) < 40 or _INTRODUCE_LISTA_RE.search(norm(cita)):
            continue
        salida.append(Exigencia(clave="obligacion", titulo=sec.encabezado, seccion=sec.encabezado, pagina=pagina, cita=cita))
    return salida


def extraer(paginas: list[Pagina]) -> Extraccion:
    todas = secciones(paginas)
    analizadas: list[SeccionAnalizada] = []
    exigencias: list[Exigencia] = []
    formatos: list[Exigencia] = []
    obligaciones: list[Exigencia] = []
    capitulo = ""
    ambitos: dict[str, Ambito] = {}
    for sec in todas:
        if "." not in sec.numero:  # título de capítulo
            capitulo = sec.titulo
        amb = ambito(sec, capitulo)
        # "3.7.1.2 PERSONAS … EXTRANJERAS" hereda el ámbito de "3.7 CAPACIDAD
        # ORGANIZACIONAL": su título solo dice a quién aplica, no de qué trata.
        padre = sec.numero.rsplit(".", 1)[0] if "." in sec.numero else None
        while padre and padre not in ambitos and "." in padre:
            padre = padre.rsplit(".", 1)[0]
        if padre in ambitos and ambitos[padre] in ("tecnica", "financiera", "puntaje") and amb in ("juridica", "general"):
            amb = ambitos[padre]
        ambitos[sec.numero] = amb
        analizadas.append(SeccionAnalizada(
            numero=sec.numero, titulo=sec.titulo, pagina=sec.pagina, ambito=amb,
            verificaciones=verificaciones_de(sec.texto) if amb == "juridica" else [],
        ))
        if amb == "juridica":
            exigencias += _detectar_vigencias(sec, paginas) + _detectar_fijos(sec, paginas)
            obligaciones += _detectar_obligaciones(sec, paginas)
        formatos += _detectar_formatos(sec, paginas)
        # "11.2 FORMATOS" viene como subsección del capítulo de anexos.
    return Extraccion(
        paginas=len(paginas), documento_tipo=codigo_documento_tipo(paginas),
        secciones=analizadas, exigencias=_sin_repetir(exigencias), formatos=formatos, obligaciones=obligaciones,
    )


def _sin_repetir(exigencias: list[Exigencia]) -> list[Exigencia]:
    """Una por detector y valor: el pliego repite la misma regla para cada tipo
    de persona (ej. 30 días para nacionales, sucursales y entidades)."""
    vistas: dict[tuple[str, object], Exigencia] = {}
    for e in exigencias:
        vistas.setdefault((e.clave, e.valor), e)
    return list(vistas.values())


# --- Comparación con la evaluación de la entidad ---
_FORMATOS_JURIDICOS: tuple[tuple[str, str], ...] = (
    ("CARTA DE PRESENTACION", "juridica.carta"),
    ("PROPONENTE PLURAL", "juridica.plural"),
    ("SEGURIDAD SOCIAL", "juridica.seguridad_social"),
)
_FORMATOS_OTROS: tuple[tuple[str, str], ...] = (
    ("CAPACIDAD RESIDUAL", "financiera"),
    ("FACTOR DE CALIDAD", "puntaje"),
    ("EXPERIENCIA", "técnica"),
    ("PERSONAL CLAVE", "técnica"),
    ("FORMACION ACADEMICA", "técnica"),
    ("CAPACIDAD FINANCIERA", "financiera"),
    ("PUNTAJE", "puntaje"),
    ("DESEMPATE", "puntaje"),
    ("DISCAPACIDAD", "puntaje o desempate"),
    ("SOSTENIBILIDAD", "puntaje"),
    ("EMPRENDIMIENTO", "puntaje o desempate"),
    ("MIPYME", "puntaje o desempate"),
    ("DATOS PERSONALES", "trámite"),
)


def comparar(extraccion: Extraccion, definicion: criterios.DefinicionEvaluacion) -> list[Hallazgo]:
    """Hallazgos del pliego frente a la definición jurídica de la entidad."""
    hallazgos: list[Hallazgo] = []
    en_plantilla = {r.verificacion for r in definicion.requisitos}
    parametros = {**{k: p.defecto for k, p in criterios.PARAMETROS.items()}, **definicion.parametros}
    por_clave: dict[str, list[Exigencia]] = {}
    for e in extraccion.exigencias:
        por_clave.setdefault(e.clave, []).append(e)

    # 1. Vigencias de los certificados de Cámara de Comercio.
    for clave, verificacion in (("vigencia_existencia", "juridica.existencia"), ("vigencia_rup", "juridica.rup")):
        valores = {e.valor for e in por_clave.get(clave, [])}
        if not valores:
            continue
        e = por_clave[clave][0]
        dias_plantilla = parametros.get("camara_dias") or 0
        meses_plantilla = parametros.get("camara_meses")
        if len(valores) > 1:
            hallazgos.append(Hallazgo(
                id=f"{clave}_varios", tipo="aclaracion", titulo=e.titulo,
                detalle=f"El pliego fija vigencias distintas ({', '.join(f'{v} días' for v in sorted(valores))}) según el caso.",
                seccion=e.seccion, pagina=e.pagina, cita=e.cita, verificacion=verificacion,
            ))
            continue
        dias = int(next(iter(valores)))
        if dias_plantilla == dias:
            continue
        actual = f"{dias_plantilla} días" if dias_plantilla else f"{meses_plantilla} {'mes' if meses_plantilla == 1 else 'meses'}"
        hallazgos.append(Hallazgo(
            id=clave, tipo="ajuste_parametro", titulo=e.titulo,
            detalle=(f"El pliego exige una fecha de expedición no mayor a {dias} días calendario antes del cierre; la "
                     f"evaluación de la entidad usa {actual}. Aplicarlo cuenta días exactos en lugar de meses."),
            seccion=e.seccion, pagina=e.pagina, cita=e.cita, verificacion=verificacion,
            parametro="camara_dias", valor_plantilla=actual, valor_pliego=dias, valor_pliego_texto=f"{dias} días",
            requiere_decision=True,
        ))
    # Las dos vigencias usan el mismo parámetro: si coinciden basta una decisión.
    ids = [h.id for h in hallazgos]
    if "vigencia_existencia" in ids and "vigencia_rup" in ids:
        rup = next(h for h in hallazgos if h.id == "vigencia_rup")
        exi = next(h for h in hallazgos if h.id == "vigencia_existencia")
        if rup.valor_pliego == exi.valor_pliego:
            exi.titulo = "Vigencia del certificado de existencia y del RUP"
            exi.detalle += " Aplica igual al RUP (" + f"pág. {rup.pagina})."
            hallazgos.remove(rup)

    # Seguridad social: si el pliego dice que basta el certificado firmado por
    # el revisor fiscal o el representante legal, una certificación propia
    # vale como el formato.
    for e in por_clave.get("certificado_seguridad_social", [])[:1]:
        if not parametros.get("seguridad_social_certificado"):
            hallazgos.append(Hallazgo(
                id="certificado_seguridad_social", tipo="ajuste_parametro", titulo=e.titulo,
                detalle=("El pliego acepta el certificado suscrito por el revisor fiscal o el representante legal, no solo "
                         "su formato: una certificación propia de pagos (art. 50 de la Ley 789 de 2002) cumple si la "
                         "firma quien corresponde. La evaluación de la entidad solo acepta el formato."),
                seccion=e.seccion, pagina=e.pagina, cita=e.cita, verificacion="juridica.seguridad_social",
                parametro="seguridad_social_certificado", valor_plantilla="Solo el formato del pliego", valor_pliego=1,
                valor_pliego_texto="También la certificación firmada", requiere_decision=True,
            ))

    # 2. Exigencias que la plantilla no evalúa.
    # (el motor los verifica solo: juridica.duracion y juridica.identidad)
    nuevos = {
        "duracion_sociedad": (
            "El certificado de existencia debe mostrar una duración de la sociedad no inferior al plazo del contrato y "
            "un año más. La evaluación de la entidad no lo verifica.",
            "juridica.duracion",
        ),
        "identidad_representante": (
            "El pliego pide copia del documento de identidad del representante legal. La evaluación de la entidad no "
            "lo verifica.",
            "juridica.identidad",
        ),
    }
    for clave, (detalle, verificacion) in nuevos.items():
        if verificacion in en_plantilla:
            continue
        ver = criterios.VERIFICACIONES[verificacion]
        for e in por_clave.get(clave, [])[:1]:
            hallazgos.append(Hallazgo(
                id=clave, tipo="requisito_nuevo", titulo=ver.titulo, detalle=detalle,
                seccion=e.seccion, pagina=e.pagina, cita=e.cita, verificacion=verificacion, requiere_decision=True,
                requisito_propuesto={"verificacion": verificacion, "titulo": ver.titulo, "corto": ver.corto,
                                     "verifica": f"{e.cita} (pliego, {e.seccion}, pág. {e.pagina})"},
            ))

    for e in por_clave.get("limitacion_mipyme", [])[:1]:
        if e.valor == "si":
            hallazgos.append(Hallazgo(
                id="limitacion_mipyme", tipo="requisito_nuevo", titulo="Proceso limitado a MiPyme",
                detalle="El pliego limita la convocatoria a MiPyme: cada proponente debe acreditar esa condición.",
                seccion=e.seccion, pagina=e.pagina, cita=e.cita, requiere_decision=True,
                requisito_propuesto={"titulo": "Acreditación de la condición de MiPyme", "corto": "MiPyme",
                                     "verifica": f"{e.cita} (pliego, {e.seccion}, pág. {e.pagina})"},
            ))
        else:
            hallazgos.append(Hallazgo(
                id="limitacion_mipyme", tipo="informativo", titulo="Sin limitación a MiPyme",
                detalle=("El pliego no afirma que la convocatoria esté limitada a MiPyme: no se exige acreditar esa "
                         "condición. Si el proceso se limitó después (por solicitud de los interesados, en el SECOP), "
                         "hay que agregarlo."),
                seccion=e.seccion, pagina=e.pagina, cita=e.cita,
            ))

    # 3. Aclaraciones sobre cómo se evalúa.
    for e in por_clave.get("consulta_antecedentes_entidad", [])[:1]:
        hallazgos.append(Hallazgo(
            id="consulta_antecedentes_entidad", tipo="aclaracion", titulo=e.titulo,
            detalle=("Según el pliego, es la entidad la que consulta en línea los antecedentes (judiciales, fiscales, "
                     "disciplinarios y medidas correctivas). Si un proponente no los aportó, se consultan en la fuente "
                     "oficial y se suben al expediente; no es por sí solo motivo de rechazo."),
            seccion=e.seccion, pagina=e.pagina, cita=e.cita,
        ))
    for e in por_clave.get("apoderado", [])[:1]:
        hallazgos.append(Hallazgo(
            id="apoderado", tipo="aclaracion", titulo=e.titulo,
            detalle="Si la oferta la firma un apoderado, debe venir el poder con facultades suficientes. El programa no lo verifica: revisarlo cuando aplique.",
            seccion=e.seccion, pagina=e.pagina, cita=e.cita,
        ))

    # 4. Verificaciones que el pliego pide y la plantilla no tiene, y al revés.
    pedidas: dict[str, SeccionAnalizada] = {}
    for s in extraccion.secciones:
        for v in s.verificaciones:
            pedidas.setdefault(v, s)
    for v, s in pedidas.items():
        if v not in en_plantilla and v in criterios.VERIFICACIONES:
            ver = criterios.VERIFICACIONES[v]
            hallazgos.append(Hallazgo(
                id=f"falta_{v}", tipo="requisito_nuevo", titulo=ver.titulo,
                detalle=f"El pliego trata este tema en «{s.numero} {s.titulo}», pero la evaluación de la entidad no lo incluye.",
                seccion=f"{s.numero} {s.titulo}", pagina=s.pagina, cita=f"{s.numero} {s.titulo}", verificacion=v,
                requiere_decision=True,
                requisito_propuesto={"verificacion": v, "titulo": ver.titulo, "corto": ver.corto},
            ))

    # 5. Formatos del pliego y quién los revisa.
    for f in extraccion.formatos:
        t = norm(f.titulo)
        juridico = next((v for pista, v in _FORMATOS_JURIDICOS if pista in t), None)
        if juridico:
            if juridico not in en_plantilla:
                hallazgos.append(Hallazgo(
                    id=f"formato_{juridico}", tipo="requisito_nuevo", titulo=f.titulo,
                    detalle="Formato jurídico del pliego que la evaluación de la entidad no revisa.",
                    seccion=f.seccion, pagina=f.pagina, cita=f.cita, verificacion=juridico, requiere_decision=True,
                    requisito_propuesto={"verificacion": juridico, "titulo": criterios.VERIFICACIONES[juridico].titulo,
                                         "corto": criterios.VERIFICACIONES[juridico].corto},
                ))
            continue
        otro = next((a for pista, a in _FORMATOS_OTROS if pista in t), None)
        hallazgos.append(Hallazgo(
            id=f"formato_{norm(f.titulo)[:40]}", tipo="fuera_de_alcance" if otro else "aclaracion", titulo=f.titulo,
            detalle=(f"Corresponde a la evaluación {otro}; no es un requisito habilitante jurídico." if otro else
                     "Formato del pliego que no corresponde a ninguna verificación jurídica: confirme si aplica."),
            seccion=f.seccion, pagina=f.pagina, cita=f.cita,
        ))

    # 6. Red de seguridad: obligaciones del pliego que nada de lo anterior cubre.
    citadas = {norm(h.cita)[:80] for h in hallazgos} | {norm(e.cita)[:80] for e in extraccion.exigencias}
    for i, o in enumerate(extraccion.obligaciones):
        cubre = verificaciones_de(o.cita)
        if norm(o.cita)[:80] in citadas or (cubre and all(v in en_plantilla for v in cubre)):
            continue
        citadas.add(norm(o.cita)[:80])  # la misma oración puede obligar dos veces
        hallazgos.append(Hallazgo(
            id=f"obligacion_{i}", tipo="obligacion", titulo=o.seccion,
            detalle="El pliego impone esta obligación y ninguna verificación automática la cubre: léala al revisar.",
            seccion=o.seccion, pagina=o.pagina, cita=o.cita,
        ))

    # 7. Si no se reconoce la estructura, el análisis no sirve de garantía.
    juridicas = [s for s in extraccion.secciones if s.ambito == "juridica"]
    if len(juridicas) < 3:
        hallazgos.insert(0, Hallazgo(
            id="estructura_no_reconocida", tipo="aclaracion", titulo="No se reconoció la estructura del pliego",
            detalle=(f"Se leyeron {extraccion.paginas} páginas pero solo se identificaron {len(juridicas)} secciones "
                     "jurídicas (puede ser un escaneo de baja calidad o un formato distinto al de los pliegos tipo). "
                     "No confíe en este análisis: revise el pliego completo antes de evaluar."),
            seccion="—", pagina=1, cita="—",
        ))

    # 8. Capítulos que no son de la evaluación jurídica (para que se vea que se leyeron).
    for s in extraccion.secciones:
        if s.ambito in ("tecnica", "financiera", "puntaje") and "." in s.numero and s.numero.count(".") == 1:
            que = {"tecnica": "Requisito de la evaluación técnica", "financiera": "Requisito de la evaluación financiera",
                   "puntaje": "Criterio de puntaje o desempate"}[s.ambito]
            hallazgos.append(Hallazgo(
                id=f"alcance_{s.numero}", tipo="fuera_de_alcance", titulo=f"{s.numero} {s.titulo}",
                detalle=f"{que}: no lo revisa la evaluación jurídica de requisitos habilitantes.",
                seccion=f"{s.numero} {s.titulo}", pagina=s.pagina, cita=f"{s.numero} {s.titulo}",
            ))
    return hallazgos
