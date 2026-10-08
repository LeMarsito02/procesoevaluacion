"""Prestación de servicios (OPS): crear la contratación con sus documentos,
revisar lo que leyó el motor, decidir y descargar el certificado de idoneidad.

Es un módulo con licencia aparte (Entidad.modulo_ops). Una contratación la ven
quien la creó y el administrador de la entidad."""
from __future__ import annotations

import io
from datetime import date
from uuid import UUID

from django.conf import settings
from django.http import FileResponse, HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File, Form, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja.throttling import AuthRateThrottle

from cuentas.models import Entidad, Rol, Usuario
from cuentas.seguridad import auditar, sesion_activa, ve_datos_de
from evaluaciones import ops
from evaluaciones.models import ContratacionOps, DocumentoOps, EstadoOps, OrigenDocumentoOps, TablaHonorariosOps
from evaluaciones.permisos import exigir_compromiso, puede_crear_procesos, ve_toda_la_entidad

router = Router(auth=sesion_activa, tags=["ops"])

SIN_LICENCIA = "La entidad no tiene la licencia del módulo de prestación de servicios."


class DecisionesIn(Schema):
    periodos: dict[str, dict] | None = None
    # Un periodo que la persona agrega a mano, y el id de uno agregado que quita.
    agregar: dict | None = None
    quitar: str | None = None
    perfil: dict | None = None
    grado: str | None = None
    posgrado: str | None = None
    documentos: dict[str, dict | None] | None = None


class DatosIn(Schema):
    contratista_nombre: str | None = None
    contratista_cedula: str | None = None
    exige_libreta: bool | None = None
    fecha_referencia: str | None = None
    referencia: str | None = None


class TablaIn(Schema):
    vigencia: int
    norma: str = ""
    profesional: list[dict]
    reconocimiento: list[dict] = []
    entidad_id: UUID | None = None


def _entidad(usuario: Usuario, entidad_id: UUID | None) -> Entidad | None:
    """La entidad sobre la que actúa la persona (el superadministrador la elige)."""
    if not usuario.es_superadmin:
        return usuario.entidad
    if entidad_id is None or not ve_datos_de(usuario, entidad_id):
        return None
    return Entidad.objects.filter(pk=entidad_id).first()


def _visibles(usuario: Usuario):
    qs = ContratacionOps.objects.select_related("creada_por", "confirmada_por", "entidad")
    if usuario.es_superadmin:
        visibles = None if settings.SUPERADMIN_SIN_PERMISO else [e for e in Entidad.objects.values_list("id", flat=True) if ve_datos_de(usuario, e)]
        return qs if visibles is None else qs.filter(entidad_id__in=visibles)
    qs = qs.filter(entidad_id=usuario.entidad_id)
    if usuario.rol == Rol.CONSULTA:
        return qs.none()
    return qs if ve_toda_la_entidad(usuario) else qs.filter(creada_por=usuario)


def _una(usuario: Usuario, contratacion_id: UUID) -> ContratacionOps:
    return get_object_or_404(_visibles(usuario), pk=contratacion_id)


def _para_modificar(request: HttpRequest, contratacion_id: UUID, *, confirmada: bool = False) -> ContratacionOps:
    usuario: Usuario = request.auth
    c = _una(usuario, contratacion_id)
    if not puede_crear_procesos(usuario):
        raise HttpError(403, "Su rol no permite modificar contrataciones.")
    exigir_compromiso(usuario)
    if not c.entidad.modulo_ops:
        raise HttpError(403, SIN_LICENCIA)
    if c.estado == EstadoOps.CONFIRMADA and not confirmada:
        raise HttpError(409, "La contratación está confirmada. Reábrala para modificarla.")
    return c


def _resumen(c: ContratacionOps) -> dict:
    return {
        "id": str(c.id), "referencia": c.referencia, "contratista_nombre": c.contratista_nombre, "contratista_cedula": c.contratista_cedula,
        "estado": c.estado, "estado_nombre": c.get_estado_display(), "creada_en": c.creada_en.isoformat(),
        "creada_por": c.creada_por.nombre_completo, "entidad": c.entidad.nombre,
        "objeto": ((c.resultado or {}).get("estudio") or {}).get("objeto", ""),
    }


