"""Factor económico de un proceso (RF-11) y alerta de ofertas artificialmente
bajas (RF-13).

Nada se califica mientras quede algo sin confirmar: el valor corregido de
cada oferta (lo propone la verificación aritmética, lo confirma una persona),
la respuesta a cada alerta de oferta baja, los parámetros del pliego y la TRM.
La calificación la confirma una persona y queda con su nombre.
"""
from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from evaluaciones.models import Evaluacion, FactorEconomico, OfertaEconomica, Proceso, Resultado, Revision
from motor.economica import ponderacion as p


def factores(proceso: Proceso) -> list[FactorEconomico]:
    """Uno por lote del documento base (o uno solo si no tiene lotes)."""
    lotes = [l.get("numero", "") for l in (proceso.documento_base or {}).get("lotes") or []] or [""]
    presupuestos = {l.get("numero", ""): l.get("valor_presupuesto") for l in (proceso.documento_base or {}).get("lotes") or []}
    for orden, lote in enumerate(lotes, 1):
        FactorEconomico.objects.get_or_create(
            proceso=proceso, lote=lote,
            defaults={"entidad_id": proceso.entidad_id, "orden": orden,
                      "presupuesto_oficial": Decimal(str(presupuestos[lote])) if presupuestos.get(lote) else None},
        )
    return list(proceso.factores_economicos.prefetch_related("ofertas__proponente").all())


def habilitacion(proceso: Proceso) -> dict[str, str]:
    """Si cada proponente quedó habilitado en todas las evaluaciones del proceso:
    «habilitado», «no_habilitado» (algún requisito quedó «no cumple» en la
    decisión final) o «pendiente» (falta evaluarlo o queda algo en revisión).
    Solo se califica la oferta económica de quien quedó habilitado."""
    ev_ids = list(Evaluacion.objects.filter(proceso=proceso).values_list("id", flat=True))
    resultados = Resultado.objects.filter(evaluacion_id__in=ev_ids).values("evaluacion_id", "proponente_id", "requisito", "requiere_revision", "datos__cumple")
    final = {(v["evaluacion_id"], v["proponente_id"], v["requisito"]): v["cumple"]
             for v in Revision.objects.filter(evaluacion_id__in=ev_ids).values("evaluacion_id", "proponente_id", "requisito", "cumple")}
    evaluado: dict[str, set] = {}
    estado: dict[str, str] = {}
    for r in resultados:
        pid = str(r["proponente_id"])
        evaluado.setdefault(pid, set()).add(r["evaluacion_id"])
        clave = (r["evaluacion_id"], r["proponente_id"], r["requisito"])
        if clave in final:
            cumple, pendiente = final[clave], False
        else:
            cumple, pendiente = r["datos__cumple"], r["requiere_revision"]
        if cumple is False and not pendiente:
            estado[pid] = "no_habilitado"
        elif pendiente and estado.get(pid) != "no_habilitado":
            estado[pid] = "pendiente"
    salida = {}
    for x in proceso.proponentes.values_list("id", flat=True):
        pid = str(x)
        if not ev_ids or evaluado.get(pid, set()) != set(ev_ids):
            salida[pid] = estado.get(pid) if estado.get(pid) == "no_habilitado" else "pendiente"
        else:
            salida[pid] = estado.get(pid, "habilitado")
    return salida


def _validas(f: FactorEconomico) -> list[OfertaEconomica]:
    return [o for o in f.ofertas.all() if o.estado == OfertaEconomica.VALIDA]


def analisis_bajas(f: FactorEconomico) -> p.AnalisisBajas | None:
    """Sobre el valor corregido confirmado (o el ofertado mientras tanto) de las ofertas válidas."""
    validas = _validas(f)
    if not validas:
        return None
    valores = {str(o.id): float(o.valor_corregido or o.valor_ofertado) for o in validas}
    costo = f.costo_estimado or f.presupuesto_oficial
    return p.ofertas_bajas(valores, float(costo) if costo else None)


