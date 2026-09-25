"""Procesos y evaluaciones guardados en el servidor: creación, asignación,
fila de evaluación, revisiones, aprobación, informe y documentos."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File, Router, Schema
from ninja.files import UploadedFile
from ninja.errors import HttpError

from cuentas.correo import enviar_asignacion
from cuentas.models import Entidad, Rol, TipoArea, Usuario
from cuentas.seguridad import auditar, requiere_rol, sesion_activa
from evaluaciones import expediente, servicios
from evaluaciones import pliego as pliego_servicio
from evaluaciones.tipos import MENSAJE_EN_PREPARACION, TIPOS
from evaluaciones.models import (
    AnalisisPliego,
    EstadoEvaluacion,
    EstadoTrabajo,
    PlantillaEvaluacion,
    Trabajador,
    Trabajo,
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
    puede_eliminar_proceso,
    puede_gestionar,
    puede_trabajar,
    puede_ver,
    tiene_area,
)
from motor.esquemas.proceso import ProcesoDocumentoBase
from motor.integrations.drive import download_file_bytes
from motor.procesamiento.zip_utils import PREFIJO_APORTADOS, extraer_pdfs

router = Router(tags=["evaluaciones"], auth=sesion_activa)



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
    en_fila: int
    procesando: int


class FilaOut(Schema):
    en_fila: int
    procesando: int
    por_delante: int
    capacidad: int
    segundos_por_proponente: float
    eta_segundos: int | None


class EvaluacionResumenOut(Schema):
    id: UUID
    tipo: str
    tipo_nombre: str
    estado: str
    estado_nombre: str
    responsable: PersonaOut | None
    avance: AvanceOut
    entidad_id: UUID
    entidad_nombre: str
    proceso_id: UUID
    proceso_codigo: str
    proceso_objeto: str
    fecha_cierre: date
    actualizada_en: datetime
    aprobada_en: datetime | None
    puede_trabajar: bool
    puede_gestionar: bool
    # Hay motor automático para este tipo (técnica y financiera: en preparación).
    tipo_disponible: bool
    # Versión de la plantilla de evaluación de la entidad con la que se evalúa.
    plantilla_version: int | None
    plantilla_nombre: str
    # La entidad publicó una versión más nueva desde que se creó esta evaluación.
    plantilla_desactualizada: bool
    # Solo cuando hay trabajos pendientes en la fila.
    fila: FilaOut | None = None


class ProcesoResumenOut(Schema):
    id: UUID
    codigo: str
    objeto: str
    fecha_cierre: date
    creado_en: datetime
    creado_por: PersonaOut
    proponentes: int
    evaluaciones: list[EvaluacionResumenOut]
    # Quien lo ve puede eliminarlo (administrador o quien lo creó) y no tiene
    # evaluaciones aprobadas.
    puede_eliminar: bool = False


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
    # Solo el superadministrador elige la entidad; los demás crean en la suya.
    entidad_id: UUID | None = None
    # Quién evalúa. Sin enviar: el evaluador que crea queda como responsable;
    # jefes y administradores dejan la evaluación sin asignar.
    responsable_id: UUID | None = None
    sin_responsable: bool = False
    # Responsable por tipo (tiene prioridad): {"juridica": id, "tecnica": null = sin asignar}.
    responsables: dict[str, UUID | None] | None = None
    # Análisis del pliego (lo devuelve /procesos/analizar) y la decisión sobre
    # cada hallazgo que cambia la evaluación: {id: {"decision": "aceptado" |
    # "rechazado", "nota": "..."}}.
    analisis_pliego_id: UUID | None = None
    decisiones_pliego: dict[str, dict] = {}


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
    # Requisitos de esta evaluación según la plantilla de la entidad.
    catalogo: list[dict]
    # Pliego del proceso: {nombre_archivo, paginas, documento_tipo, ajustes,
    # aclaraciones} o None si el proceso se creó sin analizarlo.
    pliego: dict | None = None


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


def _resumenes(usuario: Usuario, evaluaciones: list[Evaluacion]) -> list[EvaluacionResumenOut]:
    ids = [e.id for e in evaluaciones]
    avances = servicios.avances(ids)
    activas = {
        (p.entidad_id, p.tipo): p.id
        for p in PlantillaEvaluacion.objects.filter(
            activa=True, entidad_id__in={e.entidad_id for e in evaluaciones}
        ).only("id", "entidad_id", "tipo")
    }
    con_fila = [i for i in ids if avances[i].en_fila or avances[i].procesando]
    filas = servicios.estado_fila(con_fila)
    return [
        EvaluacionResumenOut(
            id=e.id,
            tipo=e.tipo,
            tipo_nombre=e.get_tipo_display(),
            estado=e.estado,
            estado_nombre=e.get_estado_display(),
            responsable=_persona(e.responsable),
            avance=AvanceOut(**avances[e.id].dict()),
            fila=FilaOut(**filas[e.id].dict()) if e.id in filas else None,
            entidad_id=e.entidad_id,
            entidad_nombre=e.entidad.nombre,
            proceso_id=e.proceso_id,
            proceso_codigo=e.proceso.codigo,
            proceso_objeto=e.proceso.objeto,
            fecha_cierre=e.proceso.fecha_cierre,
            actualizada_en=e.actualizada_en,
            aprobada_en=e.aprobada_en,
            puede_trabajar=puede_trabajar(usuario, e),
            puede_gestionar=puede_gestionar(usuario, e),
            tipo_disponible=TIPOS[e.tipo].disponible,
            plantilla_version=e.plantilla.version if e.plantilla_id else None,
            plantilla_nombre=e.plantilla.nombre if e.plantilla_id else "Base del sistema",
            plantilla_desactualizada=activas.get((e.entidad_id, e.tipo)) not in (None, e.plantilla_id),
        )
        for e in evaluaciones
    ]


def _evaluaciones_qs(usuario: Usuario):
    qs = Evaluacion.objects.select_related("proceso", "responsable", "entidad", "plantilla")
    if not usuario.es_superadmin:
        qs = qs.filter(entidad_id=usuario.entidad_id)
    return qs


def _evaluacion(usuario: Usuario, evaluacion_id: UUID) -> Evaluacion:
    evaluacion = get_object_or_404(_evaluaciones_qs(usuario), pk=evaluacion_id)
    if not puede_ver(usuario, evaluacion):
        raise HttpError(404, "No encontrado.")
    return evaluacion


def _responsable_valido(entidad_id: UUID, tipo: str, responsable_id: UUID, actor: Usuario) -> Usuario:
    """Persona activa de la entidad que puede evaluar ese tipo. Quien se asigna
    a sí mismo no necesita tener el área (p. ej. un abogado con su propio proceso)."""
    persona = (
        Usuario.objects.filter(pk=responsable_id, entidad_id=entidad_id, is_active=True)
        .exclude(rol=Rol.CONSULTA)
        .prefetch_related("areas")
        .first()
    )
    if persona is None:
        raise HttpError(400, "Esa persona no existe en la entidad o no puede evaluar.")
    if persona.id != actor.id and persona.rol == Rol.EVALUADOR and not tiene_area(persona, tipo):
        raise HttpError(400, f"{persona.nombre_completo} no pertenece al área {TipoArea(tipo).label.lower()}.")
    return persona


class TipoOut(Schema):
    clave: str
    nombre: str
    descripcion: str
    disponible: bool


@router.get("/tipos", response=list[TipoOut])
def tipos_de_evaluacion(request: HttpRequest) -> list[TipoOut]:
    return [TipoOut(clave=t.clave, nombre=t.nombre, descripcion=t.descripcion, disponible=t.disponible) for t in TIPOS.values()]


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
    aprobados = {e.proceso_id: True for e in evaluaciones if e.estado == EstadoEvaluacion.APROBADA}
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
            puede_eliminar=puede_eliminar_proceso(usuario, p) and not aprobados.get(p.id, False),
        )
        for p in procesos
    ]


class EliminarProcesoIn(Schema):
    # El código del proceso, escrito a mano: evita borrar uno por error.
    confirmacion: str


@router.delete("/procesos/{proceso_id}", response={204: None})
def eliminar_proceso(request: HttpRequest, proceso_id: UUID, datos: EliminarProcesoIn):
    """Elimina el proceso y todo lo suyo. Es irreversible: se confirma con el
    código del proceso y queda en la auditoría."""
    from evaluaciones.permisos import puede_eliminar_proceso

    usuario: Usuario = request.auth
    proceso = get_object_or_404(Proceso, pk=proceso_id)
    if not puede_eliminar_proceso(usuario, proceso):
        raise HttpError(403, "Solo el administrador de la entidad o quien creó el proceso puede eliminarlo.")
    if " ".join(datos.confirmacion.split()).upper() != proceso.codigo.strip().upper():
        raise HttpError(400, f"Para confirmar, escriba exactamente el código del proceso: {proceso.codigo}")
    codigo, entidad_id = proceso.codigo, proceso.entidad_id
    try:
        conteo = servicios.eliminar_proceso(proceso)
    except ValueError as exc:
        raise HttpError(409, str(exc)) from exc
    auditar(request, "proceso.eliminado", entidad_id=entidad_id, codigo=codigo, **conteo)
    return 204, None


@router.post("/procesos", response={201: list[EvaluacionResumenOut]})
def crear_proceso(request: HttpRequest, datos: CrearProcesoIn):
    usuario: Usuario = request.auth
    if not puede_crear_procesos(usuario):
        raise HttpError(403, "Su rol no permite crear procesos.")
    if usuario.es_superadmin:
        if datos.entidad_id is None:
            raise HttpError(400, "Elija la entidad del proceso.")
        entidad = get_object_or_404(Entidad, pk=datos.entidad_id)
    else:
        if datos.entidad_id is not None and datos.entidad_id != usuario.entidad_id:
            raise HttpError(404, "No encontrado.")
        entidad = usuario.entidad
    if not entidad.activa:
        raise HttpError(400, "La entidad está suspendida.")
    tipos = list(dict.fromkeys(datos.tipos))
    if not tipos:
        raise HttpError(400, "Elija al menos un tipo de evaluación.")
    desconocidos = [t for t in tipos if t not in TIPOS]
    if desconocidos:
        raise HttpError(400, f"Tipo de evaluación no válido: {', '.join(desconocidos)}.")
    if not datos.proponentes:
        raise HttpError(400, "El proceso no tiene proponentes. Revise la carpeta de Drive.")

    analisis = None
    ajustes: list[dict] = []
    if datos.analisis_pliego_id is not None:
        analisis = get_object_or_404(AnalisisPliego.objects.filter(entidad=entidad), pk=datos.analisis_pliego_id)
        # Los hallazgos del análisis son de la evaluación jurídica; la técnica
        # solo usa el pliego para leer sus parámetros (lotes, experiencia).
        if TipoArea.JURIDICA in tipos:
            try:
                ajustes = pliego_servicio.decidir(analisis, datos.decisiones_pliego, usuario)
            except ValueError as exc:
                raise HttpError(400, str(exc)) from exc

    gestiona = usuario.es_superadmin or usuario.rol in (Rol.ADMIN_ENTIDAD, Rol.JEFE_AREA)
    responsables: dict[str, Usuario | None] = {}
    for tipo in tipos:
        elegido = datos.responsable_id
        explicito = datos.sin_responsable or datos.responsable_id is not None
        if datos.responsables is not None and tipo in datos.responsables:
            elegido, explicito = datos.responsables[tipo], True
        elif datos.sin_responsable:
            elegido = None
        if explicito and elegido is None:
            responsables[tipo] = None
        elif explicito:
            if elegido != usuario.id and not gestiona:
                raise HttpError(403, "Solo el jefe del área o el administrador pueden asignar a otra persona.")
            responsables[tipo] = _responsable_valido(entidad.id, tipo, elegido, usuario)
        else:
            # El abogado que crea su propio proceso queda a cargo.
            responsables[tipo] = usuario if usuario.rol == Rol.EVALUADOR else None

    doc = datos.documento_base
    try:
        with transaction.atomic():
            proceso = Proceso.objects.create(
                entidad=entidad,
                codigo=doc.codigo_proceso.strip(),
                fecha_cierre=doc.fecha_cierre,
                objeto=doc.objeto_general,
                documento_base=doc.model_dump(mode="json"),
                carpeta_drive=datos.carpeta_drive.strip(),
                proponentes_no_reconocidos=datos.proponentes_no_reconocidos,
                analisis_pliego=analisis,
                ajustes_pliego=ajustes,
                creado_por=usuario,
            )
            Proponente.objects.bulk_create(
                Proponente(
                    entidad=entidad,
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
                responsable = responsables[tipo]
                evaluacion = Evaluacion.objects.create(
                    entidad=entidad,
                    proceso=proceso,
                    tipo=tipo,
                    plantilla=servicios.plantilla_activa(entidad.id, tipo),
                    responsable=responsable,
                    asignada_por=usuario if responsable else None,
                    asignada_en=timezone.now() if responsable else None,
                    estado=EstadoEvaluacion.ASIGNADA if responsable else EstadoEvaluacion.SIN_ASIGNAR,
                )
                evaluaciones.append(evaluacion)
                if responsable and responsable.id != usuario.id:
                    transaction.on_commit(lambda e=evaluacion, r=responsable: enviar_asignacion(e, r, usuario))
            auditar(
                request,
                "proceso.creado",
                entidad_id=entidad.id,
                objeto=proceso,
                codigo=proceso.codigo,
                proponentes=len(datos.proponentes),
                tipos=tipos,
                responsables={t: (r.email if r else None) for t, r in responsables.items()},
                pliego=analisis.nombre_archivo if analisis else None,
                ajustes_pliego={a["id"]: a["decision"] for a in ajustes},
            )
    except IntegrityError as exc:
        raise HttpError(409, f"Ya existe un proceso con el código {doc.codigo_proceso} en esa entidad.") from exc
    for e in evaluaciones:
        e.proceso = proceso
        e.entidad = entidad
    return 201, _resumenes(usuario, evaluaciones)


# --- Listados de evaluaciones ---
@router.get("/mias", response=list[EvaluacionResumenOut])
def mis_evaluaciones(request: HttpRequest) -> list[EvaluacionResumenOut]:
    """Asignadas a mí y, para jefes y administradores, las de las áreas que gestionan."""
    usuario: Usuario = request.auth
    qs = _evaluaciones_qs(usuario)
    if usuario.es_superadmin or usuario.rol in (Rol.ADMIN_ENTIDAD, Rol.SOPORTE):
        pass
    elif usuario.rol == Rol.JEFE_AREA:
        qs = qs.filter(Q(responsable=usuario) | Q(tipo__in=[a.tipo for a in usuario.areas.all()]))
    else:
        qs = qs.filter(responsable=usuario)
    return _resumenes(usuario, list(qs.order_by("proceso__fecha_cierre", "-creada_en")))


@router.get("/equipo", response=list[MiembroCargaOut])
def carga_del_equipo(request: HttpRequest, entidad_id: UUID | None = None) -> list[MiembroCargaOut]:
    """Personas a las que el usuario puede asignar, con su carga actual."""
    usuario: Usuario = request.auth
    if not (usuario.es_superadmin or usuario.rol in (Rol.ADMIN_ENTIDAD, Rol.JEFE_AREA)):
        raise HttpError(403, "No tiene permiso para ver la carga del equipo.")
    if usuario.es_superadmin:
        if entidad_id is None:
            raise HttpError(400, "Indique la entidad.")
        objetivo = get_object_or_404(Entidad, pk=entidad_id).id
    elif entidad_id is not None and entidad_id != usuario.entidad_id:
        raise HttpError(404, "No encontrado.")
    else:
        objetivo = usuario.entidad_id
    miembros = (
        Usuario.objects.filter(entidad_id=objetivo, is_active=True)
        .exclude(rol=Rol.CONSULTA)
        .prefetch_related("areas")
    )
    if usuario.rol == Rol.JEFE_AREA:
        miembros = miembros.filter(areas__in=usuario.areas.all()).distinct()
    miembros = list(miembros)
    activas = list(
        Evaluacion.objects.filter(entidad_id=objetivo, responsable__in=miembros).exclude(
            estado=EstadoEvaluacion.APROBADA
        )
    )
    avances = servicios.avances([e.id for e in activas])
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


class TrabajadorOut(Schema):
    id: str
    capacidad: int
    iniciado_en: datetime
    latido: datetime
    activo: bool


class EstadoFilaOut(Schema):
    capacidad_activa: int
    segundos_por_proponente: float
    total_en_fila: int
    total_procesando: int
    trabajadores: list[TrabajadorOut]
    evaluaciones: list[EvaluacionResumenOut]


@router.get("/fila/estado", response=EstadoFilaOut)
def estado_de_la_fila(request: HttpRequest) -> EstadoFilaOut:
    """Qué se está evaluando y qué espera turno. Administradores ven su
    entidad; el superadmin, toda la plataforma y los trabajadores."""
    usuario: Usuario = request.auth
    requiere_rol(usuario, (Rol.ADMIN_ENTIDAD,))
    pendientes = Trabajo.objects.filter(estado__in=servicios.PENDIENTES)
    if not usuario.es_superadmin:
        pendientes = pendientes.filter(entidad_id=usuario.entidad_id)
    ids = pendientes.values_list("evaluacion_id", flat=True).distinct()
    evaluaciones = list(_evaluaciones_qs(usuario).filter(id__in=ids).order_by("creada_en"))
    limite = timezone.now() - servicios.LATIDO_VIGENTE
    trabajadores = (
        [
            TrabajadorOut(id=t.id, capacidad=t.capacidad, iniciado_en=t.iniciado_en, latido=t.latido, activo=t.latido >= limite)
            for t in Trabajador.objects.order_by("iniciado_en")
        ]
        if usuario.es_superadmin
        else []
    )
    return EstadoFilaOut(
        capacidad_activa=servicios.capacidad_activa(),
        segundos_por_proponente=round(servicios.segundos_por_proponente(), 1),
        total_en_fila=pendientes.filter(estado=EstadoTrabajo.EN_FILA).count(),
        total_procesando=pendientes.filter(estado=EstadoTrabajo.PROCESANDO).count(),
        trabajadores=trabajadores,
        evaluaciones=_resumenes(usuario, evaluaciones),
    )


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
        catalogo=servicios.catalogo(servicios.definicion_de(evaluacion)),
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
        pliego=_pliego_out(proceso),
    )


def _pliego_out(proceso: Proceso) -> dict | None:
    analisis = proceso.analisis_pliego
    if analisis is None:
        return None
    try:
        vigentes = pliego_servicio.hallazgos(analisis)
    except Exception:  # noqa: BLE001
        vigentes = []
    return {
        "nombre_archivo": analisis.nombre_archivo,
        "paginas": analisis.paginas,
        "documento_tipo": analisis.documento_tipo,
        "ajustes": proceso.ajustes_pliego,
        # Lo que no cambia la evaluación pero hay que tener presente al revisar.
        "aclaraciones": [h.model_dump(mode="json") for h in vigentes if h.tipo in ("aclaracion", "informativo")],
        "obligaciones": [h.model_dump(mode="json") for h in vigentes if h.tipo == "obligacion"],
    }


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


class UmbralesFinancierosIn(Schema):
    liquidez_min: float
    endeudamiento_max: float
    cobertura_min: float
    roa_min: float
    roe_min: float


@router.get("/{evaluacion_id}/parametros-financieros", response={200: dict | None})
def parametros_financieros(request: HttpRequest, evaluacion_id: UUID) -> dict | None:
    """Lo que la evaluación financiera toma del pliego (presupuesto, plazo y
    anticipo por lote, capital de trabajo y capacidad residual exigidos) y
    los umbrales de la Matriz 2."""
    evaluacion = _evaluacion(request.auth, evaluacion_id)
    if evaluacion.tipo != "financiera":
        raise HttpError(400, "Solo aplica a la evaluación financiera.")
    datos = servicios.parametros_financieros_de(evaluacion.proceso)
    if datos is None:
        return None
    from motor.financiera.evaluador import parametros_de_dict

    parametros = parametros_de_dict(datos)
    return {
        **datos,
        "umbrales_completos": parametros.umbrales.completos,
        "lotes": [
            {**l, "capital_de_trabajo_demandado": lf.capital_de_trabajo_demandado,
             "capacidad_residual_del_proceso": lf.capacidad_residual_del_proceso}
            for l, lf in zip(datos.get("lotes", []), parametros.lotes)
        ],
    }


@router.post("/{evaluacion_id}/matriz2", response=dict)
def subir_matriz2(request: HttpRequest, evaluacion_id: UUID, archivo: File[UploadedFile]) -> dict:
    """Sube la Matriz 2 del proceso (PDF, Word o Excel). De ella salen los
    umbrales de los indicadores financieros, que el pliego casi nunca trae.
    Los proponentes ya evaluados vuelven a la fila para que cuente."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    if evaluacion.estado == EstadoEvaluacion.APROBADA:
        raise HttpError(409, "La evaluación está aprobada: reábrela para cambiar la Matriz 2.")
    contenido = archivo.read()
    if len(contenido) > 20 * 1024 * 1024:
        raise HttpError(400, "El archivo pasa de 20 MB.")
    from motor.procesamiento.documentos import texto_de_documento

    if len(texto_de_documento(contenido)) < 200:
        raise HttpError(400, "No se pudo leer el texto del archivo: súbelo en PDF, Word o Excel (no como imagen).")
    proceso = evaluacion.proceso
    proceso.matriz2.save(archivo.name or "matriz2", ContentFile(contenido), save=True)
    # Los umbrales se vuelven a leer del archivo la próxima vez que se pidan.
    type(proceso).objects.filter(pk=proceso.pk).update(parametros_financieros={})
    proceso.parametros_financieros = {}
    auditar(request, "proceso.matriz2_subida", objeto=proceso, archivo=archivo.name or "")
    parametros = servicios.parametros_financieros_de(proceso) or {}
    evaluados = list(evaluacion.resultados.values_list("proponente_id", flat=True).distinct())
    if evaluados:
        servicios.encolar(evaluacion, evaluados, usuario)
    return {"umbrales": parametros.get("umbrales", {}), "avisos": parametros.get("sin_confirmar", []),
            "reevaluados": len(evaluados)}


