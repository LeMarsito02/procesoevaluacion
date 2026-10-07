"""Quién puede ver, trabajar, asignar y aprobar cada evaluación."""
from __future__ import annotations

from django.db.models import Q
from ninja.errors import HttpError

from cuentas.models import Rol, Usuario
from evaluaciones.models import EstadoEvaluacion, Evaluacion


def tiene_area(usuario: Usuario, tipo: str) -> bool:
    return any(a.tipo == tipo for a in usuario.areas.all())


def de_su_entidad(usuario: Usuario, evaluacion: Evaluacion) -> bool:
    # El superadmin, solo las entidades que le dieron un permiso temporal
    # (LEG-004, 4.5).
    from cuentas.seguridad import ve_datos_de

    if usuario.es_superadmin:
        return ve_datos_de(usuario, evaluacion.entidad_id)
    return evaluacion.entidad_id == usuario.entidad_id


def ve_toda_la_entidad(usuario: Usuario) -> bool:
    """Administrador de la entidad, y LeMarTek con el permiso temporal que ese
    administrador otorga (superadministrador y soporte, solo lectura)."""
    return usuario.es_superadmin or usuario.rol in (Rol.ADMIN_ENTIDAD, Rol.SOPORTE)


def puede_ver(usuario: Usuario, evaluacion: Evaluacion) -> bool:
    """Una evaluación es reservada: la ve su comité evaluador designado (y su
    coordinador), quien la gestiona (jefe de la dependencia o del área) y el
    administrador. Pertenecer a la entidad no basta."""
    from evaluaciones.estructura import es_miembro

    if not de_su_entidad(usuario, evaluacion):
        return False
    return (
        ve_toda_la_entidad(usuario)
        or evaluacion.responsable_id == usuario.id
        or es_miembro(usuario, evaluacion)
        or puede_gestionar(usuario, evaluacion)
    )


def filtro_visibles(usuario: Usuario) -> Q | None:
    """Lo mismo que `puede_ver`, como filtro de consulta (None = sin filtro,
    ya limitado a su entidad). Úsese con `.distinct()`."""
    if ve_toda_la_entidad(usuario):
        return None
    filtro = Q(responsable=usuario) | Q(comite__usuario=usuario, comite__retirado_en__isnull=True)
    if usuario.rol != Rol.CONSULTA:
        filtro |= Q(dependencia__jefes=usuario)
    if usuario.rol == Rol.JEFE_AREA:
        filtro |= Q(dependencia__isnull=True, tipo__in=[a.tipo for a in usuario.areas.all()])
    return filtro


def puede_gestionar(usuario: Usuario, evaluacion: Evaluacion) -> bool:
    """Asignar, aprobar y reabrir: administrador, o jefe del área de la evaluación."""
    if not de_su_entidad(usuario, evaluacion):
        return False
    if usuario.es_superadmin or usuario.rol == Rol.ADMIN_ENTIDAD:
        return True
    # Con estructura por dependencias, la gestiona quien sea jefe de esa
    # dependencia (es un cargo en ella, sea cual sea su rol); sin ella
    # (evaluaciones anteriores), el jefe del área.
    if evaluacion.dependencia_id:
        return usuario.rol != Rol.CONSULTA and evaluacion.dependencia.jefes.filter(pk=usuario.pk).exists()
    return usuario.rol == Rol.JEFE_AREA and tiene_area(usuario, evaluacion.tipo)


def puede_trabajar(usuario: Usuario, evaluacion: Evaluacion) -> bool:
    """Evaluar y revisar: los miembros del comité (el coordinador incluido) o
    quien gestiona la evaluación."""
    from evaluaciones.estructura import es_miembro

    if usuario.rol in (Rol.CONSULTA, Rol.SOPORTE) or not de_su_entidad(usuario, evaluacion):
        return False
    return (
        evaluacion.responsable_id == usuario.id
        or es_miembro(usuario, evaluacion)
        or puede_gestionar(usuario, evaluacion)
    )


def puede_crear_procesos(usuario: Usuario) -> bool:
    """Todos menos consulta: los abogados también crean sus propios procesos."""
    return usuario.rol in (Rol.SUPERADMIN, Rol.ADMIN_ENTIDAD, Rol.JEFE_AREA, Rol.EVALUADOR)


def exigir_trabajo(usuario: Usuario, evaluacion: Evaluacion) -> None:
    if not puede_trabajar(usuario, evaluacion):
        raise HttpError(403, "Solo el comité evaluador o el jefe de la dependencia pueden modificar esta evaluación.")
    if evaluacion.estado == EstadoEvaluacion.APROBADA:
        raise HttpError(409, "La evaluación está aprobada. Pida al jefe del área que la reabra para modificarla.")


def compromiso_pendiente(usuario: Usuario) -> bool:
    """El compromiso de uso (LEG-004, 6.4) aplica a quien decide requisitos."""
    from evaluaciones.cumplimiento import COMPROMISO_VERSION

    if usuario.rol in (Rol.CONSULTA, Rol.SOPORTE):
        return False
    return usuario.compromiso_version != COMPROMISO_VERSION


def exigir_compromiso(usuario: Usuario) -> None:
    if compromiso_pendiente(usuario):
        raise HttpError(
            409, "Antes de decidir, acepte el compromiso de uso de MiEvaluador (se muestra al iniciar sesión)."
        )


def exigir_gestion(usuario: Usuario, evaluacion: Evaluacion) -> None:
    if not puede_gestionar(usuario, evaluacion):
        raise HttpError(403, "Solo el jefe del área o el administrador pueden hacer esto.")


def puede_eliminar_proceso(usuario: Usuario, proceso) -> bool:
    """El administrador de la entidad, el superadministrador o quien lo creó
    (los abogados crean sus propios procesos y pueden equivocarse al crearlos)."""
    if usuario.rol == Rol.CONSULTA:
        return False
    if usuario.es_superadmin:
        from cuentas.seguridad import ve_datos_de

        return ve_datos_de(usuario, proceso.entidad_id)
    if proceso.entidad_id != usuario.entidad_id:
        return False
    return usuario.rol == Rol.ADMIN_ENTIDAD or proceso.creado_por_id == usuario.id