def _error(exc: ops.ErrorOps) -> HttpError:
    return HttpError(400, str(exc))


@router.get("")
def listar(request: HttpRequest, entidad_id: UUID | None = None) -> dict:
    usuario: Usuario = request.auth
    entidad = _entidad(usuario, entidad_id)
    return {
        # El superadministrador ve la opción siempre; al crear se valida la entidad que elija.
        "licenciado": usuario.es_superadmin or bool(entidad and entidad.modulo_ops),
        "puede_crear": puede_crear_procesos(usuario),
        "puede_configurar": usuario.es_superadmin or usuario.rol == Rol.ADMIN_ENTIDAD,
        "contrataciones": [_resumen(c) for c in _visibles(usuario)[:200]],
    }


@router.post("", response={201: dict}, throttle=[AuthRateThrottle(settings.LIMITES_API["pesado"])])
def crear(
    request: HttpRequest,
    documentos_contratista: File[list[UploadedFile]],
    # Vacíos, se leen de los certificados de antecedentes del contratista.
    contratista_nombre: Form[str] = "",
    contratista_cedula: Form[str] = "",
    documentos_entidad: File[list[UploadedFile] | None] = None,
    referencia: Form[str] = "",
    fecha_referencia: Form[date | None] = None,
    # "si" / "no" / "" (no se sabe): hombre menor de 50 años.
    exige_libreta: Form[str] = "",
    entidad_id: Form[UUID | None] = None,
):
    usuario: Usuario = request.auth
    if not puede_crear_procesos(usuario):
        raise HttpError(403, "Su rol no permite crear contrataciones.")
    exigir_compromiso(usuario)
    entidad = _entidad(usuario, entidad_id)
    if entidad is None:
        raise HttpError(400, "Elija la entidad de la contratación.")
    if not entidad.modulo_ops:
        raise HttpError(403, SIN_LICENCIA)
    nombre, cedula = " ".join(contratista_nombre.split()), "".join(ch for ch in contratista_cedula if ch.isdigit())
    if (nombre or cedula) and (len(nombre) < 5 or not 5 <= len(cedula) <= 12):
        raise HttpError(400, "Escriba el nombre completo y la cédula del contratista, o deje los dos vacíos para leerlos de sus documentos.")
    c = ContratacionOps.objects.create(
        entidad=entidad, referencia=referencia.strip()[:80], contratista_nombre=nombre[:200], contratista_cedula=cedula,
        exige_libreta={"si": True, "no": False}.get(exige_libreta.strip().lower()),
        fecha_referencia=fecha_referencia or timezone.localdate(), creada_por=usuario,
    )
    try:
        n = ops.guardar_archivos(c, OrigenDocumentoOps.CONTRATISTA, [(a.name or "documento.pdf", a.read()) for a in documentos_contratista], usuario)
        if n == 0:
            raise ops.ErrorOps("Suba al menos un documento del contratista en PDF.")
        ops.guardar_archivos(c, OrigenDocumentoOps.ENTIDAD, [(a.name or "documento.pdf", a.read()) for a in documentos_entidad or []], usuario)
    except ops.ErrorOps as exc:
        _eliminar(c)
        raise _error(exc) from exc
    auditar(request, "ops.creada", entidad_id=entidad.id, objeto=c, documentos=c.documentos.count())
    return 201, ops.detalle(c)


@router.get("/honorarios")
def ver_honorarios(request: HttpRequest, vigencia: int | None = None, entidad_id: UUID | None = None) -> dict:
    usuario: Usuario = request.auth
    entidad = _entidad(usuario, entidad_id)
    if entidad is None:
        raise HttpError(400, "Elija la entidad.")
    vigencia = vigencia or timezone.localdate().year
    tabla = TablaHonorariosOps.objects.filter(entidad=entidad, vigencia=vigencia).first()
    return {
        "vigencia": vigencia, "norma": tabla.norma if tabla else "", "profesional": tabla.profesional if tabla else [],
        "reconocimiento": tabla.reconocimiento if tabla else [],
        "vigencias": list(TablaHonorariosOps.objects.filter(entidad=entidad).values_list("vigencia", flat=True)),
    }


