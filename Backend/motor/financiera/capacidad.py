"""Capacidad financiera y organizacional (pliego 3.6, 3.7 y 3.9) con la
información del RUP de cada integrante.

En proponentes plurales cada indicador se calcula con la suma de sus
componentes (Σ activo corriente / Σ pasivo corriente…), y el capital de
trabajo es la suma del de cada integrante. Excepciones del pliego:
- sin pasivo corriente, la liquidez se da por cumplida;
- sin gastos de intereses, la cobertura se da por cumplida si la utilidad
  operacional es mayor o igual a cero.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from motor.financiera.parametros import LoteFinanciero, Umbrales
from motor.tecnica.experiencia import IntegranteTecnico
from motor.tecnica.rup import normalizar


@dataclass
class Indicadores:
    activo_corriente: float
    activo_total: float
    pasivo_corriente: float
    pasivo_total: float
    patrimonio: float
    utilidad_operacional: float
    gastos_intereses: float

    @property
    def creibles(self) -> bool:
        """Las cifras del RUP tienen sentido.

        Un activo, un pasivo o unos gastos de intereses negativos no existen:
        salen de una lectura mala (los estados financieros escriben los
        negativos entre paréntesis y una lectura distraída los convierte en
        números con signo). Y eso no es inocuo: con activo y pasivo negativos
        los indicadores salen excelentes —dos negativos dan una liquidez de
        2,0— y el proponente quedaría aprobado con cifras inventadas. El
        patrimonio y la utilidad operacional sí pueden ser negativos."""
        return all(v >= 0 for v in (self.activo_corriente, self.activo_total, self.pasivo_corriente,
                                    self.pasivo_total, self.gastos_intereses))

    @property
    def liquidez(self) -> float | None:  # None = indeterminado (sin pasivo corriente)
        return self.activo_corriente / self.pasivo_corriente if self.pasivo_corriente else None

    @property
    def endeudamiento(self) -> float | None:
        return self.pasivo_total / self.activo_total if self.activo_total else None

    @property
    def cobertura(self) -> float | None:  # None = indeterminado (sin gastos de intereses)
        return self.utilidad_operacional / self.gastos_intereses if self.gastos_intereses else None

    @property
    def capital_de_trabajo(self) -> float:
        return self.activo_corriente - self.pasivo_corriente

    @property
    def roa(self) -> float | None:
        return self.utilidad_operacional / self.activo_total if self.activo_total else None

    @property
    def roe(self) -> float | None:
        return self.utilidad_operacional / self.patrimonio if self.patrimonio > 0 else None


@dataclass
class Revision:
    """Resultado de una verificación: cumple (True), no se pudo verificar o no
    cumple (False, a revisión) y el motivo."""
    cumple: bool
    motivos: list[str] = field(default_factory=list)
    detalle: dict = field(default_factory=dict)


def indicadores_del_proponente(integrantes: list[IntegranteTecnico]) -> tuple[Indicadores | None, list[str]]:
    faltan = [i.nombre for i in integrantes if i.rup is None or i.rup.financiera is None or not i.rup.financiera.completa]
    if not integrantes:
        return None, ["no se identificaron los integrantes del proponente"]
    if faltan:
        return None, [f"no se leyó la información financiera del RUP de: {', '.join(faltan)}"]
    campos = ("activo_corriente", "activo_total", "pasivo_corriente", "pasivo_total", "patrimonio",
              "utilidad_operacional", "gastos_intereses")
    return Indicadores(**{c: sum(getattr(i.rup.financiera, c) for i in integrantes) for c in campos}), []


def _f(v: float | None, dec: int = 3) -> str:
    return "indeterminado" if v is None else f"{v:,.{dec}f}"


def capacidad_financiera(ind: Indicadores | None, umbrales: Umbrales, avisos: list[str]) -> Revision:
    """3.6: liquidez, endeudamiento y cobertura de intereses."""
    if ind is None:
        return Revision(False, avisos)
    if not ind.creibles:
        return Revision(False, ["la información financiera del RUP tiene cifras imposibles (activos, pasivos o gastos "
                                "de intereses negativos): no se pudo leer bien, revísala en el documento"])
    detalle = {"liquidez": ind.liquidez, "endeudamiento": ind.endeudamiento, "cobertura": ind.cobertura}
    if not umbrales.completos:
        return Revision(False, [
            f"liquidez {_f(ind.liquidez)}, endeudamiento {_f(ind.endeudamiento)}, cobertura {_f(ind.cobertura, 2)}: "
            "falta registrar los umbrales de la Matriz 2 del proceso para decidir"
        ], detalle)
    faltas = []
    if ind.liquidez is not None and ind.liquidez < umbrales.liquidez_min:
        faltas.append(f"liquidez {_f(ind.liquidez)} (mínimo {umbrales.liquidez_min:g})")
    if ind.endeudamiento is None or ind.endeudamiento > umbrales.endeudamiento_max:
        faltas.append(f"endeudamiento {_f(ind.endeudamiento)} (máximo {umbrales.endeudamiento_max:g})")
    if ind.cobertura is None:
        if ind.utilidad_operacional < 0:
            faltas.append("sin gastos de intereses pero con utilidad operacional negativa")
    elif ind.cobertura < umbrales.cobertura_min:
        faltas.append(f"cobertura de intereses {_f(ind.cobertura, 2)} (mínimo {umbrales.cobertura_min:g})")
    resumen = (f"liquidez {_f(ind.liquidez)} (≥ {umbrales.liquidez_min:g}), endeudamiento {_f(ind.endeudamiento)} "
               f"(≤ {umbrales.endeudamiento_max:g}), cobertura {_f(ind.cobertura, 2)} (≥ {umbrales.cobertura_min:g})")
    if faltas:
        return Revision(False, [f"no alcanza: {'; '.join(faltas)}. {resumen}"], detalle)
    return Revision(True, [resumen], detalle)


def capacidad_organizacional(ind: Indicadores | None, umbrales: Umbrales, avisos: list[str]) -> Revision:
    """3.9: rentabilidad del activo y del patrimonio."""
    if ind is None:
        return Revision(False, avisos)
    if not ind.creibles:
        return Revision(False, ["la información financiera del RUP tiene cifras imposibles (activos, pasivos o gastos "
                                "de intereses negativos): no se pudo leer bien, revísala en el documento"])
    detalle = {"roa": ind.roa, "roe": ind.roe}
    if not umbrales.completos:
        return Revision(False, [
            f"rentabilidad del activo {_f(ind.roa)}, del patrimonio {_f(ind.roe)}: falta registrar los umbrales de la Matriz 2"
        ], detalle)
    faltas = []
    if ind.roa is None or ind.roa < umbrales.roa_min:
        faltas.append(f"rentabilidad del activo {_f(ind.roa)} (mínimo {umbrales.roa_min:g})")
    if ind.roe is None or ind.roe < umbrales.roe_min:
        faltas.append(f"rentabilidad del patrimonio {_f(ind.roe)} (mínimo {umbrales.roe_min:g})")
    resumen = f"rentabilidad del activo {_f(ind.roa)} (≥ {umbrales.roa_min:g}), del patrimonio {_f(ind.roe)} (≥ {umbrales.roe_min:g})"
    if faltas:
        return Revision(False, [f"no alcanza: {'; '.join(faltas)}. {resumen}"], detalle)
    return Revision(True, [resumen], detalle)


def capital_de_trabajo(ind: Indicadores | None, lote: LoteFinanciero, avisos: list[str]) -> Revision:
    """3.7, por lote: AC − PC ≥ capital de trabajo demandado del lote."""
    if ind is None:
        return Revision(False, avisos)
    if not ind.creibles:
        return Revision(False, ["la información financiera del RUP tiene cifras imposibles: revísala en el documento"])
    demandado = lote.capital_de_trabajo_demandado
    detalle = {"capital_de_trabajo": ind.capital_de_trabajo, "demandado": demandado}
    if demandado is None:
        return Revision(False, ["no se pudo calcular el capital de trabajo demandado (falta el plazo o el anticipo del lote)"], detalle)
    texto = f"capital de trabajo ${ind.capital_de_trabajo:,.0f}; se exige ${demandado:,.0f} para el {lote.nombre.lower()}"
    if ind.capital_de_trabajo < demandado:
        return Revision(False, [f"no alcanza: {texto}"], detalle)
    return Revision(True, [texto], detalle)


def _lotes_de_la_carta(pdfs: dict[str, bytes], numeros: set[str]) -> set[str]:
    """Los lotes que copia el objeto de la carta de presentación (quien se
    presenta a un solo lote copia solo ese)."""
    from motor.evaluacion.formato1 import encontrar_formato1
    from motor.evaluacion.garantia import _numeros_de_lote
    from motor.procesamiento.pdf_utils import extraer_texto

    encontrado = encontrar_formato1(pdfs)
    if encontrado is None:
        return set()
    texto = normalizar(" ".join(extraer_texto(encontrado[1], max_paginas=2).split()))
    inicio = texto.find("OBJETO")
    if inicio < 0:
        return set()
    fin = texto.find("SENORES", inicio)
    tramo = texto[inicio: fin if fin > inicio else inicio + 2500]
    tramo = re.sub(r"LOTE(\d)", r"LOTE \1", tramo)  # "LOTE2:"
    return _numeros_de_lote(tramo) & numeros


def _lotes_de_la_poliza(pdfs: dict[str, bytes], numeros: set[str]) -> set[str]:
    """Los lotes que nombra la garantía de seriedad de la oferta."""
    from motor.evaluacion.garantia import _numeros_de_lote, encontrar_poliza

    try:
        encontrada = encontrar_poliza(pdfs)
    except Exception:  # noqa: BLE001 — una póliza ilegible no puede tumbar la evaluación
        return set()
    if encontrada is None:
        return set()
    return _numeros_de_lote(normalizar(" ".join(encontrada[1].split()))) & numeros


def lotes_de_la_oferta(pdfs: dict[str, bytes], numeros: list[str]) -> tuple[set[str] | None, list[str]]:
    """(números de lote a los que se presenta, avisos). None si no se pudo
    identificar con ninguna fuente: entonces se evalúan todos.

    Se toma la UNIÓN de lo que dicen la carta de presentación y la garantía de
    seriedad, no solo la carta. La razón es cuál es el daño de equivocarse: un
    lote que no se identifica se marca «N.A. — no se presenta a este lote» y se
    da por cumplido sin mirar nada, así que una sola lectura fallida aprobaría
    un lote entero sin verificarlo. Con la unión, eso exige que fallen las dos
    fuentes, y cuando discrepan se dice."""
    del_proceso = set(numeros)
    carta = _lotes_de_la_carta(pdfs, del_proceso)
    poliza = _lotes_de_la_poliza(pdfs, del_proceso)
    avisos: list[str] = []
    solo_en_la_poliza = poliza - carta
    if carta and solo_en_la_poliza:
        avisos.append(
            "la carta de presentación nombra el lote " + ", ".join(sorted(carta))
            + " y la garantía de seriedad el " + ", ".join(sorted(solo_en_la_poliza))
            + ": se evalúan todos, confirma a cuáles se presenta"
        )
    elegidos = carta | poliza
    return (elegidos or None), avisos
