"""Lectura en segundo plano de un proceso a medio crear (PreparacionProceso).

La hace el trabajador de la fila, no la petición: leer un Documento Base
escaneado, la carpeta de ofertas y el pliego completo puede tomar minutos. Así
la persona ve el avance, puede recargar la página sin perderlo y descartarlo
cuando quiera.

Etapas y el avance con que termina cada una (la pantalla avanza la barra
despacio dentro de cada etapa):
    Documento Base   → 55 %
    Ofertas          → 75 %
    Pliego completo  → 100 %
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from evaluaciones import pliego as pliego_servicio
from evaluaciones.models import PreparacionProceso

log = logging.getLogger(__name__)

# Si el trabajador se cae a la mitad, otro la retoma pasado este tiempo.
LECTURA_CAIDA = timedelta(minutes=20)
# Sin uso, una preparación se borra a los días.
DIAS_DE_VIDA = 7

ETAPAS = {
    "documento": ("Leyendo el Documento Base", 5),
    "ofertas": ("Revisando las ofertas", 55),
    "pliego": ("Leyendo el pliego completo", 75),
}


def _avanzar(p: PreparacionProceso, etapa: str) -> None:
    texto, progreso = ETAPAS[etapa]
    PreparacionProceso.objects.filter(pk=p.pk).update(etapa=texto, progreso=progreso)


def reclamar() -> PreparacionProceso | None:
    limite = timezone.now() - LECTURA_CAIDA
    with transaction.atomic():
        p = (
            PreparacionProceso.objects.select_for_update(skip_locked=True)
            .filter(Q(estado=PreparacionProceso.PENDIENTE) | Q(estado=PreparacionProceso.LEYENDO, iniciada_en__lt=limite))
            .order_by("creada_en")
            .first()
        )
        if p is None:
            return None
        p.estado, p.error, p.iniciada_en, p.progreso = PreparacionProceso.LEYENDO, "", timezone.now(), 2
        p.save(update_fields=["estado", "error", "iniciada_en", "progreso"])
        return p


def leer(p: PreparacionProceso) -> dict:
    """Lo mismo que respondía /procesos/analizar, leído en tres etapas."""
    from motor.integrations.drive import DriveAccessError, DriveConfigError, list_proponentes
    from motor.parsers.documento_base import build_proceso
    from motor.pliego import lectura

    with p.archivo.open("rb") as f:
        pdf = f.read()

    _avanzar(p, "documento")
    documento = build_proceso(p.codigo, p.fecha_cierre, pdf)

    _avanzar(p, "ofertas")
    proponentes, no_reconocidos, drive_error = [], [], None
    if p.ofertas_subidas is not None and p.ofertas_subidas.get("pendientes"):
        # Subidas por pedazos: se reparten desde el disco, una oferta a la vez, y
        # los temporales se borran. Lo repartido queda guardado (si la lectura
        # se reintenta, no hace falta volver a subir nada).
        from evaluaciones import subidas
        from motor.integrations import ofertas_locales

        pendientes = p.ofertas_subidas["pendientes"]
        # Cada archivo se reparte por separado y se registra su huella: la próxima
        # vez que se elija el mismo archivo no se vuelve a subir. Las cargas que ya
        # estaban en el servidor traen sus ofertas de la caché.
        piezas: list[tuple[str, object]] = []
        avisos: dict[str, str] = {}
        no_reconocidos: list[str] = []
        for x in pendientes:
            if x.get("reuso"):
                partes, otros = x["reuso"]["partes"], x["reuso"].get("no_reconocidos", [])
            else:
                ruta = subidas._ruta(x["id"])
                r1 = ofertas_locales.desde_archivos([(x["nombre"], ruta)])
                partes = [{"nombre": o.nombre_archivo, "file_id": o.drive_file_id, "advertencia": o.advertencia or ""} for o in r1.proponentes]
                otros = r1.no_reconocidos
                subidas.registrar_carga(subidas.huella_rapida(ruta), x["tamano"], x["nombre"], partes, otros, p.entidad_id)
            no_reconocidos += otros
            for parte in partes:
                if parte.get("advertencia"):
                    avisos[parte["file_id"]] = parte["advertencia"]
                piezas.append((parte["nombre"], (lambda fid=parte["file_id"]: ofertas_locales.leer(fid))))
        r = ofertas_locales.desde_archivos(piezas)
        for o in r.proponentes:
            aviso = avisos.get(o.drive_file_id)
            if aviso and aviso not in (o.advertencia or ""):
                o.advertencia = f"{o.advertencia}; {aviso}" if o.advertencia else aviso
        proponentes = [x.model_dump(mode="json") for x in r.proponentes]
        no_reconocidos = [*r.no_reconocidos, *no_reconocidos]
        PreparacionProceso.objects.filter(pk=p.pk).update(ofertas_subidas={"proponentes": proponentes, "no_reconocidos": no_reconocidos})
        for x in pendientes:
            subidas.borrar(x["id"])
    elif p.ofertas_subidas is not None:
        proponentes = p.ofertas_subidas.get("proponentes", [])
        no_reconocidos = p.ofertas_subidas.get("no_reconocidos", [])
    elif p.carpeta_drive.strip():
        try:
            r = list_proponentes(p.carpeta_drive.strip(), p.entidad.microsoft_directorio or None)
            proponentes = [x.model_dump(mode="json") for x in r.proponentes]
            no_reconocidos = r.no_reconocidos
        except (DriveConfigError, DriveAccessError, ValueError) as exc:
            drive_error = str(exc)

    _avanzar(p, "pliego")
    pliego, pliego_error = None, None
    try:
        sha = lectura.huella(pdf)
        analisis = pliego_servicio.vigente(p.entidad_id, sha)
        reutilizado = analisis is not None
        if analisis is None:
            analisis = pliego_servicio.guardar(p.entidad_id, pdf, p.nombre_archivo, pliego_servicio.leer(pdf), p.creada_por)
        pliego = pliego_servicio.payload_creacion(analisis, reutilizado)
    except Exception as exc:  # noqa: BLE001
        pliego_error = f"No se pudo analizar el pliego completo: {exc}"

    return {
        "documento_base": documento.model_dump(mode="json"),
        "proponentes": proponentes,
        "proponentes_no_reconocidos": no_reconocidos,
        "drive_error": drive_error,
        "pliego": pliego,
        "pliego_error": pliego_error,
    }


def atender_pendientes() -> int:
    """Lee las preparaciones pendientes (lo llama el trabajador de la fila)."""
    n = 0
    while (p := reclamar()) is not None:
        inicio = time.monotonic()
        try:
            resultado = leer(p)
            PreparacionProceso.objects.filter(pk=p.pk).update(
                estado=PreparacionProceso.LISTA, resultado=resultado, progreso=100, etapa="Lista", terminada_en=timezone.now(),
            )
            log.info("Preparación %s leída en %.0fs", p.pk, time.monotonic() - inicio)
        except Exception as exc:  # noqa: BLE001
            log.exception("Falló la lectura de la preparación %s", p.pk)
            PreparacionProceso.objects.filter(pk=p.pk).update(
                estado=PreparacionProceso.ERROR, terminada_en=timezone.now(),
                error=f"No se pudo leer el Documento Base. Verifique que sea el PDF correcto. ({exc})"[:2000],
            )
        n += 1
    return n


def borrar(p: PreparacionProceso) -> None:
    from evaluaciones import subidas

    for x in (p.ofertas_subidas or {}).get("pendientes", []):
        subidas.borrar(x["id"])
    if p.archivo:
        p.archivo.delete(save=False)
    p.delete()


def borrar_vencidas() -> int:
    limite = timezone.now() - timedelta(days=DIAS_DE_VIDA)
    vencidas = list(PreparacionProceso.objects.filter(creada_en__lt=limite))
    for p in vencidas:
        borrar(p)
    return len(vencidas)