@router.get("/{evaluacion_id}/parametros-pliego", response=list[dict])
def parametros_pliego(request: HttpRequest, evaluacion_id: UUID) -> list[dict]:
    """Lo que el programa entendió del pliego, con la frase que lo respalda.
    Lo que solo vio la IA queda marcado: mientras nadie lo confirme, ningún
    lote se aprueba solo."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    return servicios.parametros_del_pliego(evaluacion.proceso, evaluacion.tipo)


@router.put("/{evaluacion_id}/parametros-pliego", response=dict)
def confirmar_parametros_pliego(request: HttpRequest, evaluacion_id: UUID, datos: dict) -> dict:
    """Confirma o corrige esos parámetros. Los proponentes ya evaluados
    vuelven a la fila para que el cambio cuente."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    if evaluacion.estado == EstadoEvaluacion.APROBADA:
        raise HttpError(409, "La evaluación está aprobada: reábrela para cambiar los parámetros.")
    try:
        confirmados = servicios.confirmar_parametros_del_pliego(evaluacion.proceso, datos, usuario)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    auditar(request, "proceso.parametros_pliego_confirmados", objeto=evaluacion.proceso,
            parametros=sorted(datos)[:20])
    evaluados = list(evaluacion.resultados.values_list("proponente_id", flat=True).distinct())
    if evaluados:
        servicios.encolar(evaluacion, evaluados, usuario)
    return {"confirmados": confirmados, "reevaluados": len(evaluados)}


