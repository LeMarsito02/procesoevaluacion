"""Gestión del equipo de una entidad (usuarios, invitaciones, áreas) y de las
entidades de la plataforma (solo superadministrador)."""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.contrib.auth.tokens import default_token_generator
from django.shortcuts import get_object_or_404
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from typing import Literal

from django.core.files.base import ContentFile

from api.auth import AreaOut, UsuarioOut, usuario_out
from evaluaciones import servicios
from evaluaciones.models import PlantillaEvaluacion, PlantillaInforme
from motor import criterios
from cuentas.correo import enviar_acceso_soporte, enviar_invitacion, enviar_recuperacion
from cuentas.models import AccesoSoporte, Area, Entidad, EventoAuditoria, Invitacion, Rol, TipoArea, Usuario
from cuentas.seguridad import auditar, de_mi_entidad, nuevo_token, requiere_rol, sesion_activa

equipo = Router(tags=["equipo"], auth=sesion_activa)
plataforma = Router(tags=["plataforma"], auth=sesion_activa)

ROLES_INVITABLES = {Rol.ADMIN_ENTIDAD, Rol.JEFE_AREA, Rol.EVALUADOR, Rol.CONSULTA}


# --- Esquemas ---
class InvitarIn(Schema):
    email: str
    rol: str
    areas: list[str] = []  # tipos: juridica / tecnica / financiera


class InvitacionOut(Schema):
    id: UUID
    email: str
    rol: str
    rol_nombre: str
    areas: list[str]
    creada_en: datetime
    expira_en: datetime
    vigente: bool


class ActualizarUsuarioIn(Schema):
    rol: str | None = None
    areas: list[str] | None = None
    activo: bool | None = None


class MiembroOut(UsuarioOut):
    activo: bool
    ultimo_ingreso: datetime | None


class EntidadIn(Schema):
    nombre: str
    nit: str
    email_admin: str
    # Sigla con la que aparece en códigos de proceso y pólizas (ej. ICCU, IDU).
    sigla: str = ""
    # Cómo evaluará: "sistema" = base del sistema adaptada a su sigla;
    # "copiar" = plantillas (evaluación y Excel) de otra entidad.
    base: Literal["sistema", "copiar"] = "sistema"
    copiar_de: UUID | None = None


class EntidadOut(Schema):
    id: UUID
    nombre: str
    nit: str
    activa: bool
    usuarios: int
    creada_en: datetime


class ActualizarEntidadIn(Schema):
    activa: bool


class EventoOut(Schema):
    fecha: datetime
    usuario: str | None
    accion: str
    objeto_tipo: str
    objeto_id: str
    detalles: dict
    ip: str | None


# --- Utilidades ---
def _entidad_objetivo(usuario: Usuario, entidad_id: UUID | None) -> Entidad:
    """Entidad sobre la que se actúa: la propia, o la indicada si es superadmin."""
    if usuario.es_superadmin:
        if entidad_id is None:
            raise HttpError(400, "Indica la entidad.")
        return get_object_or_404(Entidad, pk=entidad_id)
    if entidad_id is not None and entidad_id != usuario.entidad_id:
        raise HttpError(404, "No encontrado.")
    return usuario.entidad


def _areas(entidad: Entidad, tipos: list[str]) -> list[Area]:
    validos = set(TipoArea.values)
    desconocidos = set(tipos) - validos
    if desconocidos:
        raise HttpError(400, f"Área no válida: {', '.join(sorted(desconocidos))}.")
    return list(Area.objects.filter(entidad=entidad, tipo__in=tipos))


def _miembro_out(u: Usuario) -> MiembroOut:
    return MiembroOut(**usuario_out(u).dict(), activo=u.is_active, ultimo_ingreso=u.last_login)


def _invitacion_out(inv: Invitacion) -> InvitacionOut:
    return InvitacionOut(
        id=inv.id,
        email=inv.email,
        rol=inv.rol,
        rol_nombre=inv.get_rol_display(),
        areas=[a.tipo for a in inv.areas.all()],
        creada_en=inv.creada_en,
        expira_en=inv.expira_en,
        vigente=inv.vigente,
    )


