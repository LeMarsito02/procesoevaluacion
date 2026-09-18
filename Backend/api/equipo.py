"""Gestión del equipo de una entidad (usuarios, áreas) y de las entidades de
la plataforma (solo superadministrador).

Las cuentas las crea el administrador: el sistema genera una contraseña
temporal, se muestra una sola vez para entregarla a la persona, y esta debe
cambiarla al primer ingreso."""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from typing import Literal

from django.core.files.base import ContentFile

from api.auth import AreaOut, UsuarioOut, usuario_out
from evaluaciones import servicios
from evaluaciones.models import PlantillaEvaluacion, PlantillaInforme
from motor import criterios
from cuentas.correo import enviar_acceso_soporte, enviar_clave_reiniciada, enviar_cuenta_creada
from cuentas.models import AccesoSoporte, Area, Entidad, EventoAuditoria, Rol, TipoArea, Usuario
from cuentas.seguridad import auditar, clave_temporal, de_mi_entidad, requiere_rol, sesion_activa

equipo = Router(tags=["equipo"], auth=sesion_activa)
plataforma = Router(tags=["plataforma"], auth=sesion_activa)

ROLES_ASIGNABLES = {Rol.ADMIN_ENTIDAD, Rol.JEFE_AREA, Rol.EVALUADOR, Rol.CONSULTA}


# --- Esquemas ---
class CrearUsuarioIn(Schema):
    nombre_completo: str
    email: str
    rol: str
    areas: list[str] = []  # tipos: juridica / tecnica / financiera


class ActualizarUsuarioIn(Schema):
    rol: str | None = None
    areas: list[str] | None = None
    activo: bool | None = None


class MiembroOut(UsuarioOut):
    activo: bool
    ultimo_ingreso: datetime | None
    # Aún no ha entrado a cambiar la contraseña temporal que le entregaron.
    debe_cambiar_clave: bool


class CredencialesOut(Schema):
    """Se devuelve una sola vez: la contraseña no queda guardada en claro."""

    usuario: MiembroOut
    password_temporal: str


class EntidadIn(Schema):
    nombre: str
    nit: str
    email_admin: str
    nombre_admin: str
    # Sigla con la que aparece en códigos de proceso y pólizas (ej. IDU, ANI).
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


class EntidadCreadaOut(Schema):
    entidad: EntidadOut
    credenciales: CredencialesOut


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
    return MiembroOut(
        **usuario_out(u).dict(), activo=u.is_active, ultimo_ingreso=u.last_login, debe_cambiar_clave=u.debe_cambiar_clave
    )


def crear_usuario_con_clave(
    request: HttpRequest, entidad: Entidad, nombre: str, email: str, rol: str, tipos_area: list[str]
) -> tuple[Usuario, str]:
    """Crea la cuenta con una contraseña temporal y la devuelve para entregarla
    en persona. Nunca se guarda en claro ni se envía por correo."""
    email = email.strip().lower()
    nombre = " ".join(nombre.split())
    if rol not in ROLES_ASIGNABLES:
        raise HttpError(400, "Rol no válido.")
    if "@" not in email:
        raise HttpError(400, "Correo no válido.")
    if len(nombre) < 5:
        raise HttpError(400, "Escriba el nombre completo de la persona.")
    if Usuario.objects.filter(email=email).exists():
        raise HttpError(409, "Ya existe un usuario con ese correo.")
    areas = _areas(entidad, tipos_area)
    clave = clave_temporal()
    with transaction.atomic():
        usuario = Usuario.objects.create_user(
            email, clave, nombre_completo=nombre, entidad=entidad, rol=rol, debe_cambiar_clave=True
        )
        usuario.areas.set(areas)
        auditar(request, "usuario.creado", entidad_id=entidad.id, objeto=usuario, email=email, rol=rol)
        creador = request.auth
        transaction.on_commit(lambda: enviar_cuenta_creada(usuario, creador))
    return usuario, clave


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
        if datos.rol not in ROLES_ASIGNABLES:
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


@equipo.post("/usuarios", response={201: CredencialesOut})
def crear_usuario(request: HttpRequest, datos: CrearUsuarioIn, entidad_id: UUID | None = None):
    """Crea la cuenta y devuelve la contraseña temporal (se muestra una vez)."""
    requiere_rol(request.auth, (Rol.ADMIN_ENTIDAD,))
    entidad = _entidad_objetivo(request.auth, entidad_id)
    usuario, clave = crear_usuario_con_clave(request, entidad, datos.nombre_completo, datos.email, datos.rol, datos.areas)
    return 201, CredencialesOut(usuario=_miembro_out(usuario), password_temporal=clave)


