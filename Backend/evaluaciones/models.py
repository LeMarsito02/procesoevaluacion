"""Procesos de contratación, sus evaluaciones (jurídica, técnica, financiera),
los resultados del motor y las revisiones humanas.

Toda tabla lleva `entidad` (aunque se pueda deducir del proceso) para que la
Row-Level Security de PostgreSQL filtre sin joins.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from cuentas.models import Entidad, TipoArea

# RUT (Requisito 13): el abogado indicó ignorarlo; no cuenta para avance ni pendientes.
REQUISITOS_IGNORADOS = frozenset({13})


class Proceso(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entidad = models.ForeignKey(Entidad, on_delete=models.PROTECT, related_name="procesos")
    codigo = models.CharField(max_length=80)
    fecha_cierre = models.DateField()
    objeto = models.TextField(blank=True)
    # ProcesoDocumentoBase del motor (lotes, garantía, advertencias).
    documento_base = models.JSONField()
    carpeta_drive = models.CharField(max_length=500, blank=True)
    proponentes_no_reconocidos = models.JSONField(default=list, blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en"]
        constraints = [models.UniqueConstraint(fields=["entidad", "codigo"], name="proceso_codigo_unico_por_entidad")]

    def __str__(self) -> str:
        return self.codigo


class Proponente(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entidad = models.ForeignKey(Entidad, on_delete=models.PROTECT, related_name="+")
    proceso = models.ForeignKey(Proceso, on_delete=models.CASCADE, related_name="proponentes")
    numero_orden = models.PositiveIntegerField()
    hoja = models.CharField(max_length=20)
    nombre = models.CharField(max_length=300)
    nombre_archivo = models.CharField(max_length=500)
    drive_file_id = models.CharField(max_length=200)
    advertencia = models.TextField(blank=True)

    class Meta:
        ordering = ["numero_orden"]
        constraints = [models.UniqueConstraint(fields=["proceso", "hoja"], name="proponente_hoja_unica")]


class EstadoEvaluacion(models.TextChoices):
    SIN_ASIGNAR = "sin_asignar", "Sin asignar"
    ASIGNADA = "asignada", "Asignada"
    EVALUANDO = "evaluando", "Evaluando"
    EN_REVISION = "en_revision", "En revisión"
    APROBADA = "aprobada", "Aprobada"


class Evaluacion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entidad = models.ForeignKey(Entidad, on_delete=models.PROTECT, related_name="+")
    proceso = models.ForeignKey(Proceso, on_delete=models.CASCADE, related_name="evaluaciones")
    tipo = models.CharField(max_length=20, choices=TipoArea.choices)
    estado = models.CharField(max_length=20, choices=EstadoEvaluacion.choices, default=EstadoEvaluacion.SIN_ASIGNAR)
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="evaluaciones"
    )
    asignada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    asignada_en = models.DateTimeField(null=True, blank=True)
    aprobada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    aprobada_en = models.DateTimeField(null=True, blank=True)
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creada_en"]
        constraints = [models.UniqueConstraint(fields=["proceso", "tipo"], name="evaluacion_tipo_unico_por_proceso")]


class Resultado(models.Model):
    """Resultado del motor para un requisito de un proponente."""

    id = models.BigAutoField(primary_key=True)
    entidad = models.ForeignKey(Entidad, on_delete=models.PROTECT, related_name="+")
    evaluacion = models.ForeignKey(Evaluacion, on_delete=models.CASCADE, related_name="resultados")
    proponente = models.ForeignKey(Proponente, on_delete=models.CASCADE, related_name="resultados")
    requisito = models.PositiveSmallIntegerField()
    # ResultadoRequisito completo del motor.
    datos = models.JSONField()
    # Necesita revisión humana: error, o no cumple y no es "N.A.".
    requiere_revision = models.BooleanField()
    evaluado_en = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["evaluacion", "proponente", "requisito"], name="resultado_unico")
        ]


class Revision(models.Model):
    """Decisión de una persona sobre un requisito (prevalece sobre el motor)."""

    id = models.BigAutoField(primary_key=True)
    entidad = models.ForeignKey(Entidad, on_delete=models.PROTECT, related_name="+")
    evaluacion = models.ForeignKey(Evaluacion, on_delete=models.CASCADE, related_name="revisiones")
    proponente = models.ForeignKey(Proponente, on_delete=models.CASCADE, related_name="revisiones")
    requisito = models.PositiveSmallIntegerField()
    cumple = models.BooleanField()
    nota = models.TextField(blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    fecha = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["evaluacion", "proponente", "requisito"], name="revision_unica")
        ]
