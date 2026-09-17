"""Procesos y evaluaciones guardados en el servidor: creación, asignación,
evaluación por proponente, revisiones, aprobación, informe y documentos."""
from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from api.ejecucion import evaluar_todos_en_proceso
from cuentas.correo import enviar_asignacion
from cuentas.models import Rol, TipoArea, Usuario
from cuentas.seguridad import auditar, sesion_activa
from evaluaciones.models import (
    REQUISITOS_IGNORADOS,
    EstadoEvaluacion,
    Evaluacion,
    Proceso,
    Proponente,
    Resultado,
    Revision,
)
from evaluaciones.permisos import (
    exigir_gestion,
    exigir_trabajo,
    puede_crear_procesos,
    puede_gestionar,
    puede_trabajar,
    puede_ver,
    tiene_area,
)
from motor.esquemas.proceso import Proponente as ProponenteMotor
from motor.esquemas.proceso import ProcesoDocumentoBase, ResultadoRequisito
from motor.excel.filler import fill_template
from motor.integrations.drive import download_file_bytes
from motor.procesamiento.zip_utils import extraer_pdfs

router = Router(tags=["evaluaciones"], auth=sesion_activa)

PLANTILLAS = {
    TipoArea.JURIDICA: Path(__file__).resolve().parent.parent / "motor" / "plantillas" / "plantilla_evaluacion_juridica.xlsx",
}
TIPOS_DISPONIBLES = {TipoArea.JURIDICA}


# --- Esquemas ---
class PersonaOut(Schema):
    id: UUID
    nombre_completo: str
    email: str


class AvanceOut(Schema):
    proponentes: int
    evaluados: int
    con_error: int
    pendientes: int
    revisados: int


class EvaluacionResumenOut(Schema):
    id: UUID
    tipo: str
    tipo_nombre: str
    estado: str
    estado_nombre: str
    responsable: PersonaOut | None
    avance: AvanceOut
    proceso_id: UUID
    proceso_codigo: str
    proceso_objeto: str
    fecha_cierre: date
    actualizada_en: datetime
    aprobada_en: datetime | None
    puede_trabajar: bool
    puede_gestionar: bool


class ProcesoResumenOut(Schema):
    id: UUID
    codigo: str
    objeto: str
    fecha_cierre: date
    creado_en: datetime
    creado_por: PersonaOut
    proponentes: int
    evaluaciones: list[EvaluacionResumenOut]


class ProponenteIn(Schema):
    numero_orden: int
    hoja: str
    nombre_proponente: str
    nombre_archivo: str
    drive_file_id: str
    advertencia: str | None = None


class CrearProcesoIn(Schema):
    documento_base: ProcesoDocumentoBase
    carpeta_drive: str = ""
    proponentes: list[ProponenteIn]
    proponentes_no_reconocidos: list[str] = []
    tipos: list[str] = [TipoArea.JURIDICA]


class ProponenteOut(Schema):
    id: UUID
    numero_orden: int
    hoja: str
    nombre_proponente: str
    nombre_archivo: str
    drive_file_id: str
    advertencia: str | None


class RevisionOut(Schema):
    proponente_id: UUID
    hoja: str
    requisito: int
    cumple: bool
    nota: str
    usuario: str
    fecha: datetime


class EvaluacionDetalleOut(Schema):
    evaluacion: EvaluacionResumenOut
    documento_base: ProcesoDocumentoBase
    carpeta_drive: str
    proponentes_no_reconocidos: list[str]
    proponentes: list[ProponenteOut]
    resultados: list[dict]
    revisiones: list[RevisionOut]


class AsignarIn(Schema):
    responsable_id: UUID | None


class RevisarIn(Schema):
    proponente_id: UUID
    requisito: int
    cumple: bool | None  # None borra la revisión
    nota: str = ""


class MiembroCargaOut(PersonaOut):
    rol: str
    rol_nombre: str
    areas: list[str]
    evaluaciones_activas: int
    pendientes: int


