"""Evaluación financiera de un proponente, lote por lote (pliego 3.6 a 3.11).

Se habilita en un lote si cumple, con la información del RUP, la capacidad
financiera (liquidez, endeudamiento, cobertura), la organizacional (ROA,
ROE), el capital de trabajo del lote, la validez de los documentos de la
capacidad de organización y la capacidad residual.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from motor.financiera.capacidad import (
    Indicadores, Revision, capacidad_financiera, capacidad_organizacional, capital_de_trabajo,
    indicadores_del_proponente, lotes_de_la_oferta,
)
from motor.financiera.contadores import documentos_financieros, validez_capacidad_organizacional
from motor.financiera.parametros import ParametrosFinancieros
from motor.financiera.residual import residual_del_proponente
from motor.evaluacion.proponente_plural import integrantes_formato2
from motor.tecnica.experiencia import IntegranteTecnico
from motor.tecnica.proponente import _PLURAL_RE, integrantes_del_proponente, leer_rups
from motor.tecnica.rup import normalizar


@dataclass
class ResultadoFinanciero:
    lotes_presentados: list[str] = field(default_factory=list)
    integrantes: list[IntegranteTecnico] = field(default_factory=list)
    indicadores: Indicadores | None = None
    financiera: Revision | None = None
    organizacional: Revision | None = None
    validez: Revision | None = None
    capital_por_lote: dict[str, Revision] = field(default_factory=dict)
    residual: Revision | None = None
    avisos: list[str] = field(default_factory=list)


def evaluar_proponente_financiero(
    pdfs: dict[str, bytes], excels: dict[str, bytes], nombre_proponente: str, parametros: ParametrosFinancieros,
    fecha_cierre: date, codigo_proceso: str | None = None,
) -> ResultadoFinanciero:
    resultado = ResultadoFinanciero()
    rups = leer_rups(pdfs)
    plural = bool(_PLURAL_RE.match(normalizar(nombre_proponente))) or len(integrantes_formato2(pdfs, codigo_proceso)) >= 2
    integrantes, avisos = integrantes_del_proponente(pdfs, rups, plural, codigo_proceso)
    sin_confirmar = (
        ["del pliego se leyó con IA y falta confirmar: " + "; ".join(parametros.sin_confirmar[:4])]
        if parametros.sin_confirmar else []
    )
    if parametros.requisitos_sin_verificar:
        sin_confirmar.append(
            f"el pliego exige {len(parametros.requisitos_sin_verificar)} requisito(s) financiero(s) que el programa "
            "no verifica; revísalos: " + "; ".join(parametros.requisitos_sin_verificar[:3])
        )
    resultado.integrantes, resultado.avisos = integrantes, [*avisos, *parametros.avisos, *sin_confirmar]
    numeros = [m.group(0) for l in parametros.lotes if (m := re.search(r"\d+", l.nombre))]
    elegidos = lotes_de_la_oferta(pdfs, numeros) if len(parametros.lotes) > 1 else None
    if len(parametros.lotes) > 1 and elegidos is None:
        resultado.avisos.append("no se identificó en la carta a qué lotes se presenta: se evalúan todos")
    def _numero_del_lote(nombre: str) -> str | None:
        m = re.search(r"\d+", nombre)
        return m.group(0) if m else None

    lotes = [l for l in parametros.lotes if elegidos is None or _numero_del_lote(l.nombre) in elegidos]
    resultado.lotes_presentados = [l.nombre for l in lotes]
    ind, faltas = indicadores_del_proponente(integrantes)
    resultado.indicadores = ind
    resultado.financiera = capacidad_financiera(ind, parametros.umbrales, faltas)
    resultado.organizacional = capacidad_organizacional(ind, parametros.umbrales, faltas)
    docs = documentos_financieros(pdfs)
    resultado.validez = validez_capacidad_organizacional(integrantes, docs, fecha_cierre)
    for lote in lotes:
        resultado.capital_por_lote[lote.nombre] = capital_de_trabajo(ind, lote, faltas)
    resultado.residual = residual_del_proponente(pdfs, excels, integrantes, lotes, parametros.smmlv, plural, docs.estados, docs.completos)
    return resultado


def cumple_lote(resultado: ResultadoFinanciero, lote: str) -> bool | None:
    """None si no se presenta al lote."""
    if lote not in resultado.lotes_presentados:
        return None
    residual = resultado.residual
    cubierto = residual is not None and residual.cumple or (
        residual is not None and lote in (residual.detalle or {}).get("lotes_cubiertos", [])
    )
    partes = [resultado.financiera, resultado.organizacional, resultado.validez, resultado.capital_por_lote.get(lote)]
    return all(p is not None and p.cumple for p in partes) and bool(cubierto) and not resultado.avisos
