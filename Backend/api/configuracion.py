"""Configuración por entidad: plantillas de evaluación (requisitos, verificaciones,
parámetros, con versiones) y plantillas de Excel del informe, por tipo."""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from uuid import UUID

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db.models import Count
from django.db import transaction
from django.http import FileResponse, HttpRequest
from django.shortcuts import get_object_or_404
from ninja import File, Form, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja.throttling import AuthRateThrottle
from pydantic import ValidationError

from cuentas.models import Entidad, Rol, Usuario
from cuentas.seguridad import auditar, sesion_activa
from evaluaciones import servicios
from evaluaciones.models import Evaluacion, PlantillaEvaluacion, PlantillaInforme, Proponente
from evaluaciones.tipos import TIPOS
from motor import criterios
from motor.esquemas.proceso import ProcesoDocumentoBase
from motor.evaluacion.todos import probar_requisito
from motor.excel.filler import MAPEO_POR_DEFECTO, MapeoPlantilla, inspeccionar_plantilla
from motor.llm.cliente import consultar_json
from motor.workers import obtener_pool

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


@router.post("/plantillas", response={201: PlantillaOut}, throttle=[AuthRateThrottle(settings.LIMITES_API["pesado"])])
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


# --- Plantillas de evaluación (qué se evalúa y cómo) ---
class ParametroOut(Schema):
    clave: str
    nombre: str
    descripcion: str
    defecto: object
    tipo: str
    minimo: int | None
    maximo: int | None
    unidad: str


class VerificacionOut(Schema):
    clave: str
    corto: str
    titulo: str
    verifica: str
    grupo: str


class CatalogoOut(Schema):
    grupos: dict[str, str]
    parametros: list[ParametroOut]
    verificaciones: list[VerificacionOut]
    tipos_proponente: list[str]


class VersionOut(Schema):
    id: UUID
    version: int
    nombre: str
    nota: str
    activa: bool
    creada_en: datetime
    creada_por: str | None
    evaluaciones: int


class PlantillaEvaluacionOut(Schema):
    tipo: str
    tipo_nombre: str
    motor_disponible: bool
    # None = la entidad usa la base del sistema (sin versión propia).
    activa: VersionOut | None
    definicion: dict
    versiones: list[VersionOut]


class GuardarPlantillaIn(Schema):
    tipo: str
    nombre: str
    definicion: dict
    nota: str = ""


class ProbarIn(Schema):
    evaluacion_id: UUID
    requisito: dict
    parametros: dict = {}
    proponente_ids: list[UUID]


class ProponerIn(Schema):
    tipo: str = "juridica"
    descripcion: str


def _version_out(p: PlantillaEvaluacion, usos: dict) -> VersionOut:
    return VersionOut(
        id=p.id,
        version=p.version,
        nombre=p.nombre,
        nota=p.nota,
        activa=p.activa,
        creada_en=p.creada_en,
        creada_por=p.creada_por.nombre_completo if p.creada_por else None,
        evaluaciones=usos.get(p.id, 0),
    )


def _validar_definicion(datos: dict) -> criterios.DefinicionEvaluacion:
    try:
        return criterios.DefinicionEvaluacion.model_validate(datos)
    except ValidationError as exc:
        mensajes = []
        for e in exc.errors()[:5]:
            lugar = " › ".join(str(x) for x in e["loc"] if x != "__root__")
            mensajes.append(f"{e['msg'].removeprefix('Value error, ')}" + (f" ({lugar})" if lugar else ""))
        raise HttpError(400, " ".join(mensajes)) from exc


@router.get("/catalogo", response=CatalogoOut)
def catalogo_motor(request: HttpRequest, tipo: str = "juridica") -> CatalogoOut:
    return CatalogoOut(
        grupos=criterios.GRUPOS,
        parametros=[ParametroOut(**p.__dict__) for p in criterios.PARAMETROS.values()],
        verificaciones=[
            VerificacionOut(clave=v.clave, corto=v.corto, titulo=v.titulo, verifica=v.verifica, grupo=v.grupo)
            for v in criterios.VERIFICACIONES.values()
            if v.tipo == tipo
        ],
        tipos_proponente=list(criterios.TIPOS_PROPONENTE),
    )


