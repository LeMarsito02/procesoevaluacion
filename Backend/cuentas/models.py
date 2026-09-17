"""Entidades (clientes de MiEvaluador) y usuarios.

Cada usuario pertenece a una entidad, excepto el superadministrador de la
plataforma. El aislamiento completo entre entidades (consultas filtradas,
Row-Level Security) se aplica sobre las tablas de datos de cada entidad
(procesos, evaluaciones, documentos) a partir de la fase F2.
"""
from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Entidad(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nombre = models.CharField(max_length=200)
    nit = models.CharField("NIT", max_length=20, unique=True)
    activa = models.BooleanField(default=True)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "entidad"
        verbose_name_plural = "entidades"
        ordering = ["nombre"]

    def __str__(self) -> str:
        return self.nombre


class TipoArea(models.TextChoices):
    JURIDICA = "juridica", "Jurídica"
    TECNICA = "tecnica", "Técnica"
    FINANCIERA = "financiera", "Financiera"


class Area(models.Model):
    """Área de evaluación de una entidad (ej. el equipo jurídico del ICCU)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entidad = models.ForeignKey(Entidad, on_delete=models.CASCADE, related_name="areas")
    tipo = models.CharField(max_length=20, choices=TipoArea.choices)

    class Meta:
        verbose_name = "área"
        verbose_name_plural = "áreas"
        ordering = ["entidad__nombre", "tipo"]
        constraints = [models.UniqueConstraint(fields=["entidad", "tipo"], name="area_unica_por_entidad")]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} · {self.entidad}"


class Rol(models.TextChoices):
    SUPERADMIN = "superadmin", "Superadministrador"
    ADMIN_ENTIDAD = "admin_entidad", "Administrador de entidad"
    JEFE_AREA = "jefe_area", "Jefe de área"
    EVALUADOR = "evaluador", "Evaluador"
    CONSULTA = "consulta", "Consulta"


class UsuarioManager(BaseUserManager["Usuario"]):
    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **campos) -> "Usuario":
        if not email:
            raise ValueError("El usuario debe tener correo electrónico.")
        usuario = self.model(email=self.normalize_email(email).lower(), **campos)
        usuario.set_password(password)
        usuario.full_clean(exclude=["password"])
        usuario.save(using=self._db)
        return usuario

    def create_superuser(self, email: str, password: str | None = None, **campos) -> "Usuario":
        campos.update(rol=Rol.SUPERADMIN, entidad=None, is_staff=True, is_superuser=True)
        return self.create_user(email, password, **campos)


class Usuario(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField("correo electrónico", unique=True)
    nombre_completo = models.CharField(max_length=200)
    entidad = models.ForeignKey(Entidad, on_delete=models.PROTECT, null=True, blank=True, related_name="usuarios")
    rol = models.CharField(max_length=20, choices=Rol.choices, default=Rol.EVALUADOR)
    areas = models.ManyToManyField(Area, blank=True, related_name="usuarios")
    is_active = models.BooleanField("activo", default=True)
    is_staff = models.BooleanField("acceso al panel de administración", default=False)
    creado_en = models.DateTimeField(default=timezone.now)
    # Segundo factor (TOTP). Obligatorio para el superadministrador.
    totp_secreto = models.CharField(max_length=64, blank=True, editable=False)
    totp_activo = models.BooleanField("2FA activo", default=False)

    objects = UsuarioManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["nombre_completo"]

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["nombre_completo"]
        constraints = [
            # Solo el superadministrador puede no pertenecer a una entidad, y
            # un superadministrador nunca pertenece a una entidad.
            models.CheckConstraint(
                condition=(Q(rol=Rol.SUPERADMIN) & Q(entidad__isnull=True))
                | (~Q(rol=Rol.SUPERADMIN) & Q(entidad__isnull=False)),
                name="usuario_entidad_segun_rol",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.nombre_completo} <{self.email}>"

    @property
    def es_superadmin(self) -> bool:
        return self.rol == Rol.SUPERADMIN

    @property
    def requiere_2fa(self) -> bool:
        return self.es_superadmin


class Invitacion(models.Model):
    """Invitación a una entidad. Solo se guarda el hash del token: quien lea
    la base de datos no puede usar las invitaciones pendientes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entidad = models.ForeignKey(Entidad, on_delete=models.CASCADE, related_name="invitaciones")
    email = models.EmailField("correo electrónico")
    rol = models.CharField(max_length=20, choices=[c for c in Rol.choices if c[0] != Rol.SUPERADMIN])
    areas = models.ManyToManyField(Area, blank=True)
    token_hash = models.CharField(max_length=64, unique=True)
    invitada_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, related_name="+")
    creada_en = models.DateTimeField(auto_now_add=True)
    expira_en = models.DateTimeField()
    aceptada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "invitación"
        verbose_name_plural = "invitaciones"
        ordering = ["-creada_en"]

    def __str__(self) -> str:
        return f"{self.email} → {self.entidad}"

    @property
    def vigente(self) -> bool:
        return self.aceptada_en is None and self.expira_en > timezone.now()


class IntentoInicioSesion(models.Model):
    """Registro de intentos de inicio de sesión, para bloquear temporalmente
    ataques de fuerza bruta por correo y por IP."""

    email = models.EmailField(db_index=True)
    ip = models.GenericIPAddressField(null=True, db_index=True)
    exitoso = models.BooleanField(default=False)
    fecha = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "intento de inicio de sesión"
        verbose_name_plural = "intentos de inicio de sesión"
        ordering = ["-fecha"]


class EventoAuditoria(models.Model):
    """Registro inmutable de acciones relevantes (quién, qué, cuándo, desde dónde)."""

    id = models.BigAutoField(primary_key=True)
    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    entidad = models.ForeignKey(Entidad, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    accion = models.CharField(max_length=80, db_index=True)
    objeto_tipo = models.CharField(max_length=80, blank=True)
    objeto_id = models.CharField(max_length=64, blank=True)
    detalles = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "evento de auditoría"
        verbose_name_plural = "auditoría"
        ordering = ["-fecha"]

    def save(self, *args, **kwargs):
        if self._state.adding is False:
            raise ValueError("Los eventos de auditoría no se pueden modificar.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Los eventos de auditoría no se pueden eliminar.")