# --- Utilidades ---
def _persona(u: Usuario | None) -> PersonaOut | None:
    return PersonaOut(id=u.id, nombre_completo=u.nombre_completo, email=u.email) if u else None


def _avances(ids: list[UUID]) -> dict[UUID, AvanceOut]:
    """Avance de varias evaluaciones con pocas consultas."""
    if not ids:
        return {}
    evaluaciones = Evaluacion.objects.filter(id__in=ids).annotate(n=Count("proceso__proponentes", distinct=True))
    total = {e.id: e.n for e in evaluaciones}
    base = Resultado.objects.filter(evaluacion_id__in=ids).exclude(requisito__in=REQUISITOS_IGNORADOS)
    evaluados = dict(base.values("evaluacion_id").annotate(n=Count("proponente_id", distinct=True)).values_list("evaluacion_id", "n"))
    con_error = dict(
        base.exclude(datos__error=None)
        .values("evaluacion_id")
        .annotate(n=Count("proponente_id", distinct=True))
        .values_list("evaluacion_id", "n")
    )
    claves_revisadas = set(
        Revision.objects.filter(evaluacion_id__in=ids).values_list("evaluacion_id", "proponente_id", "requisito")
    )
    pendientes: dict[UUID, int] = {}
    for ev, prop, req in base.filter(requiere_revision=True).values_list("evaluacion_id", "proponente_id", "requisito"):
        if (ev, prop, req) not in claves_revisadas:
            pendientes[ev] = pendientes.get(ev, 0) + 1
    revisados: dict[UUID, int] = {}
    for ev, _, req in claves_revisadas:
        if req not in REQUISITOS_IGNORADOS:
            revisados[ev] = revisados.get(ev, 0) + 1
    return {
        i: AvanceOut(
            proponentes=total.get(i, 0),
            evaluados=evaluados.get(i, 0),
            con_error=con_error.get(i, 0),
            pendientes=pendientes.get(i, 0),
            revisados=revisados.get(i, 0),
        )
        for i in ids
    }


def _resumenes(usuario: Usuario, evaluaciones: list[Evaluacion]) -> list[EvaluacionResumenOut]:
    avances = _avances([e.id for e in evaluaciones])
    return [
        EvaluacionResumenOut(
            id=e.id,
            tipo=e.tipo,
            tipo_nombre=e.get_tipo_display(),
            estado=e.estado,
            estado_nombre=e.get_estado_display(),
            responsable=_persona(e.responsable),
            avance=avances[e.id],
            proceso_id=e.proceso_id,
            proceso_codigo=e.proceso.codigo,
            proceso_objeto=e.proceso.objeto,
            fecha_cierre=e.proceso.fecha_cierre,
            actualizada_en=e.actualizada_en,
            aprobada_en=e.aprobada_en,
            puede_trabajar=puede_trabajar(usuario, e),
            puede_gestionar=puede_gestionar(usuario, e),
        )
        for e in evaluaciones
    ]


def _evaluaciones_qs(usuario: Usuario):
    qs = Evaluacion.objects.select_related("proceso", "responsable")
    if not usuario.es_superadmin:
        qs = qs.filter(entidad_id=usuario.entidad_id)
    return qs


def _evaluacion(usuario: Usuario, evaluacion_id: UUID) -> Evaluacion:
    evaluacion = get_object_or_404(_evaluaciones_qs(usuario), pk=evaluacion_id)
    if not puede_ver(usuario, evaluacion):
        raise HttpError(404, "No encontrado.")
    return evaluacion


def _requiere_revision(r: ResultadoRequisito) -> bool:
    return bool(r.error) or (r.cumple is not True and not (r.motivo or "").startswith("N.A."))


