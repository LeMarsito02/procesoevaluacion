"""Tablero de métricas de la entidad (administrador de la entidad y
superadministrador). Ver evaluaciones/metricas.py para las definiciones."""
from __future__ import annotations

from uuid import UUID

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from cuentas.models import Entidad, Rol, Usuario
from cuentas.seguridad import requiere_rol, sesion_activa
from evaluaciones import metricas

router = Router(auth=sesion_activa, tags=["métricas"])


@router.get("", response=dict)
def ver_metricas(request: HttpRequest, anio: int | None = None, mes: int | None = None, entidad_id: UUID | None = None) -> dict:
    """El administrador ve su entidad. El superadministrador ve cualquiera o
    todas juntas: son cifras agregadas, sin proponentes ni códigos de proceso,
    así que no exigen el permiso temporal con que se abren los procesos."""
    usuario: Usuario = request.auth
    requiere_rol(usuario, [Rol.ADMIN_ENTIDAD])
    if mes is not None and not 1 <= mes <= 12:
        raise HttpError(400, "Mes no válido.")
    if anio is not None and not 2000 <= anio <= 2100:
        raise HttpError(400, "Año no válido.")
    entidad = entidad_id if usuario.es_superadmin else usuario.entidad_id
    datos = metricas.calcular(entidad, anio, mes)
    datos["periodo"] = {"anio": anio, "mes": mes, "anios_disponibles": metricas.anios_disponibles(entidad)}
    datos["entidad_id"] = str(entidad) if entidad else None
    if usuario.es_superadmin:
        datos["entidades"] = [{"id": str(e.id), "nombre": e.nombre} for e in Entidad.objects.order_by("nombre")]
    return datos
