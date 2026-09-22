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
    # Análisis del pliego con el que se creó el proceso y lo que decidió la
    # persona sobre cada hallazgo: [{id, decision, por, por_id, en, nota, hallazgo}].
    analisis_pliego = models.ForeignKey(
        "AnalisisPliego", on_delete=models.PROTECT, null=True, blank=True, related_name="procesos"
    )
    ajustes_pliego = models.JSONField(default=list, blank=True)
    # Parámetros de la evaluación técnica leídos del pliego (presupuesto de
    # cada lote, experiencia exigida, códigos UNSPSC, tabla de valor mínimo):
    # motor.tecnica.evaluador.parametros_a_dict. Se calculan la primera vez.
    parametros_tecnicos = models.JSONField(null=True, blank=True)
    # Retención: fecha en que se borraron las copias de los documentos de los
    # proponentes (se conservan resultados, decisiones e informes).
    documentos_eliminados_en = models.DateTimeField(null=True, blank=True)
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
    # Versión de la plantilla de evaluación con la que se evalúa (None = la base del sistema).
    plantilla = models.ForeignKey("PlantillaEvaluacion", on_delete=models.PROTECT, null=True, blank=True, related_name="evaluaciones")
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


class EstadoTrabajo(models.TextChoices):
    EN_FILA = "en_fila", "En fila"
    PROCESANDO = "procesando", "Procesando"
    TERMINADO = "terminado", "Terminado"
    ERROR = "error", "Error"
    CANCELADO = "cancelado", "Cancelado"


class Trabajo(models.Model):
    """Evaluación de un proponente en la fila central.

    Sin Row-Level Security a propósito: la fila es compartida y el tiempo
    estimado de cada entidad depende de los trabajos de las demás. No guarda
    contenido de documentos, solo identificadores y estado; la API siempre
    filtra por entidad antes de mostrar algo.
    """

    id = models.BigAutoField(primary_key=True)
    entidad = models.ForeignKey(Entidad, on_delete=models.PROTECT, related_name="+")
    evaluacion = models.ForeignKey(Evaluacion, on_delete=models.CASCADE, related_name="trabajos")
    proponente = models.ForeignKey(Proponente, on_delete=models.CASCADE, related_name="trabajos")
    estado = models.CharField(max_length=20, choices=EstadoTrabajo.choices, default=EstadoTrabajo.EN_FILA, db_index=True)
    # Turno dentro de su evaluación: la fila atiende primero los turnos bajos de
    # todas las evaluaciones (reparto por turnos, una grande no bloquea a otra).
    turno = models.PositiveIntegerField()
    solicitado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    creado_en = models.DateTimeField(auto_now_add=True)
    iniciado_en = models.DateTimeField(null=True, blank=True)
    terminado_en = models.DateTimeField(null=True, blank=True)
    latido = models.DateTimeField(null=True, blank=True)
    trabajador = models.CharField(max_length=120, blank=True)
    intentos = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["estado", "turno", "creado_en"], name="trabajo_orden_fila")]
        constraints = [
            # Un proponente no puede estar dos veces pendiente en la misma evaluación.
            models.UniqueConstraint(
                fields=["evaluacion", "proponente"],
                condition=models.Q(estado__in=["en_fila", "procesando"]),
                name="trabajo_pendiente_unico",
            )
        ]


class Trabajador(models.Model):
    """Proceso que atiende la fila (se registra y envía latidos)."""

    id = models.CharField(primary_key=True, max_length=120)
    capacidad = models.PositiveSmallIntegerField()
    iniciado_en = models.DateTimeField(auto_now_add=True)
    latido = models.DateTimeField()


def _ruta_plantilla(instancia: "PlantillaInforme", nombre: str) -> str:
    # Archivos separados por entidad; el nombre original no se usa en disco.
    return f"entidades/{instancia.entidad_id}/plantillas/{instancia.tipo}/{uuid.uuid4().hex}.xlsx"