def _actualizar_estado(evaluacion: Evaluacion) -> None:
    if evaluacion.estado == EstadoEvaluacion.APROBADA:
        return
    avance = _avances([evaluacion.id])[evaluacion.id]
    if avance.evaluados == 0:
        nuevo = EstadoEvaluacion.ASIGNADA if evaluacion.responsable_id else EstadoEvaluacion.SIN_ASIGNAR
    elif avance.evaluados < avance.proponentes:
        nuevo = EstadoEvaluacion.EVALUANDO
    else:
        nuevo = EstadoEvaluacion.EN_REVISION
    if nuevo != evaluacion.estado:
        evaluacion.estado = nuevo
        evaluacion.save(update_fields=["estado", "actualizada_en"])


def _aplicar_revision(datos: dict, revision: Revision | None) -> ResultadoRequisito:
    r = ResultadoRequisito.model_validate(datos)
    if revision is None:
        return r
    if revision.cumple:
        return r.model_copy(update={"cumple": True, "motivo": None, "error": None})
    motivo = revision.nota or r.motivo or r.error or "Revisado: no cumple"
    return r.model_copy(update={"cumple": False, "error": None, "motivo": motivo})


# --- Procesos ---
@router.get("/procesos", response=list[ProcesoResumenOut])
def listar_procesos(request: HttpRequest) -> list[ProcesoResumenOut]:
    """Todos los procesos de la entidad (consulta para cualquier rol)."""
    usuario: Usuario = request.auth
    procesos = Proceso.objects.select_related("creado_por").annotate(n=Count("proponentes"))
    if not usuario.es_superadmin:
        procesos = procesos.filter(entidad_id=usuario.entidad_id)
    procesos = list(procesos)
    evaluaciones = list(_evaluaciones_qs(usuario).filter(proceso__in=procesos).order_by("tipo"))
    por_proceso: dict[UUID, list[EvaluacionResumenOut]] = {}
    for resumen in _resumenes(usuario, evaluaciones):
        por_proceso.setdefault(resumen.proceso_id, []).append(resumen)
    return [
        ProcesoResumenOut(
            id=p.id,
            codigo=p.codigo,
            objeto=p.objeto,
            fecha_cierre=p.fecha_cierre,
            creado_en=p.creado_en,
            creado_por=_persona(p.creado_por),
            proponentes=p.n,
            evaluaciones=por_proceso.get(p.id, []),
        )
        for p in procesos
    ]


@router.post("/procesos", response={201: list[EvaluacionResumenOut]})
def crear_proceso(request: HttpRequest, datos: CrearProcesoIn):
    usuario: Usuario = request.auth
    if usuario.es_superadmin:
        raise HttpError(400, "El superadministrador no pertenece a una entidad; cree el proceso con un usuario de la entidad.")
    if not puede_crear_procesos(usuario):
        raise HttpError(403, "Su rol no permite crear procesos.")
    tipos = list(dict.fromkeys(datos.tipos))
    if not tipos:
        raise HttpError(400, "Elija al menos un tipo de evaluación.")
    no_disponibles = [t for t in tipos if t not in TIPOS_DISPONIBLES]
    if no_disponibles:
        raise HttpError(400, "Por ahora solo está disponible la evaluación jurídica.")
    if not datos.proponentes:
        raise HttpError(400, "El proceso no tiene proponentes. Revise la carpeta de Drive.")
    doc = datos.documento_base
    try:
        with transaction.atomic():
            proceso = Proceso.objects.create(
                entidad_id=usuario.entidad_id,
                codigo=doc.codigo_proceso.strip(),
                fecha_cierre=doc.fecha_cierre,
                objeto=doc.objeto_general,
                documento_base=doc.model_dump(mode="json"),
                carpeta_drive=datos.carpeta_drive.strip(),
                proponentes_no_reconocidos=datos.proponentes_no_reconocidos,
                creado_por=usuario,
            )
            Proponente.objects.bulk_create(
                Proponente(
                    entidad_id=usuario.entidad_id,
                    proceso=proceso,
                    numero_orden=p.numero_orden,
                    hoja=p.hoja,
                    nombre=p.nombre_proponente,
                    nombre_archivo=p.nombre_archivo,
                    drive_file_id=p.drive_file_id,
                    advertencia=p.advertencia or "",
                )
                for p in datos.proponentes
            )
            evaluaciones = []
            for tipo in tipos:
                # Un evaluador que crea el proceso queda como responsable de su área.
                propia = usuario.rol == Rol.EVALUADOR and tiene_area(usuario, tipo)
                evaluaciones.append(
                    Evaluacion.objects.create(
                        entidad_id=usuario.entidad_id,
                        proceso=proceso,
                        tipo=tipo,
                        responsable=usuario if propia else None,
                        asignada_por=usuario if propia else None,
                        asignada_en=timezone.now() if propia else None,
                        estado=EstadoEvaluacion.ASIGNADA if propia else EstadoEvaluacion.SIN_ASIGNAR,
                    )
                )
            auditar(request, "proceso.creado", objeto=proceso, codigo=proceso.codigo, proponentes=len(datos.proponentes), tipos=tipos)
    except IntegrityError as exc:
        raise HttpError(409, f"Ya existe un proceso con el código {doc.codigo_proceso} en su entidad.") from exc
    for e in evaluaciones:
        e.proceso = proceso
    return 201, _resumenes(usuario, evaluaciones)