def crear_invitacion(request: HttpRequest, entidad: Entidad, email: str, rol: str, tipos_area: list[str]) -> Invitacion:
    email = email.strip().lower()
    if rol not in ROLES_INVITABLES:
        raise HttpError(400, "Rol no válido.")
    if "@" not in email:
        raise HttpError(400, "Correo no válido.")
    if Usuario.objects.filter(email=email).exists():
        raise HttpError(409, "Ya existe un usuario con ese correo.")
    areas = _areas(entidad, tipos_area)
    token, token_hash = nuevo_token()
    with transaction.atomic():
        # Una invitación nueva reemplaza las pendientes del mismo correo.
        Invitacion.objects.filter(entidad=entidad, email=email, aceptada_en__isnull=True).delete()
        invitacion = Invitacion.objects.create(
            entidad=entidad,
            email=email,
            rol=rol,
            token_hash=token_hash,
            invitada_por=request.auth,
            expira_en=timezone.now() + timedelta(days=settings.INVITACION_VIGENCIA_DIAS),
        )
        invitacion.areas.set(areas)
        auditar(request, "invitacion.creada", entidad_id=entidad.id, objeto=invitacion, email=email, rol=rol)
        transaction.on_commit(lambda: enviar_invitacion(invitacion, token))
    return invitacion


# --- Equipo de la entidad ---
@equipo.get("/areas", response=list[AreaOut])
def listar_areas(request: HttpRequest, entidad_id: UUID | None = None) -> list[AreaOut]:
    entidad = _entidad_objetivo(request.auth, entidad_id)
    return [AreaOut(id=a.id, tipo=a.tipo, nombre=a.get_tipo_display()) for a in entidad.areas.all()]


@equipo.get("/usuarios", response=list[MiembroOut])
def listar_usuarios(request: HttpRequest, entidad_id: UUID | None = None) -> list[MiembroOut]:
    usuario: Usuario = request.auth
    requiere_rol(usuario, (Rol.ADMIN_ENTIDAD, Rol.JEFE_AREA))
    entidad = _entidad_objetivo(usuario, entidad_id)
    qs = Usuario.objects.filter(entidad=entidad).select_related("entidad").prefetch_related("areas")
    if usuario.rol == Rol.JEFE_AREA:
        # El jefe ve a quienes comparten alguna de sus áreas.
        qs = qs.filter(areas__in=usuario.areas.all()).distinct()
    return [_miembro_out(u) for u in qs]


@equipo.patch("/usuarios/{usuario_id}", response=MiembroOut)
def actualizar_usuario(request: HttpRequest, usuario_id: UUID, datos: ActualizarUsuarioIn) -> MiembroOut:
    actor: Usuario = request.auth
    requiere_rol(actor, (Rol.ADMIN_ENTIDAD,))
    objetivo = get_object_or_404(de_mi_entidad(Usuario.objects.exclude(rol=Rol.SUPERADMIN), actor), pk=usuario_id)
    if objetivo.pk == actor.pk and (datos.rol is not None or datos.activo is False):
        raise HttpError(400, "No puedes cambiar tu propio rol ni desactivarte.")

    cambios: dict = {}
    if datos.rol is not None and datos.rol != objetivo.rol:
        if datos.rol not in ROLES_INVITABLES:
            raise HttpError(400, "Rol no válido.")
        cambios["rol"] = [objetivo.rol, datos.rol]
        objetivo.rol = datos.rol
    if datos.activo is not None and datos.activo != objetivo.is_active:
        cambios["activo"] = [objetivo.is_active, datos.activo]
        objetivo.is_active = datos.activo
    # Un usuario desactivado pierde el acceso de inmediato: la autenticación
    # rechaza sus sesiones abiertas en la siguiente petición.
    with transaction.atomic():
        objetivo.save()
        if datos.areas is not None:
            antes = sorted(a.tipo for a in objetivo.areas.all())
            objetivo.areas.set(_areas(objetivo.entidad, datos.areas))
            if antes != sorted(datos.areas):
                cambios["areas"] = [antes, sorted(datos.areas)]
        if cambios:
            auditar(request, "usuario.actualizado", entidad_id=objetivo.entidad_id, objeto=objetivo, **cambios)
    return _miembro_out(objetivo)