@router.put("/honorarios")
def guardar_honorarios(request: HttpRequest, datos: TablaIn) -> dict:
    usuario: Usuario = request.auth
    if not (usuario.es_superadmin or usuario.rol == Rol.ADMIN_ENTIDAD):
        raise HttpError(403, "Solo el administrador de la entidad registra la tabla de honorarios.")
    entidad = _entidad(usuario, datos.entidad_id)
    if entidad is None:
        raise HttpError(400, "Elija la entidad.")
    if not 2000 <= datos.vigencia <= 2100:
        raise HttpError(400, "La vigencia no es válida.")
    try:
        ops.validar_tabla(datos.profesional, datos.reconocimiento)
    except ops.ErrorOps as exc:
        raise _error(exc) from exc
    TablaHonorariosOps.objects.update_or_create(
        entidad=entidad, vigencia=datos.vigencia,
        defaults={"norma": datos.norma.strip()[:200], "profesional": datos.profesional, "reconocimiento": datos.reconocimiento, "actualizada_por": usuario},
    )
    auditar(request, "ops.honorarios", entidad_id=entidad.id, vigencia=datos.vigencia, norma=datos.norma.strip()[:200])
    return ver_honorarios(request, datos.vigencia, datos.entidad_id)


@router.get("/{contratacion_id}")
def ver(request: HttpRequest, contratacion_id: UUID) -> dict:
    return ops.detalle(_una(request.auth, contratacion_id))


@router.put("/{contratacion_id}/decisiones")
def decidir(request: HttpRequest, contratacion_id: UUID, datos: DecisionesIn) -> dict:
    c = _para_modificar(request, contratacion_id)
    if c.resultado is None:
        raise HttpError(409, "Todavía no termina el análisis de los documentos.")
    cambios = datos.dict(exclude_unset=True)
    try:
        ops.aplicar_decisiones(c, cambios)
    except ops.ErrorOps as exc:
        raise _error(exc) from exc
    auditar(request, "ops.decision", entidad_id=c.entidad_id, objeto=c, cambios=cambios)
    return ops.detalle(c)


@router.put("/{contratacion_id}/datos")
def corregir_datos(request: HttpRequest, contratacion_id: UUID, datos: DatosIn) -> dict:
    """Nombre, cédula, libreta militar o fecha del estudio previo. Si cambian,
    los documentos se leen de nuevo (lo decidido se conserva)."""
    c = _para_modificar(request, contratacion_id)
    cambios = datos.dict(exclude_unset=True)
    try:
        releer = ops.cambiar_datos(c, cambios)
    except ops.ErrorOps as exc:
        raise _error(exc) from exc
    if releer:
        ops.pedir_analisis(c)
    auditar(request, "ops.datos", entidad_id=c.entidad_id, objeto=c, cambios=sorted(cambios))
    return ops.detalle(c)


@router.post("/{contratacion_id}/documentos", throttle=[AuthRateThrottle(settings.LIMITES_API["pesado"])])
def agregar_documentos(request: HttpRequest, contratacion_id: UUID, origen: Form[str], archivos: File[list[UploadedFile]]) -> dict:
    """Documentos que faltaban (o una subsanación): se analiza todo de nuevo
    y las decisiones ya tomadas se conservan."""
    c = _para_modificar(request, contratacion_id)
    if origen not in OrigenDocumentoOps.values:
        raise HttpError(400, "Indique si el documento es de la entidad o del contratista.")
    try:
        n = ops.guardar_archivos(c, origen, [(a.name or "documento.pdf", a.read()) for a in archivos], request.auth)
    except ops.ErrorOps as exc:
        raise _error(exc) from exc
    if n:
        ops.pedir_analisis(c)
        auditar(request, "ops.documentos", entidad_id=c.entidad_id, objeto=c, origen=origen, agregados=n)
    return ops.detalle(c)


@router.post("/{contratacion_id}/reanalizar")
def reanalizar(request: HttpRequest, contratacion_id: UUID) -> dict:
    c = _para_modificar(request, contratacion_id)
    if c.estado in (EstadoOps.PENDIENTE, EstadoOps.ANALIZANDO):
        raise HttpError(409, "El análisis ya está en curso.")
    ops.pedir_analisis(c)
    auditar(request, "ops.reanalizar", entidad_id=c.entidad_id, objeto=c)
    return ops.detalle(c)


