"""Inicio de sesión, segundo factor, cambio obligatorio de la contraseña
temporal y recuperación de contraseña."""
from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

import pyotp
from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.utils import check_csrf

from cuentas.correo import enviar_recuperacion
from cuentas.models import AccesoSoporte, Usuario
from cuentas.seguridad import auditar, inicio_bloqueado, ip_de, registrar_intento, sesion_activa

router = Router(tags=["autenticación"])

VIGENCIA_PENDIENTE = 5 * 60
MAX_FALLOS_2FA = 5
MENSAJE_CREDENCIALES = "Correo o contraseña incorrectos."


# --- Esquemas ---
class AreaOut(Schema):
    id: UUID
    tipo: str
    nombre: str


class EntidadResumen(Schema):
    id: UUID
    nombre: str


class UsuarioOut(Schema):
    id: UUID
    email: str
    nombre_completo: str
    rol: str
    rol_nombre: str
    entidad: EntidadResumen | None
    areas: list[AreaOut]
    # Soporte de LeMarTek: hasta cuándo puede ver la entidad elegida (solo lectura).
    acceso_soporte_hasta: datetime | None = None


class CsrfOut(Schema):
    csrf: str


class LoginIn(Schema):
    email: str
    password: str


class LoginOut(Schema):
    # "ok": sesión iniciada. "cambiar_clave": entró con la contraseña temporal
    # y debe elegir una propia. "verificar_2fa": falta el código de la app.
    # "configurar_2fa": el rol exige 2FA y aún no está configurado.
    estado: str
    csrf: str
    usuario: UsuarioOut | None = None


class Configurar2faOut(Schema):
    otpauth_uri: str
    secreto: str


class CodigoIn(Schema):
    codigo: str


class RecuperarIn(Schema):
    email: str


class RestablecerIn(Schema):
    uid: str
    token: str
    password: str


class CambiarClaveIn(Schema):
    actual: str
    nueva: str


class ClaveInicialIn(Schema):
    nueva: str


def usuario_out(usuario: Usuario) -> UsuarioOut:
    return UsuarioOut(
        id=usuario.id,
        email=usuario.email,
        nombre_completo=usuario.nombre_completo,
        rol=usuario.rol,
        rol_nombre=usuario.get_rol_display(),
        entidad=EntidadResumen(id=usuario.entidad.id, nombre=usuario.entidad.nombre) if usuario.entidad else None,
        areas=[AreaOut(id=a.id, tipo=a.tipo, nombre=a.get_tipo_display()) for a in usuario.areas.all()],
        acceso_soporte_hasta=getattr(getattr(usuario, "acceso_soporte", None), "expira_en", None),
    )


def _exigir_csrf(request: HttpRequest) -> None:
    # Las rutas sin sesión también verifican CSRF (evita "login CSRF").
    if check_csrf(request) is not None:
        raise HttpError(403, "La sesión del navegador expiró. Recarga la página.")


def _validar_clave(password: str, usuario: Usuario) -> None:
    try:
        validate_password(password, usuario)
    except ValidationError as exc:
        raise HttpError(400, " ".join(exc.messages)) from exc


def _iniciar(request: HttpRequest, usuario: Usuario, segundo_factor: bool) -> LoginOut:
    login(request, usuario, backend="django.contrib.auth.backends.ModelBackend")
    request.session["segundo_factor_ok"] = segundo_factor
    registrar_intento(usuario.email, ip_de(request), exitoso=True)
    auditar(request, "sesion.inicio", usuario=usuario, segundo_factor=segundo_factor)
    return LoginOut(estado="ok", csrf=get_token(request), usuario=usuario_out(usuario))


def _usuario_pendiente(request: HttpRequest) -> Usuario:
    """Quien ya acertó su contraseña pero aún no tiene sesión: le falta cambiar
    la contraseña temporal o pasar el segundo factor."""
    usuario_id = request.session.get("pendiente_usuario")
    desde = request.session.get("pendiente_desde", 0)
    if not usuario_id or time.time() - desde > VIGENCIA_PENDIENTE:
        request.session.pop("pendiente_usuario", None)
        raise HttpError(401, "Vuelve a ingresar tu correo y contraseña.")
    usuario = Usuario.objects.filter(pk=usuario_id, is_active=True).first()
    if usuario is None:
        raise HttpError(401, "Vuelve a ingresar tu correo y contraseña.")
    return usuario


def _pendiente(request: HttpRequest, usuario: Usuario, estado: str) -> LoginOut:
    request.session["pendiente_usuario"] = str(usuario.pk)
    request.session["pendiente_desde"] = time.time()
    return LoginOut(estado=estado, csrf=get_token(request))


def _siguiente_paso(request: HttpRequest, usuario: Usuario) -> LoginOut:
    """Qué falta después de acertar la contraseña: cambiarla si es temporal,
    luego el segundo factor si el rol lo exige, y si no, entrar."""
    if usuario.debe_cambiar_clave:
        return _pendiente(request, usuario, "cambiar_clave")
    if not usuario.requiere_2fa:
        return _iniciar(request, usuario, segundo_factor=False)
    return _pendiente(request, usuario, "verificar_2fa" if usuario.totp_activo else "configurar_2fa")