def por_confirmar(f: FactorEconomico) -> list[str]:
    faltan: list[str] = []
    if f.puntaje_maximo is None:
        faltan.append("Registrar el puntaje máximo del factor económico que fija el pliego.")
    if f.trm is None or f.fecha_trm is None:
        faltan.append("Registrar la TRM y su fecha, según la regla del pliego.")
    validas = _validas(f)
    if not validas:
        faltan.append("Registrar al menos una oferta económica válida.")
    habil = habilitacion(f.proceso)
    no_habilitadas = [o.proponente.hoja for o in validas if habil.get(str(o.proponente_id)) == "no_habilitado"]
    if no_habilitadas:
        faltan.append(f"Rechazar las ofertas de quienes no quedaron habilitados ({', '.join(no_habilitadas)}): solo se califica a los habilitados.")
    pendientes = [o.proponente.hoja for o in validas if habil.get(str(o.proponente_id), "pendiente") == "pendiente"]
    if pendientes:
        faltan.append(f"Terminar la evaluación de los requisitos habilitantes de {', '.join(pendientes)} (falta evaluar o queda algo en revisión).")
    sin_corregir = [o for o in validas if o.valor_corregido is None]
    if sin_corregir:
        faltan.append(f"Confirmar el valor corregido de {len(sin_corregir)} ofertas (verificación aritmética).")
    bajas = analisis_bajas(f)
    if bajas and not sin_corregir:
        sin_resolver = [a for a in bajas.alertas if next(o for o in validas if str(o.id) == a.clave).justificacion != OfertaEconomica.ACEPTADA]
        if sin_resolver:
            faltan.append(f"Resolver {len(sin_resolver)} ofertas que pueden ser artificialmente bajas: aceptar su justificación o rechazarlas.")
    if (f.tabla_metodos == FactorEconomico.ANTERIORES or f.trm is not None) and f.presupuesto_oficial is None:
        try:
            if metodo(f) == p.MEDIA_GEOMETRICA_PRESUPUESTO:
                faltan.append("Registrar el presupuesto oficial (lo usa la media geométrica con presupuesto oficial).")
        except p.ErrorPonderacion:
            pass
    return faltan


def metodo(f: FactorEconomico) -> str | None:
    if f.trm is None:
        return None
    rangos = p.RANGOS_ANTERIORES if f.tabla_metodos == FactorEconomico.ANTERIORES else p.RANGOS_VIGENTES
    return p.metodo_por_trm(f.trm, rangos, f.orden)


def calificar(f: FactorEconomico, usuario) -> dict:
    faltan = por_confirmar(f)
    if faltan:
        raise p.ErrorPonderacion("Antes de calificar falta: " + " ".join(faltan))
    m = metodo(f)
    validas = _validas(f)
    c = p.calificar({str(o.id): float(o.valor_corregido) for o in validas}, m, float(f.puntaje_maximo),
                    float(f.presupuesto_oficial) if f.presupuesto_oficial else None)
    f.calificacion = {
        "metodo": m, "metodo_nombre": p.NOMBRES[m], "referencia": c.referencia, "explicacion": c.explicacion,
        "centavos_trm": p.centavos(f.trm), "trm": str(f.trm), "fecha_trm": f.fecha_trm.isoformat(),
        "puntajes": [
            {"proponente": o.proponente.nombre, "hoja": o.proponente.hoja, "valor": str(o.valor_corregido), "puntaje": c.puntajes[str(o.id)]}
            for o in sorted(validas, key=lambda o: -c.puntajes[str(o.id)])
        ],
    }
    f.confirmada_por, f.confirmada_en = usuario, timezone.now()
    f.save(update_fields=["calificacion", "confirmada_por", "confirmada_en"])
    return f.calificacion


def anular_calificacion(f: FactorEconomico) -> None:
    """Cualquier cambio en los datos deja sin efecto la calificación confirmada."""
    if f.calificacion is not None:
        f.calificacion, f.confirmada_por, f.confirmada_en = None, None, None
        f.save(update_fields=["calificacion", "confirmada_por", "confirmada_en"])
