"""Tabla de honorarios máximos de una entidad para contratos de prestación
de servicios (en el ICCU, la Resolución 1750 de 2025 para la vigencia 2026).

Cada entidad expide la suya por vigencia: aquí solo está la forma de la tabla
y cómo se consulta; los valores los registra la entidad. La franja «entre 10
y 15» incluye los 10 años exactos y no los 15.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from motor.ops.tiempo import DIAS_ANIO

SIN_POSGRADO = "ninguno"
ESPECIALIZACION = "especializacion"
MAESTRIA = "maestria"
_ORDEN_POSGRADO = [SIN_POSGRADO, ESPECIALIZACION, MAESTRIA]


@dataclass(frozen=True)
class FranjaProfesional:
    desde: float  # años de experiencia profesional
    hasta: float | None  # None: sin tope («mayor a 30»)
    sin_especializacion: int
    con_especializacion: int
    con_maestria: int

    def tope(self, posgrado: str) -> int:
        return {SIN_POSGRADO: self.sin_especializacion, ESPECIALIZACION: self.con_especializacion}.get(posgrado, self.con_maestria)

    @property
    def nombre(self) -> str:
        return f"mayor a {self.desde:g} años" if self.hasta is None else f"entre {self.desde:g} y {self.hasta:g} años"


@dataclass(frozen=True)
class FranjaReconocimiento:
    """Valor que se reconoce por experiencia específica (relacionada)."""

    desde: float
    hasta: float | None
    valor: int


@dataclass
class TablaHonorarios:
    vigencia: int
    norma: str
    profesional: list[FranjaProfesional]
    reconocimiento: list[FranjaReconocimiento] = field(default_factory=list)

    def franja(self, dias_profesional: int) -> FranjaProfesional | None:
        anios = dias_profesional / DIAS_ANIO
        for f in self.profesional:
            if anios >= f.desde and (f.hasta is None or anios < f.hasta):
                return f
        return None

    def valor_reconocimiento(self, dias_especifica: int) -> int:
        anios = dias_especifica / DIAS_ANIO
        for f in self.reconocimiento:
            if anios >= f.desde and (f.hasta is None or anios < f.hasta):
                return f.valor
        return 0

    def franja_minima_para(self, honorarios: int, posgrado: str) -> FranjaProfesional | None:
        """La franja más baja cuyo tope alcanza para esos honorarios."""
        for f in sorted(self.profesional, key=lambda f: f.desde):
            if f.tope(posgrado) >= honorarios:
                return f
        return None


def posgrado_mayor(niveles: list[str]) -> str:
    """El posgrado más alto entre los títulos de la persona."""
    return max((n for n in niveles if n in _ORDEN_POSGRADO), key=_ORDEN_POSGRADO.index, default=SIN_POSGRADO)
