"""Procesos y evaluaciones guardados en el servidor: creación, asignación,
fila de evaluación, revisiones, aprobación, informe y documentos."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from django.conf import settings
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
from cuentas.seguridad import auditar, entidades_con_datos, requiere_rol, sesion_activa, ve_datos_de
from evaluaciones import cumplimiento, estructura, expediente, muestra, puntaje, servicios
from evaluaciones import pliego as pliego_servicio
from evaluaciones.tipos import MENSAJE_EN_PREPARACION, TIPOS
from evaluaciones.models import (
    AnalisisPliego,
    EstadoEvaluacion,
    MiembroComite,
    ItemMuestra,
    MuestraControl,
    EstadoTrabajo,
    Expediente,
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
    exigir_compromiso,
    exigir_gestion,
    exigir_trabajo,
    puede_crear_procesos,
    puede_eliminar_proceso,
    puede_gestionar,
    puede_trabajar,
    filtro_visibles,
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
    # Dependencia que evalúa y comité designado (el primero es el coordinador).
    dependencia: dict | None = None
    comite: list[PersonaOut] = []


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
    # evaluaciones aprobadas ni expedientes.
    puede_eliminar: bool = False
    # Archivar: quien puede eliminarlo, aunque tenga expediente.
    puede_archivar: bool = False
    archivado_en: datetime | None = None


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
    # Dependencia que evalúa cada área: {"tecnica": id}. Sin enviar, la que
    # sugiere el objeto del contrato (o la única del área).
    dependencias: dict[str, UUID | None] | None = None
    # La preparación de la que sale (proceso a medio crear): se borra al crearlo.
    preparacion_id: UUID | None = None
    # Más integrantes del comité por tipo, además del responsable (que lo coordina):
    # {"juridica": [id, id]}. Solo jefes y administradores.
    comites: dict[str, list[UUID]] | None = None


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


class ExplicacionOut(Schema):
    """La explicación en palabras llanas de un resultado. `texto` es None
    cuando el modelo local no está disponible o no se pudo verificar lo que
    respondió: entonces la pantalla se queda con el detalle técnico."""

    texto: str | None = None


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
    # Las otras áreas del mismo proceso que este usuario puede poner a evaluar
    # ahora (les faltan proponentes): [{id, tipo_nombre}]. Para evaluar las
    # tres a la vez desde los datos del proceso.
    otras_por_evaluar: list[dict] = []


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
    comites: dict = {}
    for m in MiembroComite.objects.filter(evaluacion_id__in=ids, retirado_en__isnull=True).select_related("usuario"):
        comites.setdefault(m.evaluacion_id, []).append(m.usuario)
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
            dependencia={"id": str(e.dependencia_id), "nombre": e.dependencia.nombre} if e.dependencia_id else None,
            comite=[_persona(u) for u in comites.get(e.id, [])],
        )
        for e in evaluaciones
    ]


def _evaluaciones_qs(usuario: Usuario):
    qs = Evaluacion.objects.select_related("proceso", "responsable", "entidad", "plantilla", "dependencia")
    visibles = entidades_con_datos(usuario)
    if visibles is not None:
        qs = qs.filter(entidad_id__in=visibles)
    # Dentro de la entidad, solo las que le corresponden: comité designado,
    # quien la gestiona o el administrador.
    reservadas = filtro_visibles(usuario)
    if reservadas is not None:
        qs = qs.filter(pk__in=Evaluacion.objects.filter(reservadas).values("pk"))
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
def listar_procesos(request: HttpRequest, archivados: bool = False) -> list[ProcesoResumenOut]:
    """Los procesos en los que la persona tiene alguna evaluación a la vista
    (comité designado, quien la gestiona o el administrador) y los que ella
    misma creó. Los archivados solo con `archivados=true`."""
    usuario: Usuario = request.auth
    procesos = Proceso.objects.select_related("creado_por").annotate(n=Count("proponentes"))
    visibles = entidades_con_datos(usuario)
    if visibles is not None:
        procesos = procesos.filter(entidad_id__in=visibles)
    procesos = procesos.filter(archivado_en__isnull=not archivados)
    if filtro_visibles(usuario) is not None:
        procesos = procesos.filter(Q(creado_por=usuario) | Q(pk__in=_evaluaciones_qs(usuario).values("proceso_id")))
    procesos = list(procesos)
    evaluaciones = list(_evaluaciones_qs(usuario).filter(proceso__in=procesos).order_by("tipo"))
    por_proceso: dict[UUID, list[EvaluacionResumenOut]] = {}
    aprobados = {e.proceso_id: True for e in evaluaciones if e.estado == EstadoEvaluacion.APROBADA}
    con_expediente = set(Expediente.objects.filter(evaluacion__proceso__in=procesos).values_list("evaluacion__proceso_id", flat=True))
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
            puede_eliminar=puede_eliminar_proceso(usuario, p) and not aprobados.get(p.id, False) and p.id not in con_expediente,
            puede_archivar=puede_eliminar_proceso(usuario, p),
            archivado_en=p.archivado_en,
        )
        for p in procesos
    ]


@router.post("/procesos/{proceso_id}/archivar", response={204: None})
def archivar_proceso(request: HttpRequest, proceso_id: UUID, archivar: bool = True):
    """Archiva (o desarchiva) un proceso: deja de aparecer en las listas, pero
    se conserva con todo lo suyo. Es la salida para un proceso que ya tuvo
    expediente y por eso no se puede eliminar."""
    usuario: Usuario = request.auth
    proceso = get_object_or_404(Proceso, pk=proceso_id)
    if not puede_eliminar_proceso(usuario, proceso):
        raise HttpError(403, "Solo el administrador de la entidad o quien creó el proceso puede archivarlo.")
    proceso.archivado_en = timezone.now() if archivar else None
    proceso.archivado_por = usuario if archivar else None
    proceso.save(update_fields=["archivado_en", "archivado_por"])
    auditar(request, "proceso.archivado" if archivar else "proceso.desarchivado", objeto=proceso, codigo=proceso.codigo)
    return 204, None


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
        if not ve_datos_de(usuario, entidad.id):
            raise HttpError(403, "Necesita un permiso temporal del administrador de esa entidad para trabajar en sus procesos.")
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

    # Un archivo del OneDrive de Microsoft 365 solo puede ser del directorio de
    # la entidad: el identificador llega del navegador y podría apuntar a otra.
    from motor.integrations import onedrive_empresa

    for p in datos.proponentes:
        if onedrive_empresa.es_id(p.drive_file_id):
            directorio = onedrive_empresa.partes(p.drive_file_id)[0]
            if not entidad.microsoft_directorio or directorio.lower() != entidad.microsoft_directorio.lower():
                raise HttpError(400, f"La oferta de {p.hoja} es de un OneDrive de otra organización.")

    # Integrantes adicionales del comité: válidos, sin repetir y con responsable.
    adicionales: dict[str, list[Usuario]] = {}
    for tipo, ids in (datos.comites or {}).items():
        ids = [x for x in dict.fromkeys(ids) if not (responsables.get(tipo) and x == responsables[tipo].id)]
        if not ids or tipo not in tipos:
            continue
        if not gestiona:
            raise HttpError(403, "Solo el jefe del área o el administrador designan el comité.")
        if not responsables.get(tipo):
            raise HttpError(400, f"Elija primero el responsable de la evaluación {TipoArea(tipo).label.lower()}: él coordina el comité.")
        adicionales[tipo] = [_responsable_valido(entidad.id, tipo, x, usuario) for x in ids]

    doc = datos.documento_base
    try:
        with transaction.atomic():
            proceso = Proceso.objects.create(
                entidad=entidad,
                codigo=doc.codigo_proceso.strip().upper(),
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
                elegida = (datos.dependencias or {}).get(tipo)
                try:
                    dependencia = (
                        estructura.dependencia_valida(entidad.id, tipo, elegida)
                        if elegida
                        else estructura.sugerir_dependencia(entidad.id, tipo, doc.objeto_general)
                    )
                except estructura.ErrorEstructura as exc:
                    raise HttpError(400, str(exc)) from exc
                evaluacion = Evaluacion.objects.create(
                    entidad=entidad,
                    proceso=proceso,
                    tipo=tipo,
                    dependencia=dependencia,
                    plantilla=servicios.plantilla_activa(entidad.id, tipo),
                    responsable=responsable,
                    asignada_por=usuario if responsable else None,
                    asignada_en=timezone.now() if responsable else None,
                    estado=EstadoEvaluacion.ASIGNADA if responsable else EstadoEvaluacion.SIN_ASIGNAR,
                )
                evaluaciones.append(evaluacion)
                if responsable:
                    # Queda en el comité (con los demás integrantes, si se eligieron);
                    # si lo designa un jefe o administrador, con su documento de designación.
                    miembros = [responsable, *adicionales.get(tipo, [])]
                    estructura.designar_comite(evaluacion, miembros, usuario,
                                               documentar=gestiona and any(m.id != usuario.id for m in miembros))
                    for miembro in miembros:
                        if miembro.id != usuario.id:
                            transaction.on_commit(lambda e=evaluacion, m=miembro: enviar_asignacion(e, m, usuario))
            auditar(
                request,
                "proceso.creado",
                entidad_id=entidad.id,
                objeto=proceso,
                codigo=proceso.codigo,
                proponentes=len(datos.proponentes),
                tipos=tipos,
                responsables={t: (r.email if r else None) for t, r in responsables.items()},
                comites={t: [m.email for m in ms] for t, ms in adicionales.items()},
                pliego=analisis.nombre_archivo if analisis else None,
                ajustes_pliego={a["id"]: a["decision"] for a in ajustes},
            )
    except IntegrityError as exc:
        raise HttpError(409, f"Ya existe un proceso con el código {doc.codigo_proceso} en esa entidad.") from exc
    for e in evaluaciones:
        e.proceso = proceso
        e.entidad = entidad
    if datos.preparacion_id:
        # El proceso ya existe: el borrador del que salió sobra.
        from evaluaciones import preparacion
        from evaluaciones.models import PreparacionProceso

        borrador = PreparacionProceso.objects.filter(pk=datos.preparacion_id, creada_por=usuario).first()
        if borrador is not None:
            preparacion.borrar(borrador)
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
@router.get("/requisitos-no-automatizados", response=list[dict])
def requisitos_no_automatizados(request: HttpRequest, limite: int = 200) -> list[dict]:
    """Lo que los pliegos exigen y el programa no sabe verificar, acumulado de
    todos los procesos evaluados y ordenado por lo que más trabajo humano
    cuesta. Es la lista de qué automatizar primero: sale de los pliegos reales,
    no de suposiciones.

    Solo para superadministración y soporte: junta información de varias
    entidades."""
    from evaluaciones.models import RequisitoNoAutomatizado

    usuario: Usuario = request.auth
    if not (usuario.es_superadmin or usuario.rol == Rol.SOPORTE):
        raise HttpError(403, "Solo superadministración y soporte pueden ver este registro.")
    filas = RequisitoNoAutomatizado.objects.filter(verificacion="").prefetch_related("entidades")[: max(1, min(limite, 500))]
    return [
        # Lo que el pliego exige y no sabemos verificar.
        {
            "clave": f.clave,
            "requisito": f.requisito,
            "cita": f.cita,
            "clase": f.clase,
            "area": f.area,
            "veces": f.veces,
            "veces_asumido": f.veces_asumido,
            "procesos": f.procesos,
            "entidades": f.entidades.count(),
            "primera_vez": f.primera_vez,
            "ultima_vez": f.ultima_vez,
        }
        for f in filas
    ]


@router.get("/causas-de-revision", response=list[dict])
def causas_de_revision(request: HttpRequest, limite: int = 200) -> list[dict]:
    """Por qué las ofertas necesitaron que las mirara una persona cuando el
    programa sí sabía qué verificar: la lectura que falló, y en cuántas ofertas.
    La otra mitad de la hoja de ruta —esto se arregla mejorando una lectura que
    ya existe, no programando una verificación nueva—.

    Solo para superadministración y soporte: junta información de varias
    entidades."""
    from evaluaciones.models import CausaDeRevision

    usuario: Usuario = request.auth
    if not (usuario.es_superadmin or usuario.rol == Rol.SOPORTE):
        raise HttpError(403, "Solo superadministración y soporte pueden ver este registro.")
    return [
        {"clave": c.clave, "ambito": c.ambito, "area": c.area, "ejemplo": c.ejemplo,
         "ofertas": c.ofertas, "veces": c.veces, "procesos": c.procesos,
         "primera_vez": c.primera_vez, "ultima_vez": c.ultima_vez, "nota": c.nota}
        for c in CausaDeRevision.objects.all()[: max(1, min(limite, 500))]
    ]


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
        otras_por_evaluar=_otras_por_evaluar(usuario, evaluacion, len(proponentes)),
    )


def _otras_por_evaluar(usuario: Usuario, evaluacion: Evaluacion, n_proponentes: int) -> list[dict]:
    otras = (
        Evaluacion.objects.filter(proceso_id=evaluacion.proceso_id)
        .exclude(id=evaluacion.id)
        .exclude(estado__in=[EstadoEvaluacion.APROBADA, EstadoEvaluacion.EVALUANDO])
        .annotate(evaluados=Count("resultados__proponente", distinct=True))
    )
    return [
        {"id": str(e.id), "tipo_nombre": TIPOS[e.tipo].nombre}
        for e in sorted(otras, key=lambda e: list(TIPOS).index(e.tipo) if e.tipo in TIPOS else 99)
        if TIPOS[e.tipo].disponible and puede_trabajar(usuario, e) and e.evaluados < n_proponentes
    ]


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
    if datos.codigo_proceso.strip().upper() != proceso.codigo.upper():
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
        if nuevo:
            # El nuevo coordinador encabeza el comité; los demás siguen.
            otros = [u for u in estructura.comite_activo(evaluacion) if u.id not in (nuevo.id, anterior and anterior.id)]
            try:
                estructura.designar_comite(evaluacion, [nuevo, *otros], usuario)
            except estructura.ErrorEstructura as exc:
                raise HttpError(400, str(exc)) from exc
        else:
            MiembroComite.objects.filter(evaluacion=evaluacion, retirado_en__isnull=True).update(retirado_en=timezone.now())
            evaluacion.responsable = None
            evaluacion.asignada_por = None
            evaluacion.asignada_en = None
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
    # Quién está revisando cada proponente ahora mismo: [{hoja, nombre, propio}].
    bloqueos: list[dict] = []


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
        bloqueos=_bloqueos_out(evaluacion, usuario),
    )


def _bloqueos_out(evaluacion: Evaluacion, usuario: Usuario) -> list[dict]:
    return [
        {"hoja": b.proponente.hoja, "nombre": b.usuario.nombre_completo, "propio": b.usuario_id == usuario.id}
        for b in estructura.bloqueos_vigentes(evaluacion)
    ]


@router.put("/{evaluacion_id}/revisiones", response={200: RevisionOut | None})
def revisar(request: HttpRequest, evaluacion_id: UUID, datos: RevisarIn):
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    proponente = get_object_or_404(Proponente, pk=datos.proponente_id, proceso_id=evaluacion.proceso_id)
    otro = estructura.bloqueado_por_otro(evaluacion, proponente, usuario)
    if otro is not None:
        raise HttpError(409, f"{otro.nombre_completo} está revisando este proponente. Espere a que lo cierre.")
    if datos.cumple is not None and len(datos.nota.strip()) < 5:
        raise HttpError(400, "Escriba la justificación de su decisión: queda en el reporte formal de evaluación.")
    if datos.cumple is not None:
        # Decidir exige el compromiso de uso y haber visto el soporte (LEG-004, 3.1 y 6.4).
        exigir_compromiso(usuario)
        resultado = Resultado.objects.filter(evaluacion=evaluacion, proponente=proponente, requisito=datos.requisito).first()
        try:
            muestra.exigir_soporte(usuario, evaluacion, proponente, resultado.datos if resultado else None, datos.nota)
        except muestra.ErrorMuestra as exc:
            raise HttpError(409, str(exc)) from exc
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
    exigir_compromiso(usuario)
    # Lo verificado por el sistema se adopta con la muestra de control, y el
    # puntaje, por una persona (LEG-004, 1.2, 3 y 3.1).
    motivo = muestra.motivo_para_no_aprobar(evaluacion)
    if motivo:
        raise HttpError(409, motivo)
    if puntaje.tiene_puntaje(evaluacion):
        faltan = puntaje.sin_adoptar(evaluacion)
        if faltan:
            raise HttpError(409, f"Falta adoptar el puntaje de {len(faltan)} proponentes ({', '.join(faltan[:8])}{'…' if len(faltan) > 8 else ''}).")
    with transaction.atomic():
        evaluacion.estado = EstadoEvaluacion.APROBADA
        evaluacion.aprobada_por = usuario
        evaluacion.aprobada_en = timezone.now()
        evaluacion.version_sistema = settings.MIEVALUADOR_VERSION
        evaluacion.modelos_ia = cumplimiento.modelos_ia()
        evaluacion.save()
        # Expediente permanente (lo arma el trabajador en segundo plano).
        expediente.solicitar(evaluacion, usuario)
        auditar(request, "evaluacion.aprobada", objeto=evaluacion, proceso=evaluacion.proceso.codigo)
    return _resumenes(usuario, [evaluacion])[0]


# --- Muestra de control (LEG-004, numerales 3 y 3.1) -------------------------------
class ItemMuestraIn(Schema):
    conforme: bool
    nota: str = ""


def _muestra_out(evaluacion: Evaluacion) -> dict:
    return {
        "muestra": muestra.resumen(muestra.vigente(evaluacion)),
        "motivo_para_no_aprobar": muestra.motivo_para_no_aprobar(evaluacion),
        "verificaciones_por_muestra": settings.MUESTRA_VERIFICACIONES,
    }


@router.get("/{evaluacion_id}/muestra", response=dict)
def ver_muestra(request: HttpRequest, evaluacion_id: UUID) -> dict:
    evaluacion = _evaluacion(request.auth, evaluacion_id)
    return _muestra_out(evaluacion)


@router.post("/{evaluacion_id}/muestra", response=dict)
def crear_muestra(request: HttpRequest, evaluacion_id: UUID) -> dict:
    """Sortea las ofertas de la muestra de control (o devuelve la que está en curso)."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    exigir_compromiso(usuario)
    antes = muestra.vigente(evaluacion)
    try:
        nueva = muestra.crear(evaluacion, usuario)
    except muestra.ErrorMuestra as exc:
        raise HttpError(409, str(exc)) from exc
    if antes is None or antes.id != nueva.id:
        auditar(
            request, "muestra.creada", objeto=evaluacion, muestra=str(nueva.id), semilla=str(nueva.semilla),
            ofertas=nueva.ofertas_sorteadas, items=nueva.items.count(),
        )
    return _muestra_out(evaluacion)


