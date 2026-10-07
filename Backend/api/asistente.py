"""Asistente de consulta: conversaciones guardadas y respuesta transmitida en
vivo. Ver evaluaciones/asistente.py para las reglas de lo que puede consultar."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.errors import HttpError

from cuentas.aislamiento import SISTEMA, fijar_entidad
from cuentas.models import Usuario
from cuentas.seguridad import auditar, sesion_activa
from evaluaciones import asistente
from evaluaciones.models import ConversacionAsistente, MensajeAsistente

router = Router(auth=sesion_activa, tags=["asistente"])


class ConversacionOut(Schema):
    id: UUID
    titulo: str
    actualizada_en: datetime
    evaluacion_id: UUID | None = None


class EvaluacionOpcion(Schema):
    id: UUID
    etiqueta: str
    objeto: str


class MensajeOut(Schema):
    id: int
    rol: str
    contenido: str
    fuentes: list[dict]
    creado_en: datetime


class ConversacionDetalleOut(ConversacionOut):
    mensajes: list[MensajeOut]


class EstadoOut(Schema):
    habilitado: bool
    aviso: str
    conversaciones: list[ConversacionOut]
    # Evaluaciones que la persona puede elegir como tema de la conversación.
    evaluaciones: list[EvaluacionOpcion]


class NuevaIn(Schema):
    evaluacion_id: UUID | None = None


class PreguntaIn(Schema):
    texto: str
    # Cambia la evaluación sobre la que se conversa ("" o null = todas).
    evaluacion_id: UUID | None = None
    cambiar_evaluacion: bool = False


def _mias(usuario: Usuario):
    # Las conversaciones son personales: ni el administrador ve las de otro.
    return ConversacionAsistente.objects.filter(usuario=usuario)


def _evaluacion_elegida(usuario: Usuario, evaluacion_id: UUID | None):
    if evaluacion_id is None:
        return None
    evaluacion = asistente.evaluacion_visible(usuario, evaluacion_id)
    if evaluacion is None:
        raise HttpError(404, "No encontrado.")
    return evaluacion


@router.get("", response=EstadoOut)
def estado(request: HttpRequest, evaluacion_id: UUID | None = None) -> EstadoOut:
    """Con `evaluacion_id`, solo las conversaciones sobre esa evaluación (el
    chat que se abre dentro de ella)."""
    usuario: Usuario = request.auth
    conversaciones = _mias(usuario)
    if evaluacion_id is not None:
        conversaciones = conversaciones.filter(evaluacion=_evaluacion_elegida(usuario, evaluacion_id))
    opciones = [
        EvaluacionOpcion(id=e.id, etiqueta=asistente._fuente(e)["etiqueta"], objeto=(e.proceso.objeto or "")[:120])
        for e in asistente._visibles(usuario).order_by("-creada_en")[:60]
    ]
    return EstadoOut(habilitado=asistente.habilitado(), aviso=asistente.AVISO, conversaciones=list(conversaciones[:50]), evaluaciones=opciones)


@router.post("/conversaciones", response={201: ConversacionOut})
def nueva_conversacion(request: HttpRequest, datos: NuevaIn | None = None):
    usuario: Usuario = request.auth
    evaluacion = _evaluacion_elegida(usuario, datos.evaluacion_id if datos else None)
    return 201, ConversacionAsistente.objects.create(usuario=usuario, entidad_id=usuario.entidad_id, evaluacion=evaluacion)


@router.get("/conversaciones/{conversacion_id}", response=ConversacionDetalleOut)
def ver_conversacion(request: HttpRequest, conversacion_id: UUID):
    c = get_object_or_404(_mias(request.auth), pk=conversacion_id)
    return ConversacionDetalleOut(
        id=c.id, titulo=c.titulo, actualizada_en=c.actualizada_en, evaluacion_id=c.evaluacion_id, mensajes=list(c.mensajes.all())
    )


# Turnos para generar respuestas, y quién tiene una en curso (con la hora, por
# si una respuesta se interrumpe sin liberar: a los 6 minutos se da por terminada).
_turnos = threading.BoundedSemaphore(max(1, settings.ASISTENTE_SIMULTANEOS))
_en_curso: dict = {}
_candado_en_curso = threading.Lock()
_VIGENCIA_EN_CURSO = 360


def _ocupar(usuario_id) -> bool:
    """Una pregunta a la vez por persona."""
    ahora = time.monotonic()
    with _candado_en_curso:
        if ahora - _en_curso.get(usuario_id, -_VIGENCIA_EN_CURSO) < _VIGENCIA_EN_CURSO:
            return False
        _en_curso[usuario_id] = ahora
        return True


def _liberar(usuario_id) -> None:
    with _candado_en_curso:
        _en_curso.pop(usuario_id, None)


def _linea(evento: dict) -> bytes:
    return json.dumps(evento, ensure_ascii=False).encode() + b"\n"


def _producir(request: HttpRequest, usuario: Usuario, conversacion: ConversacionAsistente, historial: list[dict]) -> Iterator[bytes]:
    """Espera turno, transmite la respuesta y, al terminar, la guarda con sus fuentes."""
    con_turno = _turnos.acquire(blocking=False)
    try:
        if not con_turno:
            yield _linea({"tipo": "espera"})
            con_turno = _turnos.acquire(timeout=settings.ASISTENTE_ESPERA_MAX)
        if not con_turno:
            yield _linea({"tipo": "error", "texto": "Hay muchas consultas al asistente en este momento. Inténtelo de nuevo en un minuto."})
        else:
            yield from _responder_y_guardar(request, usuario, conversacion, historial)
    finally:
        if con_turno:
            _turnos.release()
        _liberar(usuario.id)
    yield _linea({"tipo": "fin"})


def _responder_y_guardar(request: HttpRequest, usuario: Usuario, conversacion: ConversacionAsistente, historial: list[dict]) -> Iterator[bytes]:
    texto, consultas, fuentes, fallo = "", [], [], False
    # El permiso se comprueba en cada pregunta: quien salió del comité deja de
    # recibir datos de esa evaluación aunque la conversación siga abierta.
    evaluacion = asistente.evaluacion_visible(usuario, conversacion.evaluacion_id)
    for evento in asistente.responder(usuario, historial, evaluacion):
        if evento["tipo"] == "texto":
            texto += evento["texto"]
        elif evento["tipo"] == "consulta":
            consultas.append(evento["nombre"])
        elif evento["tipo"] == "fuentes":
            fuentes = evento["fuentes"]
        elif evento["tipo"] == "error":
            fallo = True
        yield _linea(evento)
    if not fallo and texto.strip():
        mensaje = MensajeAsistente.objects.create(
            conversacion=conversacion, entidad_id=conversacion.entidad_id, rol="asistente", contenido=texto.strip(),
            consultas=consultas, fuentes=fuentes, modelo=asistente.modelo(),
        )
        conversacion.save(update_fields=["actualizada_en"])
        auditar(request, "asistente.respuesta", usuario=usuario, entidad_id=conversacion.entidad_id, objeto=conversacion,
                mensaje=mensaje.id, consultas=consultas, evaluaciones=[f["evaluacion_id"] for f in fuentes], modelo=mensaje.modelo)


async def _en_hilo(fabrica, entidad: str):
    """Ejecuta el generador en un hilo y entrega cada fragmento en cuanto
    sale: una respuesta transmitida no debe ocupar el hilo de las peticiones."""
    bucle, cola = asyncio.get_running_loop(), asyncio.Queue()

    def trabajo():
        try:
            # El hilo abre su propia conexión, que nace con acceso de sistema:
            # se limita a la entidad de la persona antes de cualquier consulta.
            fijar_entidad(entidad)
            for fragmento in fabrica():
                bucle.call_soon_threadsafe(cola.put_nowait, fragmento)
        except Exception:  # noqa: BLE001 (el fallo se informa al cliente, no se propaga al bucle)
            asistente.log.exception("Falló la respuesta del asistente")
            bucle.call_soon_threadsafe(cola.put_nowait, _linea({"tipo": "error", "texto": "El asistente tuvo un problema. Inténtelo de nuevo."}))
        finally:
            connection.close()
            bucle.call_soon_threadsafe(cola.put_nowait, None)

    threading.Thread(target=trabajo, daemon=True).start()
    while (fragmento := await cola.get()) is not None:
        yield fragmento


@router.post("/conversaciones/{conversacion_id}/mensajes")
def preguntar(request: HttpRequest, conversacion_id: UUID, datos: PreguntaIn):
    usuario: Usuario = request.auth
    if not asistente.habilitado():
        raise HttpError(503, "El asistente no está habilitado en esta instalación.")
    texto = datos.texto.strip()
    if not texto:
        raise HttpError(400, "Escriba su pregunta.")
    if len(texto) > asistente.MAX_PREGUNTA:
        raise HttpError(400, f"La pregunta es muy larga (máximo {asistente.MAX_PREGUNTA} caracteres).")
    conversacion = get_object_or_404(_mias(usuario), pk=conversacion_id)
    if datos.cambiar_evaluacion:
        conversacion.evaluacion = _evaluacion_elegida(usuario, datos.evaluacion_id)
    if not _ocupar(usuario.id):
        raise HttpError(429, "Espere a que termine la respuesta anterior antes de enviar otra pregunta.")
    MensajeAsistente.objects.create(conversacion=conversacion, entidad_id=conversacion.entidad_id, rol="usuario", contenido=texto)
    if not conversacion.titulo:
        conversacion.titulo = texto[:80]
    conversacion.save()
    historial = [{"rol": m.rol, "contenido": m.contenido} for m in conversacion.mensajes.all()]

    def fabrica():
        return _producir(request, usuario, conversacion, historial)

    if settings.ASISTENTE_EN_HILO:
        contenido = _en_hilo(fabrica, str(usuario.entidad_id) if usuario.entidad_id and not usuario.es_superadmin else SISTEMA)
    else:
        contenido = fabrica()
    respuesta = StreamingHttpResponse(contenido, content_type="application/x-ndjson")
    respuesta["Cache-Control"] = "no-cache"
    respuesta["X-Accel-Buffering"] = "no"  # el proxy no debe juntar los fragmentos
    return respuesta