# --- Listados de evaluaciones ---
@router.get("/mias", response=list[EvaluacionResumenOut])
def mis_evaluaciones(request: HttpRequest) -> list[EvaluacionResumenOut]:
    """Asignadas a mí y, para jefes y administradores, las de las áreas que gestionan."""
    usuario: Usuario = request.auth
    qs = _evaluaciones_qs(usuario)
    if usuario.es_superadmin or usuario.rol == Rol.ADMIN_ENTIDAD:
        pass
    elif usuario.rol == Rol.JEFE_AREA:
        qs = qs.filter(Q(responsable=usuario) | Q(tipo__in=[a.tipo for a in usuario.areas.all()]))
    else:
        qs = qs.filter(responsable=usuario)
    return _resumenes(usuario, list(qs.order_by("proceso__fecha_cierre", "-creada_en")))


@router.get("/equipo", response=list[MiembroCargaOut])
def carga_del_equipo(request: HttpRequest) -> list[MiembroCargaOut]:
    """Personas a las que el usuario puede asignar, con su carga actual."""
    usuario: Usuario = request.auth
    if not (usuario.es_superadmin or usuario.rol in (Rol.ADMIN_ENTIDAD, Rol.JEFE_AREA)):
        raise HttpError(403, "No tiene permiso para ver la carga del equipo.")
    if usuario.es_superadmin:
        raise HttpError(400, "Consulte el equipo desde un usuario de la entidad.")
    miembros = (
        Usuario.objects.filter(entidad_id=usuario.entidad_id, is_active=True)
        .exclude(rol=Rol.CONSULTA)
        .prefetch_related("areas")
    )
    if usuario.rol == Rol.JEFE_AREA:
        miembros = miembros.filter(areas__in=usuario.areas.all()).distinct()
    miembros = list(miembros)
    activas = list(
        Evaluacion.objects.filter(entidad_id=usuario.entidad_id, responsable__in=miembros).exclude(
            estado=EstadoEvaluacion.APROBADA
        )
    )
    avances = _avances([e.id for e in activas])
    salida = []
    for m in miembros:
        propias = [e for e in activas if e.responsable_id == m.id]
        salida.append(
            MiembroCargaOut(
                id=m.id,
                nombre_completo=m.nombre_completo,
                email=m.email,
                rol=m.rol,
                rol_nombre=m.get_rol_display(),
                areas=[a.tipo for a in m.areas.all()],
                evaluaciones_activas=len(propias),
                pendientes=sum(avances[e.id].pendientes for e in propias),
            )
        )
    return salida