@equipo.get("/invitaciones", response=list[InvitacionOut])
def listar_invitaciones(request: HttpRequest, entidad_id: UUID | None = None) -> list[InvitacionOut]:
    requiere_rol(request.auth, (Rol.ADMIN_ENTIDAD,))
    entidad = _entidad_objetivo(request.auth, entidad_id)
    qs = Invitacion.objects.filter(entidad=entidad, aceptada_en__isnull=True).prefetch_related("areas")
    return [_invitacion_out(i) for i in qs]


@equipo.post("/invitaciones", response={201: InvitacionOut})
def invitar(request: HttpRequest, datos: InvitarIn, entidad_id: UUID | None = None):
    requiere_rol(request.auth, (Rol.ADMIN_ENTIDAD,))
    entidad = _entidad_objetivo(request.auth, entidad_id)
    return 201, _invitacion_out(crear_invitacion(request, entidad, datos.email, datos.rol, datos.areas))


@equipo.delete("/invitaciones/{invitacion_id}", response={204: None})
def revocar_invitacion(request: HttpRequest, invitacion_id: UUID):
    requiere_rol(request.auth, (Rol.ADMIN_ENTIDAD,))
    invitacion = get_object_or_404(
        de_mi_entidad(Invitacion.objects.filter(aceptada_en__isnull=True), request.auth), pk=invitacion_id
    )
    auditar(request, "invitacion.revocada", entidad_id=invitacion.entidad_id, objeto=invitacion, email=invitacion.email)
    invitacion.delete()
    return 204, None


# --- Plataforma (solo superadministrador) ---
def _solo_superadmin(request: HttpRequest) -> None:
    if not request.auth.es_superadmin:
        raise HttpError(403, "No tienes permiso para esta acción.")


def _entidad_out(e: Entidad) -> EntidadOut:
    return EntidadOut(id=e.id, nombre=e.nombre, nit=e.nit, activa=e.activa, usuarios=e.usuarios.count(), creada_en=e.creada_en)


@plataforma.get("/entidades", response=list[EntidadOut])
def listar_entidades(request: HttpRequest) -> list[EntidadOut]:
    _solo_superadmin(request)
    return [_entidad_out(e) for e in Entidad.objects.all()]


@plataforma.post("/entidades", response={201: EntidadOut})
def crear_entidad(request: HttpRequest, datos: EntidadIn):
    """Crea la entidad con sus tres áreas e invita a su primer administrador."""
    _solo_superadmin(request)
    nombre = " ".join(datos.nombre.split())
    nit = datos.nit.strip()
    if not nombre or not nit:
        raise HttpError(400, "Nombre y NIT son obligatorios.")
    try:
        with transaction.atomic():
            entidad = Entidad.objects.create(nombre=nombre, nit=nit)
            Area.objects.bulk_create([Area(entidad=entidad, tipo=t) for t in TipoArea.values])
            auditar(request, "entidad.creada", entidad_id=entidad.id, objeto=entidad, nombre=nombre, nit=nit)
            _plantillas_iniciales(request, entidad, datos)
            crear_invitacion(request, entidad, datos.email_admin, Rol.ADMIN_ENTIDAD, [])
    except IntegrityError as exc:
        raise HttpError(409, "Ya existe una entidad con ese NIT.") from exc
    return 201, _entidad_out(entidad)