@router.get("/{evaluacion_id}/requisitos-pliego", response=list[dict])
def requisitos_pliego(request: HttpRequest, evaluacion_id: UUID) -> list[dict]:
    """Los requisitos que el pliego exige y el programa no sabe verificar.
    Cada uno frena la aprobación automática de todos los proponentes, así que
    aquí se ve de una vez qué hay que mirar a mano en este proceso."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    return servicios.requisitos_del_pliego_sin_verificar(evaluacion.proceso)


@router.post("/{evaluacion_id}/requisitos-pliego", response=dict)
def asumir_requisitos_pliego(request: HttpRequest, evaluacion_id: UUID, datos: dict) -> dict:
    """Marca requisitos como revisados por una persona: se asumen para el
    proceso completo, no proponente por proponente. Los ya evaluados vuelven a
    la fila para que el cambio cuente."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    if evaluacion.estado == EstadoEvaluacion.APROBADA:
        raise HttpError(409, "La evaluación está aprobada: reábrela para asumir requisitos.")
    claves = datos.get("claves")
    if not isinstance(claves, list):
        raise HttpError(400, "Se esperaba una lista de requisitos en «claves».")
    try:
        asumidos = servicios.asumir_requisitos_del_pliego(evaluacion.proceso, claves, usuario)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    auditar(request, "proceso.requisitos_pliego_asumidos", objeto=evaluacion.proceso,
            requisitos=[str(c)[:40] for c in claves][:50])
    evaluados = list(evaluacion.resultados.values_list("proponente_id", flat=True).distinct())
    if evaluados:
        servicios.encolar(evaluacion, evaluados, usuario)
    return {"asumidos": asumidos, "reevaluados": len(evaluados)}


