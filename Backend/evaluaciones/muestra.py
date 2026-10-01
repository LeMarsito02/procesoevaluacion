"""Muestra de control: la adopción humana de lo que el sistema verificó.

Expediente LEG-004, numerales 3 y 3.1, y Concepto C-1015 de 2026: el control
humano debe ser sustantivo, "capaz de validar, corregir o descartar el
resultado". Los requisitos que MiEvaluador verificó con evidencia no se
revisan uno por uno; se adoptan en bloque después de revisar, contra su
soporte, una muestra de esas verificaciones:

1. Se sortean `settings.MUESTRA_VERIFICACIONES` verificaciones (10 por
   defecto) entre las que el sistema dio por cumplidas y nadie revisó,
   repartidas primero entre ofertas y requisitos distintos. La semilla queda
   guardada: cualquiera puede repetir el sorteo y obtener las mismas.

   Se puede sortear apenas el sistema termina de evaluar, sin haber resuelto
   todavía lo que quedó por revisar. Es a propósito: un ítem no conforme manda
   a revisión humana ese requisito en todas las ofertas, y encontrarlo al
   principio permite revisar eso junto con el resto en una sola pasada, en vez
   de revisar trescientos requisitos y que aparezcan cuarenta más después.
2. El puntaje técnico no entra: se adopta aparte (evaluaciones.puntaje).
3. Cada ítem se marca conforme o no conforme después de abrir su soporte.
4. Un ítem no conforme amplía la revisión: todas las verificaciones del
   sistema de ese requisito en el proceso pasan a revisión humana.
5. La muestra se cierra cuando todo está revisado y no queda nada pendiente.
   Solo con una muestra cerrada, posterior al último cambio, se puede aprobar.
"""
from __future__ import annotations

import io
import random
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from evaluaciones.models import (
    EstadoMuestra,
    Evaluacion,
    ItemMuestra,
    MuestraControl,
    Proponente,
    Resultado,
    Revision,
)

# Una decisión sobre un requisito exige haber abierto un documento del
# proponente en las últimas horas (LEG-004, 3.1: validar exige ver el soporte).
VENTANA_SOPORTE = timedelta(hours=12)
NOTA_MINIMA_SIN_DOCUMENTO = 15


class ErrorMuestra(ValueError):
    pass


# --- Soporte visto -------------------------------------------------------------
def vio_soporte(usuario, evaluacion: Evaluacion, hoja: str, desde) -> bool:
    from cuentas.models import EventoAuditoria

    return EventoAuditoria.objects.filter(
        usuario=usuario,
        accion="documento.visto",
        objeto_tipo="Evaluacion",
        objeto_id=str(evaluacion.pk),
        detalles__hoja=hoja,
        fecha__gte=desde,
    ).exists()


def soporte_en_pliego(datos: dict | None) -> bool:
    """La decisión no sale de la oferta sino del pliego ("N.A. — el pliego no
    exige capacidad residual"): su soporte es el pliego del proceso, y es la
    misma para todos los proponentes."""
    return bool(datos) and (datos.get("motivo") or "").startswith("N.A. — el pliego")


def vio_pliego(usuario, evaluacion: Evaluacion, desde) -> bool:
    from cuentas.models import EventoAuditoria

    return EventoAuditoria.objects.filter(
        usuario=usuario, accion="pliego.visto", objeto_tipo="Evaluacion", objeto_id=str(evaluacion.pk), fecha__gte=desde
    ).exists()