def _plantillas_iniciales(request: HttpRequest, entidad: Entidad, datos: EntidadIn) -> None:
    usuario = request.auth
    if datos.base == "copiar":
        if datos.copiar_de is None:
            raise HttpError(400, "Elija la entidad de la que se copian las plantillas.")
        origen = get_object_or_404(Entidad, pk=datos.copiar_de)
        for p in PlantillaEvaluacion.objects.filter(entidad=origen, activa=True):
            servicios.nueva_version(
                entidad.id, p.tipo, p.nombre, criterios.DefinicionEvaluacion.model_validate(p.definicion), usuario,
                f"Copiada de {origen.nombre} (versión {p.version}).",
            )
        for pi in PlantillaInforme.objects.filter(entidad=origen, activa=True):
            copia = PlantillaInforme(
                entidad=entidad, tipo=pi.tipo, nombre_original=pi.nombre_original, mapeo=pi.mapeo, inspeccion=pi.inspeccion, subida_por=usuario
            )
            with pi.archivo.open("rb") as f:
                copia.archivo.save(pi.nombre_original, ContentFile(f.read()), save=False)
            copia.save()
        return
    definicion = servicios.definicion_base_para(TipoArea.JURIDICA, datos.sigla, entidad.nombre)
    servicios.nueva_version(
        entidad.id, TipoArea.JURIDICA, f"Evaluación jurídica {datos.sigla.strip().upper() or entidad.nombre}", definicion, usuario,
        "Base del sistema al crear la entidad.",
    )


@plataforma.patch("/entidades/{entidad_id}", response=EntidadOut)
def actualizar_entidad(request: HttpRequest, entidad_id: UUID, datos: ActualizarEntidadIn) -> EntidadOut:
    _solo_superadmin(request)
    entidad = get_object_or_404(Entidad, pk=entidad_id)
    if entidad.activa != datos.activa:
        entidad.activa = datos.activa
        entidad.save(update_fields=["activa"])
        auditar(request, "entidad.activada" if datos.activa else "entidad.suspendida", entidad_id=entidad.id, objeto=entidad)
    return _entidad_out(entidad)


@equipo.get("/auditoria", response=list[EventoOut])
def ver_auditoria(request: HttpRequest, entidad_id: UUID | None = None, limite: int = 200) -> list[EventoOut]:
    usuario: Usuario = request.auth
    requiere_rol(usuario, (Rol.ADMIN_ENTIDAD,))
    qs = EventoAuditoria.objects.select_related("usuario")
    if usuario.es_superadmin:
        if entidad_id is not None:
            qs = qs.filter(entidad_id=entidad_id)
    else:
        qs = qs.filter(entidad_id=usuario.entidad_id)
    return [
        EventoOut(
            fecha=e.fecha,
            usuario=e.usuario.email if e.usuario else None,
            accion=e.accion,
            objeto_tipo=e.objeto_tipo,
            objeto_id=e.objeto_id,
            detalles=e.detalles,
            ip=e.ip,
        )
        for e in qs[: max(1, min(limite, 1000))]
    ]


# --- Acceso temporal de soporte de LeMarTek ---
class SoporteOut(Schema):
    id: UUID
    nombre_completo: str
    email: str


class AccesoSoporteOut(Schema):
    id: UUID
    soporte: SoporteOut
    otorgado_por: str | None
    motivo: str
    creado_en: datetime
    expira_en: datetime
    revocado_en: datetime | None
    vigente: bool


class OtorgarSoporteIn(Schema):
    soporte_id: UUID
    horas: int
    motivo: str


class CrearSoporteIn(Schema):
    email: str
    nombre_completo: str


def _acceso_out(a: AccesoSoporte) -> AccesoSoporteOut:
    return AccesoSoporteOut(
        id=a.id,
        soporte=SoporteOut(id=a.soporte.id, nombre_completo=a.soporte.nombre_completo, email=a.soporte.email),
        otorgado_por=a.otorgado_por.nombre_completo if a.otorgado_por else None,
        motivo=a.motivo,
        creado_en=a.creado_en,
        expira_en=a.expira_en,
        revocado_en=a.revocado_en,
        vigente=a.vigente,
    )


@equipo.get("/soporte", response=dict)
def soporte_de_la_entidad(request: HttpRequest, entidad_id: UUID | None = None) -> dict:
    requiere_rol(request.auth, (Rol.ADMIN_ENTIDAD,))
    entidad = _entidad_objetivo(request.auth, entidad_id)
    accesos = AccesoSoporte.objects.filter(entidad=entidad).select_related("soporte", "otorgado_por")[:50]
    personal = Usuario.objects.filter(rol=Rol.SOPORTE, is_active=True).order_by("nombre_completo")
    return {
        "accesos": [_acceso_out(a).dict() for a in accesos],
        "personal": [SoporteOut(id=u.id, nombre_completo=u.nombre_completo, email=u.email).dict() for u in personal],
    }