@router.put("/{evaluacion_id}/umbrales-financieros", response=dict)
def registrar_umbrales(request: HttpRequest, evaluacion_id: UUID, datos: UmbralesFinancierosIn) -> dict:
    """Registra los umbrales de la Matriz 2 del proceso. Los proponentes ya
    evaluados se vuelven a poner en la fila para que cuenten."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    if evaluacion.tipo != "financiera":
        raise HttpError(400, "Solo aplica a la evaluación financiera.")
    if evaluacion.estado == EstadoEvaluacion.APROBADA:
        raise HttpError(409, "La evaluación está aprobada: reábrela para cambiar los umbrales.")
    try:
        parametros = servicios.registrar_umbrales_financieros(evaluacion.proceso, datos.dict(), usuario)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    auditar(request, "proceso.umbrales_financieros", objeto=evaluacion.proceso, **datos.dict())
    evaluados = list(evaluacion.resultados.values_list("proponente_id", flat=True).distinct())
    if evaluados:
        servicios.encolar(evaluacion, evaluados, usuario)
    return parametros


@router.post("/{evaluacion_id}/asignar", response=EvaluacionResumenOut)
def asignar(request: HttpRequest, evaluacion_id: UUID, datos: AsignarIn) -> EvaluacionResumenOut:
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_gestion(usuario, evaluacion)
    anterior = evaluacion.responsable
    nuevo = None
    if datos.responsable_id is not None:
        nuevo = _responsable_valido(evaluacion.entidad_id, evaluacion.tipo, datos.responsable_id, usuario)
    if (anterior and anterior.id) == (nuevo and nuevo.id):
        return _resumenes(usuario, [evaluacion])[0]
    with transaction.atomic():
        evaluacion.responsable = nuevo
        evaluacion.asignada_por = usuario if nuevo else None
        evaluacion.asignada_en = timezone.now() if nuevo else None
        evaluacion.save()
        servicios.actualizar_estado(evaluacion)
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


class EncolarIn(Schema):
    # None = los que faltan o quedaron con error.
    proponente_ids: list[UUID] | None = None


class NovedadesOut(Schema):
    evaluacion: EvaluacionResumenOut
    resultados: list[dict]
    hasta: datetime


@router.post("/{evaluacion_id}/evaluar", response=EvaluacionResumenOut)
def evaluar(request: HttpRequest, evaluacion_id: UUID, datos: EncolarIn) -> EvaluacionResumenOut:
    """Pone proponentes en la fila central. La evaluación sigue en el servidor
    aunque el usuario cierre la página; al terminar se le avisa por correo."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    if not TIPOS[evaluacion.tipo].disponible:
        raise HttpError(409, MENSAJE_EN_PREPARACION.format(nombre=TIPOS[evaluacion.tipo].nombre.lower()))
    if datos.proponente_ids is not None:
        propios = set(Proponente.objects.filter(proceso_id=evaluacion.proceso_id, id__in=datos.proponente_ids).values_list("id", flat=True))
        if propios != set(datos.proponente_ids):
            raise HttpError(404, "Algún proponente no pertenece a este proceso.")
    n = servicios.encolar(evaluacion, datos.proponente_ids, usuario)
    if n:
        auditar(request, "evaluacion.encolada", objeto=evaluacion, proceso=evaluacion.proceso.codigo, proponentes=n)
    evaluacion.refresh_from_db()
    return _resumenes(usuario, [evaluacion])[0]