# --- Rutas ---
@router.get("/csrf", response=CsrfOut)
def csrf(request: HttpRequest) -> CsrfOut:
    return CsrfOut(csrf=get_token(request))


@router.post("/login", response=LoginOut)
def iniciar_sesion(request: HttpRequest, datos: LoginIn) -> LoginOut:
    _exigir_csrf(request)
    email = datos.email.strip().lower()
    ip = ip_de(request)
    if inicio_bloqueado(email, ip):
        raise HttpError(429, "Demasiados intentos fallidos. Espera 15 minutos e inténtalo de nuevo.")

    usuario = authenticate(request, username=email, password=datos.password)
    if usuario is None or (usuario.entidad_id and not usuario.entidad.activa):
        registrar_intento(email, ip, exitoso=False)
        raise HttpError(401, MENSAJE_CREDENCIALES)

    # Contraseña correcta; si falta algún paso, aún no hay sesión.
    request.session.cycle_key()
    request.session["2fa_fallos"] = 0
    return _siguiente_paso(request, usuario)


@router.post("/2fa/configurar", response=Configurar2faOut)
def configurar_2fa(request: HttpRequest) -> Configurar2faOut:
    _exigir_csrf(request)
    usuario = _usuario_pendiente(request)
    if usuario.debe_cambiar_clave:
        raise HttpError(400, "Primero cambia tu contraseña temporal.")
    if usuario.totp_activo:
        raise HttpError(400, "El segundo factor ya está configurado.")
    usuario.totp_secreto = pyotp.random_base32()
    usuario.save(update_fields=["totp_secreto"])
    # Las apps que aceptan el parámetro `image` (FreeOTP, 2FAS, Ente Auth…) muestran
    # el logo; debe ser una URL pública HTTPS. Authy ignora el parámetro.
    logo = f"{settings.FRONTEND_URL}/icono-mievaluador.png"
    extra = {"image": logo} if logo.startswith("https://") else {}
    uri = pyotp.TOTP(usuario.totp_secreto).provisioning_uri(name=usuario.email, issuer_name="MiEvaluador", **extra)
    return Configurar2faOut(otpauth_uri=uri, secreto=usuario.totp_secreto)


@router.post("/2fa/verificar", response=LoginOut)
def verificar_2fa(request: HttpRequest, datos: CodigoIn) -> LoginOut:
    _exigir_csrf(request)
    usuario = _usuario_pendiente(request)
    if usuario.debe_cambiar_clave:
        raise HttpError(400, "Primero cambia tu contraseña temporal.")
    codigo = "".join(c for c in datos.codigo if c.isdigit())
    if not usuario.totp_secreto or not pyotp.TOTP(usuario.totp_secreto).verify(codigo, valid_window=1):
        fallos = request.session.get("2fa_fallos", 0) + 1
        request.session["2fa_fallos"] = fallos
        registrar_intento(usuario.email, ip_de(request), exitoso=False)
        if fallos >= MAX_FALLOS_2FA:
            request.session.flush()
            raise HttpError(401, "Demasiados códigos incorrectos. Vuelve a iniciar sesión.")
        raise HttpError(401, "Código incorrecto.")

    for clave in ("pendiente_usuario", "pendiente_desde", "2fa_fallos"):
        request.session.pop(clave, None)
    if not usuario.totp_activo:
        usuario.totp_activo = True
        usuario.save(update_fields=["totp_activo"])
        auditar(request, "usuario.2fa_activado", usuario=usuario, objeto=usuario)
    return _iniciar(request, usuario, segundo_factor=True)


@router.post("/logout", auth=sesion_activa)
def cerrar_sesion(request: HttpRequest) -> dict[str, bool]:
    auditar(request, "sesion.cierre")
    logout(request)
    return {"ok": True}


@router.get("/yo", auth=sesion_activa, response=UsuarioOut)
def yo(request: HttpRequest) -> UsuarioOut:
    return usuario_out(request.auth)


@router.post("/cambiar-clave", auth=sesion_activa)
def cambiar_clave(request: HttpRequest, datos: CambiarClaveIn) -> dict[str, bool]:
    usuario: Usuario = request.auth
    if not usuario.check_password(datos.actual):
        raise HttpError(400, "La contraseña actual no es correcta.")
    _validar_clave(datos.nueva, usuario)
    usuario.set_password(datos.nueva)
    usuario.debe_cambiar_clave = False
    usuario.save(update_fields=["password", "debe_cambiar_clave"])
    update_session_auth_hash(request, usuario)  # cierra las demás sesiones, conserva esta
    auditar(request, "usuario.cambio_clave", objeto=usuario)
    return {"ok": True}