@equipo.post("/soporte", response={201: AccesoSoporteOut})
def otorgar_soporte(request: HttpRequest, datos: OtorgarSoporteIn, entidad_id: UUID | None = None):
    usuario: Usuario = request.auth
    requiere_rol(usuario, (Rol.ADMIN_ENTIDAD,))
    entidad = _entidad_objetivo(usuario, entidad_id)
    if not 1 <= datos.horas <= 72:
        raise HttpError(400, "El acceso puede durar entre 1 y 72 horas.")
    motivo = " ".join(datos.motivo.split())
    if len(motivo) < 5:
        raise HttpError(400, "Indique el motivo del acceso (queda en la auditoría).")
    soporte = Usuario.objects.filter(pk=datos.soporte_id, rol=Rol.SOPORTE, is_active=True).first()
    if soporte is None:
        raise HttpError(400, "Esa persona no es del soporte de LeMarTek.")
    with transaction.atomic():
        acceso = AccesoSoporte.objects.create(
            entidad=entidad, soporte=soporte, otorgado_por=usuario, motivo=motivo, expira_en=timezone.now() + timedelta(hours=datos.horas)
        )
        auditar(request, "soporte.acceso_otorgado", entidad_id=entidad.id, objeto=acceso, soporte=soporte.email, horas=datos.horas, motivo=motivo)
        transaction.on_commit(lambda: enviar_acceso_soporte(acceso, soporte))
    return 201, _acceso_out(acceso)


@equipo.delete("/soporte/{acceso_id}", response={204: None})
def revocar_soporte(request: HttpRequest, acceso_id: UUID):
    usuario: Usuario = request.auth
    requiere_rol(usuario, (Rol.ADMIN_ENTIDAD,))
    acceso = get_object_or_404(de_mi_entidad(AccesoSoporte.objects.select_related("soporte"), usuario), pk=acceso_id)
    if acceso.revocado_en is None:
        acceso.revocado_en = timezone.now()
        acceso.save(update_fields=["revocado_en"])
        auditar(request, "soporte.acceso_revocado", entidad_id=acceso.entidad_id, objeto=acceso, soporte=acceso.soporte.email)
    return 204, None


@plataforma.get("/soporte", response=list[SoporteOut])
def personal_de_soporte(request: HttpRequest) -> list[SoporteOut]:
    _solo_superadmin(request)
    return [SoporteOut(id=u.id, nombre_completo=u.nombre_completo, email=u.email) for u in Usuario.objects.filter(rol=Rol.SOPORTE)]


@plataforma.post("/soporte", response={201: SoporteOut})
def crear_soporte(request: HttpRequest, datos: CrearSoporteIn):
    """Crea una cuenta de soporte de LeMarTek; la persona define su contraseña
    con el enlace de recuperación que le llega al correo."""
    _solo_superadmin(request)
    email = datos.email.strip().lower()
    if not email.endswith("@lemartek.com"):
        raise HttpError(400, "El soporte debe usar un correo @lemartek.com.")
    if Usuario.objects.filter(email=email).exists():
        raise HttpError(409, "Ya existe un usuario con ese correo.")
    usuario = Usuario.objects.create_user(email, None, nombre_completo=" ".join(datos.nombre_completo.split()), rol=Rol.SOPORTE)
    uid = urlsafe_base64_encode(force_bytes(usuario.pk))
    transaction.on_commit(lambda: enviar_recuperacion(usuario, uid, default_token_generator.make_token(usuario)))
    auditar(request, "soporte.cuenta_creada", entidad_id=None, objeto=usuario, email=email)
    return 201, SoporteOut(id=usuario.id, nombre_completo=usuario.nombre_completo, email=usuario.email)