# --- Una evaluación ---
@router.get("/{evaluacion_id}", response=EvaluacionDetalleOut)
def detalle(request: HttpRequest, evaluacion_id: UUID) -> EvaluacionDetalleOut:
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    proceso = evaluacion.proceso
    proponentes = list(proceso.proponentes.all())
    revisiones = Revision.objects.filter(evaluacion=evaluacion).select_related("proponente", "usuario")
    return EvaluacionDetalleOut(
        evaluacion=_resumenes(usuario, [evaluacion])[0],
        documento_base=ProcesoDocumentoBase.model_validate(proceso.documento_base),
        carpeta_drive=proceso.carpeta_drive,
        proponentes_no_reconocidos=proceso.proponentes_no_reconocidos,
        proponentes=[
            ProponenteOut(
                id=p.id,
                numero_orden=p.numero_orden,
                hoja=p.hoja,
                nombre_proponente=p.nombre,
                nombre_archivo=p.nombre_archivo,
                drive_file_id=p.drive_file_id,
                advertencia=p.advertencia or None,
            )
            for p in proponentes
        ],
        resultados=list(Resultado.objects.filter(evaluacion=evaluacion).values_list("datos", flat=True)),
        revisiones=[
            RevisionOut(
                proponente_id=r.proponente_id,
                hoja=r.proponente.hoja,
                requisito=r.requisito,
                cumple=r.cumple,
                nota=r.nota,
                usuario=r.usuario.nombre_completo,
                fecha=r.fecha,
            )
            for r in revisiones
        ],
    )