@router.put("/{evaluacion_id}/muestra/items/{item_id}", response=dict)
def revisar_item_muestra(request: HttpRequest, evaluacion_id: UUID, item_id: int, datos: ItemMuestraIn) -> dict:
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    exigir_compromiso(usuario)
    item = get_object_or_404(ItemMuestra.objects.select_related("muestra", "proponente"), pk=item_id, muestra__evaluacion=evaluacion)
    try:
        muestra.registrar(item, usuario, datos.conforme, datos.nota)
    except muestra.ErrorMuestra as exc:
        raise HttpError(409, str(exc)) from exc
    auditar(
        request, "muestra.item", objeto=evaluacion, hoja=item.proponente.hoja, requisito=item.requisito,
        resultado=item.resultado, soporte_visto=item.soporte_visto,
    )
    if not datos.conforme:
        auditar(request, "muestra.ampliada", objeto=evaluacion, requisito=item.requisito)
    return _muestra_out(evaluacion)


@router.post("/{evaluacion_id}/muestra/cerrar", response=dict)
def cerrar_muestra(request: HttpRequest, evaluacion_id: UUID) -> dict:
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    exigir_compromiso(usuario)
    actual = muestra.vigente(evaluacion)
    if actual is None:
        raise HttpError(409, "No hay una muestra de control en curso.")
    try:
        muestra.cerrar(actual, usuario)
    except muestra.ErrorMuestra as exc:
        raise HttpError(409, str(exc)) from exc
    auditar(request, "muestra.cerrada", objeto=evaluacion, muestra=str(actual.id), ampliados=actual.requisitos_ampliados)
    return _muestra_out(evaluacion)


