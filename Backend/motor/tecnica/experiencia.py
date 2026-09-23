"""Experiencia habilitante (pliego 3.5) de un proponente, lote por lote.

Cómo lo hace el evaluador técnico, y aquí igual:
1. Toma los contratos del Formato 3 (máximo 5, los de mayor valor).
2. Busca cada uno en el RUP del integrante que lo aporta por su número
   consecutivo: de ahí salen el valor en SMMLV, la participación y los
   códigos UNSPSC (el RUP es la fuente oficial, el formato solo el índice).
3. Valor que aporta = valor del contrato × participación (3.5.3 F). Si dos
   integrantes del proponente ejecutaron juntos el mismo contrato, cuenta como
   uno solo con la suma de sus participaciones (3.5.3 H).
4. Por lote: la suma debe llegar al valor mínimo a certificar (tabla 3.5.9 ×
   presupuesto del lote en SMMLV), un contrato debe valer al menos el 70 % del
   presupuesto, y en plurales se revisan los porcentajes de 3.5.3 D.

Solo se aprueba lo que se pudo verificar completo. Lo que no se pudo leer
(longitud intervenida, un consecutivo que no está en el RUP, un objeto que
no se entiende) va a revisión con el motivo.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from motor.tecnica.formato3 import ContratoFormato3, Formato3
from motor.tecnica.parametros import LoteTecnico, ParametrosTecnicos
from motor.tecnica.rup import ExperienciaRup, Rup, normalizar

# Tolerancia al comparar valores en SMMLV (redondeos del formato y del RUP).
TOLERANCIA_VALOR = 0.02


@dataclass
class IntegranteTecnico:
    nombre: str
    nit: str | None
    participacion: float | None  # en el proponente plural (0 a 1)
    rup: Rup | None = None


@dataclass
class ContratoEvaluado:
    orden: int
    consecutivos: list[str]
    contratante: str
    objeto: str
    numero_contrato: str = ""
    # Integrante del proponente -> su parte del contrato en SMMLV.
    aportes: dict[str, float] = field(default_factory=dict)
    valor_smmlv: float | None = None
    participacion: float | None = None
    unspsc: bool | None = None
    # Experiencia de un socio o accionista (3.5.2 E): solo vale si la sociedad
    # tiene menos de tres años y aporta el documento de conformación.
    de_un_socio: bool = False
    socios_de: list[str] = field(default_factory=list)
    terminado: bool | None = None
    lotes: set[str] = field(default_factory=set)
    problemas: list[str] = field(default_factory=list)
    # Longitud intervenida (km) leída en los soportes, y de qué archivo.
    longitud_km: float | None = None
    soporte_longitud: str | None = None
    # Cita del soporte cuando la longitud la leyó el modelo local.
    cita_longitud: str | None = None
    longitud_buscada: bool = False
    # Acta o certificación que cita el contrato (3.5.6).
    soporte: str | None = None
    soporte_buscado: bool = False
    # Área intervenida (m²) cuando el soporte no trae la longitud.
    area_m2: float | None = None
    soporte_area: str | None = None

    @property
    def valor_aportado(self) -> float | None:
        return sum(self.aportes.values()) if self.aportes else None

    @property
    def valido(self) -> bool:
        # unspsc None = no se pudieron leer los códigos del pliego: el
        # contrato no se descarta por eso, el lote entero va a revisión.
        return self.valor_aportado is not None and self.unspsc is not False and self.terminado is not False


@dataclass
class ResultadoLote:
    lote: str
    cumple: bool | None = None
    contratos: list[ContratoEvaluado] = field(default_factory=list)
    valor_a_certificar: float | None = None
    factor: float | None = None
    valor_certificado: float = 0.0
    un_contrato_70: bool | None = None
    longitud: bool | None = None
    longitud_minima_km: float | None = None
    area: bool | None = None
    area_minima_m2: float | None = None
    area: bool | None = None
    area_minima_m2: float | None = None
    condiciones_plural: bool | None = None
    aporte_por_integrante: dict[str, float] = field(default_factory=dict)
    motivos: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- objeto

# Las actividades con que un pliego de obra describe la experiencia general.
_ACTIVIDADES_OBRA = (r"CONSTRUC|MANTENI|MEJORA|REHABILIT|ADECU|AMPLI|REMODEL|PAVIMENT|RESTAUR|CONSERV"
                     r"|INSTAL|REPAR|RECONSTRUC|INTERVEN|REFORZA|REPOTENCI|OPTIMIZ|TERMINACION|DOTACION")

# Cada familia de obra trae dos listas: cómo se nombra en la experiencia
# general del pliego y cómo puede aparecer en el objeto de un contrato. Los
# procesos de vías dicen "EN PAVIMENTO … DE CARRETERAS"; los de edificaciones,
# "… DE EDIFICACIONES" y los contratos hablan de sedes, instalaciones o
# templos. Lo que no cae en ninguna familia no se descarta: va a revisión.
_FAMILIAS: dict[str, tuple[str, str]] = {
    "vías": (
        r"VIA|VIAL|CARRETERA|PAVIMENT|CALZADA|CORREDOR|TRONCAL|AUTOPISTA|PLACA\s*HUELLA",
        r"\bVIA|\bVIAL|CARRETERA|CALLE|PAVIMENT|MALLA VIAL|RED VIAL|CORREDOR|TRAMO|AUTOPISTA|PISTA|CALZADA"
        r"|AVENIDA|CARRERA\b|TRONCAL|PLACA HUELLA|PUENTE|ANDEN|CICLORRUTA|GLORIETA",
    ),
    "edificaciones": (
        r"EDIFICAC|EDIFICIO|BIEN(?:ES)?\s+DE\s+INTERES\s+CULTURAL|PATRIMONI|INFRAESTRUCTURA\s+SOCIAL",
        r"EDIFICAC|EDIFICIO|\bSEDE|INSTALACION|COLEGIO|ESCUELA|INSTITUCION\s+EDUCATIVA|HOSPITAL|CENTRO\s+DE\s+SALUD"
        r"|TEMPLO|IGLESIA|CAPILLA|PARROQUI|VIVIENDA|LOCATIV|CUBIERTA|MUSEO|BIBLIOTECA|ESTACION|BATALLON|COMANDO"
        r"|ALCALDIA|POLIDEPORTIVO|ESCENARIO\s+DEPORTIVO|PLAZA\s+DE\s+MERCADO|PATRIMONI|INFRAESTRUCTURA\s+SOCIAL"
        r"|BIEN(?:ES)?\s+DE\s+INTERES\s+CULTURAL|SALON|AULA|OFICINA|PLANTA\s+FISICA",
    ),
    "acueducto": (
        r"ACUEDUCTO|ALCANTARILLADO|PTAP|PTAR|REDES\s+HIDRAULICAS",
        r"ACUEDUCTO|ALCANTARILLADO|PTAP|PTAR|RED(?:ES)?\s+(?:HIDRAULICA|DE\s+ACUEDUCTO)|COLECTOR|EMISARIO",
    ),
}
_CONECTOR_RE = re.compile(r"\s*(?:Y\s*/\s*O|/|,|\sO\s|\sU\s)\s*")


def _actividades_y_materia(lote: LoteTecnico) -> tuple[str, str]:
    """Parte la experiencia general en lo que se hace y sobre qué se hace:
    "… O CONSERVACIÓN | EN PAVIMENTO … DE CARRETERAS", "… REPOTENCIACIÓN
    ESTRUCTURAL | DE EDIFICACIONES".

    El corte no siempre es el primer "de": algunos pliegos empiezan con un
    preámbulo ("PROYECTOS QUE CORRESPONDAN Y/O CONTEMPLEN ACTIVIDADES DE:
    CONSTRUCCIÓN Y/O … DE EDIFICACIONES"), y cortar ahí dejaría el preámbulo
    como actividades y las actividades como materia. Se prueba cada corte y
    se toma el que deje actividades de obra a la izquierda."""
    general = normalizar(lote.experiencia_general)
    cortes = list(re.finditer(r"\s+(?:EN|DE)\s+", general))
    if not cortes:
        return general, ""
    for corte in cortes:
        izquierda, derecha = general[: corte.start()], general[corte.end():]
        if re.search(_ACTIVIDADES_OBRA, izquierda) and _familia_de(derecha) is not None:
            return izquierda, derecha
    return general[: cortes[0].start()], general[cortes[0].end():]


def _familia_de(texto: str) -> str | None:
    for familia, (en_el_pliego, _) in _FAMILIAS.items():
        if re.search(en_el_pliego, texto):
            return familia
    return None


def actividades_del_lote(lote: LoteTecnico) -> list[str]:
    """Las actividades de la experiencia general ("CONSTRUCCIÓN O
    MEJORAMIENTO O MANTENIMIENTO RUTINARIO …", "CONSTRUCCIÓN Y/O AMPLIACIÓN
    Y/O …"), comparadas por su raíz: "MANTENIMIENTO RUTINARIO" -> "MANTENI"."""
    antes, _ = _actividades_y_materia(lote)
    raices = []
    for actividad in _CONECTOR_RE.split(antes):
        # La actividad no siempre es la primera palabra del trozo: el pliego
        # puede escribir "CONTEMPLEN ACTIVIDADES DE: CONSTRUCCIÓN". Se busca
        # la primera palabra que sea una actividad de obra; así tampoco
        # entran las del preámbulo ("PROYECTOS", "CONTEMPLEN").
        for palabra in actividad.strip(" .,:").split():
            raiz = re.sub(r"(CION|MIENTO|ACION|CIONES)$", "", palabra.strip(" .,:"))
            if len(raiz) >= 5 and re.match(_ACTIVIDADES_OBRA, raiz):
                if raiz not in raices:
                    raices.append(raiz)
                break
    return raices


def familia_del_lote(lote: LoteTecnico) -> str | None:
    """Sobre qué obra pide experiencia el lote: vías, edificaciones, acueducto.
    None cuando el pliego no lo dice en esos términos (o no se leyó): entonces
    ningún contrato se descarta por el objeto, se mandan a revisión."""
    _, materia = _actividades_y_materia(lote)
    return _familia_de(materia or normalizar(lote.experiencia_general))


def objeto_valido(objeto: str, lote: LoteTecnico) -> bool | None:
    """True si el objeto nombra una actividad de la experiencia general del
    lote y la clase de obra que pide el proceso; False si claramente es de
    otra cosa; None si no se puede decir (lo resuelve quien revisa con la
    certificación)."""
    texto = normalizar(objeto)
    if not texto.strip():
        return None
    actividades = actividades_del_lote(lote)
    familia = familia_del_lote(lote)
    if not actividades or familia is None:
        # Sin la experiencia general del pliego no hay con qué comparar: no se
        # descarta nada por el objeto.
        return None
    tiene_actividad = any(re.search(rf"\b{re.escape(a)}", texto) for a in actividades)
    tiene_materia = bool(re.search(_FAMILIAS[familia][1], texto))
    if tiene_actividad and tiene_materia:
        return True
    if not tiene_materia and not re.search(r"OBRA|INFRAESTRUCTURA", texto):
        return False
    return None


# ----------------------------------------------------------- cruce con el RUP

def _palabras(texto: str) -> set[str]:
    return {p for p in re.findall(r"[A-Z]{4,}", normalizar(texto)) if p not in {"MUNICIPIO", "DEPARTAMENTO", "ALCALDIA", "GOBERNACION", "INSTITUTO", "NACIONAL", "SECRETARIA"}}


def _contratante_coincide(a: str, b: str) -> bool:
    pa, pb = _palabras(a), _palabras(b)
    if not pa or not pb:
        # "IDU", "INVIAS": siglas cortas; se comparan completas.
        return normalizar(a).strip() == normalizar(b).strip() or not a.strip() or not b.strip()
    return bool(pa & pb)


def _valor_coincide(fila: ContratoFormato3, exp: ExperienciaRup) -> bool:
    if exp.valor_smmlv is None:
        return False
    for valor in (fila.valor_rup, fila.valor_smmlv):
        if valor and valor < 10_000_000 and abs(valor - exp.valor_smmlv) <= TOLERANCIA_VALOR * exp.valor_smmlv:
            return True
    return False


def _nombrado(integrante: IntegranteTecnico, texto: str, integrantes: list[IntegranteTecnico] | None = None) -> bool:
    """El texto (columna del integrante o de los consecutivos) nombra al
    integrante: trae una palabra propia de su nombre (que no esté en el de
    los demás integrantes). Tolera nombres partidos por la lectura del PDF
    ("AXIS INFRAESTRUCTUR A SAS")."""
    comunes = {"SAS", "LTDA", "CONSTRUCCIONES", "CONSTRUCTORA", "INGENIERIA", "INGENIEROS", "OBRAS", "CIVILES",
               "GRUPO", "GROUP", "SERVICIOS", "COLOMBIA", "PROYECTOS", "INVERSIONES", "SOCIEDAD"}

    def palabras(t: str) -> set[str]:
        return set(re.findall(r"[A-Z0-9&]{3,}", normalizar(t).replace(".", "")))

    de_otros = set().union(*(palabras(i.nombre) for i in (integrantes or []) if i is not integrante))
    propias = {p for p in palabras(integrante.nombre) if p not in comunes and p not in de_otros}
    return bool(propias & palabras(texto))


def _lotes_de(fila: ContratoFormato3, lotes: list[LoteTecnico]) -> set[str]:
    texto = normalizar(fila.lotes)
    if not texto or "TODOS" in texto:
        return {l.nombre for l in lotes}
    numeros = set(re.findall(r"\d+", texto.replace(".", " ")))
    elegidos = {l.nombre for l in lotes if (m := re.search(r"\d+", l.nombre)) and m.group(0) in numeros}
    return elegidos or {l.nombre for l in lotes}


def cruzar_contrato(
    fila: ContratoFormato3, integrantes: list[IntegranteTecnico], parametros: ParametrosTecnicos,
    lotes: list[LoteTecnico], fecha_cierre: date,
) -> ContratoEvaluado:
    contrato = ContratoEvaluado(
        orden=fila.orden, consecutivos=fila.consecutivos, contratante=fila.contratante, objeto=fila.objeto,
        numero_contrato=fila.numero_contrato, lotes=_lotes_de(fila, lotes),
    )
    if not fila.consecutivos:
        contrato.problemas.append("el Formato 3 no indica el número consecutivo del contrato en el RUP")
        return contrato
    # El integrante que aporta el contrato, si el formato lo nombra: los
    # consecutivos se repiten entre los RUP de distintos integrantes (el 15 de
    # uno no es el 15 de otro).
    nombrados = [i for i in integrantes if _nombrado(i, f"{fila.integrante} {fila.texto_consecutivo}", integrantes)]
    encontrados: list[tuple[IntegranteTecnico, ExperienciaRup]] = []
    for consecutivo in fila.consecutivos:
        candidatos = []
        for integrante in integrantes:
            exp = integrante.rup.experiencias.get(consecutivo) if integrante.rup else None
            if exp is not None and all(integrante is not i for i, _ in encontrados):
                candidatos.append((integrante, exp, _contratante_coincide(fila.contratante, exp.contratante), _valor_coincide(fila, exp)))
        elegidos = [(i, e) for i, e, c, v in candidatos if i in nombrados and (c or v)]
        if not elegidos:
            # Sin integrante nombrado (o ilegible): contratante y valor, o uno
            # de los dos si solo un RUP tiene ese consecutivo.
            elegidos = [(i, e) for i, e, c, v in candidatos if c and v]
            debiles = [(i, e) for i, e, c, v in candidatos if c or v]
            if not elegidos and len(debiles) == 1 and len(candidatos) == 1:
                elegidos = debiles
        encontrados.extend(elegidos[:1] if len(fila.consecutivos) == 1 else elegidos)
    if not encontrados:
        faltan = ", ".join(fila.consecutivos)
        contrato.problemas.append(
            f"el consecutivo {faltan} ({fila.contratante or 'sin contratante'}) no se encontró en el RUP de ningún integrante"
        )
        return contrato
    valores = [e.valor_smmlv for _, e in encontrados if e.valor_smmlv is not None]
    if not valores:
        contrato.problemas.append("el RUP no trae el valor del contrato en SMMLV")
        return contrato
    contrato.valor_smmlv = max(valores)
    if max(valores) - min(valores) > TOLERANCIA_VALOR * max(valores):
        contrato.problemas.append("los integrantes reportan valores distintos del mismo contrato en sus RUP")
    participacion_total = 0.0
    for integrante, exp in encontrados:
        # Si el RUP trae un porcentaje se aplica siempre (lo conservador).
        parte = exp.participacion if exp.participacion is not None else (None if exp.en_consorcio else 1.0)
        if parte is None:
            contrato.problemas.append(f"el RUP de {integrante.nombre} no trae su porcentaje de participación en el contrato")
            contrato.aportes = {}
            return contrato
        participacion_total += parte
        contrato.aportes[integrante.nombre] = contrato.aportes.get(integrante.nombre, 0.0) + contrato.valor_smmlv * parte
    contrato.participacion = participacion_total
    contrato.de_un_socio = any(e.de_un_socio for _, e in encontrados)
    contrato.socios_de = [i.nombre for i, e in encontrados if e.de_un_socio]
    if participacion_total > 1.0001:
        contrato.problemas.append("la suma de participaciones en el contrato pasa del 100 %")
        contrato.aportes = {}
        return contrato
    clases = set().union(*(e.clases for _, e in encontrados))
    contrato.unspsc = bool(clases & parametros.clases_unspsc) if parametros.clases_unspsc else None
    if contrato.unspsc is False:
        contrato.problemas.append("el contrato no está clasificado en el RUP con los códigos UNSPSC del pliego")
    if fila.terminacion is not None:
        contrato.terminado = fila.terminacion < fecha_cierre
        if not contrato.terminado:
            contrato.problemas.append(f"terminó el {fila.terminacion:%d/%m/%Y}, después del cierre")
    return contrato


# --------------------------------------------------------------- por lote

BuscarLongitud = Callable[[ContratoEvaluado], tuple[float | None, str | None, str | None]]
BuscarArea = Callable[[ContratoEvaluado], tuple[float | None, str | None, str | None]]
# Verifica la experiencia de socios de un integrante (3.5.2 E): (vale, explicación).
VerificarSocio = Callable[[str], tuple[bool | None, str]]
BuscarSoporte = Callable[[ContratoEvaluado], str | None]


def evaluar_lote(
    lote: LoteTecnico, contratos: list[ContratoEvaluado], integrantes: list[IntegranteTecnico],
    parametros: ParametrosTecnicos, plural: bool, buscar_longitud: BuscarLongitud | None = None,
    verificar_socio: VerificarSocio | None = None, buscar_area: BuscarArea | None = None,
    buscar_soporte: BuscarSoporte | None = None,
) -> ResultadoLote:
    resultado = ResultadoLote(lote=lote.nombre, longitud_minima_km=lote.longitud_minima_km)
    del_lote = [c for c in contratos if lote.nombre in c.lotes]
    # El objeto se juzga contra la experiencia general de cada lote (el lote 2
    # de un proceso puede no admitir "mantenimiento" y el lote 1 sí).
    objeto = {id(c): objeto_valido(c.objeto, lote) for c in del_lote}
    # Máximo de contratos: los de mayor valor (3.5.3 C).
    del_lote.sort(key=lambda c: c.valor_aportado or 0, reverse=True)
    if len(del_lote) > parametros.max_contratos:
        resultado.motivos.append(
            f"aporta {len(del_lote)} contratos; se tomaron los {parametros.max_contratos} de mayor valor "
            "(revisa si acredita MIPYME o emprendimiento de mujeres, que permiten 6 o 7)"
        )
        del_lote = del_lote[: parametros.max_contratos]
    resultado.contratos = del_lote
    validos = [c for c in del_lote if c.valido and objeto[id(c)] is not False]
    presupuesto = parametros.presupuesto_smmlv(lote)
    if presupuesto is None:
        resultado.motivos.append("no se pudo leer el presupuesto oficial del lote en el pliego")
        return resultado
    resultado.factor = parametros.factor(len(validos)) if validos else None
    resultado.valor_certificado = sum(c.valor_aportado or 0 for c in validos)
    if resultado.factor is not None:
        resultado.valor_a_certificar = presupuesto * resultado.factor
    socio_ok: dict[int, bool] = {}
    for c in del_lote:
        for problema in c.problemas:
            resultado.motivos.append(f"contrato {c.orden}: {problema} (no se tuvo en cuenta)")
        if c.de_un_socio and c in validos:
            for nombre in c.socios_de:
                vale, explicacion = verificar_socio(nombre) if verificar_socio else (None, "")
                socio_ok[id(c)] = socio_ok.get(id(c), True) and vale is True
                resultado.motivos.append(
                    f"contrato {c.orden}: experiencia de un socio o accionista de {nombre} (3.5.2 E): "
                    + (explicacion or "verifica que la sociedad tenga menos de tres años y el documento de conformación")
                )
        if objeto[id(c)] is None and c in validos:
            resultado.motivos.append(f"contrato {c.orden}: revisa que el objeto corresponda a la experiencia general del lote: «{c.objeto[:160]}»")
        elif objeto[id(c)] is False and c.valor_aportado is not None:
            resultado.motivos.append(f"contrato {c.orden}: el objeto no corresponde a la experiencia general del lote (no se tuvo en cuenta): «{c.objeto[:160]}»")
    if not validos:
        resultado.cumple = False
        resultado.motivos.append("ningún contrato se pudo validar")
        return resultado
    cumple_valor = resultado.valor_a_certificar is not None and resultado.valor_certificado >= resultado.valor_a_certificar
    if not cumple_valor:
        resultado.motivos.append(
            f"certifica {resultado.valor_certificado:,.2f} SMMLV y se requieren {resultado.valor_a_certificar or 0:,.2f}"
            f" ({(resultado.factor or 0) * 100:.0f} % de {presupuesto:,.2f} con {len(validos)} contrato(s))"
        )
    if lote.fraccion_un_contrato is not None:
        minimo = presupuesto * lote.fraccion_un_contrato
        resultado.un_contrato_70 = any((c.valor_aportado or 0) >= minimo for c in validos)
        if not resultado.un_contrato_70:
            resultado.motivos.append(
                f"ningún contrato llega al {lote.fraccion_un_contrato * 100:.0f} % del presupuesto ({minimo:,.2f} SMMLV)"
            )
    if lote.longitud_minima_km is not None:
        resultado.longitud = _longitud_del_lote(lote, validos, resultado, buscar_longitud, buscar_area)
    resultado.area_minima_m2 = lote.area_minima_m2
    if lote.area_minima_m2 is not None:
        resultado.area = _area_del_lote(lote, validos, resultado, buscar_area)
    if lote.area_minima_m2 is not None:
        resultado.area_minima_m2 = lote.area_minima_m2
        resultado.area = _area_del_lote(lote, validos, resultado, buscar_area)
    if plural:
        resultado.condiciones_plural = _condiciones_plural(resultado, validos, integrantes, parametros)
    # Cada contrato que cuenta necesita su acta o certificación: el evaluador
    # verifica el objeto con ella y rechaza el que solo está en el RUP.
    sin_soporte = []
    if buscar_soporte is not None:
        for c in validos:
            if not c.soporte_buscado:
                c.soporte, c.soporte_buscado = buscar_soporte(c), True
            if c.soporte is None:
                sin_soporte.append(c)
                resultado.motivos.append(
                    f"contrato {c.orden}: no se encontró su acta o certificación entre los documentos de la oferta (3.5.6); "
                    "verifica que el proponente la haya aportado"
                )
    exigencias = [cumple_valor, resultado.un_contrato_70 is not False, resultado.condiciones_plural is not False]
    if lote.condicion_objeto and validos:
        # El pliego pide, además de la experiencia general, que al menos un
        # contrato cumpla una condición del objeto ("…DECLARADAS COMO BIENES
        # DE INTERÉS CULTURAL"). La entidad la da por acreditada con los
        # documentos de la declaratoria, no con el objeto del contrato: no se
        # puede aprobar sola.
        palabras = {p for p in re.findall(r"[A-ZÑ]{5,}", lote.condicion_objeto) if p not in ("COMO", "BIENES")}
        parecidos = [str(c.orden) for c in validos
                     if palabras & set(re.findall(r"[A-ZÑ]{5,}", normalizar(c.objeto)))]
        resultado.motivos.append(
            f"la experiencia específica exige que al menos un contrato sea «{lote.condicion_objeto.lower()}»: "
            + (f"revisa el contrato {', '.join(parecidos)} y el documento que acredita esa condición"
               if parecidos else "ningún contrato lo dice en su objeto; revisa los documentos aportados")
        )
    if not parametros.clases_unspsc:
        resultado.motivos.append(
            "no se leyeron en el pliego los códigos UNSPSC exigidos: no se verificó la clasificación de los contratos"
        )
    if parametros.requisitos_sin_verificar:
        # El pliego exige cosas que el motor no sabe comprobar: se dicen, y el
        # lote no se aprueba solo (nunca se da por cumplido lo que no se miró).
        resultado.motivos.append(
            f"el pliego exige {len(parametros.requisitos_sin_verificar)} requisito(s) que el programa no verifica; "
            "revísalos: " + "; ".join(parametros.requisitos_sin_verificar[:3])
            + (" …" if len(parametros.requisitos_sin_verificar) > 3 else "")
        )
    if parametros.sin_confirmar:
        # Se evalúa con lo que la IA leyó del pliego, pero no se aprueba solo
        # hasta que alguien confirme esos parámetros en la plataforma.
        resultado.motivos.append(
            "del pliego se leyó con IA y falta confirmar: " + "; ".join(parametros.sin_confirmar[:4])
            + (f" (y {len(parametros.sin_confirmar) - 4} más)" if len(parametros.sin_confirmar) > 4 else "")
        )
    dudas = [
        bool(parametros.requisitos_sin_verificar),
        bool(parametros.sin_confirmar),
        bool(lote.condicion_objeto),
        not parametros.clases_unspsc,
        any(objeto[id(c)] is None or (c.de_un_socio and not socio_ok.get(id(c))) for c in validos),
        lote.longitud_minima_km is not None and resultado.longitud is not True,
        lote.area_minima_m2 is not None and resultado.area is not True,
        lote.area_minima_m2 is not None and resultado.area is not True,
        plural and resultado.condiciones_plural is None,
        bool(sin_soporte),
    ]
    resultado.cumple = all(exigencias) and not any(dudas)
    return resultado


def _longitud_del_lote(
    lote: LoteTecnico, validos: list[ContratoEvaluado], resultado: ResultadoLote, buscar: BuscarLongitud | None,
    buscar_area: BuscarArea | None = None,
) -> bool | None:
    """True si un contrato válido acredita la longitud mínima afectada por la
    participación (3.5.3 G). Si no se encuentra, None: a revisión."""
    minimo = lote.longitud_minima_km
    for c in validos:
        if not c.longitud_buscada and buscar is not None:
            c.longitud_km, c.soporte_longitud, c.cita_longitud = buscar(c)
            c.longitud_buscada = True
        if c.longitud_km is not None and c.longitud_km * min(c.participacion or 0, 1.0) >= minimo - 1e-9:
            if c.cita_longitud:
                resultado.motivos.append(
                    f"contrato {c.orden}: longitud de {c.longitud_km:.3f} km leída con IA local en {c.soporte_longitud} "
                    f"(cita verificada en el documento: «{c.cita_longitud}»)"
                )
            return True
    leidas = [
        f"contrato {c.orden}: {c.longitud_km:.3f} km × {min(c.participacion or 0, 1.0) * 100:.0f} %"
        for c in validos if c.longitud_km is not None
    ]
    # Soportes que traen el área intervenida y no la longitud: el pliego pide
    # la longitud (3.5.5 D); se reporta para pedir la aclaración.
    for c in validos:
        if c.longitud_km is None and buscar_area is not None and c.area_m2 is None:
            c.area_m2, c.soporte_area, cita = buscar_area(c)
            if c.area_m2 is not None:
                resultado.motivos.append(
                    f"contrato {c.orden}: el soporte ({c.soporte_area}) presenta el área intervenida "
                    f"({c.area_m2:,.2f} m²) y no la longitud intervenida que exige el pliego (3.5.5 D); "
                    "solicita la aclaración al proponente"
                    + (f" (leída con IA local, cita verificada: «{cita}»)" if cita else "")
                )
    resultado.motivos.append(
        f"verifica en las certificaciones que un contrato acredite al menos {minimo:.3f} km intervenidos "
        f"({(lote.fraccion_longitud or 0) * 100:.0f} % de {lote.longitud_total_km} km, afectado por la participación)"
        + (f"; se leyó {'; '.join(leidas)}" if leidas else "; no se encontró la longitud en los soportes")
    )
    return None


def _area_del_lote(
    lote: LoteTecnico, validos: list[ContratoEvaluado], resultado: ResultadoLote, buscar: BuscarArea | None,
) -> bool | None:
    """True si un contrato válido acredita los metros cuadrados mínimos que
    pide el pliego en los procesos de edificaciones ("un área intervenida o
    construida igual o superior al 50 % del total de metros cuadrados del
    proceso"). Si no se encuentra el área en los soportes, None: a revisión,
    nunca se da por cumplido."""
    minimo = lote.area_minima_m2
    for c in validos:
        if c.area_m2 is None and buscar is not None:
            c.area_m2, c.soporte_area, cita = buscar(c)
            if c.area_m2 is not None and cita:
                resultado.motivos.append(
                    f"contrato {c.orden}: área de {c.area_m2:,.2f} m² leída con IA local en {c.soporte_area} "
                    f"(cita verificada en el documento: «{cita}»)"
                )
        if c.area_m2 is not None and c.area_m2 * min(c.participacion or 0, 1.0) >= minimo - 1e-9:
            return True
    leidas = [f"contrato {c.orden}: {c.area_m2:,.2f} m² × {min(c.participacion or 0, 1.0) * 100:.0f} %"
              for c in validos if c.area_m2 is not None]
    resultado.motivos.append(
        f"verifica en las certificaciones que un contrato acredite al menos {minimo:,.2f} m² intervenidos o "
        f"construidos ({(lote.fraccion_area or 0) * 100:.0f} % de {lote.area_total_m2:,.2f} m², afectado por la "
        "participación)" + (f"; se leyó {'; '.join(leidas)}" if leidas else "; no se encontró el área en los soportes")
    )
    return None


def _area_del_lote(
    lote: LoteTecnico, validos: list[ContratoEvaluado], resultado: ResultadoLote, buscar_area: BuscarArea | None,
) -> bool | None:
    """True si un contrato válido acredita el área mínima intervenida o
    construida (en edificaciones el pliego la exige en vez de la longitud).
    Si no se encuentra en los soportes, None: el lote va a revisión, nunca se
    aprueba dando el requisito por cumplido."""
    minimo = lote.area_minima_m2
    citas: dict[int, str] = {}
    for c in validos:
        if c.area_m2 is None and buscar_area is not None:
            c.area_m2, c.soporte_area, cita = buscar_area(c)
            if cita:
                citas[id(c)] = cita
        if c.area_m2 is not None and c.area_m2 * min(c.participacion or 0, 1.0) >= minimo - 1e-9:
            resultado.motivos.append(
                f"contrato {c.orden}: área de {c.area_m2:,.2f} m² acreditada en {c.soporte_area}"
                + (f" (leída con IA local, cita verificada: «{citas[id(c)]}»)" if citas.get(id(c)) else "")
            )
            return True
    leidas = [f"contrato {c.orden}: {c.area_m2:,.2f} m² × {min(c.participacion or 0, 1.0) * 100:.0f} %"
              for c in validos if c.area_m2 is not None]
    resultado.motivos.append(
        f"verifica en las certificaciones que un contrato acredite al menos {minimo:,.2f} m² intervenidos o "
        f"construidos ({(lote.fraccion_area or 0) * 100:.0f} % de {lote.area_total_m2:,.2f} m², afectado por la "
        "participación)" + (f"; se leyó {'; '.join(leidas)}" if leidas else "; no se encontró el área en los soportes")
    )
    return None


def _condiciones_plural(
    resultado: ResultadoLote, validos: list[ContratoEvaluado], integrantes: list[IntegranteTecnico], parametros: ParametrosTecnicos,
) -> bool | None:
    """3.5.3 D, sobre el valor mínimo a certificar."""
    base = resultado.valor_a_certificar
    if not base:
        return None
    aportes = {i.nombre: 0.0 for i in integrantes}
    for c in validos:
        for nombre, valor in c.aportes.items():
            aportes[nombre] = aportes.get(nombre, 0.0) + valor
    resultado.aporte_por_integrante = aportes
    if any(i.participacion is None for i in integrantes):
        resultado.motivos.append("no se leyó el porcentaje de participación de cada integrante (Formato 2)")
        return None
    fracciones = {n: v / base for n, v in aportes.items()}
    ok = True
    if max(fracciones.values(), default=0) < parametros.plural_principal:
        resultado.motivos.append(f"ningún integrante aporta el {parametros.plural_principal * 100:.0f} % de la experiencia requerida")
        ok = False
    sin_experiencia = [i for i in integrantes if fracciones.get(i.nombre, 0) == 0]
    if len(sin_experiencia) > 1:
        resultado.motivos.append("más de un integrante no aporta experiencia")
        ok = False
    for i in sin_experiencia:
        if (i.participacion or 0) > parametros.plural_sin_experiencia_max + 1e-9:
            resultado.motivos.append(
                f"{i.nombre} no aporta experiencia y su participación ({i.participacion * 100:.0f} %) pasa del "
                f"{parametros.plural_sin_experiencia_max * 100:.0f} %"
            )
            ok = False
    for i in integrantes:
        f = fracciones.get(i.nombre, 0)
        if 0 < f < parametros.plural_demas:
            resultado.motivos.append(f"{i.nombre} aporta {f * 100:.1f} %, menos del {parametros.plural_demas * 100:.0f} % exigido")
            ok = False
    return ok


def evaluar_experiencia(
    formato3: Formato3 | None, integrantes: list[IntegranteTecnico], parametros: ParametrosTecnicos,
    fecha_cierre: date, plural: bool, buscar_longitud: BuscarLongitud | None = None,
    verificar_socio: VerificarSocio | None = None, buscar_area: BuscarArea | None = None,
    buscar_soporte: BuscarSoporte | None = None,
) -> list[ResultadoLote]:
    if formato3 is None:
        return [
            ResultadoLote(lote=l.nombre, cumple=False, motivos=["no se encontró el Formato 3 – Experiencia (el pliego permite subsanarlo)"])
            for l in parametros.lotes
        ]
    contratos = [cruzar_contrato(f, integrantes, parametros, parametros.lotes, fecha_cierre) for f in formato3.contratos]
    return [
        evaluar_lote(l, contratos, integrantes, parametros, plural, buscar_longitud, verificar_socio, buscar_area, buscar_soporte)
        for l in parametros.lotes
    ]