@router.post("/{evaluacion_id}/actualizar-plantilla", response=EvaluacionResumenOut)
def actualizar_plantilla(request: HttpRequest, evaluacion_id: UUID) -> EvaluacionResumenOut:
    """Pasa la evaluación a la versión vigente de la plantilla de la entidad y,
    si ya tenía resultados, vuelve a evaluar a todos los proponentes."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    activa = servicios.plantilla_activa(evaluacion.entidad_id, evaluacion.tipo)
    if activa is None or activa.id == evaluacion.plantilla_id:
        raise HttpError(409, "La evaluación ya usa la versión vigente de la plantilla.")
    anterior = evaluacion.plantilla.version if evaluacion.plantilla_id else None
    with transaction.atomic():
        evaluacion.plantilla = activa
        evaluacion.save(update_fields=["plantilla", "actualizada_en"])
        # Los resultados y revisiones de requisitos que ya no existen se descartan.
        numeros = {r.numero for r in servicios.definicion_de(evaluacion).requisitos}
        Resultado.objects.filter(evaluacion=evaluacion).exclude(requisito__in=numeros).delete()
        Revision.objects.filter(evaluacion=evaluacion).exclude(requisito__in=numeros).delete()
        if TIPOS[evaluacion.tipo].disponible and Resultado.objects.filter(evaluacion=evaluacion).exists():
            todos = list(Proponente.objects.filter(proceso_id=evaluacion.proceso_id).values_list("id", flat=True))
            servicios.encolar(evaluacion, todos, usuario)
        servicios.actualizar_estado(evaluacion)
        auditar(request, "evaluacion.plantilla_actualizada", objeto=evaluacion, antes=anterior, ahora=activa.version)
    evaluacion.refresh_from_db()
    return _resumenes(usuario, [evaluacion])[0]


@router.post("/{evaluacion_id}/pausar", response=EvaluacionResumenOut)
def pausar(request: HttpRequest, evaluacion_id: UUID) -> EvaluacionResumenOut:
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    if not puede_trabajar(usuario, evaluacion):
        raise HttpError(403, "Solo el responsable o el jefe del área pueden pausar esta evaluación.")
    n = servicios.cancelar(evaluacion)
    if n:
        auditar(request, "evaluacion.pausada", objeto=evaluacion, proceso=evaluacion.proceso.codigo, retirados=n)
    evaluacion.refresh_from_db()
    return _resumenes(usuario, [evaluacion])[0]


@router.get("/{evaluacion_id}/novedades", response=NovedadesOut)
def novedades(request: HttpRequest, evaluacion_id: UUID, desde: datetime | None = None) -> NovedadesOut:
    """Estado y resultados nuevos desde `desde` (para refrescar mientras evalúa)."""
    usuario: Usuario = request.auth
    ahora = timezone.now()
    evaluacion = _evaluacion(usuario, evaluacion_id)
    resultados = Resultado.objects.filter(evaluacion=evaluacion)
    if desde is not None:
        resultados = resultados.filter(evaluado_en__gte=desde)
    return NovedadesOut(
        evaluacion=_resumenes(usuario, [evaluacion])[0],
        resultados=list(resultados.values_list("datos", flat=True)),
        hasta=ahora,
    )


@router.put("/{evaluacion_id}/revisiones", response={200: RevisionOut | None})
def revisar(request: HttpRequest, evaluacion_id: UUID, datos: RevisarIn):
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    proponente = get_object_or_404(Proponente, pk=datos.proponente_id, proceso_id=evaluacion.proceso_id)
    if datos.cumple is not None and len(datos.nota.strip()) < 5:
        raise HttpError(400, "Escriba la justificación de su decisión: queda en el reporte formal de evaluación.")
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
    avance = servicios.avances([evaluacion.id])[evaluacion.id]
    if avance.evaluados < avance.proponentes:
        raise HttpError(409, f"Faltan {avance.proponentes - avance.evaluados} proponentes por evaluar.")
    if avance.pendientes:
        raise HttpError(409, f"Quedan {avance.pendientes} requisitos por revisar.")
    with transaction.atomic():
        evaluacion.estado = EstadoEvaluacion.APROBADA
        evaluacion.aprobada_por = usuario
        evaluacion.aprobada_en = timezone.now()
        evaluacion.save()
        # Expediente permanente (lo arma el trabajador en segundo plano).
        expediente.solicitar(evaluacion, usuario)
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
    servicios.actualizar_estado(evaluacion)
    auditar(request, "evaluacion.reabierta", objeto=evaluacion, proceso=evaluacion.proceso.codigo)
    return _resumenes(usuario, [evaluacion])[0]


@router.get("/{evaluacion_id}/consolidado")
def informe_consolidado(request: HttpRequest, evaluacion_id: UUID) -> HttpResponse:
    """Las tres áreas del proceso en un solo archivo, con el puntaje y el
    orden de elegibilidad por lote."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    proceso = evaluacion.proceso
    try:
        contenido, nombre = servicios.generar_informe_consolidado(proceso)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    auditar(request, "informe.consolidado_descargado", objeto=evaluacion, proceso=proceso.codigo)
    respuesta = HttpResponse(contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


@router.get("/{evaluacion_id}/informe")
def informe(request: HttpRequest, evaluacion_id: UUID) -> HttpResponse:
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    try:
        contenido, nombre = servicios.generar_informe_excel(evaluacion)
    except servicios.SinPlantillaInforme as exc:
        raise HttpError(400, "Este tipo de evaluación aún no tiene plantilla de informe. El administrador puede subirla en Configuración.") from exc
    proceso = evaluacion.proceso
    borrador = evaluacion.estado != EstadoEvaluacion.APROBADA
    auditar(request, "informe.descargado", objeto=evaluacion, proceso=proceso.codigo, borrador=bool(borrador))
    respuesta = HttpResponse(contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


def _contenido_aportado(evaluacion, proponente, nombre: str) -> bytes | None:
    from evaluaciones.models import DocumentoAportado

    for d in DocumentoAportado.objects.filter(evaluacion=evaluacion, proponente=proponente):
        if f"Req {d.requisito} - {d.nombre_original}" == nombre:
            with d.archivo.open("rb") as archivo_aportado:
                return archivo_aportado.read()
    return None


@router.get("/{evaluacion_id}/proponentes/{proponente_id}/documento")
def documento(request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID, archivo: str) -> HttpResponse:
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    proponente = get_object_or_404(Proponente, pk=proponente_id, proceso_id=evaluacion.proceso_id)
    if evaluacion.proceso.documentos_eliminados_en:
        raise HttpError(
            410,
            f"Los documentos de este proceso se eliminaron el {timezone.localtime(evaluacion.proceso.documentos_eliminados_en):%d/%m/%Y} "
            "por la política de retención. Los resultados, decisiones e informes se conservan.",
        )
    # Certificados que el evaluador subió o que el programa consultó en línea:
    # el motor los evalúa como documentos del proponente, así que también se
    # abren desde aquí ("aportados/Req 17 - RNMC 43001767.pdf").
    if archivo.startswith(PREFIJO_APORTADOS):
        contenido = _contenido_aportado(evaluacion, proponente, archivo[len(PREFIJO_APORTADOS) :])
        if contenido is None:
            raise HttpError(404, "Ese certificado aportado ya no está disponible.")
        auditar(request, "documento.visto", objeto=evaluacion, hoja=proponente.hoja, archivo=archivo)
        return HttpResponse(contenido, content_type="application/pdf")
    try:
        zip_bytes = download_file_bytes(proponente.drive_file_id)
    except Exception as exc:  # noqa: BLE001
        raise HttpError(502, "No se pudo descargar la oferta de Google Drive. Inténtelo de nuevo en unos minutos.") from exc
    contenido = extraer_pdfs(zip_bytes).get(archivo)
    if contenido is None:
        raise HttpError(404, "No se encontró ese documento dentro de la oferta del proponente.")
    auditar(request, "documento.visto", objeto=evaluacion, hoja=proponente.hoja, archivo=archivo)
    return HttpResponse(contenido, content_type="application/pdf")
