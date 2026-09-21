"""Quién puede ver, trabajar, asignar y aprobar cada evaluación."""
from __future__ import annotations

from ninja.errors import HttpError

from cuentas.models import Rol, Usuario
from evaluaciones.models import EstadoEvaluacion, Evaluacion


def tiene_area(usuario: Usuario, tipo: str) -> bool:
    return any(a.tipo == tipo for a in usuario.areas.all())


def puede_ver(usuario: Usuario, evaluacion: Evaluacion) -> bool:
    # Todos los de la entidad consultan (solo lectura); el superadmin, todo.
    return usuario.es_superadmin or evaluacion.entidad_id == usuario.entidad_id


def puede_gestionar(usuario: Usuario, evaluacion: Evaluacion) -> bool:
    """Asignar, aprobar y reabrir: administrador, o jefe del área de la evaluación."""
    if not puede_ver(usuario, evaluacion):
        return False
    if usuario.es_superadmin or usuario.rol == Rol.ADMIN_ENTIDAD:
        return True
    return usuario.rol == Rol.JEFE_AREA and tiene_area(usuario, evaluacion.tipo)


def puede_trabajar(usuario: Usuario, evaluacion: Evaluacion) -> bool:
    """Evaluar y revisar: el responsable o quien gestiona el área."""
    if usuario.rol == Rol.CONSULTA or not puede_ver(usuario, evaluacion):
        return False
    return evaluacion.responsable_id == usuario.id or puede_gestionar(usuario, evaluacion)


def puede_crear_procesos(usuario: Usuario) -> bool:
    """Todos menos consulta: los abogados también crean sus propios procesos."""
    return usuario.rol in (Rol.SUPERADMIN, Rol.ADMIN_ENTIDAD, Rol.JEFE_AREA, Rol.EVALUADOR)


def exigir_trabajo(usuario: Usuario, evaluacion: Evaluacion) -> None:
    if not puede_trabajar(usuario, evaluacion):
        raise HttpError(403, "Solo el responsable o el jefe del área pueden modificar esta evaluación.")
    if evaluacion.estado == EstadoEvaluacion.APROBADA:
        raise HttpError(409, "La evaluación está aprobada. Pida al jefe del área que la reabra para modificarla.")


def exigir_gestion(usuario: Usuario, evaluacion: Evaluacion) -> None:
    if not puede_gestionar(usuario, evaluacion):
        raise HttpError(403, "Solo el jefe del área o el administrador pueden hacer esto.")


def puede_eliminar_proceso(usuario: Usuario, proceso) -> bool:
    """El administrador de la entidad, el superadministrador o quien lo creó
    (los abogados crean sus propios procesos y pueden equivocarse al crearlos)."""
    if usuario.rol == Rol.CONSULTA:
        return False
    if usuario.es_superadmin:
        return True
    if proceso.entidad_id != usuario.entidad_id:
        return False
    return usuario.rol == Rol.ADMIN_ENTIDAD or proceso.creado_por_id == usuario.id
