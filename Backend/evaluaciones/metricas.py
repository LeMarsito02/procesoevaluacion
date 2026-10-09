"""Métricas de uso de MiEvaluador por entidad (tablero para el administrador
de la entidad y el superadministrador).

Todo sale de los datos de operación (procesos, resultados, revisiones,
muestras de control y fila de trabajos), filtrado por año y mes de creación
del proceso. Son cifras agregadas: no incluyen nombres de proponentes ni
códigos de proceso.

Definiciones:
- Verificación: un requisito evaluado para una oferta en un área.
- Verificada por el sistema: el sistema la decidió con su soporte, sin que
  quedara pendiente para una persona (no requiere revisión).
- Corrección: una persona cambió la decisión que había tomado el sistema.
- Tiempo por oferta: tiempo de máquina de cada oferta en la fila (no cuenta
  los procesos de demostración, que restauran resultados ya calculados).
- Horas ahorradas: estimación con los minutos que tarda una persona en una
  verificación de cada área (los mismos supuestos de la medición).
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from django.db.models import Q

from evaluaciones.models import (
    DocumentoAportado,
    EstadoEvaluacion,
    EstadoTrabajo,
    Evaluacion,
    ItemMuestra,
    MuestraControl,
    ObservacionInforme,
    Proceso,
    Proponente,
    Resultado,
    Revision,
    Trabajo,
)
from evaluaciones.tipos import TIPOS

MINUTOS_POR_VERIFICACION = {"juridica": 6.0, "tecnica": 10.0, "financiera": 15.0}
MODALIDADES = {"interventoria": "Interventorías", "obra": "Obras", "otra": "Otras modalidades"}


def modalidad_de(proceso: Proceso) -> str:
    """Interventoría u obra, según lo que leyó el motor del pliego; si no lo
    leyó, por el código del proceso (CM = concurso de méritos, LP = licitación)."""
    modalidad = (proceso.documento_base or {}).get("modalidad") or ""
    if modalidad.startswith("interventoria"):
        return "interventoria"
    if modalidad.startswith(("obra", "licitacion")):
        return "obra"
    codigo = proceso.codigo.upper()
    if "-CM-" in codigo:
        return "interventoria"
    if "-LP-" in codigo:
        return "obra"
    objeto = (proceso.objeto or (proceso.documento_base or {}).get("objeto_general") or "").upper()
    if "INTERVENTOR" in objeto:
        return "interventoria"
    if any(p in objeto for p in ("CONSTRUCCI", "OBRA", "PAVIMENT", "REHABILITACI")):
        return "obra"
    return "otra"


def _procesos(entidad_id, anio: int | None, mes: int | None):
    qs = Proceso.objects.all()
    if entidad_id:
        qs = qs.filter(entidad_id=entidad_id)
    if anio:
        qs = qs.filter(creado_en__year=anio)
    if mes:
        qs = qs.filter(creado_en__month=mes)
    return qs


def anios_disponibles(entidad_id) -> list[int]:
    qs = Proceso.objects.all()
    if entidad_id:
        qs = qs.filter(entidad_id=entidad_id)
    return sorted({d.year for d in qs.dates("creado_en", "year")}, reverse=True)


def calcular(entidad_id=None, anio: int | None = None, mes: int | None = None) -> dict:
    procesos = list(_procesos(entidad_id, anio, mes))
    ids = [p.id for p in procesos]
    evaluaciones = list(Evaluacion.objects.filter(proceso_id__in=ids).select_related("proceso"))
    ev_ids = [e.id for e in evaluaciones]
    resultados = list(
        Resultado.objects.filter(evaluacion_id__in=ev_ids).values(
            "evaluacion_id", "proponente_id", "requisito", "requiere_revision", "datos__cumple", "datos__archivo_evaluado"
        )
    )
    revisiones = list(Revision.objects.filter(evaluacion_id__in=ev_ids).values("evaluacion_id", "proponente_id", "requisito", "cumple"))
    tipo_de = {e.id: e.tipo for e in evaluaciones}

    # --- Procesos y proponentes por modalidad ---
    n_proponentes = Counter(Proponente.objects.filter(proceso_id__in=ids).values_list("proceso_id", flat=True))
    con_resultados = {r["evaluacion_id"] for r in resultados}
    procesos_evaluados = {e.proceso_id for e in evaluaciones if e.id in con_resultados}
    por_modalidad: dict[str, list[int]] = defaultdict(list)
    for p in procesos:
        if p.id in procesos_evaluados:
            por_modalidad[modalidad_de(p)].append(n_proponentes.get(p.id, 0))
    modalidades = [
        {
            "clave": clave,
            "nombre": nombre,
            "procesos": len(por_modalidad.get(clave, [])),
            "ofertas": sum(por_modalidad.get(clave, [])),
            "promedio_ofertas": round(statistics.mean(por_modalidad[clave]), 1) if por_modalidad.get(clave) else None,
        }
        for clave, nombre in MODALIDADES.items()
    ]

    # --- Revisión humana: correcciones al sistema ---
    decision_sistema = {(r["evaluacion_id"], r["proponente_id"], r["requisito"]): r["datos__cumple"] for r in resultados}
    correcciones = Counter()
    revisadas = Counter()
    for v in revisiones:
        tipo = tipo_de[v["evaluacion_id"]]
        revisadas[tipo] += 1
        sistema = decision_sistema.get((v["evaluacion_id"], v["proponente_id"], v["requisito"]))
        if sistema is not None and v["cumple"] is not None and bool(sistema) != bool(v["cumple"]):
            correcciones[tipo] += 1
    revisado = {(v["evaluacion_id"], v["proponente_id"], v["requisito"]) for v in revisiones}

    # --- Tiempos de máquina (sin procesos de demostración) ---
    trabajos = list(
        Trabajo.objects.filter(
            evaluacion_id__in=ev_ids, estado=EstadoTrabajo.TERMINADO, iniciado_en__isnull=False, terminado_en__isnull=False
        )
        .exclude(evaluacion__proceso__codigo__istartswith="DEMO-")
        .values("evaluacion_id", "iniciado_en", "terminado_en")
    )
    segundos_area: dict[str, list[float]] = defaultdict(list)
    for t in trabajos:
        segundos_area[tipo_de[t["evaluacion_id"]]].append((t["terminado_en"] - t["iniciado_en"]).total_seconds())

    # --- Por área ---
    areas = []
    pendientes_total = 0
    for clave, tipo in TIPOS.items():
        del_area = [r for r in resultados if tipo_de[r["evaluacion_id"]] == clave]
        evs = [e for e in evaluaciones if e.tipo == clave]
        automaticas = sum(1 for r in del_area if not r["requiere_revision"])
        pendientes = sum(
            1 for r in del_area if r["requiere_revision"] and (r["evaluacion_id"], r["proponente_id"], r["requisito"]) not in revisado
        )
        pendientes_total += pendientes
        segundos = segundos_area.get(clave, [])
        areas.append({
            "clave": clave,
            "nombre": tipo.nombre,
            "evaluaciones": len(evs),
            "evaluadas": sum(1 for e in evs if e.id in con_resultados),
            "aprobadas": sum(1 for e in evs if e.estado == EstadoEvaluacion.APROBADA),
            "ofertas": len({(r["evaluacion_id"], r["proponente_id"]) for r in del_area}),
            "verificaciones": len(del_area),
            "verificadas_sistema": automaticas,
            "porcentaje_sistema": automaticas / len(del_area) if del_area else None,
            "revisadas_personas": revisadas[clave],
            "correcciones": correcciones[clave],
            "pendientes": pendientes,
            "segundos_por_oferta": statistics.mean(segundos) if segundos else None,
            "horas_ahorradas": automaticas * MINUTOS_POR_VERIFICACION.get(clave, 0) / 60,
        })

    # --- Documentos ---
    soportes = {(r["proponente_id"], r["datos__archivo_evaluado"]) for r in resultados if r["datos__archivo_evaluado"]}
    aportados = DocumentoAportado.objects.filter(evaluacion_id__in=ev_ids).count()

    # --- Muestra de control ---
    muestras = MuestraControl.objects.filter(evaluacion_id__in=ev_ids).exclude(estado="anulada")
    items = ItemMuestra.objects.filter(muestra__in=muestras).exclude(Q(resultado="") | Q(resultado__isnull=True))
    conformes = items.filter(resultado=ItemMuestra.CONFORME).count()
    revisados_muestra = items.count()

    # --- Días hasta aprobar ---
    dias = [(e.aprobada_en - e.creada_en).total_seconds() / 86400 for e in evaluaciones if e.aprobada_en]

    # --- Serie mensual (procesos y ofertas por mes de creación) ---
    mensual = defaultdict(lambda: {"procesos": 0, "ofertas": 0})
    for p in procesos:
        m = p.creado_en.month
        mensual[m]["procesos"] += 1
        mensual[m]["ofertas"] += n_proponentes.get(p.id, 0)

    # --- Requisitos que más van a revisión ---
    causas = Counter()
    for r in resultados:
        if r["requiere_revision"]:
            causas[(tipo_de[r["evaluacion_id"]], r["requisito"])] += 1
    titulos = _titulos(evaluaciones)

    # --- Causales de rechazo: lo que quedó «no cumple» en la decisión final ---
    # (la de la persona si revisó; si no, la del sistema cuando no la dejó en
    # revisión). Un N.A. no es rechazo.
    final = {(v["evaluacion_id"], v["proponente_id"], v["requisito"]): v["cumple"] for v in revisiones}
    rechazos = Counter()
    ofertas_rechazadas = set()
    for r in resultados:
        clave = (r["evaluacion_id"], r["proponente_id"], r["requisito"])
        cumple = final[clave] if clave in final else (None if r["requiere_revision"] else r["datos__cumple"])
        if cumple is False:
            rechazos[(tipo_de[r["evaluacion_id"]], r["requisito"])] += 1
            ofertas_rechazadas.add((r["evaluacion_id"], r["proponente_id"]))

    # --- Traslado del informe: observaciones ---
    observaciones = list(ObservacionInforme.objects.filter(evaluacion_id__in=ev_ids).values("decision", "respondida_en", "recibida_en",
                                                                                            "registrada_en", "modifica_resultado"))
    respondidas = [o for o in observaciones if o["respondida_en"]]

    # --- Tiempos por proceso: días de la creación a la aprobación de su última evaluación ---
    cierre: dict = {}
    for e in evaluaciones:
        if e.aprobada_en:
            cierre[e.proceso_id] = max(cierre.get(e.proceso_id, e.aprobada_en), e.aprobada_en)
    por_proceso: dict[str, list[float]] = defaultdict(list)
    for proc in procesos:
        if proc.id in cierre:
            por_proceso[modalidad_de(proc)].append((cierre[proc.id] - proc.creado_en).total_seconds() / 86400)
    todos_dias = [d for lista in por_proceso.values() for d in lista]

    verificaciones = len(resultados)
    automaticas = sum(a["verificadas_sistema"] for a in areas)
    todos_segundos = [s for lista in segundos_area.values() for s in lista]
    return {
        "procesos": {
            "creados": len(procesos),
            "evaluados": len(procesos_evaluados),
            "aprobados": len({e.proceso_id for e in evaluaciones if e.estado == EstadoEvaluacion.APROBADA}),
        },
        "modalidades": modalidades,
        "areas": areas,
        "totales": {
            # Ofertas (proponentes) de los procesos evaluados, y evaluaciones de
            # oferta: una por cada área en que se evaluó.
            "ofertas": sum(n_proponentes.get(i, 0) for i in procesos_evaluados),
            "evaluaciones_de_oferta": len({(r["evaluacion_id"], r["proponente_id"]) for r in resultados}),
            "verificaciones": verificaciones,
            "verificadas_sistema": automaticas,
            "porcentaje_sistema": automaticas / verificaciones if verificaciones else None,
            "revisadas_personas": sum(revisadas.values()),
            "correcciones": sum(correcciones.values()),
            "pendientes": pendientes_total,
            "documentos_soporte": len(soportes),
            "documentos_aportados": aportados,
            "horas_ahorradas": sum(a["horas_ahorradas"] for a in areas),
        },
        "tiempos": {
            "segundos_por_oferta": statistics.mean(todos_segundos) if todos_segundos else None,
            "ofertas_medidas": len(todos_segundos),
            "dias_hasta_aprobar": statistics.mean(dias) if dias else None,
        },
        "control": {
            "muestras": muestras.count(),
            "verificaciones_revisadas": revisados_muestra,
            "conformes": conformes,
            "hallazgos": revisados_muestra - conformes,
            "porcentaje_conforme": conformes / revisados_muestra if revisados_muestra else None,
        },
        "mensual": [{"mes": m, **mensual[m]} for m in range(1, 13)],
        "causas_revision": [
            {"area": TIPOS[a].nombre if a in TIPOS else a, "requisito": n, "titulo": titulos.get((a, n), f"Requisito {n}"), "casos": c}
            for (a, n), c in causas.most_common(6)
        ],
        "causas_rechazo": [
            {"area": TIPOS[a].nombre if a in TIPOS else a, "requisito": n, "titulo": titulos.get((a, n), f"Requisito {n}"), "casos": c}
            for (a, n), c in rechazos.most_common(8)
        ],
        "ofertas_rechazadas": len(ofertas_rechazadas),
        "observaciones": {
            "recibidas": len(observaciones),
            "respondidas": len(respondidas),
            "pendientes": len(observaciones) - len(respondidas),
            "acogidas": sum(1 for o in observaciones if o["decision"] in ("acoge", "acoge_parcial")),
            "modifican_resultado": sum(1 for o in observaciones if o["modifica_resultado"]),
            "dias_para_responder": statistics.mean(
                [(o["respondida_en"].date() - o["recibida_en"]).days for o in respondidas]
            ) if respondidas else None,
        },
        "tiempos_por_proceso": {
            "procesos_cerrados": len(todos_dias),
            "promedio_dias": statistics.mean(todos_dias) if todos_dias else None,
            "mediana_dias": statistics.median(todos_dias) if todos_dias else None,
            "maximo_dias": max(todos_dias) if todos_dias else None,
            "por_modalidad": [
                {"nombre": MODALIDADES.get(m, m), "procesos": len(d), "promedio_dias": statistics.mean(d)} for m, d in por_proceso.items()
            ],
        },
        "minutos_por_verificacion": MINUTOS_POR_VERIFICACION,
    }


def _titulos(evaluaciones: list[Evaluacion]) -> dict[tuple[str, int], str]:
    from evaluaciones.servicios import definicion_de

    titulos: dict[tuple[str, int], str] = {}
    vistas = set()
    for e in evaluaciones:
        clave = (e.tipo, e.plantilla_id)
        if clave in vistas:
            continue
        vistas.add(clave)
        try:
            for r in definicion_de(e).requisitos:
                titulos.setdefault((e.tipo, r.numero), r.titulo)
        except Exception:  # noqa: BLE001 — sin título, se muestra el número
            continue
    return titulos