def exigir_soporte(usuario, evaluacion: Evaluacion, proponente: Proponente, datos: dict | None, nota: str, desde=None) -> bool:
    """Valida que quien decide haya visto el soporte. Si el resultado no tiene
    documento (p. ej., "no aportó"), exige en cambio una justificación que diga
    qué se consultó. Devuelve si el soporte fue visto."""
    desde = desde or (timezone.now() - VENTANA_SOPORTE)
    if soporte_en_pliego(datos) and evaluacion.proceso.analisis_pliego_id:
        if vio_pliego(usuario, evaluacion, desde):
            return True
        raise ErrorMuestra("Esta decisión sale del pliego: ábralo antes de decidir, la decisión debe tomarse viendo la evidencia.")
    if vio_soporte(usuario, evaluacion, proponente.hoja, desde):
        return True
    if datos and datos.get("archivo_evaluado"):
        raise ErrorMuestra(
            "Abra el documento soporte de este proponente antes de decidir: la decisión debe tomarse viendo la evidencia."
        )
    if len((nota or "").strip()) < NOTA_MINIMA_SIN_DOCUMENTO:
        raise ErrorMuestra(
            "Este requisito no tiene documento soporte: explique en la justificación qué consultó para decidir "
            f"(al menos {NOTA_MINIMA_SIN_DOCUMENTO} caracteres)."
        )
    return False


# --- Universo y sorteo ----------------------------------------------------------
def universo(evaluacion: Evaluacion) -> dict:
    """Por proponente, las verificaciones del sistema que ninguna persona ha
    revisado: [(requisito, usa_ia, del_pliego)]. Sin el puntaje técnico."""
    from evaluaciones.cumplimiento import numeros_puntaje, usa_ia
    from evaluaciones.servicios import definicion_de

    excluidos = numeros_puntaje(definicion_de(evaluacion))
    revisados = set(Revision.objects.filter(evaluacion=evaluacion).values_list("proponente_id", "requisito"))
    salida: dict = {}
    for r in Resultado.objects.filter(evaluacion=evaluacion, requiere_revision=False).order_by("requisito"):
        if r.requisito in excluidos or (r.proponente_id, r.requisito) in revisados:
            continue
        salida.setdefault(r.proponente_id, []).append((r.requisito, usa_ia(r.datos), soporte_en_pliego(r.datos)))
    return salida


def sortear(candidatos: list[tuple], semilla: int, cantidad: int) -> list[tuple]:
    """Sorteo reproducible de verificaciones (numero_orden, hoja, requisito, …):
    misma semilla y mismo universo, misma muestra. Primero cubre ofertas y
    requisitos distintos; después completa con el resto."""
    orden = sorted(candidatos)
    random.Random(semilla).shuffle(orden)
    elegidas: list[tuple] = []
    ofertas: set = set()
    requisitos: set = set()
    for c in orden:  # 1) oferta y requisito nuevos
        if len(elegidas) < cantidad and c[1] not in ofertas and c[2] not in requisitos:
            elegidas.append(c)
            ofertas.add(c[1])
            requisitos.add(c[2])
    for c in orden:  # 2) al menos oferta o requisito nuevo
        if len(elegidas) < cantidad and c not in elegidas and (c[1] not in ofertas or c[2] not in requisitos):
            elegidas.append(c)
            ofertas.add(c[1])
            requisitos.add(c[2])
    for c in orden:  # 3) lo que falte
        if len(elegidas) < cantidad and c not in elegidas:
            elegidas.append(c)
    return elegidas


def ultimo_cambio(evaluacion: Evaluacion):
    fechas = [
        Resultado.objects.filter(evaluacion=evaluacion).aggregate(m=Max("evaluado_en"))["m"],
        Revision.objects.filter(evaluacion=evaluacion).aggregate(m=Max("fecha"))["m"],
    ]
    fechas = [f for f in fechas if f is not None]
    return max(fechas) if fechas else None


def vigente(evaluacion: Evaluacion) -> MuestraControl | None:
    """La muestra en curso o la última cerrada (sin las anuladas)."""
    return MuestraControl.objects.filter(evaluacion=evaluacion).exclude(estado=EstadoMuestra.ANULADA).first()