@router.get("/evaluaciones", response=list[PlantillaEvaluacionOut])
def listar_plantillas_evaluacion(request: HttpRequest, entidad_id: UUID | None = None) -> list[PlantillaEvaluacionOut]:
    entidad = entidad_configurable(request.auth, entidad_id)
    versiones = list(PlantillaEvaluacion.objects.filter(entidad=entidad).select_related("creada_por"))
    usos = dict(
        Evaluacion.objects.filter(plantilla__in=versiones).values("plantilla_id").annotate(n=Count("id")).values_list("plantilla_id", "n")
    )
    salida = []
    for t in TIPOS.values():
        propias = [v for v in versiones if v.tipo == t.clave]
        activa = next((v for v in propias if v.activa), None)
        definicion = activa.definicion if activa else criterios.definicion_sistema(t.clave).model_dump(mode="json")
        salida.append(
            PlantillaEvaluacionOut(
                tipo=t.clave,
                tipo_nombre=t.nombre,
                motor_disponible=t.disponible,
                activa=_version_out(activa, usos) if activa else None,
                definicion=definicion,
                versiones=[_version_out(v, usos) for v in propias],
            )
        )
    return salida


@router.post("/evaluaciones", response={201: VersionOut})
def guardar_plantilla_evaluacion(request: HttpRequest, datos: GuardarPlantillaIn, entidad_id: UUID | None = None):
    """Publica una versión nueva. Las evaluaciones existentes siguen con su
    versión hasta que alguien las actualice; las nuevas usan esta."""
    usuario: Usuario = request.auth
    entidad = entidad_configurable(usuario, entidad_id)
    if datos.tipo not in TIPOS:
        raise HttpError(400, "Tipo de evaluación no válido.")
    if len(datos.nombre.strip()) < 3:
        raise HttpError(400, "Póngale un nombre a la plantilla (ej. «Evaluación jurídica 2026»).")
    definicion = _validar_definicion(datos.definicion)
    if not definicion.requisitos:
        raise HttpError(400, "La plantilla debe tener al menos un requisito.")
    version = servicios.nueva_version(entidad.id, datos.tipo, datos.nombre, definicion, usuario, datos.nota)
    auditar(
        request,
        "plantilla_evaluacion.publicada",
        entidad_id=entidad.id,
        objeto=version,
        tipo=datos.tipo,
        version=version.version,
        requisitos=len(definicion.requisitos),
    )
    return 201, _version_out(version, {})


@router.post("/evaluaciones/{version_id}/activar", response=VersionOut)
def activar_version(request: HttpRequest, version_id: UUID) -> VersionOut:
    usuario: Usuario = request.auth
    version = get_object_or_404(PlantillaEvaluacion.objects.select_related("creada_por"), pk=version_id)
    entidad_configurable(usuario, version.entidad_id if usuario.es_superadmin else None)
    if not usuario.es_superadmin and version.entidad_id != usuario.entidad_id:
        raise HttpError(404, "No encontrado.")
    with transaction.atomic():
        PlantillaEvaluacion.objects.filter(entidad_id=version.entidad_id, tipo=version.tipo, activa=True).update(activa=False)
        version.activa = True
        version.save(update_fields=["activa"])
        auditar(request, "plantilla_evaluacion.activada", entidad_id=version.entidad_id, objeto=version, version=version.version)
    return _version_out(version, {})


