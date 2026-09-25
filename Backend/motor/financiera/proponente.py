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
from motor.tecnica.experiencia import IntegranteTecnico, PuntoDeRevision
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
    # Lo que solo explica cómo se evaluó (con qué tabla de la Matriz 2, por
    # ejemplo). No frena nada: un aviso frena la aprobación, una explicación no,
    # y confundirlos deja sin aprobar a quien cumplía todo.
    explicaciones: list[str] = field(default_factory=list)
    # Lo mismo que los avisos, pero separado por ámbito: lo que sale del pliego
    # se resuelve una vez para todos los proponentes y lo de la oferta hay que
    # mirarlo en esta. Ninguno de los dos aprueba solo.
    revisiones: list[PuntoDeRevision] = field(default_factory=list)

    @property
    def revisiones_del_proceso(self) -> list[PuntoDeRevision]:
        return [r for r in self.revisiones if r.ambito == "proceso"]

    @property
    def revisiones_de_la_oferta(self) -> list[PuntoDeRevision]:
        return [r for r in self.revisiones if r.ambito == "oferta"]


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
    if parametros.permisos_del_pliego:
        # Ni frena la aprobación ni es un punto por resolver: el pliego permite
        # más de lo que el programa aplica, y eso solo puede perjudicar al
        # proponente. Va como explicación, para que nadie se rechace por omisión.
        explicaciones_permisos = [
            f"antes de rechazar, mira que el pliego admite {len(parametros.permisos_del_pliego)} forma(s) de "
            "acreditar que el programa no aplica: " + "; ".join(parametros.permisos_del_pliego[:2])
        ]
    else:
        explicaciones_permisos = []
    resultado.integrantes, resultado.avisos = integrantes, [*avisos, *parametros.avisos, *sin_confirmar]
    # Los avisos del pliego (lo leído con IA sin confirmar, los requisitos que
    # el motor no verifica, lo que las reglas no pudieron leer) son del proceso.
    resultado.revisiones = [
        *(PuntoDeRevision(f"integrantes_{i}", "oferta", a) for i, a in enumerate(avisos)),
        *(PuntoDeRevision(f"pliego_{i}", "proceso", a) for i, a in enumerate([*parametros.avisos, *sin_confirmar])),
    ]
    resultado.explicaciones.extend(explicaciones_permisos)
    numeros = [m.group(0) for l in parametros.lotes if (m := re.search(r"\d+", l.nombre))]
    elegidos, avisos_lotes = lotes_de_la_oferta(pdfs, numeros) if len(parametros.lotes) > 1 else (None, [])
    resultado.avisos.extend(avisos_lotes)
    resultado.revisiones.extend(PuntoDeRevision(f"lotes_{i}", "oferta", a) for i, a in enumerate(avisos_lotes))
    if len(parametros.lotes) > 1 and elegidos is None:
        resultado.avisos.append("no se identificó en la carta ni en la garantía a qué lotes se presenta: se evalúan todos")
    def _numero_del_lote(nombre: str) -> str | None:
        m = re.search(r"\d+", nombre)
        return m.group(0) if m else None

    lotes = [l for l in parametros.lotes if elegidos is None or _numero_del_lote(l.nombre) in elegidos]
    resultado.lotes_presentados = [l.nombre for l in lotes]
    ind, faltas = indicadores_del_proponente(integrantes)
    resultado.indicadores = ind
    umbrales = _umbrales_del_proponente(parametros, integrantes, plural, resultado)
    resultado.financiera = capacidad_financiera(ind, umbrales, faltas)
    resultado.organizacional = capacidad_organizacional(ind, umbrales, faltas)
    docs = documentos_financieros(pdfs)
    resultado.validez = validez_capacidad_organizacional(integrantes, docs, fecha_cierre)
    # Cada cosa que falta de la validez es su propio punto de revisión, con su
    # evidencia: así quien revisa mira ese certificado y no la oferta entera.
    if not resultado.validez.cumple:
        for i, motivo in enumerate(resultado.validez.motivos):
            if "vigentes al cierre" in motivo:
                continue  # lo que sí está bien no es un punto por revisar
            resultado.revisiones.append(PuntoDeRevision(f"validez_{i}", "oferta", motivo))
    for lote in lotes:
        resultado.capital_por_lote[lote.nombre] = capital_de_trabajo(ind, lote, faltas)
    resultado.residual = residual_del_proponente(pdfs, excels, integrantes, lotes, parametros.smmlv, plural, docs.estados, docs.completos)
    return resultado


def _umbrales_del_proponente(parametros: ParametrosFinancieros, integrantes: list[IntegranteTecnico],
                             plural: bool, resultado: ResultadoFinanciero):
    """Los indicadores que le aplican a ESTE proponente.

    La Matriz 2 reserva unos más laxos a quien acredite ser Mipyme, y eso no es
    del proceso sino del proponente: lo dice el tamaño de empresa de su RUP. En
    proponentes plurales basta con un integrante Mipyme que tenga al menos el
    10 % de participación, que es la misma regla del puntaje del documento tipo
    (4.7).

    Los dos errores cuestan: aplicárselos a todos aprueba a quien no cumple; no
    aplicárselos a quien los tiene rechaza a quien sí cumplía. Así que se decide
    con el RUP y se deja dicho por qué."""
    if parametros.umbrales_mipyme is None:
        return parametros.umbrales
    for i in integrantes:
        if i.rup is None or not i.rup.es_mipyme:
            continue
        if plural and (i.participacion is None or i.participacion < 0.10 - 1e-9):
            continue
        resultado.explicaciones.append(
            f"se evalúa con los indicadores que la Matriz 2 reserva a los proponentes Mipyme porque "
            f"{i.nombre} es {i.rup.tamano_empresa.lower()} según su RUP"
            + (f" y tiene el {i.participacion * 100:.0f} % de participación" if plural and i.participacion else "")
        )
        return parametros.umbrales_mipyme
    sin_rup = [i.nombre for i in integrantes if i.rup is None]
    if sin_rup:
        # Sin el RUP no se sabe el tamaño de empresa. Se usan los indicadores
        # generales, que son los más exigentes, y se dice: si resulta que era
        # Mipyme, se le estaría exigiendo más de lo que el pliego le exige.
        resultado.explicaciones.append(
            "no se leyó el RUP de " + ", ".join(sin_rup) + ", así que no se sabe si acredita ser Mipyme: se evalúa con "
            "los indicadores de los demás proponentes, que son los más exigentes"
        )
    return parametros.umbrales


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


def capacidad_acreditada(resultado: ResultadoFinanciero, lote: str) -> bool:
    """La capacidad financiera del proponente quedó acreditada con lo que trae
    su oferta y lo único que falta sale del pliego —igual para todos—. Sirve
    para dirigir la revisión: quien revisa mira el pliego una vez en vez de
    volver a los estados financieros de cada proponente. No aprueba nada por su
    cuenta: el lote sigue sin cumplir hasta que eso del pliego se resuelva."""
    if lote not in resultado.lotes_presentados:
        return False
    residual = resultado.residual
    cubierto = residual is not None and residual.cumple or (
        residual is not None and lote in (residual.detalle or {}).get("lotes_cubiertos", [])
    )
    partes = [resultado.financiera, resultado.organizacional, resultado.validez, resultado.capital_por_lote.get(lote)]
    return (all(p is not None and p.cumple for p in partes) and bool(cubierto)
            and not resultado.revisiones_de_la_oferta)