# --- Ciclo de la muestra ---------------------------------------------------------
def crear(evaluacion: Evaluacion, usuario) -> MuestraControl:
    from evaluaciones.servicios import avances

    avance = avances([evaluacion.id])[evaluacion.id]
    if avance.evaluados < avance.proponentes or avance.en_fila or avance.procesando:
        raise ErrorMuestra("Todavía hay proponentes sin evaluar: la muestra se hace cuando el sistema termina.")
    actual = vigente(evaluacion)
    if actual is not None and actual.estado in (EstadoMuestra.EN_CURSO, EstadoMuestra.CON_HALLAZGOS):
        return actual
    semilla = secrets.randbits(62)
    items_por_proponente = universo(evaluacion)
    proponentes = {p.id: p for p in Proponente.objects.filter(id__in=items_por_proponente.keys())}
    candidatos = [
        (proponentes[pid].numero_orden, proponentes[pid].hoja, req, ia, str(pid))
        for pid, lista in items_por_proponente.items()
        for req, ia, del_pliego in lista
        if not del_pliego
    ]
    # Lo que sale del pliego es una sola decisión repetida en cada oferta: entra
    # al sorteo una vez por requisito (en un proponente al azar), no seis veces.
    # Antes ocupaba la mitad de la muestra con lo mismo, sin documento de la oferta.
    del_pliego: dict[int, list[tuple]] = {}
    for pid, lista in items_por_proponente.items():
        for req, ia, es_del_pliego in lista:
            if es_del_pliego:
                del_pliego.setdefault(req, []).append((proponentes[pid].numero_orden, proponentes[pid].hoja, req, ia, str(pid)))
    azar = random.Random(semilla)
    candidatos += [azar.choice(sorted(lista)) for _, lista in sorted(del_pliego.items())]
    elegidos = sortear(candidatos, semilla, settings.MUESTRA_VERIFICACIONES)
    with transaction.atomic():
        MuestraControl.objects.filter(evaluacion=evaluacion).exclude(estado=EstadoMuestra.ANULADA).update(
            estado=EstadoMuestra.ANULADA
        )
        muestra = MuestraControl.objects.create(
            entidad_id=evaluacion.entidad_id,
            evaluacion=evaluacion,
            semilla=semilla,
            parametros={
                "verificaciones": settings.MUESTRA_VERIFICACIONES,
                "universo_ofertas": len(proponentes),
                "universo_verificaciones": sum(len(lista) for lista in items_por_proponente.values()),
                "version_sistema": settings.MIEVALUADOR_VERSION,
            },
            ofertas_sorteadas=[hoja for _, hoja in sorted({(c[0], c[1]) for c in elegidos})],
            creada_por=usuario,
        )
        ItemMuestra.objects.bulk_create(
            [
                ItemMuestra(entidad_id=evaluacion.entidad_id, muestra=muestra, proponente_id=pid, requisito=req, usa_ia=ia)
                for _, _, req, ia, pid in elegidos
            ]
        )
        if not elegidos:
            # Todo lo revisó una persona: no hay nada que muestrear.
            muestra.estado = EstadoMuestra.CERRADA
            muestra.cerrada_por = usuario
            muestra.cerrada_en = timezone.now()
            muestra.save()
    return muestra


def registrar(item: ItemMuestra, usuario, conforme: bool, nota: str) -> ItemMuestra:
    muestra = item.muestra
    if muestra.estado not in (EstadoMuestra.EN_CURSO, EstadoMuestra.CON_HALLAZGOS):
        raise ErrorMuestra("Esta muestra ya está cerrada o fue anulada.")
    evaluacion = muestra.evaluacion
    resultado = Resultado.objects.filter(evaluacion=evaluacion, proponente=item.proponente, requisito=item.requisito).first()
    if not conforme and len((nota or "").strip()) < 5:
        raise ErrorMuestra("Explique qué encontró: queda en el acta de la muestra de control.")
    visto = exigir_soporte(usuario, evaluacion, item.proponente, resultado.datos if resultado else None, nota, desde=muestra.creada_en)
    with transaction.atomic():
        item.resultado = ItemMuestra.CONFORME if conforme else ItemMuestra.NO_CONFORME
        item.nota = (nota or "").strip()
        item.soporte_visto = visto
        item.usuario = usuario
        item.fecha = timezone.now()
        item.save()
        if not conforme:
            ampliar(muestra, item.requisito)
    return item