@router.post("/recuperar")
def recuperar_clave(request: HttpRequest, datos: RecuperarIn) -> dict[str, bool]:
    _exigir_csrf(request)
    email = datos.email.strip().lower()
    ip = ip_de(request)
    if inicio_bloqueado(email, ip):
        raise HttpError(429, "Demasiados intentos. Espera 15 minutos e inténtalo de nuevo.")
    # Cuenta como intento para limitar el envío masivo de correos.
    registrar_intento(email, ip, exitoso=False)
    usuario = Usuario.objects.filter(email=email, is_active=True).first()
    if usuario is not None:
        uid = urlsafe_base64_encode(force_bytes(usuario.pk))
        enviar_recuperacion(usuario, uid, default_token_generator.make_token(usuario))
        auditar(request, "usuario.recuperacion_solicitada", usuario=usuario, objeto=usuario)
    # Misma respuesta exista o no la cuenta: no revela qué correos están registrados.
    return {"ok": True}


@router.post("/restablecer")
def restablecer_clave(request: HttpRequest, datos: RestablecerIn) -> dict[str, bool]:
    _exigir_csrf(request)
    try:
        usuario = Usuario.objects.get(pk=force_str(urlsafe_base64_decode(datos.uid)), is_active=True)
    except (ValueError, ValidationError, Usuario.DoesNotExist):
        usuario = None
    if usuario is None or not default_token_generator.check_token(usuario, datos.token):
        raise HttpError(400, "El enlace no es válido o ya venció. Solicita uno nuevo.")
    _validar_clave(datos.password, usuario)
    usuario.set_password(datos.password)
    usuario.debe_cambiar_clave = False
    usuario.save(update_fields=["password", "debe_cambiar_clave"])  # invalida el enlace y las sesiones abiertas
    auditar(request, "usuario.clave_restablecida", usuario=usuario, objeto=usuario)
    return {"ok": True}


@router.post("/clave-inicial", response=LoginOut)
def fijar_clave_inicial(request: HttpRequest, datos: ClaveInicialIn) -> LoginOut:
    """Cambio obligatorio de la contraseña temporal, antes de tener sesión."""
    _exigir_csrf(request)
    usuario = _usuario_pendiente(request)
    if not usuario.debe_cambiar_clave:
        raise HttpError(400, "Esta cuenta ya tiene contraseña definitiva.")
    if usuario.check_password(datos.nueva):
        raise HttpError(400, "Elige una contraseña distinta de la temporal.")
    _validar_clave(datos.nueva, usuario)
    usuario.set_password(datos.nueva)
    usuario.debe_cambiar_clave = False
    usuario.save(update_fields=["password", "debe_cambiar_clave"])
    auditar(request, "usuario.clave_inicial", usuario=usuario, objeto=usuario)
    # Sigue el camino normal: si su rol exige segundo factor, aún falta ese paso.
    return _siguiente_paso(request, usuario)


# --- Soporte de LeMarTek ---
class AccesoDisponibleOut(Schema):
    entidad: EntidadResumen
    expira_en: datetime
    motivo: str


class EntrarSoporteIn(Schema):
    entidad_id: UUID


def _solo_soporte(usuario: Usuario) -> None:
    if not usuario.es_soporte:
        raise HttpError(403, "Solo para el personal de soporte de LeMarTek.")


@router.get("/soporte/accesos", auth=sesion_activa, response=list[AccesoDisponibleOut])
def accesos_de_soporte(request: HttpRequest) -> list[AccesoDisponibleOut]:
    _solo_soporte(request.auth)
    accesos = AccesoSoporte.objects.filter(
        soporte=request.auth, revocado_en__isnull=True, expira_en__gt=timezone.now(), entidad__activa=True
    ).select_related("entidad")
    return [
        AccesoDisponibleOut(entidad=EntidadResumen(id=a.entidad.id, nombre=a.entidad.nombre), expira_en=a.expira_en, motivo=a.motivo)
        for a in accesos
    ]


@router.post("/soporte/entrar", auth=sesion_activa, response=UsuarioOut)
def entrar_como_soporte(request: HttpRequest, datos: EntrarSoporteIn) -> UsuarioOut:
    usuario: Usuario = request.auth
    _solo_soporte(usuario)
    request.session["soporte_entidad"] = str(datos.entidad_id)
    request.user = usuario  # se vuelve a evaluar el permiso con la entidad elegida
    sesion_activa.authenticate(request, None)
    if usuario.entidad_id is None:
        raise HttpError(403, "No tiene un permiso vigente para esa entidad.")
    auditar(request, "soporte.ingreso", usuario=usuario, entidad_id=usuario.entidad_id, hasta=usuario.acceso_soporte.expira_en.isoformat())
    return usuario_out(usuario)


@router.post("/soporte/salir", auth=sesion_activa, response=UsuarioOut)
def salir_de_entidad(request: HttpRequest) -> UsuarioOut:
    usuario: Usuario = request.auth
    _solo_soporte(usuario)
    request.session.pop("soporte_entidad", None)
    usuario.entidad = None
    usuario.acceso_soporte = None
    return usuario_out(usuario)