class PlantillaInforme(models.Model):
    """Plantilla de Excel del informe de una entidad para un tipo de evaluación."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entidad = models.ForeignKey(Entidad, on_delete=models.CASCADE, related_name="plantillas")
    tipo = models.CharField(max_length=20, choices=TipoArea.choices)
    nombre_original = models.CharField(max_length=255)
    archivo = models.FileField(upload_to=_ruta_plantilla, max_length=300)
    # MapeoPlantilla del motor (dónde escribir cada dato).
    mapeo = models.JSONField()
    # Resultado de revisar la plantilla con su mapeo (hojas, texto de cada fila, problemas).
    inspeccion = models.JSONField(default=dict)
    activa = models.BooleanField(default=True)
    subida_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    subida_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-subida_en"]
        constraints = [
            models.UniqueConstraint(
                fields=["entidad", "tipo"], condition=models.Q(activa=True), name="plantilla_activa_unica"
            )
        ]


class PlantillaEvaluacion(models.Model):
    """Cómo evalúa una entidad un tipo de evaluación: requisitos, verificación
    de cada uno, parámetros y (opcional) su plantilla de Excel. Cada cambio es
    una versión nueva; las evaluaciones guardan la versión con la que se hicieron."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entidad = models.ForeignKey(Entidad, on_delete=models.CASCADE, related_name="plantillas_evaluacion")
    tipo = models.CharField(max_length=20, choices=TipoArea.choices)
    version = models.PositiveIntegerField()
    nombre = models.CharField(max_length=200)
    # motor.criterios.DefinicionEvaluacion
    definicion = models.JSONField()
    nota = models.TextField(blank=True)
    activa = models.BooleanField(default=True)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["entidad", "tipo", "version"], name="plantilla_evaluacion_version_unica"),
            models.UniqueConstraint(
                fields=["entidad", "tipo"], condition=models.Q(activa=True), name="plantilla_evaluacion_activa_unica"
            ),
        ]


class TipoPersona(models.TextChoices):
    NATURAL = "natural", "Persona natural"
    JURIDICA = "juridica", "Persona jurídica"


class RolPersona(models.TextChoices):
    PROPONENTE = "proponente", "Proponente"
    REPRESENTANTE = "representante_legal", "Representante legal"
    SUPLENTE = "suplente", "Representante legal suplente"
    INTEGRANTE = "integrante", "Integrante del consorcio o unión temporal"


class PersonaVerificada(models.Model):
    """Persona (natural o jurídica) cuyos antecedentes se verifican para un proponente.

    - Persona natural: nombre, cédula y fecha de expedición de la cédula.
    - Persona jurídica: razón social y NIT, con su representante legal (y suplente si lo tiene)
      registrados como personas hijas (`de`).
    - Consorcio / unión temporal: cada integrante es una persona con rol "integrante" y, si es
      jurídica, sus representantes cuelgan de ella.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entidad = models.ForeignKey(Entidad, on_delete=models.PROTECT, related_name="+")
    evaluacion = models.ForeignKey(Evaluacion, on_delete=models.CASCADE, related_name="personas")
    proponente = models.ForeignKey(Proponente, on_delete=models.CASCADE, related_name="personas")
    de = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="representantes")
    rol = models.CharField(max_length=30, choices=RolPersona.choices)
    tipo = models.CharField(max_length=10, choices=TipoPersona.choices)
    nombre = models.CharField(max_length=300)
    # Cédula (persona natural) o NIT (persona jurídica).
    documento = models.CharField(max_length=30)
    fecha_expedicion_documento = models.DateField(null=True, blank=True)
    # La detectó el programa en la oferta (no la agregó el evaluador): se
    # actualiza sola cuando se vuelve a evaluar.
    detectada = models.BooleanField(default=False)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["creada_en"]


def _ruta_aportado(instancia: "DocumentoAportado", nombre: str) -> str:
    return f"entidades/{instancia.entidad_id}/evaluaciones/{instancia.evaluacion_id}/aportados/{uuid.uuid4().hex}.pdf"


class DocumentoAportado(models.Model):
    """Certificado que el evaluador consultó y subió porque el proponente no lo aportó."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entidad = models.ForeignKey(Entidad, on_delete=models.PROTECT, related_name="+")
    evaluacion = models.ForeignKey(Evaluacion, on_delete=models.CASCADE, related_name="documentos_aportados")
    proponente = models.ForeignKey(Proponente, on_delete=models.CASCADE, related_name="documentos_aportados")
    persona = models.ForeignKey(PersonaVerificada, on_delete=models.PROTECT, null=True, blank=True, related_name="documentos")
    requisito = models.PositiveSmallIntegerField()
    fecha_expedicion = models.DateField()
    nombre_original = models.CharField(max_length=255)
    archivo = models.FileField(upload_to=_ruta_aportado, max_length=300)
    observacion = models.TextField(blank=True)
    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    subido_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["subido_en"]


