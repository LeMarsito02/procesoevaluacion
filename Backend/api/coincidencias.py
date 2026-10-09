"""Coincidencias entre ofertas de un proceso (RF-14). Es un insumo: el comité
revisa cada una y deja su nota; no cambia ningún resultado."""
from __future__ import annotations

from uuid import UUID

from django.http import HttpRequest
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from api.economica import _para_registrar, _puede_registrar
from api.evaluaciones import _proceso_visible
from cuentas.seguridad import auditar, sesion_activa
from evaluaciones import coincidencias
from evaluaciones.models import AnalisisCoincidencias

router = Router(auth=sesion_activa, tags=["coincidencias"])


class RevisionIn(Schema):
    nota: str


def _salida(proceso, usuario) -> dict:
    a = AnalisisCoincidencias.objects.filter(proceso=proceso).select_related("calculado_por").first()
    if a is None:
        return {"puede_registrar": _puede_registrar(usuario, proceso), "calculado": False}
    return {
        "puede_registrar": _puede_registrar(usuario, proceso), "calculado": True, **a.resultado,
        "revisiones": a.revisiones, "calculado_en": a.calculado_en.isoformat(),
        "calculado_por": a.calculado_por.nombre_completo if a.calculado_por_id else None,
    }


@router.get("/procesos/{proceso_id}")
def ver(request: HttpRequest, proceso_id: UUID) -> dict:
    return _salida(_proceso_visible(request.auth, proceso_id), request.auth)


@router.post("/procesos/{proceso_id}")
def calcular(request: HttpRequest, proceso_id: UUID) -> dict:
    proceso = _para_registrar(request, proceso_id)
    a = coincidencias.calcular(proceso, request.auth)
    auditar(request, "coincidencias.calculadas", entidad_id=proceso.entidad_id, objeto=proceso,
            coincidencias=len(a.resultado["coincidencias"]), comunes=len(a.resultado["comunes"]))
    return _salida(proceso, request.auth)


@router.put("/procesos/{proceso_id}/{clave}")
def revisar(request: HttpRequest, proceso_id: UUID, clave: str, datos: RevisionIn) -> dict:
    proceso = _para_registrar(request, proceso_id)
    a = AnalisisCoincidencias.objects.filter(proceso=proceso).first()
    if a is None or clave not in {c["clave"] for c in a.resultado.get("coincidencias", [])}:
        raise HttpError(404, "Esa coincidencia no existe.")
    nota = datos.nota.strip()
    if not nota:
        raise HttpError(400, "Escriba qué concluyó el comité sobre esta coincidencia.")
    a.revisiones = {**a.revisiones, clave: {"nota": nota[:2000], "por": request.auth.nombre_completo, "en": timezone.now().isoformat()}}
    a.save(update_fields=["revisiones"])
    auditar(request, "coincidencias.revisada", entidad_id=proceso.entidad_id, objeto=proceso, clave=clave, nota=nota[:2000])
    return _salida(proceso, request.auth)