def ampliar(muestra: MuestraControl, requisito: int) -> int:
    """Un error en la muestra: todas las verificaciones del sistema de ese
    requisito en el proceso pasan a revisión humana. Devuelve cuántas."""
    revisados = set(
        Revision.objects.filter(evaluacion=muestra.evaluacion, requisito=requisito).values_list("proponente_id", flat=True)
    )
    aviso = "Muestra de control: se encontró un error en este requisito, así que se revisa en todas las ofertas."
    ids = []
    for r in Resultado.objects.filter(evaluacion=muestra.evaluacion, requisito=requisito, requiere_revision=False):
        if r.proponente_id in revisados:
            continue
        ids.append(r.id)
        # La interfaz lo muestra como pendiente con este motivo. update() y no
        # save(): no cambia la fecha de evaluación del resultado.
        Resultado.objects.filter(pk=r.pk).update(requiere_revision=True, datos={**r.datos, "revision_forzada": aviso})
    if requisito not in muestra.requisitos_ampliados:
        muestra.requisitos_ampliados = [*muestra.requisitos_ampliados, requisito]
    muestra.estado = EstadoMuestra.CON_HALLAZGOS
    muestra.save(update_fields=["requisitos_ampliados", "estado"])
    return len(ids)


def cerrar(muestra: MuestraControl, usuario) -> MuestraControl:
    from evaluaciones.servicios import avances

    if muestra.estado not in (EstadoMuestra.EN_CURSO, EstadoMuestra.CON_HALLAZGOS):
        raise ErrorMuestra("Esta muestra ya está cerrada o fue anulada.")
    faltan = muestra.items.filter(resultado="").count()
    if faltan:
        raise ErrorMuestra(f"Faltan {faltan} verificaciones de la muestra por revisar.")
    # La garantía está aquí, no en el sorteo: la muestra solo se cierra cuando no
    # queda nada por revisar en la evaluación, y sin muestra cerrada no se aprueba.
    pendientes = avances([muestra.evaluacion_id])[muestra.evaluacion_id].pendientes
    if pendientes:
        raise ErrorMuestra(f"Quedan {pendientes} requisitos por revisar: resuélvalos antes de cerrar la muestra.")
    muestra.estado = EstadoMuestra.CERRADA
    muestra.cerrada_por = usuario
    muestra.cerrada_en = timezone.now()
    muestra.save()
    return muestra


def motivo_para_no_aprobar(evaluacion: Evaluacion) -> str | None:
    """None si la muestra permite aprobar; si no, el porqué."""
    muestra = vigente(evaluacion)
    if muestra is None:
        return "Falta la muestra de control: revise la muestra antes de aprobar."
    if muestra.estado != EstadoMuestra.CERRADA:
        return "La muestra de control no está cerrada."
    cambio = ultimo_cambio(evaluacion)
    if cambio is not None and muestra.cerrada_en is not None and cambio > muestra.cerrada_en:
        return "La evaluación cambió después de la muestra de control: haga una nueva muestra antes de aprobar."
    return None


def resumen(muestra: MuestraControl | None) -> dict | None:
    if muestra is None:
        return None
    items = list(muestra.items.select_related("proponente", "usuario").order_by("proponente__numero_orden", "requisito"))
    datos = {
        (r.proponente_id, r.requisito): r.datos
        for r in Resultado.objects.filter(evaluacion_id=muestra.evaluacion_id, proponente_id__in={i.proponente_id for i in items})
    }
    return {
        "id": str(muestra.id),
        "estado": muestra.estado,
        "estado_nombre": muestra.get_estado_display(),
        "semilla": str(muestra.semilla),
        "parametros": muestra.parametros,
        "ofertas_sorteadas": muestra.ofertas_sorteadas,
        "requisitos_ampliados": muestra.requisitos_ampliados,
        "creada_por": muestra.creada_por.nombre_completo,
        "creada_en": muestra.creada_en.isoformat(),
        "cerrada_por": muestra.cerrada_por.nombre_completo if muestra.cerrada_por_id else None,
        "cerrada_en": muestra.cerrada_en.isoformat() if muestra.cerrada_en else None,
        "items": [
            {
                "id": i.id,
                "proponente_id": str(i.proponente_id),
                "hoja": i.proponente.hoja,
                "proponente": i.proponente.nombre,
                "requisito": i.requisito,
                "usa_ia": i.usa_ia,
                "resultado": i.resultado or None,
                "nota": i.nota,
                "soporte_visto": i.soporte_visto,
                # El soporte es el pliego del proceso, no un documento de la oferta.
                "soporte_pliego": soporte_en_pliego(datos.get((i.proponente_id, i.requisito))),
                "usuario": i.usuario.nombre_completo if i.usuario_id else None,
                "fecha": i.fecha.isoformat() if i.fecha else None,
            }
            for i in items
        ],
    }


