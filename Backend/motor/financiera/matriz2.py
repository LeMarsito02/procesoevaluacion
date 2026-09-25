"""La Matriz 2 del pliego: qué indicadores financieros exige y a quién.

La matriz es un anexo aparte (un Word, no el pliego), y no trae un solo juego
de umbrales: trae dos tablas —una para los proponentes que acrediten la calidad
de Mipyme y otra para los demás— y, dentro de cada una, una columna por rango de
presupuesto. Por eso, leída como texto corrido, de cada indicador salen cuatro
valores y hasta ahora había que pedirle a una persona que escogiera.

Pero la matriz dice ella misma cuál aplica: los rangos van en SMMLV ("Rango 1:
>0 <4.000; Rango 2: >=4.000") y los indicadores "deberán ser solicitados por las
Entidades (…) de acuerdo al rango en el cual se encuentre el presupuesto
oficial"; si el proceso va por lotes, "según el presupuesto del lote (…) al que
se presente". Con el presupuesto del lote y el salario mínimo del año, el rango
se elige solo.

Entre las dos tablas se toma la de los demás proponentes, que es la que aplica
salvo que el proponente demuestre ser Mipyme —y eso se sabe por proponente, no
por proceso—. Importa cuál: la de Mipyme es más laxa (liquidez ≥1,1 frente a
≥1,2), así que usarla con quien no lo es aprobaría a quien no cumple.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from motor.financiera.parametros import _INDICADORES_MATRIZ, _OTRO_INDICADOR_RE, _VALOR, Umbrales
from motor.tecnica.rup import normalizar

# Los encabezados con que la matriz separa sus dos tablas.
_TABLA_MIPYME_RE = re.compile(r"(?:INDICES|INDICADORES)[^\n]{0,80}PARA\s+MIPYME|PARA\s+MIPYME\b")
_TABLA_DEMAS_RE = re.compile(r"PARA\s+LOS\s+DEMAS\s+PROPONENTES|QUE\s+NO\s+DEMUESTREN\s+LA\s+CONDICION\s+DE\s+MIPYME")

# "Rango 1 … >0 <4.000 … Rango 2 … >= 4.000 … (Cifras expresadas en SMMLV)".
_LIMITE_RANGO_RE = re.compile(r">=?\s*(\d[\d.,]*)")
_EN_SMMLV_RE = re.compile(r"EXPRESADAS?\s+EN\s+SMMLV|EN\s+SMMLV")


def _numero(texto: str) -> float | None:
    """"4.000" son cuatro mil, no cuatro: en la matriz el punto es de miles."""
    limpio = texto.replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


@dataclass
class TablaMatriz2:
    """Una de las dos tablas: para Mipyme o para los demás proponentes."""

    para_mipyme: bool
    por_rango: dict[int, Umbrales]


@dataclass
class Matriz2:
    """La matriz entendida: sus rangos de presupuesto y sus dos tablas."""

    # Para cada rango (1, 2, …), desde cuántos SMMLV aplica. El último no tiene tope.
    desde_smmlv: dict[int, float]
    tablas: list[TablaMatriz2]

    @property
    def un_solo_juego(self) -> bool:
        """Hay matrices (las de menor cuantía, por ejemplo) que no van por
        rangos: traen un solo juego de indicadores por tabla. Entonces no hay
        nada que escoger."""
        return all(len(t.por_rango) == 1 for t in self.tablas)

    def rango_de(self, presupuesto_smmlv: float) -> int | None:
        """El rango en el que cae un presupuesto, o None si la matriz va por
        rangos y no dijo sus límites en SMMLV (entonces no se adivina)."""
        if self.un_solo_juego:
            return next(iter(self.tablas[0].por_rango))
        if not self.desde_smmlv:
            return None
        elegido = None
        for rango, desde in sorted(self.desde_smmlv.items()):
            if presupuesto_smmlv >= desde:
                elegido = rango
        return elegido or min(self.desde_smmlv)

    def umbrales(self, presupuesto_smmlv: float, *, mipyme: bool = False) -> tuple[Umbrales, str] | None:
        """(umbrales, de dónde salieron) para un presupuesto en SMMLV, o None si
        la matriz no alcanzó a entenderse y hay que preguntarle a una persona."""
        rango = self.rango_de(presupuesto_smmlv)
        if rango is None:
            return None
        tabla = next((t for t in self.tablas if t.para_mipyme == mipyme), None)
        if tabla is None or rango not in tabla.por_rango:
            return None
        umbrales = tabla.por_rango[rango]
        if not umbrales.completos:
            return None
        quien = "proponentes Mipyme" if mipyme else "los demás proponentes"
        if rango in self.desde_smmlv and not self.un_solo_juego:
            fuente = (f"Matriz 2, tabla de {quien}, rango {rango} "
                      f"(presupuesto de {presupuesto_smmlv:,.0f} SMMLV, el rango va desde "
                      f"{self.desde_smmlv[rango]:,.0f})")
        else:
            fuente = f"Matriz 2, tabla de {quien} (trae un solo juego de indicadores, sin rangos)"
        return Umbrales(**{**umbrales.__dict__, "fuente": fuente}), fuente


def _umbrales_por_rango(trozo: str) -> dict[int, Umbrales]:
    """Los valores de una tabla, columna por columna. En el texto de la tabla,
    los valores de cada indicador salen en el orden de sus columnas: el primero
    es el rango 1, el segundo el rango 2."""
    por_rango: dict[int, Umbrales] = {}
    for campo, (nombre, comparador) in _INDICADORES_MATRIZ.items():
        for m in re.finditer(nombre, trozo):
            resto = trozo[m.end(): m.end() + 240]
            corte = re.search(_OTRO_INDICADOR_RE, resto)
            ventana = resto[: corte.start()] if corte else resto
            valores = []
            for v in re.finditer(rf"(?:{comparador})\s*{_VALOR}", ventana):
                valor = _numero(v.group(1))
                if valor is not None and 0 < valor <= 100:
                    valores.append(valor / 100 if v.group(2) else valor)
            if not valores:
                continue
            for i, valor in enumerate(valores, start=1):
                setattr(por_rango.setdefault(i, Umbrales()), campo, valor)
            break  # la primera aparición del indicador es su fila
    return por_rango


def leer_matriz2(texto: str) -> Matriz2 | None:
    """La Matriz 2 entendida, o None si no se reconoce (entonces sigue haciendo
    falta que una persona registre los umbrales)."""
    t = re.sub(r"\s+", " ", normalizar(texto.replace("≥", ">=").replace("≤", "<=")))
    partes = [(m.start(), m.end(), True) for m in _TABLA_MIPYME_RE.finditer(t)]
    partes += [(m.start(), m.end(), False) for m in _TABLA_DEMAS_RE.finditer(t)]
    partes.sort()
    if not partes:
        return None
    tablas: list[TablaMatriz2] = []
    for i, (_, fin, para_mipyme) in enumerate(partes):
        hasta = partes[i + 1][0] if i + 1 < len(partes) else len(t)
        por_rango = _umbrales_por_rango(t[fin:hasta])
        if por_rango and not any(x.para_mipyme == para_mipyme for x in tablas):
            tablas.append(TablaMatriz2(para_mipyme, por_rango))
    if not tablas:
        return None
    return Matriz2(_rangos_en_smmlv(t), tablas)


def _rangos_en_smmlv(t: str) -> dict[int, float]:
    """Desde cuántos SMMLV aplica cada rango. Solo se leen si la matriz dice que
    las cifras van en SMMLV: sin esa marca no se sabe de qué son los números y
    no se adivina."""
    inicio = t.find("RANGO 1")
    if inicio < 0:
        return {}
    marca = _EN_SMMLV_RE.search(t[inicio: inicio + 600])
    if marca is None:
        return {}
    # Los límites van entre el encabezado de los rangos y la nota de que las
    # cifras son SMMLV. Acotarlo ahí importa: más allá empiezan los valores de
    # los indicadores (≥1,2) y se colarían como si fueran límites de rango.
    ventana = t[inicio: inicio + marca.start()]
    limites = [v for m in _LIMITE_RANGO_RE.finditer(ventana) if (v := _numero(m.group(1))) is not None]
    if not limites:
        return {}
    ordenados = sorted(set(limites))
    return {i: desde for i, desde in enumerate(ordenados, start=1)}