@router.post("/requisitos/probar", response=list[dict], throttle=[AuthRateThrottle(settings.LIMITES_API["pesado"])])
async def probar_requisito_en_ofertas(request: HttpRequest, datos: ProbarIn) -> list[dict]:
    """Prueba un requisito (nuevo o ajustado) contra ofertas reales de una
    evaluación de la entidad, sin guardar nada."""
    usuario: Usuario = request.auth
    if not datos.proponente_ids or len(datos.proponente_ids) > 5:
        raise HttpError(400, "Elija entre 1 y 5 proponentes para la prueba.")

    def preparar():
        evaluacion = get_object_or_404(Evaluacion.objects.select_related("proceso"), pk=datos.evaluacion_id)
        entidad_configurable(usuario, evaluacion.entidad_id if usuario.es_superadmin else None)
        if not usuario.es_superadmin and evaluacion.entidad_id != usuario.entidad_id:
            raise HttpError(404, "No encontrado.")
        requisito = _validar_definicion({"parametros": datos.parametros, "requisitos": [datos.requisito]})
        proponentes = list(Proponente.objects.filter(proceso_id=evaluacion.proceso_id, id__in=datos.proponente_ids))
        if len(proponentes) != len(set(datos.proponente_ids)):
            raise HttpError(404, "Algún proponente no pertenece a esa evaluación.")
        documento = ProcesoDocumentoBase.model_validate(evaluacion.proceso.documento_base)
        return requisito, proponentes, documento

    requisito, proponentes, documento = await sync_to_async(preparar)()
    loop = asyncio.get_running_loop()
    resultados = await asyncio.gather(
        *(
            loop.run_in_executor(
                obtener_pool(),
                probar_requisito,
                servicios.proponente_motor(p),
                documento,
                requisito.requisitos[0].model_dump(mode="json"),
                requisito.parametros,
            )
            for p in proponentes
        )
    )
    return [r.model_dump(mode="json") for r in resultados]


_INSTRUCCION_PROPONER = """Eres un asistente que convierte la descripción de un requisito habilitante de un proceso
de contratación estatal colombiano en una regla verificable. Responde SOLO un JSON con esta forma:
{"titulo": "...", "corto": "máx 14 caracteres", "grupo": "oferta|camara|antecedentes|adicionales",
 "verifica": "frase corta de qué se verifica",
 "config": {"frases_documento": ["frases en MAYÚSCULAS que aparecen en el título o encabezado del documento"],
            "paginas": 3,
            "bloques": [{"tipo": "vigencia_maxima", "meses": N} | {"tipo": "contiene", "frases": ["..."]} |
                        {"tipo": "no_contiene", "frases": ["..."]} | {"tipo": "menciona_representante"} | {"tipo": "menciona_proponente"}],
            "aplica_a": []}}
Usa solo esos tipos de bloque. "aplica_a" puede incluir persona_natural, persona_juridica, consorcio, union_temporal
(vacío = todos). No inventes requisitos que la descripción no pida."""


@router.post("/requisitos/proponer", response=dict, throttle=[AuthRateThrottle(settings.LIMITES_API["pesado"])])
async def proponer_requisito_con_ia(request: HttpRequest, datos: ProponerIn) -> dict:
    """La IA local propone la regla con los bloques; nunca se activa sola:
    el administrador la revisa, la prueba contra ofertas reales y la guarda."""
    usuario: Usuario = request.auth
    if not (usuario.es_superadmin or usuario.rol == Rol.ADMIN_ENTIDAD):
        raise HttpError(403, "Solo el administrador de la entidad puede crear requisitos.")
    descripcion = " ".join(datos.descripcion.split())
    if len(descripcion) < 15:
        raise HttpError(400, "Describa el requisito con más detalle (qué documento, qué debe decir, vigencia…).")
    respuesta = await asyncio.to_thread(consultar_json, _INSTRUCCION_PROPONER, descripcion[:2000])
    if not respuesta:
        raise HttpError(503, "El asistente de IA no está disponible en este momento. Puede armar el requisito con los bloques.")
    propuesta = {
        "numero": 900,
        "titulo": str(respuesta.get("titulo") or descripcion[:80]),
        "corto": str(respuesta.get("corto") or "Nuevo")[:20],
        "grupo": respuesta.get("grupo") if respuesta.get("grupo") in criterios.GRUPOS else "adicionales",
        "verificacion": criterios.PERSONALIZADO,
        "verifica": str(respuesta.get("verifica") or ""),
        "config": respuesta.get("config") or {},
    }
    try:
        criterios.RequisitoDefinicion.model_validate(propuesta)
    except ValidationError as exc:
        raise HttpError(422, "La IA no logró proponer una regla válida. Intente describirlo de otra forma o use los bloques.") from exc
    return propuesta
