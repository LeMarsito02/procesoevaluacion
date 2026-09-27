"""Ficha de transparencia algorítmica (Directiva Conjunta 007 de 2025)."""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from ninja import Router

from cuentas.seguridad import auditar, sesion_activa
from evaluaciones.transparencia import ficha, generar_ficha_docx

router = Router(tags=["transparencia"], auth=sesion_activa)


@router.get("", response=dict)
def acerca(request: HttpRequest) -> dict:
    """Qué es MiEvaluador, qué hace y qué no, con qué modelos y controles."""
    return ficha()


@router.get("/ficha")
def ficha_docx(request: HttpRequest) -> HttpResponse:
    contenido, nombre = generar_ficha_docx()
    auditar(request, "transparencia.ficha_descargada")
    respuesta = HttpResponse(contenido, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta
