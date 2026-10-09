"""Días hábiles en Colombia: lunes a viernes que no sean festivos.

Festivos de la Ley 51 de 1983: los fijos, los que se trasladan al lunes
siguiente («ley Emiliani») y los que dependen de la Pascua. Sirve para contar
los términos de la etapa de evaluación (traslado del informe, subsanaciones).
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


def _pascua(anio: int) -> date:
    """Domingo de Pascua (algoritmo de Meeus/Jones/Butcher, calendario gregoriano)."""
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(anio, mes, dia)


def _al_lunes(fecha: date) -> date:
    return fecha + timedelta(days=(7 - fecha.weekday()) % 7)


@lru_cache(maxsize=64)
def festivos(anio: int) -> frozenset[date]:
    pascua = _pascua(anio)
    fijos = [date(anio, 1, 1), date(anio, 5, 1), date(anio, 7, 20), date(anio, 8, 7), date(anio, 12, 8), date(anio, 12, 25)]
    trasladables = [
        date(anio, 1, 6), date(anio, 3, 19), date(anio, 6, 29), date(anio, 8, 15),
        date(anio, 10, 12), date(anio, 11, 1), date(anio, 11, 11),
        pascua + timedelta(days=43),  # Ascensión (lunes siguiente al jueves)
        pascua + timedelta(days=64),  # Corpus Christi
        pascua + timedelta(days=71),  # Sagrado Corazón
    ]
    semana_santa = [pascua - timedelta(days=3), pascua - timedelta(days=2)]  # jueves y viernes santos
    return frozenset([*fijos, *semana_santa, *(_al_lunes(f) for f in trasladables)])


def es_habil(fecha: date) -> bool:
    return fecha.weekday() < 5 and fecha not in festivos(fecha.year)


def sumar_dias_habiles(desde: date, dias: int) -> date:
    """El día hábil número `dias` contado desde el siguiente a `desde`
    (así se cuentan los términos: el día del aviso no cuenta)."""
    fecha, contados = desde, 0
    while contados < dias:
        fecha += timedelta(days=1)
        if es_habil(fecha):
            contados += 1
    return fecha


def dias_habiles_entre(desde: date, hasta: date) -> int:
    """Días hábiles después de `desde` y hasta `hasta` inclusive (negativo si `hasta` es anterior)."""
    if hasta < desde:
        return -dias_habiles_entre(hasta, desde)
    return sum(1 for i in range(1, (hasta - desde).days + 1) if es_habil(desde + timedelta(days=i)))
