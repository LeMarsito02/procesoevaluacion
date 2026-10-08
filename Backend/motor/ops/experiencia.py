"""Experiencia de un contratista de prestación de servicios, puesta en línea.

Una persona puede tener varios contratos en el mismo periodo, pero el tiempo
solo cuenta una vez: tres contratos en el mismo año valen un año. Aquí se
toman los periodos leídos de las certificaciones y se dejan sin traslapes:

1. Lo anterior a la fecha desde la que cuenta la experiencia (el grado) se
   descarta.
2. De dos periodos que se cruzan, el que empezó después solo aporta los días
   que el anterior no cubría.
3. Las suspensiones del contrato se descuentan.

Nada se oculta: cada periodo que no aporta queda en `descartados` con el
motivo, para que la persona lo vea y lo confirme.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from motor.ops.tiempo import DIAS_ANIO, dias_comerciales


@dataclass
class Periodo:
    inicio: date
    fin: date
    entidad: str = ""
    referencia: str = ""  # número del contrato o «vinculación laboral»
    suspensiones: list[tuple[date, date]] = field(default_factory=list)
    # La certificación no trae fecha de terminación (contrato en ejecución,
    # persona activa): se contó hasta la fecha en que se expidió.
    abierto: bool = False
    # Sus obligaciones son las mismas del contrato que se va a celebrar.
    relacionada: bool = False
    # Algo de la lectura que una persona debe confirmar (inicio deducido, fecha recortada…).
    nota: str = ""
    # La persona decidió conservarlo: no se propone retirarlo aunque sobre experiencia.
    fijo: bool = False
    # Obligaciones del estudio previo (por número) que la certificación repite.
    obligaciones_iguales: list[int] = field(default_factory=list)
    # Texto de la certificación (su página y la siguiente), para compararlo.
    texto: str = field(default="", repr=False)
    archivo: str = ""
    pagina: int | None = None


@dataclass
class Tramo:
    """La parte de un periodo que cuenta."""

    periodo: Periodo
    inicio: date
    fin: date
    dias: int

    @property
    def recortado(self) -> bool:
        return self.inicio != self.periodo.inicio


@dataclass
class Descartado:
    periodo: Periodo
    motivo: str


@dataclass
class ExperienciaLineal:
    tramos: list[Tramo] = field(default_factory=list)
    descartados: list[Descartado] = field(default_factory=list)

    @property
    def dias(self) -> int:
        return sum(t.dias for t in self.tramos)


def _nombre(periodo: Periodo) -> str:
    return periodo.referencia or periodo.entidad or f"el periodo que empieza el {periodo.inicio:%d/%m/%Y}"


def _dias_del_tramo(periodo: Periodo, inicio: date, fin: date, ambos_extremos: bool) -> int:
    dias = dias_comerciales(inicio, fin, ambos_extremos)
    for desde, hasta in periodo.suspensiones:
        dias -= dias_comerciales(max(desde, inicio), min(hasta, fin))
    return max(dias, 0)


def poner_en_linea(periodos: list[Periodo], desde: date | None = None, ambos_extremos: bool = True) -> ExperienciaLineal:
    """Deja los periodos sin traslapes. `desde` es la fecha a partir de la cual
    cuenta la experiencia (el grado); sin ella cuenta todo."""
    lineal = ExperienciaLineal()
    cubierto_hasta: date | None = None
    cubre: Periodo | None = None
    for periodo in sorted(periodos, key=lambda p: (p.inicio, -p.fin.toordinal())):
        if periodo.fin < periodo.inicio:
            lineal.descartados.append(Descartado(periodo, "La fecha de terminación es anterior a la de inicio."))
            continue
        inicio = periodo.inicio
        if desde and periodo.fin < desde:
            lineal.descartados.append(Descartado(periodo, f"Es anterior al grado ({desde:%d/%m/%Y})."))
            continue
        if desde and inicio < desde:
            inicio = desde
        if cubierto_hasta and inicio <= cubierto_hasta:
            inicio = cubierto_hasta + timedelta(days=1)
        if inicio > periodo.fin:
            lineal.descartados.append(Descartado(periodo, f"Se traslapa por completo con {_nombre(cubre)}."))
            continue
        lineal.tramos.append(Tramo(periodo, inicio, periodo.fin, _dias_del_tramo(periodo, inicio, periodo.fin, ambos_extremos)))
        if cubierto_hasta is None or periodo.fin > cubierto_hasta:
            cubierto_hasta, cubre = periodo.fin, periodo
    return lineal


def ajustar_a_franja(lineal: ExperienciaLineal, anios_minimos: float, anios_maximos: float | None) -> list[Tramo]:
    """Los tramos que sobran para quedar dentro de la franja del perfil.

    Solo se deja la experiencia más relevante: se conserva primero la
    relacionada y luego la más reciente, y se retiran periodos completos
    mientras el total siga por encima del máximo sin bajar del mínimo.
    """
    if anios_maximos is None:
        return []
    maximo, minimo = anios_maximos * DIAS_ANIO, anios_minimos * DIAS_ANIO
    total = lineal.dias
    sobran: list[Tramo] = []
    for tramo in sorted(lineal.tramos, key=lambda t: (t.periodo.relacionada, t.inicio)):
        if total <= maximo:
            break
        if not tramo.periodo.fijo and total - tramo.dias >= minimo:
            sobran.append(tramo)
            total -= tramo.dias
    return sobran