# --- Acta -------------------------------------------------------------------------
def generar_acta(muestra: MuestraControl) -> tuple[bytes, str]:
    """Acta de la muestra de control, en Word, para el expediente."""
    from docx import Document
    from docx.shared import Pt

    from evaluaciones.reporte import _parrafo, _tabla, _titulo, fecha_larga

    evaluacion = muestra.evaluacion
    proceso = evaluacion.proceso
    doc = Document()
    doc.styles["Normal"].font.name = "Arial"
    doc.styles["Normal"].font.size = Pt(10)
    _titulo(doc, "Acta de la muestra de control")
    _parrafo(
        doc,
        f"Proceso {proceso.codigo} · {evaluacion.entidad.nombre} · evaluación {evaluacion.get_tipo_display().lower()}.",
        negrita=True,
    )
    p = muestra.parametros or {}
    _parrafo(
        doc,
        "Objeto: dejar constancia de la revisión humana, contra su documento soporte, de las verificaciones realizadas "
        "por MiEvaluador que se sortearon, como condición para adoptar los resultados verificados por la "
        "herramienta (expediente LEG-004, numerales 3 y 3.1; Concepto C-1015 de 2026 de la ANCP-CCE).",
    )
    _tabla(
        doc,
        ["Dato", "Valor"],
        [
            ["Verificaciones sorteadas", f"{muestra.items.count()} de {p.get('universo_verificaciones', '—')} verificadas por el sistema"],
            ["Ofertas que tocó la muestra", ", ".join(muestra.ofertas_sorteadas) or "Ninguna (todo fue revisado individualmente)"],
            ["Semilla del sorteo (permite reproducirlo)", str(muestra.semilla)],
            ["Versión de MiEvaluador", p.get("version_sistema", settings.MIEVALUADOR_VERSION)],
            ["Requisitos ampliados a revisión total", ", ".join(str(n) for n in muestra.requisitos_ampliados) or "Ninguno"],
            ["Realizada por", f"{muestra.creada_por.nombre_completo}, {fecha_larga(muestra.creada_en)}"],
            ["Cerrada por", f"{muestra.cerrada_por.nombre_completo}, {fecha_larga(muestra.cerrada_en)}" if muestra.cerrada_por_id else "Sin cerrar"],
            ["Estado", muestra.get_estado_display()],
        ],
        [7.0, 9.6],
    )
    _titulo(doc, "Verificaciones revisadas", nivel=2)
    filas = [
        [
            i.proponente.hoja,
            str(i.requisito),
            {"conforme": "Conforme", "no_conforme": "No conforme"}.get(i.resultado, "Sin revisar"),
            "Sí" if i.soporte_visto else "No (justificado)",
            i.nota or "—",
            f"{i.usuario.nombre_completo}, {fecha_larga(i.fecha)}" if i.usuario_id else "—",
        ]
        for i in muestra.items.select_related("proponente", "usuario").order_by("proponente__numero_orden", "requisito")
    ]
    _tabla(doc, ["Prop.", "Req.", "Resultado", "Soporte visto", "Observación", "Revisó"], filas, [1.4, 1.2, 2.2, 2.0, 6.0, 3.8])
    _parrafo(
        doc,
        "Si la muestra revela un error en un requisito, se revisan individualmente todas las verificaciones del sistema "
        "de ese requisito en el proceso antes de cerrarla.",
        tam=9,
    )
    salida = io.BytesIO()
    doc.save(salida)
    return salida.getvalue(), f"ACTA MUESTRA DE CONTROL {evaluacion.tipo.upper()} {proceso.codigo}.docx"
