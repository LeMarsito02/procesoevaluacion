"""Adopción del puntaje técnico, proponente por proponente.

El puntaje es evaluación en sentido estricto (art. 5, num. 2, Ley 1150 de 2007):
no se adopta por muestra. El sistema calcula un puntaje preliminar con los
factores del pliego; el evaluador técnico lo adopta para cada proponente (o
lo ajusta revisando el factor que corresponda). Una adopción deja de valer si
después cambia cualquier factor del puntaje de ese proponente.
"""
from __future__ import annotations

from evaluaciones.models import AdopcionPuntaje, Evaluacion, Proponente, Resultado, Revision


def _puntajes(evaluacion: Evaluacion) -> dict[str, tuple[float | str, dict]]:
    """Por hoja: (puntaje preliminar o PENDIENTE, puntos por factor)."""
    from evaluaciones.cumplimiento import numeros_puntaje
    from evaluaciones.servicios import _resultados_para_informe, definicion_de
    from motor.consolidado import _puntaje
    from motor.tecnica.informe import OBRAS_INCONCLUSAS, _puntos, _reduccion

    numeros = numeros_puntaje(definicion_de(evaluacion))
    resultados = _resultados_para_informe(evaluacion)
    hojas = sorted({h for h, _ in resultados})
    salida = {}
    for hoja in hojas:
        detalle = {}
        for n in sorted(numeros):
            r = resultados.get((hoja, n))
            if r is None:
                continue
            detalle[str(n)] = _reduccion(r) if n == OBRAS_INCONCLUSAS else _puntos(r)
        salida[hoja] = (_puntaje(resultados, hoja), detalle)
    return salida


def tiene_puntaje(evaluacion: Evaluacion) -> bool:
    from evaluaciones.cumplimiento import numeros_puntaje
    from evaluaciones.servicios import definicion_de

    return evaluacion.tipo == "tecnica" and bool(numeros_puntaje(definicion_de(evaluacion)))


def _ultimo_cambio(evaluacion: Evaluacion, proponente: Proponente):
    """Fecha del último cambio en los factores de puntaje de un proponente."""
    from django.db.models import Max

    from evaluaciones.cumplimiento import numeros_puntaje
    from evaluaciones.servicios import definicion_de

    numeros = numeros_puntaje(definicion_de(evaluacion))
    fechas = [
        Resultado.objects.filter(evaluacion=evaluacion, proponente=proponente, requisito__in=numeros).aggregate(m=Max("evaluado_en"))["m"],
        Revision.objects.filter(evaluacion=evaluacion, proponente=proponente, requisito__in=numeros).aggregate(m=Max("fecha"))["m"],
    ]
    fechas = [f for f in fechas if f is not None]
    return max(fechas) if fechas else None


def estado_puntajes(evaluacion: Evaluacion) -> list[dict]:
    """Puntaje preliminar de cada proponente y si ya lo adoptó una persona."""
    from motor.tecnica.informe import PENDIENTE

    puntajes = _puntajes(evaluacion)
    adopciones = {a.proponente_id: a for a in AdopcionPuntaje.objects.filter(evaluacion=evaluacion).select_related("usuario")}
    salida = []
    for p in evaluacion.proceso.proponentes.order_by("numero_orden"):
        puntaje, detalle = puntajes.get(p.hoja, (PENDIENTE, {}))
        a = adopciones.get(p.id)
        vigente = False
        if a is not None and puntaje != PENDIENTE:
            cambio = _ultimo_cambio(evaluacion, p)
            vigente = abs(float(puntaje) - a.puntaje) < 1e-9 and (cambio is None or cambio <= a.fecha)
        salida.append(
            {
                "proponente_id": str(p.id),
                "hoja": p.hoja,
                "nombre": p.nombre,
                "puntaje": None if puntaje == PENDIENTE else float(puntaje),
                "resuelto": puntaje != PENDIENTE,
                "detalle": detalle,
                "adoptado": vigente,
                "adoptado_por": a.usuario.nombre_completo if (a and vigente) else None,
                "adoptado_en": a.fecha.isoformat() if (a and vigente) else None,
                "adopcion_desactualizada": a is not None and not vigente,
            }
        )
    return salida


def adoptar(evaluacion: Evaluacion, proponente: Proponente, usuario, nota: str = "") -> AdopcionPuntaje:
    from motor.tecnica.informe import PENDIENTE

    puntaje, detalle = _puntajes(evaluacion).get(proponente.hoja, (PENDIENTE, {}))
    if puntaje == PENDIENTE:
        raise ValueError("El puntaje de este proponente tiene factores pendientes: resuélvalos antes de adoptarlo.")
    adopcion, _ = AdopcionPuntaje.objects.update_or_create(
        evaluacion=evaluacion,
        proponente=proponente,
        defaults={
            "entidad_id": evaluacion.entidad_id,
            "puntaje": float(puntaje),
            "detalle": detalle,
            "nota": nota.strip(),
            "usuario": usuario,
        },
    )
    return adopcion


def adopciones_vigentes(evaluacion: Evaluacion) -> list[Proponente]:
    vigentes = {e["proponente_id"] for e in estado_puntajes(evaluacion) if e["adoptado"]}
    return [p for p in evaluacion.proceso.proponentes.all() if str(p.id) in vigentes]


def sin_adoptar(evaluacion: Evaluacion) -> list[str]:
    """Hojas con puntaje resuelto que nadie ha adoptado (o cuya adopción quedó vieja)."""
    return [e["hoja"] for e in estado_puntajes(evaluacion) if e["resuelto"] and not e["adoptado"]]