@equipo.post("/usuarios/{usuario_id}/clave", response=CredencialesOut)
def reiniciar_clave(request: HttpRequest, usuario_id: UUID) -> CredencialesOut:
    """Le pone una contraseña temporal nueva a alguien que perdió la suya."""
    actor: Usuario = request.auth
    requiere_rol(actor, (Rol.ADMIN_ENTIDAD,))
    objetivo = get_object_or_404(de_mi_entidad(Usuario.objects.exclude(rol=Rol.SUPERADMIN), actor), pk=usuario_id)
    if objetivo.pk == actor.pk:
        raise HttpError(400, "Cambie su propia contraseña desde «Mi cuenta».")
    clave = clave_temporal()
    objetivo.set_password(clave)  # invalida sus sesiones abiertas
    objetivo.debe_cambiar_clave = True
    objetivo.save(update_fields=["password", "debe_cambiar_clave"])
    auditar(request, "usuario.clave_reiniciada", entidad_id=objetivo.entidad_id, objeto=objetivo, email=objetivo.email)
    transaction.on_commit(lambda: enviar_clave_reiniciada(objetivo, actor))
    return CredencialesOut(usuario=_miembro_out(objetivo), password_temporal=clave)


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


@plataforma.post("/entidades", response={201: EntidadCreadaOut})
def crear_entidad(request: HttpRequest, datos: EntidadIn):
    """Crea la entidad con sus tres áreas y la cuenta de su primer administrador,
    cuya contraseña temporal se devuelve una sola vez."""
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
            admin, clave = crear_usuario_con_clave(
                request, entidad, datos.nombre_admin, datos.email_admin, Rol.ADMIN_ENTIDAD, []
            )
    except IntegrityError as exc:
        raise HttpError(409, "Ya existe una entidad con ese NIT.") from exc
    return 201, EntidadCreadaOut(
        entidad=_entidad_out(entidad), credenciales=CredencialesOut(usuario=_miembro_out(admin), password_temporal=clave)
    )


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


class CredencialesSoporteOut(Schema):
    soporte: SoporteOut
    password_temporal: str


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


@plataforma.post("/soporte", response={201: CredencialesSoporteOut})
def crear_soporte(request: HttpRequest, datos: CrearSoporteIn):
    """Crea una cuenta de soporte de LeMarTek con contraseña temporal; la
    persona la cambia y configura su segundo factor al primer ingreso."""
    _solo_superadmin(request)
    email = datos.email.strip().lower()
    nombre = " ".join(datos.nombre_completo.split())
    if not email.endswith("@lemartek.com"):
        raise HttpError(400, "El soporte debe usar un correo @lemartek.com.")
    if Usuario.objects.filter(email=email).exists():
        raise HttpError(409, "Ya existe un usuario con ese correo.")
    clave = clave_temporal()
    usuario = Usuario.objects.create_user(email, clave, nombre_completo=nombre, rol=Rol.SOPORTE, debe_cambiar_clave=True)
    creador = request.auth
    transaction.on_commit(lambda: enviar_cuenta_creada(usuario, creador))
    auditar(request, "soporte.cuenta_creada", entidad_id=None, objeto=usuario, email=email)
    return 201, CredencialesSoporteOut(
        soporte=SoporteOut(id=usuario.id, nombre_completo=usuario.nombre_completo, email=usuario.email),
        password_temporal=clave,
    )


# --- Salario mínimo por año (plataforma) ---
class SalarioMinimoOut(Schema):
    ano: int
    valor: int
    norma: str
    actualizado_por: str | None
    actualizado_en: datetime


class SalarioMinimoIn(Schema):
    valor: int
    norma: str = ""


def _salario_out(s) -> SalarioMinimoOut:
    return SalarioMinimoOut(
        ano=s.ano, valor=s.valor, norma=s.norma,
        actualizado_por=s.actualizado_por.nombre_completo if s.actualizado_por else None, actualizado_en=s.actualizado_en,
    )


@plataforma.get("/salarios-minimos", response=list[SalarioMinimoOut])
def listar_salarios_minimos(request: HttpRequest) -> list[SalarioMinimoOut]:
    _solo_superadmin(request)
    from evaluaciones.models import SalarioMinimo

    return [_salario_out(s) for s in SalarioMinimo.objects.select_related("actualizado_por")]


@plataforma.put("/salarios-minimos/{ano}", response=SalarioMinimoOut)
def guardar_salario_minimo(request: HttpRequest, ano: int, datos: SalarioMinimoIn) -> SalarioMinimoOut:
    """Cada diciembre el Gobierno fija el del año siguiente: se registra aquí y
    lo usan los procesos que cierran ese año."""
    _solo_superadmin(request)
    from evaluaciones.models import SalarioMinimo

    if not 2000 <= ano <= 2100:
        raise HttpError(400, "Año no válido.")
    if not 100_000 <= datos.valor <= 100_000_000:
        raise HttpError(400, "Escriba el valor mensual en pesos, sin puntos (ej. 1750905).")
    anterior = SalarioMinimo.objects.filter(ano=ano).values_list("valor", flat=True).first()
    s, _ = SalarioMinimo.objects.update_or_create(
        ano=ano, defaults={"valor": datos.valor, "norma": " ".join(datos.norma.split())[:200], "actualizado_por": request.auth}
    )
    auditar(request, "plataforma.salario_minimo", entidad_id=None, ano=ano, anterior=anterior, valor=datos.valor, norma=s.norma)
    return _salario_out(s)