@router.post("/{contratacion_id}/confirmar")
def confirmar(request: HttpRequest, contratacion_id: UUID) -> dict:
    """La persona da por revisada la idoneidad: queda su nombre y la fecha, y
    ya no se modifica sin reabrirla."""
    c = _para_modificar(request, contratacion_id)
    if c.estado != EstadoOps.LISTA:
        raise HttpError(409, "Solo se confirma una contratación ya analizada.")
    datos = ops.detalle(c)
    if datos.get("perfil") is None:
        raise HttpError(409, "Registre primero el perfil que exige el estudio previo.")
    if datos["documentos_pendientes"]:
        raise HttpError(409, f"Quedan {datos['documentos_pendientes']} documentos por revisar: decida cada uno antes de confirmar.")
    c.estado, c.confirmada_por, c.confirmada_en = EstadoOps.CONFIRMADA, request.auth, timezone.now()
    c.save(update_fields=["estado", "confirmada_por", "confirmada_en", "actualizada_en"])
    auditar(request, "ops.confirmada", entidad_id=c.entidad_id, objeto=c, cumple=datos["cumple"], total_dias=datos["total_dias"])
    return ops.detalle(c)


@router.post("/{contratacion_id}/reabrir")
def reabrir(request: HttpRequest, contratacion_id: UUID) -> dict:
    c = _para_modificar(request, contratacion_id, confirmada=True)
    if c.estado != EstadoOps.CONFIRMADA:
        raise HttpError(409, "La contratación no está confirmada.")
    c.estado, c.confirmada_por, c.confirmada_en = EstadoOps.LISTA, None, None
    c.save(update_fields=["estado", "confirmada_por", "confirmada_en", "actualizada_en"])
    auditar(request, "ops.reabierta", entidad_id=c.entidad_id, objeto=c)
    return ops.detalle(c)


@router.get("/{contratacion_id}/certificado")
def descargar_certificado(request: HttpRequest, contratacion_id: UUID):
    c = _una(request.auth, contratacion_id)
    if c.resultado is None:
        raise HttpError(409, "Todavía no termina el análisis de los documentos.")
    try:
        contenido = ops.certificado(c)
    except ops.ErrorOps as exc:
        raise HttpError(409, str(exc)) from exc
    auditar(request, "ops.certificado", entidad_id=c.entidad_id, objeto=c, confirmada=c.estado == EstadoOps.CONFIRMADA)
    return FileResponse(
        io.BytesIO(contenido), as_attachment=True, filename=f"Certificado de idoneidad - {c.contratista_nombre}.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.get("/{contratacion_id}/documentos/{documento_id}")
def ver_documento(request: HttpRequest, contratacion_id: UUID, documento_id: UUID):
    c = _una(request.auth, contratacion_id)
    doc = get_object_or_404(DocumentoOps, pk=documento_id, contratacion=c)
    auditar(request, "ops.documento_visto", entidad_id=c.entidad_id, objeto=c, archivo=doc.nombre_original)
    respuesta = FileResponse(doc.archivo.open("rb"), content_type="application/pdf", filename=doc.nombre_original)
    # Se muestra dentro de la página (ver api.ver_pliego_analizado).
    respuesta["X-Frame-Options"] = "SAMEORIGIN"
    return respuesta


def _eliminar(c: ContratacionOps) -> None:
    for doc in c.documentos.all():
        doc.archivo.delete(save=False)
    c.delete()


@router.delete("/{contratacion_id}", response={204: None})
def eliminar(request: HttpRequest, contratacion_id: UUID):
    """Quien la creó o el administrador, mientras no esté confirmada."""
    usuario: Usuario = request.auth
    c = _una(usuario, contratacion_id)
    if usuario.rol in (Rol.CONSULTA, Rol.SOPORTE) or not (ve_toda_la_entidad(usuario) or c.creada_por_id == usuario.id):
        raise HttpError(403, "No tiene permiso para eliminar esta contratación.")
    if c.estado == EstadoOps.CONFIRMADA:
        raise HttpError(409, "Una contratación confirmada no se elimina: es registro de la decisión.")
    auditar(request, "ops.eliminada", entidad_id=c.entidad_id, objeto=c, contratista=c.contratista_nombre)
    _eliminar(c)
    return 204, None