class EstadoExpediente(models.TextChoices):
    PENDIENTE = "pendiente", "Pendiente"
    GENERANDO = "generando", "Generando"
    LISTO = "listo", "Listo"
    ERROR = "error", "Error"


def _ruta_expediente(instancia: "Expediente", nombre: str) -> str:
    return f"entidades/{instancia.entidad_id}/expedientes/{instancia.evaluacion_id}/v{instancia.version}.zip"


class Expediente(models.Model):
    """Archivo final permanente de una evaluación aprobada: documentos evaluados,
    certificados aportados, informe Excel, reporte Word y registro de resultados.
    No lo borra la retención; cada reaprobación crea una versión nueva."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entidad = models.ForeignKey(Entidad, on_delete=models.PROTECT, related_name="+")
    evaluacion = models.ForeignKey(Evaluacion, on_delete=models.PROTECT, related_name="expedientes")
    version = models.PositiveIntegerField()
    estado = models.CharField(max_length=20, choices=EstadoExpediente.choices, default=EstadoExpediente.PENDIENTE)
    archivo = models.FileField(upload_to=_ruta_expediente, max_length=300, blank=True)
    tamano = models.BigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    error = models.TextField(blank=True)
    solicitado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    creado_en = models.DateTimeField(auto_now_add=True)
    terminado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["evaluacion", "version"], name="expediente_version_unica")]


def _ruta_pliego(instance: "AnalisisPliego", filename: str) -> str:
    return f"pliegos/{instance.entidad_id}/{instance.sha256}.pdf"


class AnalisisPliego(models.Model):
    """Lectura completa de un pliego para una entidad. Se identifica por la
    huella SHA-256 del PDF: si la entidad vuelve a subir el mismo pliego, se
    reutiliza en vez de leerlo otra vez. Lo que se guarda es independiente de
    la plantilla de la entidad; la comparación con ella se hace al crear cada
    proceso."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entidad = models.ForeignKey(Entidad, on_delete=models.PROTECT, related_name="+")
    sha256 = models.CharField(max_length=64)
    nombre_archivo = models.CharField(max_length=300)
    archivo = models.FileField(upload_to=_ruta_pliego, max_length=300)
    paginas = models.PositiveIntegerField()
    documento_tipo = models.CharField(max_length=80, blank=True)
    # motor.pliego.analisis.Extraccion
    extraccion = models.JSONField()
    version = models.PositiveIntegerField()
    # Lectura profunda con IA local (motor.pliego.lector_ia): todos los
    # requisitos jurídicos del pliego. Corre en el trabajador de la fila.
    estado_ia = models.CharField(max_length=20, default="pendiente")  # pendiente | leyendo | listo | error | no_disponible
    progreso_ia = models.PositiveSmallIntegerField(default=0)  # 0-100
    requisitos_ia = models.JSONField(default=list, blank=True)  # [motor.pliego.lector_ia.RequisitoPliego]
    modelo_ia = models.CharField(max_length=80, blank=True)
    version_ia = models.PositiveIntegerField(default=0)
    error_ia = models.TextField(blank=True)
    ia_iniciada = models.DateTimeField(null=True, blank=True)
    ia_terminada = models.DateTimeField(null=True, blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado_en"]
        constraints = [models.UniqueConstraint(fields=["entidad", "sha256"], name="pliego_unico_por_entidad")]

    def __str__(self) -> str:
        return self.nombre_archivo


class SalarioMinimo(models.Model):
    """Salario mínimo mensual legal vigente de cada año (lo fija el Gobierno
    cada diciembre). Es de la plataforma, no de una entidad: el superadmin lo
    actualiza cada año y cada proceso usa el del año de su fecha de cierre."""

    ano = models.PositiveIntegerField("año", primary_key=True)
    valor = models.PositiveIntegerField()
    norma = models.CharField(max_length=200, blank=True)
    actualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-ano"]
        verbose_name = "salario mínimo"
        verbose_name_plural = "salarios mínimos"

    def __str__(self) -> str:
        return f"{self.ano}: ${self.valor:,}"


class MedicionRendimiento(models.Model):
    """Foto de la analítica de rendimiento (evaluaciones.analitica): el programa
    contra evaluaciones reales ya hechas por entidades. La genera el comando
    `manage.py medir_rendimiento`; el tablero muestra la última."""

    id = models.BigAutoField(primary_key=True)
    creada_en = models.DateTimeField(auto_now_add=True)
    datos = models.JSONField()
    nota = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-creada_en"]
