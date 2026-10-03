"""Estructura de evaluación de la entidad: sus dependencias por área, con
jefes, integrantes y palabras clave para sugerir la dependencia técnica."""
from __future__ import annotations

from uuid import UUID

from django.db import IntegrityError
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.errors import HttpError

from cuentas.models import Rol, TipoArea, Usuario
from cuentas.seguridad import auditar, requiere_rol, sesion_activa
from evaluaciones import estructura
from evaluaciones.models import Dependencia

router = Router(auth=sesion_activa, tags=["estructura"])


class DependenciaIn(Schema):
    tipo: str
    nombre: str
    palabras_clave: str = ""
    jefes: list[UUID] = []
    miembros: list[UUID] = []
    activa: bool = True
    orden: int = 0


def _entidad(usuario: Usuario, entidad_id: UUID | None):
    if usuario.es_superadmin:
        if entidad_id is None:
            raise HttpError(400, "Elija la entidad.")
        return entidad_id
    return usuario.entidad_id


def _out(d: Dependencia) -> dict:
    return {
        "id": str(d.id), "tipo": d.tipo, "tipo_nombre": d.get_tipo_display(), "nombre": d.nombre,
        "palabras_clave": d.palabras_clave, "activa": d.activa, "orden": d.orden,
        "jefes": [{"id": str(u.id), "nombre_completo": u.nombre_completo, "email": u.email} for u in d.jefes.all()],
        "miembros": [{"id": str(u.id), "nombre_completo": u.nombre_completo, "email": u.email} for u in d.miembros.all()],
    }


@router.get("/dependencias", response=list[dict])
def listar(request: HttpRequest, entidad_id: UUID | None = None) -> list[dict]:
    """Todos los de la entidad la ven (para elegir dependencia y comité)."""
    entidad = _entidad(request.auth, entidad_id)
    return [_out(d) for d in Dependencia.objects.filter(entidad_id=entidad).prefetch_related("jefes", "miembros")]


@router.get("/sugerir", response=dict)
def sugerir(request: HttpRequest, tipo: str, objeto: str = "", entidad_id: UUID | None = None) -> dict:
    d = estructura.sugerir_dependencia(_entidad(request.auth, entidad_id), tipo, objeto)
    return {"dependencia": {"id": str(d.id), "nombre": d.nombre} if d else None}


def _guardar(request: HttpRequest, d: Dependencia, datos: DependenciaIn) -> dict:
    if datos.tipo not in TipoArea.values:
        raise HttpError(400, "Área no válida.")
    nombre = " ".join(datos.nombre.split())
    if len(nombre) < 3:
        raise HttpError(400, "Escriba el nombre de la dependencia.")
    personas = {u.id: u for u in Usuario.objects.filter(pk__in=[*datos.jefes, *datos.miembros], entidad_id=d.entidad_id, is_active=True)}
    if (set(datos.jefes) | set(datos.miembros)) - set(personas):
        raise HttpError(400, "Alguna persona no es un usuario activo de la entidad.")
    if any(personas[j].rol not in (Rol.JEFE_AREA, Rol.ADMIN_ENTIDAD) for j in datos.jefes):
        raise HttpError(400, "Los jefes de una dependencia deben tener rol de jefe de área (o administrador).")
    d.tipo, d.nombre, d.palabras_clave = datos.tipo, nombre, datos.palabras_clave.strip()
    d.activa, d.orden = datos.activa, datos.orden
    try:
        d.save()
    except IntegrityError as exc:
        raise HttpError(409, "Ya existe una dependencia con ese nombre en esa área.") from exc
    d.jefes.set([personas[i] for i in datos.jefes])
    d.miembros.set([personas[i] for i in datos.miembros])
    auditar(request, "dependencia.guardada", entidad_id=d.entidad_id, objeto=d, nombre=d.nombre, tipo=d.tipo,
            jefes=[personas[i].email for i in datos.jefes], miembros=[personas[i].email for i in datos.miembros])
    return _out(d)


@router.post("/dependencias", response={201: dict})
def crear(request: HttpRequest, datos: DependenciaIn, entidad_id: UUID | None = None):
    requiere_rol(request.auth, [Rol.ADMIN_ENTIDAD])
    return 201, _guardar(request, Dependencia(entidad_id=_entidad(request.auth, entidad_id)), datos)


@router.put("/dependencias/{dependencia_id}", response=dict)
def editar(request: HttpRequest, dependencia_id: UUID, datos: DependenciaIn, entidad_id: UUID | None = None) -> dict:
    requiere_rol(request.auth, [Rol.ADMIN_ENTIDAD])
    d = get_object_or_404(Dependencia, pk=dependencia_id, entidad_id=_entidad(request.auth, entidad_id))
    return _guardar(request, d, datos)