@router.put("/{evaluacion_id}/documento-base", response=ProcesoDocumentoBase)
def actualizar_documento_base(request: HttpRequest, evaluacion_id: UUID, datos: ProcesoDocumentoBase) -> ProcesoDocumentoBase:
    """Corrige los datos del proceso (lotes, garantía). Los proponentes ya
    evaluados conservan su resultado hasta que se vuelvan a evaluar."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    proceso = evaluacion.proceso
    if datos.codigo_proceso.strip() != proceso.codigo:
        raise HttpError(400, "El código del proceso no se puede cambiar.")
    proceso.documento_base = datos.model_dump(mode="json")
    proceso.fecha_cierre = datos.fecha_cierre
    proceso.objeto = datos.objeto_general
    proceso.save(update_fields=["documento_base", "fecha_cierre", "objeto"])
    auditar(request, "proceso.datos_actualizados", objeto=proceso)
    return datos


@router.post("/{evaluacion_id}/asignar", response=EvaluacionResumenOut)
def asignar(request: HttpRequest, evaluacion_id: UUID, datos: AsignarIn) -> EvaluacionResumenOut:
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_gestion(usuario, evaluacion)
    anterior = evaluacion.responsable
    nuevo = None
    if datos.responsable_id is not None:
        nuevo = (
            Usuario.objects.filter(pk=datos.responsable_id, entidad_id=evaluacion.entidad_id, is_active=True)
            .exclude(rol=Rol.CONSULTA)
            .prefetch_related("areas")
            .first()
        )
        if nuevo is None:
            raise HttpError(400, "Esa persona no existe en la entidad o no puede evaluar.")
        if not tiene_area(nuevo, evaluacion.tipo):
            raise HttpError(400, f"{nuevo.nombre_completo} no pertenece al área {evaluacion.get_tipo_display().lower()}.")
    if (anterior and anterior.id) == (nuevo and nuevo.id):
        return _resumenes(usuario, [evaluacion])[0]
    with transaction.atomic():
        evaluacion.responsable = nuevo
        evaluacion.asignada_por = usuario if nuevo else None
        evaluacion.asignada_en = timezone.now() if nuevo else None
        evaluacion.save()
        _actualizar_estado(evaluacion)
        auditar(
            request,
            "evaluacion.asignada" if nuevo else "evaluacion.desasignada",
            entidad_id=evaluacion.entidad_id,
            objeto=evaluacion,
            proceso=evaluacion.proceso.codigo,
            antes=anterior.email if anterior else None,
            ahora=nuevo.email if nuevo else None,
        )
        if nuevo and nuevo.id != usuario.id:
            transaction.on_commit(lambda: enviar_asignacion(evaluacion, nuevo, usuario))
    return _resumenes(usuario, [evaluacion])[0]


def _preparar_evaluacion(usuario: Usuario, evaluacion_id: UUID, proponente_id: UUID):
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    if evaluacion.tipo not in TIPOS_DISPONIBLES:
        raise HttpError(400, "Este tipo de evaluación aún no está disponible.")
    proponente = get_object_or_404(Proponente, pk=proponente_id, proceso_id=evaluacion.proceso_id)
    motor_proponente = ProponenteMotor(
        numero_orden=proponente.numero_orden,
        hoja=proponente.hoja,
        nombre_proponente=proponente.nombre,
        nombre_archivo=proponente.nombre_archivo,
        drive_file_id=proponente.drive_file_id,
        advertencia=proponente.advertencia or None,
    )
    documento = ProcesoDocumentoBase.model_validate(evaluacion.proceso.documento_base)
    return evaluacion, proponente, motor_proponente, documento


def _guardar_resultados(evaluacion: Evaluacion, proponente: Proponente, resultados: list[ResultadoRequisito]) -> None:
    with transaction.atomic():
        for r in resultados:
            Resultado.objects.update_or_create(
                evaluacion=evaluacion,
                proponente=proponente,
                requisito=r.requisito,
                defaults={
                    "entidad_id": evaluacion.entidad_id,
                    "datos": r.model_dump(mode="json"),
                    "requiere_revision": _requiere_revision(r),
                },
            )
        _actualizar_estado(evaluacion)


@router.post("/{evaluacion_id}/proponentes/{proponente_id}/evaluar", response=list[ResultadoRequisito])
async def evaluar_proponente(request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID) -> list[ResultadoRequisito]:
    usuario: Usuario = request.auth
    evaluacion, proponente, motor_proponente, documento = await sync_to_async(_preparar_evaluacion)(
        usuario, evaluacion_id, proponente_id
    )
    resultados = await evaluar_todos_en_proceso(motor_proponente, documento)
    # Si el usuario cerró la página, el resultado igual se guarda.
    await asyncio.shield(sync_to_async(_guardar_resultados)(evaluacion, proponente, resultados))
    return resultados


@router.put("/{evaluacion_id}/revisiones", response={200: RevisionOut | None})
def revisar(request: HttpRequest, evaluacion_id: UUID, datos: RevisarIn):
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    proponente = get_object_or_404(Proponente, pk=datos.proponente_id, proceso_id=evaluacion.proceso_id)
    with transaction.atomic():
        anterior = Revision.objects.filter(evaluacion=evaluacion, proponente=proponente, requisito=datos.requisito).first()
        if datos.cumple is None:
            if anterior:
                anterior.delete()
                auditar(request, "revision.borrada", objeto=evaluacion, hoja=proponente.hoja, requisito=datos.requisito, antes=anterior.cumple)
            return 200, None
        revision, _ = Revision.objects.update_or_create(
            evaluacion=evaluacion,
            proponente=proponente,
            requisito=datos.requisito,
            defaults={"entidad_id": evaluacion.entidad_id, "cumple": datos.cumple, "nota": datos.nota.strip(), "usuario": usuario},
        )
        auditar(
            request,
            "revision.guardada",
            objeto=evaluacion,
            hoja=proponente.hoja,
            requisito=datos.requisito,
            antes=anterior.cumple if anterior else None,
            ahora=datos.cumple,
        )
    return 200, RevisionOut(
        proponente_id=proponente.id,
        hoja=proponente.hoja,
        requisito=revision.requisito,
        cumple=revision.cumple,
        nota=revision.nota,
        usuario=usuario.nombre_completo,
        fecha=revision.fecha,
    )


@router.post("/{evaluacion_id}/aprobar", response=EvaluacionResumenOut)
def aprobar(request: HttpRequest, evaluacion_id: UUID) -> EvaluacionResumenOut:
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_gestion(usuario, evaluacion)
    avance = _avances([evaluacion.id])[evaluacion.id]
    if avance.evaluados < avance.proponentes:
        raise HttpError(409, f"Faltan {avance.proponentes - avance.evaluados} proponentes por evaluar.")
    if avance.pendientes:
        raise HttpError(409, f"Quedan {avance.pendientes} requisitos por revisar.")
    evaluacion.estado = EstadoEvaluacion.APROBADA
    evaluacion.aprobada_por = usuario
    evaluacion.aprobada_en = timezone.now()
    evaluacion.save()
    auditar(request, "evaluacion.aprobada", objeto=evaluacion, proceso=evaluacion.proceso.codigo)
    return _resumenes(usuario, [evaluacion])[0]


@router.post("/{evaluacion_id}/reabrir", response=EvaluacionResumenOut)
def reabrir(request: HttpRequest, evaluacion_id: UUID) -> EvaluacionResumenOut:
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_gestion(usuario, evaluacion)
    if evaluacion.estado != EstadoEvaluacion.APROBADA:
        raise HttpError(409, "La evaluación no está aprobada.")
    evaluacion.estado = EstadoEvaluacion.EN_REVISION
    evaluacion.aprobada_por = None
    evaluacion.aprobada_en = None
    evaluacion.save()
    _actualizar_estado(evaluacion)
    auditar(request, "evaluacion.reabierta", objeto=evaluacion, proceso=evaluacion.proceso.codigo)
    return _resumenes(usuario, [evaluacion])[0]


@router.get("/{evaluacion_id}/informe")
def informe(request: HttpRequest, evaluacion_id: UUID) -> HttpResponse:
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    plantilla = PLANTILLAS.get(evaluacion.tipo)
    if plantilla is None or not plantilla.exists():
        raise HttpError(400, "Este tipo de evaluación aún no tiene plantilla de informe.")
    proceso = evaluacion.proceso
    proponentes = list(proceso.proponentes.all())
    revisiones = {(r.proponente_id, r.requisito): r for r in Revision.objects.filter(evaluacion=evaluacion)}
    resultados = [
        _aplicar_revision(r.datos, revisiones.get((r.proponente_id, r.requisito)))
        for r in Resultado.objects.filter(evaluacion=evaluacion)
    ]
    contenido = fill_template(
        str(plantilla),
        ProcesoDocumentoBase.model_validate(proceso.documento_base),
        [
            ProponenteMotor(
                numero_orden=p.numero_orden,
                hoja=p.hoja,
                nombre_proponente=p.nombre,
                nombre_archivo=p.nombre_archivo,
                drive_file_id=p.drive_file_id,
                advertencia=p.advertencia or None,
            )
            for p in proponentes
        ],
        resultados,
    )
    borrador = "" if evaluacion.estado == EstadoEvaluacion.APROBADA else " (BORRADOR)"
    # Mismo nombre que usa la plantilla oficial ("INFORME EVALUACION JURIDICA …"), sin tildes.
    nombre = f"INFORME EVALUACION {evaluacion.tipo.upper()} {proceso.codigo}{borrador}.xlsx"
    auditar(request, "informe.descargado", objeto=evaluacion, proceso=proceso.codigo, borrador=bool(borrador))
    respuesta = HttpResponse(contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


@router.get("/{evaluacion_id}/proponentes/{proponente_id}/documento")
def documento(request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID, archivo: str) -> HttpResponse:
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    proponente = get_object_or_404(Proponente, pk=proponente_id, proceso_id=evaluacion.proceso_id)
    try:
        zip_bytes = download_file_bytes(proponente.drive_file_id)
    except Exception as exc:  # noqa: BLE001
        raise HttpError(502, "No se pudo descargar la oferta de Google Drive. Inténtelo de nuevo en unos minutos.") from exc
    contenido = extraer_pdfs(zip_bytes).get(archivo)
    if contenido is None:
        raise HttpError(404, "No se encontró ese documento dentro de la oferta del proponente.")
    auditar(request, "documento.visto", objeto=evaluacion, hoja=proponente.hoja, archivo=archivo)
    return HttpResponse(contenido, content_type="application/pdf")
