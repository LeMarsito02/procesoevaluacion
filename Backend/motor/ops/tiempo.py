"""Cuenta del tiempo de experiencia en forma comercial: todos los meses valen
30 días y el año 360, como en la liquidación de nómina.

El día 31 y el último día de febrero valen 30. Se cuentan los dos extremos
del periodo (del 1 al 30 de un mes es un mes completo); `ambos_extremos`
permite no contar el último día si la entidad lo hace así.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

DIAS_MES = 30
DIAS_ANIO = 360

MESES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7,
    "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}
_M = "|".join(MESES)
_ABREVIADOS = {m[:3]: n for m, n in MESES.items() if m != "SETIEMBRE"}
_ABR = "|".join(_ABREVIADOS)
# Año de cuatro cifras, a veces con punto de mil («1.984»).
_ANIO = r"(?:\d{4}|\d\.\d{3})"
# Con el mes en letras, como lo escribe cada quien: «20 de febrero de 2025»,
# «05 de enero 1991», «31/octubre/2025», «18/Jul/2024», «a los 11 días del mes
# de mayo año de 1990». El mes abreviado solo vale con un separador detrás.
_CON_MES = (
    rf"\(?\d{{1,2}}\)?[O*]?(?:\s+DIAS)?\s*(?:DEL?\s+MES\s+DE\s+|DE\s+|[/-]\s*)?(?:{_M}|(?:{_ABR})(?=[\s./-]))\.?\s*"
    rf"(?:DEL?\s+|[/-]\s*)?(?:ANO\s+)?(?:DE\s+)?{_ANIO}"
)
# Una fecha escrita en un documento ya normalizado (mayúsculas, sin tildes).
FECHA = rf"(?:\d{{1,2}}\s*[/-]\s*\d{{1,2}}\s*[/-]\s*\d{{4}}|{_CON_MES}|(?:{_M})\s+\d{{1,2}}\s+DE\s+{_ANIO})"
_PATRONES = [
    re.compile(r"\b(?P<d>\d{1,2})\s*[/-]\s*(?P<m>\d{1,2})\s*[/-]\s*(?P<a>\d{4})\b"),
    re.compile(
        rf"(?<![\d/.-])\(?(?P<d>\d{{1,2}})\)?[O*]?(?:\s+DIAS)?\s*(?:DEL?\s+MES\s+DE\s+|DE\s+|[/-]\s*)?(?:(?P<mes>{_M})|(?P<abr>{_ABR})(?=[\s./-]))\.?\s*"
        rf"(?:DEL?\s+|[/-]\s*)?(?:ANO\s+)?(?:DE\s+)?(?P<a>{_ANIO})\b"
    ),
    re.compile(rf"\b(?P<mes>{_M})\s+(?P<d>\d{{1,2}})\s+DE\s+(?P<a>{_ANIO})\b"),
    # «a los veinticinco (25) días del mes de mayo del año dos mil once (2011)»
    re.compile(
        rf"\((?P<d>\d{{1,2}})\)\s+DIAS?\s+DEL\s+MES\s+DE\s+(?P<mes>{_M})\s+DEL?\s+(?:ANO\s+)?(?:[A-Z ]{{0,40}}\()?(?P<a>\d{{4}})\)?"
    ),
]
# Años creíbles en un documento de experiencia o de estudios.
_ANIO_MINIMO, _ANIO_MAXIMO = 1940, 2100


def fechas_con_tramo(texto_norm: str) -> list[tuple[int, int, date]]:
    """Las fechas escritas en el texto con dónde empieza y termina cada una, en orden."""
    halladas: dict[int, tuple[int, date]] = {}
    for patron in _PATRONES:
        for m in patron.finditer(texto_norm):
            g = m.groupdict()
            try:
                mes = int(g["m"]) if g.get("m") else _ABREVIADOS[g["abr"]] if g.get("abr") else MESES[g["mes"]]
                anio = int(g["a"].replace(".", ""))
                if _ANIO_MINIMO <= anio <= _ANIO_MAXIMO:
                    halladas.setdefault(m.start(), (m.end(), date(anio, mes, int(g["d"]))))
            except (ValueError, KeyError):
                continue
    # Una fecha que quedó dentro de otra ya leída (el «2 de 2009» de «febrero 2 de 2009») no es otra fecha.
    tramos: list[tuple[int, int, date]] = []
    for inicio, (fin, fecha) in sorted(halladas.items()):
        if tramos and inicio < tramos[-1][1]:
            continue
        tramos.append((inicio, fin, fecha))
    return tramos


def fechas_en(texto_norm: str) -> list[tuple[int, date]]:
    """Las fechas escritas en el texto, con su posición, en el orden en que aparecen."""
    return [(inicio, fecha) for inicio, _, fecha in fechas_con_tramo(texto_norm)]


def fecha_de(texto_norm: str) -> date | None:
    fechas = fechas_en(texto_norm)
    return fechas[0][1] if fechas else None


def _dia_comercial(fecha: date) -> int:
    ultimo_de_febrero = fecha.month == 2 and (fecha + timedelta(days=1)).month == 3
    return DIAS_MES if fecha.day > DIAS_MES or ultimo_de_febrero else fecha.day


def dias_comerciales(inicio: date, fin: date, ambos_extremos: bool = True) -> int:
    """Días entre dos fechas con meses de 30 días. Cero si el fin es anterior al inicio."""
    if fin < inicio:
        return 0
    dias = (
        (fin.year - inicio.year) * DIAS_ANIO
        + (fin.month - inicio.month) * DIAS_MES
        + _dia_comercial(fin) - _dia_comercial(inicio)
    )
    return max(dias + (1 if ambos_extremos else 0), 0)


def anios_meses_dias(dias: int) -> tuple[int, int, int]:
    return dias // DIAS_ANIO, dias % DIAS_ANIO // DIAS_MES, dias % DIAS_MES


def texto_duracion(dias: int) -> str:
    """«15 años, 11 meses y 28 días»; omite lo que vale cero."""
    anios, meses, resto = anios_meses_dias(dias)
    partes = [
        f"{n} {uno if n == 1 else varios}"
        for n, uno, varios in ((anios, "año", "años"), (meses, "mes", "meses"), (resto, "día", "días"))
        if n
    ]
    if not partes:
        return "0 días"
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]
