"""Entidades (clientes de MiEvaluador) y usuarios.

Cada usuario pertenece a una entidad, excepto el superadministrador de la
plataforma. El aislamiento completo entre entidades (consultas filtradas,
Row-Level Security) se construye sobre estos modelos en la fase F1.
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
    is_active = models.BooleanField("activo", default=True)
    is_staff = models.BooleanField("acceso al panel de administración", default=False)
    creado_en = models.DateTimeField(default=timezone.now)

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
