"""Autenticación, permisos por rol, bloqueo de fuerza bruta y auditoría.

Reglas de aislamiento: todo usuario, excepto el superadministrador, solo ve
datos de su propia entidad. Las consultas de datos de entidad deben pasar por
`de_mi_entidad` (o filtrar explícitamente por `usuario.entidad_id`).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Iterable

from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone
from ninja.errors import HttpError
from ninja.security import APIKeyCookie
from django.conf import settings

from cuentas.models import EventoAuditoria, IntentoInicioSesion, Rol, Usuario

# --- Bloqueo de fuerza bruta ---
VENTANA_BLOQUEO = timedelta(minutes=15)
MAX_FALLOS_POR_CORREO = 5
MAX_FALLOS_POR_IP = 30


class SesionActiva(APIKeyCookie):
    """Sesión de Django válida, usuario activo, entidad activa y, si el rol
    lo exige, segundo factor verificado. Verifica también el token CSRF."""

    param_name = settings.SESSION_COOKIE_NAME

    def authenticate(self, request: HttpRequest, key: str | None) -> Usuario | None:
        usuario = request.user
        if not usuario.is_authenticated or not usuario.is_active:
            return None
        if usuario.entidad_id is not None and not usuario.entidad.activa:
            return None
        if usuario.requiere_2fa and not request.session.get("segundo_factor_ok"):
            return None
        return usuario


sesion_activa = SesionActiva()


def requiere_rol(usuario: Usuario, roles: Iterable[str]) -> None:
    """El superadministrador pasa siempre; los demás solo con uno de `roles`."""
    if usuario.es_superadmin or usuario.rol in set(roles):
        return
    raise HttpError(403, "No tienes permiso para esta acción.")


def de_mi_entidad(qs: QuerySet, usuario: Usuario, campo: str = "entidad") -> QuerySet:
    """Restringe un queryset a la entidad del usuario (el superadmin ve todo)."""
    if usuario.es_superadmin:
        return qs
    return qs.filter(**{f"{campo}_id": usuario.entidad_id})


def ip_de(request: HttpRequest) -> str | None:
    # Detrás del proxy de producción, la IP real llega en X-Forwarded-For.
    reenviada = request.META.get("HTTP_X_FORWARDED_FOR") if not settings.DEBUG else None
    if reenviada:
        return reenviada.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def inicio_bloqueado(email: str, ip: str | None) -> bool:
    desde = timezone.now() - VENTANA_BLOQUEO
    fallidos = IntentoInicioSesion.objects.filter(exitoso=False, fecha__gte=desde)
    if fallidos.filter(email=email).count() >= MAX_FALLOS_POR_CORREO:
        return True
    return ip is not None and fallidos.filter(ip=ip).count() >= MAX_FALLOS_POR_IP


def registrar_intento(email: str, ip: str | None, exitoso: bool) -> None:
    IntentoInicioSesion.objects.create(email=email, ip=ip, exitoso=exitoso)
    if exitoso:
        # Un inicio correcto limpia los fallos previos de ese correo.
        IntentoInicioSesion.objects.filter(email=email, exitoso=False).delete()


def auditar(
    request: HttpRequest | None,
    accion: str,
    *,
    usuario: Usuario | None = None,
    entidad_id=None,
    objeto=None,
    **detalles,
) -> None:
    if usuario is None and request is not None and request.user.is_authenticated:
        usuario = request.user
    if entidad_id is None and usuario is not None:
        entidad_id = usuario.entidad_id
    EventoAuditoria.objects.create(
        usuario=usuario,
        entidad_id=entidad_id,
        accion=accion,
        objeto_tipo=type(objeto).__name__ if objeto is not None else "",
        objeto_id=str(getattr(objeto, "pk", "")) if objeto is not None else "",
        detalles=detalles,
        ip=ip_de(request) if request is not None else None,
    )


# --- Tokens de un solo uso (invitaciones) ---
def nuevo_token() -> tuple[str, str]:
    """Devuelve (token para el enlace, hash para guardar)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


ROLES_GESTION_EQUIPO = (Rol.ADMIN_ENTIDAD,)