@router.get("/{evaluacion_id}/muestra/acta")
def acta_muestra(request: HttpRequest, evaluacion_id: UUID) -> HttpResponse:
    evaluacion = _evaluacion(request.auth, evaluacion_id)
    actual = muestra.vigente(evaluacion)
    if actual is None:
        raise HttpError(404, "Esta evaluación no tiene muestra de control.")
    contenido, nombre = muestra.generar_acta(actual)
    auditar(request, "muestra.acta_descargada", objeto=evaluacion)
    respuesta = HttpResponse(
        contenido, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


# --- Puntaje técnico: adopción por una persona ------------------------------------
class AdoptarPuntajeIn(Schema):
    nota: str = ""


@router.get("/{evaluacion_id}/puntajes", response=list[dict])
def ver_puntajes(request: HttpRequest, evaluacion_id: UUID) -> list[dict]:
    evaluacion = _evaluacion(request.auth, evaluacion_id)
    if not puntaje.tiene_puntaje(evaluacion):
        return []
    return puntaje.estado_puntajes(evaluacion)


@router.post("/{evaluacion_id}/puntajes/adoptar", response=list[dict])
def adoptar_puntajes(request: HttpRequest, evaluacion_id: UUID, datos: AdoptarPuntajeIn) -> list[dict]:
    """Adopta de una vez todos los puntajes resueltos, después de ver la tabla."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    exigir_compromiso(usuario)
    if not puntaje.tiene_puntaje(evaluacion):
        raise HttpError(409, "Esta evaluación no asigna puntaje.")
    try:
        adopciones = puntaje.adoptar_todos(evaluacion, usuario, datos.nota)
    except ValueError as exc:
        raise HttpError(409, str(exc)) from exc
    auditar(
        request, "puntaje.adoptado", objeto=evaluacion,
        puntajes={a.proponente.hoja: a.puntaje for a in adopciones}, detalle={a.proponente.hoja: a.detalle for a in adopciones},
    )
    return puntaje.estado_puntajes(evaluacion)


@router.post("/{evaluacion_id}/puntajes/{proponente_id}/adoptar", response=list[dict])
def adoptar_puntaje(request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID, datos: AdoptarPuntajeIn) -> list[dict]:
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    exigir_compromiso(usuario)
    if not puntaje.tiene_puntaje(evaluacion):
        raise HttpError(409, "Esta evaluación no asigna puntaje.")
    proponente = get_object_or_404(Proponente, pk=proponente_id, proceso_id=evaluacion.proceso_id)
    try:
        adopcion = puntaje.adoptar(evaluacion, proponente, usuario, datos.nota)
    except ValueError as exc:
        raise HttpError(409, str(exc)) from exc
    auditar(request, "puntaje.adoptado", objeto=evaluacion, hoja=proponente.hoja, puntaje=adopcion.puntaje, detalle=adopcion.detalle)
    return puntaje.estado_puntajes(evaluacion)


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
    evaluacion.version_sistema = ""
    evaluacion.modelos_ia = None
    evaluacion.save()
    servicios.actualizar_estado(evaluacion)
    auditar(request, "evaluacion.reabierta", objeto=evaluacion, proceso=evaluacion.proceso.codigo)
    return _resumenes(usuario, [evaluacion])[0]


FORMATOS = ("xlsx", "pdf")


def _entregar(request: HttpRequest, contenido: bytes, nombre: str, formato: str) -> HttpResponse:
    """El informe en Excel o, si se pide, en PDF (RF-22)."""
    from evaluaciones import exportar

    tipo = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if formato == "pdf":
        try:
            contenido = exportar.a_pdf(contenido, nombre)
        except exportar.ErrorExportacion as exc:
            raise HttpError(503, str(exc)) from exc
        nombre, tipo = f"{nombre.rsplit('.', 1)[0]}.pdf", "application/pdf"
    respuesta = HttpResponse(contenido, content_type=tipo)
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


@router.get("/{evaluacion_id}/consolidado")
def informe_consolidado(request: HttpRequest, evaluacion_id: UUID, formato: str = "xlsx") -> HttpResponse:
    """Las tres áreas del proceso en un solo archivo, con el puntaje y el
    orden de elegibilidad por lote."""
    if formato not in FORMATOS:
        raise HttpError(400, "Formato no válido: use xlsx o pdf.")
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    proceso = evaluacion.proceso
    try:
        contenido, nombre = servicios.generar_informe_consolidado(proceso)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    respuesta = _entregar(request, contenido, nombre, formato)
    auditar(request, "informe.consolidado_descargado", objeto=evaluacion, proceso=proceso.codigo, formato=formato)
    return respuesta


@router.get("/{evaluacion_id}/informe")
def informe(request: HttpRequest, evaluacion_id: UUID, formato: str = "xlsx") -> HttpResponse:
    if formato not in FORMATOS:
        raise HttpError(400, "Formato no válido: use xlsx o pdf.")
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    try:
        contenido, nombre = servicios.generar_informe_excel(evaluacion)
    except servicios.SinPlantillaInforme as exc:
        raise HttpError(400, "Este tipo de evaluación aún no tiene plantilla de informe. El administrador puede subirla en Configuración.") from exc
    proceso = evaluacion.proceso
    borrador = evaluacion.estado != EstadoEvaluacion.APROBADA
    respuesta = _entregar(request, contenido, nombre, formato)
    auditar(request, "informe.descargado", objeto=evaluacion, proceso=proceso.codigo, borrador=bool(borrador), formato=formato)
    return respuesta


@router.get("/{evaluacion_id}/resultados.csv")
def resultados_csv(request: HttpRequest, evaluacion_id: UUID) -> HttpResponse:
    """Resultados por proponente y requisito, con la decisión final, en CSV (RF-22)."""
    from evaluaciones.exportar import csv_resultados

    evaluacion = _evaluacion(request.auth, evaluacion_id)
    respuesta = HttpResponse(csv_resultados(evaluacion), content_type="text/csv; charset=utf-8")
    respuesta["Content-Disposition"] = f'attachment; filename="Resultados {evaluacion.proceso.codigo} {evaluacion.tipo}.csv"'
    auditar(request, "informe.csv_descargado", objeto=evaluacion, proceso=evaluacion.proceso.codigo)
    return respuesta


def _contenido_aportado(evaluacion, proponente, nombre: str) -> bytes | None:
    for como_se_llama, d in servicios.aportados_con_nombre(evaluacion, proponente):
        if como_se_llama == nombre:
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
    contenido = _pdf_de_la_oferta(proponente, archivo)
    auditar(request, "documento.visto", objeto=evaluacion, hoja=proponente.hoja, archivo=archivo)
    return HttpResponse(contenido, content_type="application/pdf")


def _pdf_de_la_oferta(proponente, archivo: str) -> bytes:
    try:
        zip_bytes = download_file_bytes(proponente.drive_file_id)
    except Exception as exc:  # noqa: BLE001
        raise HttpError(502, "No se pudo descargar la oferta de Google Drive. Inténtelo de nuevo en unos minutos.") from exc
    contenido = extraer_pdfs(zip_bytes).get(archivo)
    if contenido is None:
        raise HttpError(404, "No se encontró ese documento dentro de la oferta del proponente.")
    return contenido


@router.get("/{evaluacion_id}/proponentes/{proponente_id}/documento/pagina")
def pagina_del_documento(
    request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID, archivo: str, n: int = 1, resolucion: int = 110
) -> HttpResponse:
    """Una página del documento como imagen. Para los equipos cuyo navegador no
    muestra un PDF dentro de la página (tabletas y teléfonos): el visor pasa las
    páginas una por una. El total de páginas va en la cabecera X-Paginas."""
    import io

    from motor.procesamiento.pdf_utils import abrir_pdf

    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    proponente = get_object_or_404(Proponente, pk=proponente_id, proceso_id=evaluacion.proceso_id)
    if evaluacion.proceso.documentos_eliminados_en:
        raise HttpError(410, "Los documentos de este proceso se eliminaron por la política de retención.")
    if archivo.startswith(PREFIJO_APORTADOS):
        contenido = _contenido_aportado(evaluacion, proponente, archivo[len(PREFIJO_APORTADOS) :])
        if contenido is None:
            raise HttpError(404, "Ese certificado aportado ya no está disponible.")
    else:
        contenido = _pdf_de_la_oferta(proponente, archivo)
    try:
        with abrir_pdf(contenido) as pdf:
            total = len(pdf.pages)
            if total == 0:
                raise HttpError(422, "No se pudo abrir este documento para mostrarlo: descárguelo con «Abrir en pestaña nueva».")
            numero = min(max(1, n), total)
            imagen = pdf.pages[numero - 1].to_image(resolution=min(max(60, resolucion), 200)).original.convert("RGB")
    except HttpError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HttpError(422, "No se pudo dibujar esa página del documento.") from exc
    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", quality=82)
    if numero == 1:
        auditar(request, "documento.visto", objeto=evaluacion, hoja=proponente.hoja, archivo=archivo)
    respuesta = HttpResponse(salida.getvalue(), content_type="image/jpeg")
    respuesta["X-Paginas"] = str(total)
    respuesta["X-Pagina"] = str(numero)
    respuesta["Cache-Control"] = "private, max-age=300"
    return respuesta


class CoincidenciaOut(Schema):
    pagina: int
    fragmento: str


@router.get("/{evaluacion_id}/proponentes/{proponente_id}/documento/buscar", response=list[CoincidenciaOut])
def buscar_en_documento(request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID, archivo: str, q: str):
    """Busca un texto dentro de un documento de la oferta, página por página.
    Con el texto que leyó el programa (OCR en las páginas escaneadas): el
    buscador del navegador no encuentra nada en un escaneo, y la mayoría de las
    ofertas lo son. Sin distinguir mayúsculas ni tildes."""
    import re
    import unicodedata

    from motor.procesamiento.pdf_utils import paginas_de_texto

    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    proponente = get_object_or_404(Proponente, pk=proponente_id, proceso_id=evaluacion.proceso_id)
    if evaluacion.proceso.documentos_eliminados_en:
        raise HttpError(410, "Los documentos de este proceso se eliminaron por la política de retención.")
    buscado = q.strip()
    if len(buscado) < 2:
        return []
    if archivo.startswith(PREFIJO_APORTADOS):
        contenido = _contenido_aportado(evaluacion, proponente, archivo[len(PREFIJO_APORTADOS) :])
        if contenido is None:
            raise HttpError(404, "Ese certificado aportado ya no está disponible.")
    else:
        contenido = _pdf_de_la_oferta(proponente, archivo)

    def plano(texto: str) -> str:
        # Una letra por letra (sin tildes) para que las posiciones coincidan con el original.
        return "".join(unicodedata.normalize("NFD", c)[0] for c in texto).upper()

    patron = re.compile(r"\s+".join(re.escape(parte) for parte in plano(buscado).split()))
    salida: list[CoincidenciaOut] = []
    for numero, texto in enumerate(paginas_de_texto(contenido), 1):
        texto = " ".join(texto.split())
        for m in patron.finditer(plano(texto)):
            desde, hasta = max(0, m.start() - 70), min(len(texto), m.end() + 70)
            fragmento = ("…" if desde else "") + texto[desde:hasta] + ("…" if hasta < len(texto) else "")
            salida.append(CoincidenciaOut(pagina=numero, fragmento=fragmento))
            if len(salida) >= 100:
                return salida
    return salida


class AsociarDocumentosIn(Schema):
    # La lista completa de documentos asociados a mano al requisito (reemplaza la anterior).
    archivos: list[str]
    # Los que el programa relacionó y la persona quita porque no corresponden
    # (lista completa; None = no se toca).
    excluidos: list[str] | None = None


@router.put("/{evaluacion_id}/proponentes/{proponente_id}/requisitos/{numero}/documentos", response=dict)
def asociar_documentos(
    request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID, numero: int, datos: AsociarDocumentosIn
) -> dict:
    """Asocia a un requisito documentos de la carpeta del proponente que el
    programa no relacionó (llegaron con otro nombre, dentro de otro PDF…), o
    quita los que una persona había asociado. Queda guardado y se conserva al
    volver a evaluar. No cambia el resultado: solo qué documentos lo acompañan."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    if evaluacion.estado == EstadoEvaluacion.APROBADA:
        raise HttpError(409, "La evaluación está aprobada: reábrela para cambiar los documentos de un requisito.")
    proponente = get_object_or_404(Proponente, pk=proponente_id, proceso_id=evaluacion.proceso_id)
    resultado = Resultado.objects.filter(evaluacion=evaluacion, proponente=proponente, requisito=numero).first()
    if resultado is None:
        raise HttpError(404, "Ese requisito todavía no se evaluó para este proponente.")
    from evaluaciones.models import DocumentoAportado, Revision

    # Lo que el programa dio por verificado no se toca, salvo que la persona
    # haya dejado constancia de que no está de acuerdo con ese resultado.
    if (resultado.datos or {}).get("cumple") is True and not Revision.objects.filter(
        evaluacion=evaluacion, proponente=proponente, requisito=numero, cumple=False
    ).exists():
        raise HttpError(
            409,
            "El programa dio por verificado este requisito. Para cambiar sus documentos, primero marque que no está "
            "de acuerdo con el resultado.",
        )

    try:
        validos = set(extraer_pdfs(download_file_bytes(proponente.drive_file_id)).keys())
    except Exception as exc:  # noqa: BLE001
        raise HttpError(502, "No se pudo abrir la carpeta del proponente. Inténtelo de nuevo en unos minutos.") from exc
    validos |= {f"{PREFIJO_APORTADOS}{nombre}" for nombre, _ in servicios.aportados_con_nombre(evaluacion, proponente)}
    pedidos = list(dict.fromkeys(a for a in datos.archivos if a))
    excluidos_antes = list((resultado.datos or {}).get("archivos_excluidos") or [])
    excluidos = excluidos_antes if datos.excluidos is None else list(dict.fromkeys(a for a in datos.excluidos if a))
    ajenos = [a for a in [*pedidos, *excluidos] if a not in validos]
    if ajenos:
        raise HttpError(400, f"Ese documento no está en la carpeta del proponente: {ajenos[0]}")
    if len(pedidos) > 30:
        raise HttpError(400, "Son demasiados documentos para un solo requisito (máximo 30).")
    antes = list((resultado.datos or {}).get("archivos_asociados") or [])
    resultado.datos = {**(resultado.datos or {}), "archivos_asociados": pedidos, "archivos_excluidos": excluidos}
    resultado.save(update_fields=["datos"])
    # Quién añadió o quitó qué documento, y cuándo: queda en la auditoría.
    auditar(request, "requisito.documentos_cambiados", objeto=evaluacion, hoja=proponente.hoja, requisito=numero,
            anadidos=[a for a in pedidos if a not in antes], ya_no_anadidos=[a for a in antes if a not in pedidos],
            quitados=[a for a in excluidos if a not in excluidos_antes],
            restaurados=[a for a in excluidos_antes if a not in excluidos])
    return resultado.datos


class ArchivosProponenteOut(Schema):
    # Todos los documentos de la oferta, para poder mirar la carpeta y buscar a
    # mano el que el motor no encontró (llega con otro nombre, escaneado, etc.).
    archivos: list[str]
    # Certificados que el evaluador subió o que el programa consultó en línea.
    aportados: list[str]


@router.get("/{evaluacion_id}/proponentes/{proponente_id}/archivos", response=ArchivosProponenteOut)
def archivos_del_proponente(request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID) -> ArchivosProponenteOut:
    """Lista todos los documentos de la oferta del proponente. Sirve para que,
    cuando el motor no encuentra un documento (o lo encuentra con un nombre
    distinto), la persona pueda abrir la carpeta, verla y buscarlo. Cada nombre
    se abre con el endpoint /documento?archivo=…, incluidos los aportados."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    proponente = get_object_or_404(Proponente, pk=proponente_id, proceso_id=evaluacion.proceso_id)
    if evaluacion.proceso.documentos_eliminados_en:
        raise HttpError(
            410,
            f"Los documentos de este proceso se eliminaron el {timezone.localtime(evaluacion.proceso.documentos_eliminados_en):%d/%m/%Y} "
            "por la política de retención. Los resultados, decisiones e informes se conservan.",
        )
    from evaluaciones.models import DocumentoAportado

    aportados = [f"{PREFIJO_APORTADOS}{nombre}" for nombre, _ in servicios.aportados_con_nombre(evaluacion, proponente)]
    try:
        zip_bytes = download_file_bytes(proponente.drive_file_id)
    except Exception as exc:  # noqa: BLE001
        raise HttpError(502, "No se pudo descargar la oferta de Google Drive. Inténtelo de nuevo en unos minutos.") from exc
    return ArchivosProponenteOut(archivos=sorted(extraer_pdfs(zip_bytes).keys()), aportados=sorted(aportados))


_CLAVES_QUE_NO_EXPLICAN = {
    "contratos", "integrantes", "revisiones", "rups", "aporte_por_integrante", "lotes_presentados",
    "tarjetas", "estados", "no_aplica", "presentado",
}


def _lineas_del_detalle(detalle: dict | None, profundidad: int = 0) -> list[str]:
    """El detalle del motor en líneas de texto legibles, sin las listas largas
    (contratos, integrantes): lo que se explica es el resultado, no el volcado
    completo."""
    if not isinstance(detalle, dict) or profundidad > 2:
        return []
    lineas = []
    for clave, valor in detalle.items():
        if clave in _CLAVES_QUE_NO_EXPLICAN:
            continue
        nombre = str(clave).replace("_", " ")
        if isinstance(valor, dict):
            lineas.extend(f"{nombre}: {x}" for x in _lineas_del_detalle(valor, profundidad + 1))
        elif isinstance(valor, (str, int, float, bool)) and str(valor).strip():
            lineas.append(f"{nombre}: {valor}")
    return lineas


@router.get("/{evaluacion_id}/proponentes/{proponente_id}/explicacion/{numero}", response=ExplicacionOut)
def explicacion_del_resultado(
    request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID, numero: int, guardada: bool = False
) -> ExplicacionOut:
    """El resultado de un requisito contado en palabras llanas por el modelo
    local, para acompañar al detalle técnico (que no se reemplaza: es el dato
    que se puede verificar contra el documento).

    El modelo no decide nada. Recibe lo que el motor ya calculó y solo lo
    redacta; si añade una cifra que no venía, la respuesta se descarta y esto
    devuelve None."""
    from motor.llm.explicacion import explicar

    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    proponente = get_object_or_404(Proponente, pk=proponente_id, proceso_id=evaluacion.proceso_id)
    resultado = (
        Resultado.objects.filter(evaluacion=evaluacion, proponente=proponente, requisito=numero)
        .values_list("datos", flat=True)
        .first()
    )
    if resultado is None:
        raise HttpError(404, "Ese requisito todavía no se evaluó para este proponente.")
    catalogo = {r.get("numero"): r.get("nombre") for r in servicios.catalogo(servicios.definicion_de(evaluacion))}
    detalle = resultado.get("detalle") if isinstance(resultado, dict) else None
    por_revisar = []
    for area in (detalle or {}).values():
        if isinstance(area, dict):
            por_revisar.extend(
                str(r.get("que")) for r in (area.get("revisiones") or []) if isinstance(r, dict) and r.get("que")
            )
    texto = explicar(
        titulo=str(catalogo.get(numero) or f"Requisito {numero}"),
        motivo=str(resultado.get("motivo") or ("Cumple." if resultado.get("cumple") else "")),
        datos="\n".join(_lineas_del_detalle(detalle))[:2500],
        por_revisar=por_revisar[:8],
        # Al abrir el requisito solo se muestra la que ya existe; el modelo se
        # llama únicamente cuando la persona la pide.
        solo_guardada=guardada,
    )
    return ExplicacionOut(texto=texto)


# --- Comité evaluador y colaboración ---
class ComiteIn(Schema):
    # El primero es el coordinador.
    miembros: list[UUID]
    dependencia_id: UUID | None = None


class ComiteOut(Schema):
    dependencia: dict | None
    miembros: list[PersonaOut]
    designaciones: list[dict]


def _comite_out(evaluacion: Evaluacion) -> ComiteOut:
    return ComiteOut(
        dependencia={"id": str(evaluacion.dependencia_id), "nombre": evaluacion.dependencia.nombre} if evaluacion.dependencia_id else None,
        miembros=[_persona(u) for u in estructura.comite_activo(evaluacion)],
        designaciones=[
            {
                "id": d.id, "consecutivo": d.consecutivo, "version": d.version, "dependencia": d.dependencia,
                "miembros": d.miembros, "designado_por": d.designado_por.nombre_completo,
                "designado_en": d.designado_en.isoformat(), "sha256": d.sha256,
            }
            for d in evaluacion.designaciones.select_related("designado_por")
        ],
    )


@router.get("/{evaluacion_id}/comite", response=ComiteOut)
def ver_comite(request: HttpRequest, evaluacion_id: UUID) -> ComiteOut:
    return _comite_out(_evaluacion(request.auth, evaluacion_id))


@router.put("/{evaluacion_id}/comite", response=ComiteOut)
def designar_comite(request: HttpRequest, evaluacion_id: UUID, datos: ComiteIn) -> ComiteOut:
    """El jefe de la dependencia (o el administrador) designa el comité. Genera
    el documento de designación y avisa a los nuevos integrantes."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_gestion(usuario, evaluacion)
    miembros_qs = {u.id: u for u in Usuario.objects.filter(pk__in=datos.miembros)}
    if len(miembros_qs) != len(set(datos.miembros)):
        raise HttpError(400, "Algún integrante no existe.")
    miembros = [miembros_qs[i] for i in datos.miembros]
    antes = {u.id for u in estructura.comite_activo(evaluacion)}
    try:
        dependencia = estructura.dependencia_valida(evaluacion.entidad_id, evaluacion.tipo, datos.dependencia_id)
        with transaction.atomic():
            designacion = estructura.designar_comite(evaluacion, miembros, usuario, dependencia=dependencia)
            auditar(
                request, "comite.designado", objeto=evaluacion, proceso=evaluacion.proceso.codigo,
                consecutivo=designacion.consecutivo, sha256=designacion.sha256,
                dependencia=evaluacion.dependencia.nombre if evaluacion.dependencia_id else None,
                miembros=[m.email for m in miembros],
            )
            for m in miembros:
                if m.id not in antes and m.id != usuario.id:
                    transaction.on_commit(lambda m=m: enviar_asignacion(evaluacion, m, usuario))
    except estructura.ErrorEstructura as exc:
        raise HttpError(400, str(exc)) from exc
    evaluacion.refresh_from_db()
    return _comite_out(evaluacion)


@router.get("/{evaluacion_id}/designaciones/{designacion_id}/documento")
def documento_designacion(request: HttpRequest, evaluacion_id: UUID, designacion_id: int):
    from django.http import FileResponse

    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    d = get_object_or_404(evaluacion.designaciones, pk=designacion_id)
    auditar(request, "designacion.descargada", objeto=evaluacion, consecutivo=d.consecutivo)
    return FileResponse(
        d.archivo.open("rb"), as_attachment=True, filename=f"{d.consecutivo} designacion comite {evaluacion.proceso.codigo}.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.post("/{evaluacion_id}/proponentes/{proponente_id}/bloqueo", response=dict)
def tomar_bloqueo(request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID) -> dict:
    """Abre (o mantiene abierto) un proponente para revisarlo. Si otro
    integrante del comité lo tiene abierto, dice quién y no lo toma."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    if not puede_trabajar(usuario, evaluacion) or evaluacion.estado == EstadoEvaluacion.APROBADA:
        return {"propio": False, "nombre": None, "solo_lectura": True}
    proponente = get_object_or_404(Proponente, pk=proponente_id, proceso_id=evaluacion.proceso_id)
    propio, quien = estructura.tomar_bloqueo(evaluacion, proponente, usuario)
    return {"propio": propio, "nombre": quien.nombre_completo, "solo_lectura": False}


@router.delete("/{evaluacion_id}/proponentes/{proponente_id}/bloqueo", response={204: None})
def soltar_bloqueo(request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID):
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    proponente = get_object_or_404(Proponente, pk=proponente_id, proceso_id=evaluacion.proceso_id)
    estructura.soltar_bloqueo(evaluacion, proponente, usuario)
    return 204, None


# --- Acta de revisión cruzada de los comités (por proceso) ---
def _proceso_visible(usuario: Usuario, proceso_id: UUID) -> Proceso:
    proceso = get_object_or_404(Proceso.objects.select_related("entidad"), pk=proceso_id)
    if not ve_datos_de(usuario, proceso.entidad_id) or (not usuario.es_superadmin and proceso.entidad_id != usuario.entidad_id):
        raise HttpError(404, "No encontrado.")
    # El acta reúne las tres áreas: la ve quien tiene a la vista alguna de sus evaluaciones.
    if not _evaluaciones_qs(usuario).filter(proceso=proceso).exists():
        raise HttpError(404, "No encontrado.")
    return proceso


def _actas_out(usuario: Usuario, proceso: Proceso) -> dict:
    from evaluaciones import revision_cruzada

    return {
        "puede_generar": revision_cruzada.puede_generar(usuario, proceso),
        "actas": [
            {
                "id": a.id, "consecutivo": a.consecutivo, "version": a.version, "generada_por": a.generada_por.nombre_completo,
                "generada_en": a.generada_en.isoformat(), "sha256": a.sha256,
                "todas_aprobadas": all(x["aprobada"] for x in a.resumen.get("areas", [])),
                "pendientes": sum(x["pendientes"] for x in a.resumen.get("areas", [])),
            }
            for a in proceso.actas_revision_cruzada.select_related("generada_por")
        ],
    }


@router.get("/procesos/{proceso_id}/revision-cruzada", response=dict)
def ver_actas_revision_cruzada(request: HttpRequest, proceso_id: UUID) -> dict:
    usuario: Usuario = request.auth
    return _actas_out(usuario, _proceso_visible(usuario, proceso_id))


@router.post("/procesos/{proceso_id}/revision-cruzada", response=dict)
def generar_acta_revision_cruzada(request: HttpRequest, proceso_id: UUID) -> dict:
    """El jefe de una dependencia del proceso (o el administrador) genera el
    acta para la reunión de revisión cruzada de los tres comités."""
    from evaluaciones import revision_cruzada

    usuario: Usuario = request.auth
    proceso = _proceso_visible(usuario, proceso_id)
    if not revision_cruzada.puede_generar(usuario, proceso):
        raise HttpError(403, "Solo el jefe de una dependencia del proceso o el administrador generan el acta.")
    try:
        acta = revision_cruzada.generar(proceso, usuario)
    except revision_cruzada.ErrorActa as exc:
        raise HttpError(400, str(exc)) from exc
    auditar(request, "revision_cruzada.generada", entidad_id=proceso.entidad_id, objeto=proceso, codigo=proceso.codigo,
            consecutivo=acta.consecutivo, version=acta.version, sha256=acta.sha256)
    return _actas_out(usuario, proceso)


@router.get("/procesos/{proceso_id}/revision-cruzada/{acta_id}/documento")
def documento_revision_cruzada(request: HttpRequest, proceso_id: UUID, acta_id: int):
    from django.http import FileResponse

    usuario: Usuario = request.auth
    proceso = _proceso_visible(usuario, proceso_id)
    acta = get_object_or_404(proceso.actas_revision_cruzada, pk=acta_id)
    auditar(request, "revision_cruzada.descargada", entidad_id=proceso.entidad_id, objeto=proceso, consecutivo=acta.consecutivo)
    return FileResponse(
        acta.archivo.open("rb"), as_attachment=True, filename=f"{acta.consecutivo} revision cruzada {proceso.codigo}.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
