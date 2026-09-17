"""Trabajador de la fila central: toma trabajos de PostgreSQL y evalúa
proponentes en el pool de procesos del motor. Se pueden correr varios
trabajadores (en una o varias máquinas) contra la misma base de datos."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import uuid

from asgiref.sync import sync_to_async
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from api.ejecucion import evaluar_todos_en_proceso
from cuentas.correo import enviar_evaluacion_terminada
from evaluaciones.models import EstadoTrabajo, Trabajador, Trabajo
from evaluaciones.servicios import (
    PENDIENTES,
    actualizar_estado,
    avances,
    definicion_de,
    guardar_resultados,
    proponente_motor,
    reclamar,
    recuperar_huerfanos,
)
from motor.esquemas.proceso import ProcesoDocumentoBase
from motor.workers import detener_pool

log = logging.getLogger("mievaluador.fila")

ESPERA_SIN_TRABAJO = 2.0
INTERVALO_LATIDO = 20.0


def _renovar_conexion() -> None:
    # Cierra conexiones caídas o viejas (proceso de larga duración). Dentro de
    # una transacción abierta (pruebas) no se toca.
    if not connection.in_atomic_block:
        close_old_connections()


def _registrar(trabajador_id: str, capacidad: int) -> None:
    Trabajador.objects.update_or_create(id=trabajador_id, defaults={"capacidad": capacidad, "latido": timezone.now()})


def _latir(trabajador_id: str) -> None:
    ahora = timezone.now()
    Trabajador.objects.filter(id=trabajador_id).update(latido=ahora)
    Trabajo.objects.filter(trabajador=trabajador_id, estado=EstadoTrabajo.PROCESANDO).update(latido=ahora)


def _retirar(trabajador_id: str) -> None:
    Trabajador.objects.filter(id=trabajador_id).delete()
    # Lo que quedó a medias vuelve a la fila para otro trabajador.
    Trabajo.objects.filter(trabajador=trabajador_id, estado=EstadoTrabajo.PROCESANDO).update(
        estado=EstadoTrabajo.EN_FILA, intentos=0
    )


def _cerrar(trabajo: Trabajo, resultados, error: str | None) -> None:
    evaluacion = trabajo.evaluacion
    with transaction.atomic():
        if resultados is not None:
            guardar_resultados(evaluacion, trabajo.proponente, resultados)
        Trabajo.objects.filter(pk=trabajo.pk).update(
            estado=EstadoTrabajo.ERROR if error else EstadoTrabajo.TERMINADO,
            error=error or "",
            terminado_en=timezone.now(),
        )
        actualizar_estado(evaluacion)
        quedan = Trabajo.objects.filter(evaluacion=evaluacion, estado__in=PENDIENTES).exists()
        if not quedan:
            destinatario = evaluacion.responsable or trabajo.solicitado_por
            if destinatario is not None:
                avance = avances([evaluacion.id])[evaluacion.id]
                transaction.on_commit(lambda: enviar_evaluacion_terminada(evaluacion, destinatario, avance))


async def _atender(trabajo: Trabajo) -> None:
    documento = ProcesoDocumentoBase.model_validate(trabajo.evaluacion.proceso.documento_base)
    # Cómo evalúa la entidad (versión guardada en la evaluación).
    documento.criterios = (await sync_to_async(definicion_de)(trabajo.evaluacion)).model_dump(mode="json")
    inicio = timezone.now()
    try:
        resultados = await evaluar_todos_en_proceso(proponente_motor(trabajo.proponente), documento)
        await sync_to_async(_cerrar)(trabajo, resultados, None)
        log.info("%s %s en %.0fs", trabajo.evaluacion.proceso.codigo, trabajo.proponente.hoja, (timezone.now() - inicio).total_seconds())
    except Exception as exc:  # noqa: BLE001
        log.exception("Falló %s", trabajo.proponente.hoja)
        await sync_to_async(_cerrar)(trabajo, None, f"No se pudo evaluar: {exc}")


async def trabajar(capacidad: int, una_vez: bool = False) -> None:
    trabajador_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
    await sync_to_async(_registrar)(trabajador_id, capacidad)
    detener = asyncio.Event()
    loop = asyncio.get_running_loop()
    for senal in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(senal, detener.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass
    log.info("Trabajador %s atendiendo la fila con %d cupos", trabajador_id, capacidad)

    async def latidos():
        while not detener.is_set():
            await sync_to_async(_latir)(trabajador_id)
            await sync_to_async(recuperar_huerfanos)()
            await sync_to_async(_renovar_conexion)()
            try:
                await asyncio.wait_for(detener.wait(), INTERVALO_LATIDO)
            except TimeoutError:
                pass

    async def cupo():
        while not detener.is_set():
            trabajo = await sync_to_async(reclamar)(trabajador_id)
            if trabajo is None:
                if una_vez:
                    return
                try:
                    await asyncio.wait_for(detener.wait(), ESPERA_SIN_TRABAJO)
                except TimeoutError:
                    pass
                continue
            await _atender(trabajo)

    tarea_latidos = asyncio.create_task(latidos())
    try:
        await asyncio.gather(*(cupo() for _ in range(capacidad)))
    finally:
        detener.set()
        await tarea_latidos
        await sync_to_async(_retirar)(trabajador_id)
        detener_pool()
        log.info("Trabajador %s detenido", trabajador_id)
