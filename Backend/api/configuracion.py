"""Configuración por entidad: plantillas de informe por tipo de evaluación."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, HttpRequest
from django.shortcuts import get_object_or_404
from ninja import File, Form, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from cuentas.models import Entidad, Rol, Usuario
from cuentas.seguridad import auditar, sesion_activa
from evaluaciones.models import PlantillaInforme
from evaluaciones.tipos import TIPOS
from motor.excel.filler import MAPEO_POR_DEFECTO, MapeoPlantilla, inspeccionar_plantilla

router = Router(tags=["configuración"], auth=sesion_activa)


class PlantillaOut(Schema):
    id: UUID
    tipo: str
    nombre_original: str
    subida_en: datetime
    subida_por: str | None
    activa: bool
    mapeo: dict
    inspeccion: dict


class PlantillasTipoOut(Schema):
    tipo: str
    tipo_nombre: str
    motor_disponible: bool
    activa: PlantillaOut | None
    # Sin plantilla propia: se usa la de ejemplo del sistema (solo jurídica).
    usa_plantilla_del_sistema: bool
    historial: list[PlantillaOut]


class MapeoIn(Schema):
    mapeo: MapeoPlantilla


def entidad_configurable(usuario: Usuario, entidad_id: UUID | None) -> Entidad:
    """Superadmin: cualquier entidad (indicándola). Administrador: la suya."""
    if usuario.es_superadmin:
        if entidad_id is None:
            raise HttpError(400, "Indique la entidad.")
        return get_object_or_404(Entidad, pk=entidad_id)
    if usuario.rol != Rol.ADMIN_ENTIDAD:
        raise HttpError(403, "Solo el administrador de la entidad puede cambiar su configuración.")
    if entidad_id is not None and entidad_id != usuario.entidad_id:
        raise HttpError(404, "No encontrado.")
    return usuario.entidad


def _out(p: PlantillaInforme) -> PlantillaOut:
    return PlantillaOut(
        id=p.id,
        tipo=p.tipo,
        nombre_original=p.nombre_original,
        subida_en=p.subida_en,
        subida_por=p.subida_por.nombre_completo if p.subida_por else None,
        activa=p.activa,
        mapeo=p.mapeo,
        inspeccion=p.inspeccion,
    )


def _plantilla(usuario: Usuario, plantilla_id: UUID) -> PlantillaInforme:
    plantilla = get_object_or_404(PlantillaInforme.objects.select_related("subida_por"), pk=plantilla_id)
    entidad_configurable(usuario, plantilla.entidad_id if usuario.es_superadmin else None)
    if not usuario.es_superadmin and plantilla.entidad_id != usuario.entidad_id:
        raise HttpError(404, "No encontrado.")
    return plantilla


def plantilla_para_informe(entidad_id: UUID, tipo: str) -> tuple[Path, MapeoPlantilla] | None:
    """Plantilla activa de la entidad o, si no tiene, la de ejemplo del sistema."""
    propia = PlantillaInforme.objects.filter(entidad_id=entidad_id, tipo=tipo, activa=True).first()
    if propia is not None:
        return Path(propia.archivo.path), MapeoPlantilla.model_validate(propia.mapeo)
    del_sistema = TIPOS[tipo].plantilla
    if del_sistema is not None and del_sistema.exists():
        return del_sistema, MAPEO_POR_DEFECTO
    return None


@router.get("/plantillas", response=list[PlantillasTipoOut])
def listar_plantillas(request: HttpRequest, entidad_id: UUID | None = None) -> list[PlantillasTipoOut]:
    entidad = entidad_configurable(request.auth, entidad_id)
    todas = list(PlantillaInforme.objects.filter(entidad=entidad).select_related("subida_por"))
    salida = []
    for t in TIPOS.values():
        propias = [p for p in todas if p.tipo == t.clave]
        activa = next((p for p in propias if p.activa), None)
        salida.append(
            PlantillasTipoOut(
                tipo=t.clave,
                tipo_nombre=t.nombre,
                motor_disponible=t.disponible,
                activa=_out(activa) if activa else None,
                usa_plantilla_del_sistema=activa is None and t.plantilla is not None,
                historial=[_out(p) for p in propias],
            )
        )
    return salida


@router.post("/plantillas", response={201: PlantillaOut})
def subir_plantilla(
    request: HttpRequest,
    tipo: Form[str],
    archivo: File[UploadedFile],
    entidad_id: UUID | None = None,
):
    usuario: Usuario = request.auth
    entidad = entidad_configurable(usuario, entidad_id)
    if tipo not in TIPOS:
        raise HttpError(400, "Tipo de evaluación no válido.")
    nombre = (archivo.name or "plantilla.xlsx").strip()
    if not nombre.lower().endswith(".xlsx"):
        raise HttpError(400, "La plantilla debe ser un archivo de Excel .xlsx (sin macros).")
    if archivo.size > settings.PLANTILLA_MAX_BYTES:
        raise HttpError(400, "La plantilla supera el tamaño máximo de 20 MB.")
    contenido = archivo.read()
    if not contenido.startswith(b"PK"):
        raise HttpError(400, "El archivo no es un Excel .xlsx válido.")
    # Si la entidad ya tenía plantilla de ese tipo, se parte de su mapeo.
    anterior = PlantillaInforme.objects.filter(entidad=entidad, tipo=tipo, activa=True).first()
    mapeo = MapeoPlantilla.model_validate(anterior.mapeo) if anterior else MAPEO_POR_DEFECTO
    inspeccion = inspeccionar_plantilla(contenido, mapeo)
    if not inspeccion["hojas"]:
        raise HttpError(400, inspeccion["problemas"][0] if inspeccion["problemas"] else "No se pudo leer la plantilla.")
    archivo.seek(0)
    with transaction.atomic():
        PlantillaInforme.objects.filter(entidad=entidad, tipo=tipo, activa=True).update(activa=False)
        plantilla = PlantillaInforme(
            entidad=entidad,
            tipo=tipo,
            nombre_original=nombre[:255],
            mapeo=mapeo.model_dump(),
            inspeccion=inspeccion,
            subida_por=usuario,
        )
        plantilla.archivo.save(nombre, archivo, save=False)
        plantilla.save()
        auditar(request, "plantilla.subida", entidad_id=entidad.id, objeto=plantilla, tipo=tipo, archivo=nombre)
    return 201, _out(plantilla)


@router.put("/plantillas/{plantilla_id}/mapeo", response=PlantillaOut)
def ajustar_mapeo(request: HttpRequest, plantilla_id: UUID, datos: MapeoIn) -> PlantillaOut:
    plantilla = _plantilla(request.auth, plantilla_id)
    with plantilla.archivo.open("rb") as f:
        inspeccion = inspeccionar_plantilla(f.read(), datos.mapeo)
    plantilla.mapeo = datos.mapeo.model_dump()
    plantilla.inspeccion = inspeccion
    plantilla.save(update_fields=["mapeo", "inspeccion"])
    auditar(request, "plantilla.mapeo_ajustado", entidad_id=plantilla.entidad_id, objeto=plantilla, tipo=plantilla.tipo)
    return _out(plantilla)


@router.post("/plantillas/{plantilla_id}/activar", response=PlantillaOut)
def activar_plantilla(request: HttpRequest, plantilla_id: UUID) -> PlantillaOut:
    plantilla = _plantilla(request.auth, plantilla_id)
    with transaction.atomic():
        PlantillaInforme.objects.filter(entidad_id=plantilla.entidad_id, tipo=plantilla.tipo, activa=True).update(activa=False)
        plantilla.activa = True
        plantilla.save(update_fields=["activa"])
        auditar(request, "plantilla.activada", entidad_id=plantilla.entidad_id, objeto=plantilla, tipo=plantilla.tipo)
    return _out(plantilla)


@router.delete("/plantillas/{plantilla_id}", response={204: None})
def borrar_plantilla(request: HttpRequest, plantilla_id: UUID):
    plantilla = _plantilla(request.auth, plantilla_id)
    auditar(request, "plantilla.borrada", entidad_id=plantilla.entidad_id, objeto=plantilla, tipo=plantilla.tipo, archivo=plantilla.nombre_original)
    plantilla.archivo.delete(save=False)
    plantilla.delete()
    return 204, None


@router.get("/plantillas/{plantilla_id}/archivo")
def descargar_plantilla(request: HttpRequest, plantilla_id: UUID) -> FileResponse:
    plantilla = _plantilla(request.auth, plantilla_id)
    return FileResponse(plantilla.archivo.open("rb"), as_attachment=True, filename=plantilla.nombre_original)
