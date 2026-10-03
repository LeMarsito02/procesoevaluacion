"""Estructura de evaluación de cada entidad: dependencias, comités evaluadores,
su designación documentada y la colaboración en tiempo real (bloqueos).

- Cada entidad configura sus dependencias por área (en el ICCU, lo técnico lo
  evalúa Construcciones, Caminos e Infraestructura Vial o Concesiones, según el
  contrato). Al crear un proceso se sugiere la dependencia por el objeto.
- El jefe de la dependencia designa el comité de cada evaluación. Todos sus
  miembros trabajan el mismo proceso a la vez; el primero es el coordinador.
- Cada designación genera un documento controlado (ISO 9001, 7.5) con
  consecutivo, versión y huella, que queda en el expediente.
- Para que dos personas no decidan lo mismo a la vez, quien abre un
  proponente lo bloquea mientras lo tenga abierto.
"""
from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from cuentas.models import Rol, Usuario
from evaluaciones.models import (
    BloqueoProponente,
    Dependencia,
    DesignacionComite,
    EstadoEvaluacion,
    Evaluacion,
    MiembroComite,
    Proponente,
)

# Un bloqueo vence si no se renueva en este tiempo (la pantalla lo renueva
# cada 30 s mientras el proponente está abierto).
VIGENCIA_BLOQUEO = timedelta(seconds=90)
CODIGO_FORMATO = "MEV-FOR-DES-01"
VERSION_FORMATO = "1"


class ErrorEstructura(ValueError):
    pass


# --- Dependencias --------------------------------------------------------------
def _norm(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).upper()


def sugerir_dependencia(entidad_id, tipo: str, objeto: str) -> Dependencia | None:
    """La dependencia del área cuyo nombre o palabras clave más aparecen en el
    objeto del contrato. Si el área tiene una sola dependencia, esa."""
    candidatas = list(Dependencia.objects.filter(entidad_id=entidad_id, tipo=tipo, activa=True))
    if len(candidatas) <= 1:
        return candidatas[0] if candidatas else None
    texto = _norm(objeto)
    mejor, puntos_mejor = None, 0
    for d in candidatas:
        palabras = [p.strip() for p in d.palabras_clave.splitlines() if p.strip()]
        # Cada palabra clave cuenta una vez, como palabra completa (singular o
        # plural), y pesa por su largo: «concesión» es más específica que
        # «vial», así que una «concesión vial» va a Concesiones.
        puntos = sum(len(p) for p in palabras if re.search(rf"\b{re.escape(_norm(p))}(?:ES|S)?\b", texto))
        if puntos > puntos_mejor:
            mejor, puntos_mejor = d, puntos
    return mejor


def dependencia_valida(entidad_id, tipo: str, dependencia_id) -> Dependencia | None:
    if dependencia_id is None:
        return None
    d = Dependencia.objects.filter(pk=dependencia_id, entidad_id=entidad_id, tipo=tipo, activa=True).first()
    if d is None:
        raise ErrorEstructura("Esa dependencia no existe, no está activa o no evalúa esta área.")
    return d


# --- Comité --------------------------------------------------------------------
def comite_activo(evaluacion: Evaluacion) -> list[Usuario]:
    return [m.usuario for m in evaluacion.comite.filter(retirado_en__isnull=True).select_related("usuario")]


def es_miembro(usuario: Usuario, evaluacion: Evaluacion) -> bool:
    return evaluacion.comite.filter(usuario=usuario, retirado_en__isnull=True).exists()


def _validar_miembros(evaluacion: Evaluacion, miembros: list[Usuario]) -> None:
    if not miembros:
        raise ErrorEstructura("El comité necesita al menos un evaluador.")
    if len({m.id for m in miembros}) != len(miembros):
        raise ErrorEstructura("Hay un evaluador repetido en el comité.")
    for m in miembros:
        if m.entidad_id != evaluacion.entidad_id or not m.is_active:
            raise ErrorEstructura(f"{m.nombre_completo} no es un usuario activo de la entidad.")
        if m.rol == Rol.CONSULTA:
            raise ErrorEstructura(f"{m.nombre_completo} tiene rol de consulta: no puede evaluar.")


def _consecutivo(entidad_id) -> str:
    anio = timezone.localdate().year
    n = DesignacionComite.objects.filter(entidad_id=entidad_id, consecutivo__startswith=f"DES-{anio}-").count() + 1
    return f"DES-{anio}-{n:04d}"


def designar_comite(evaluacion: Evaluacion, miembros: list[Usuario], actor: Usuario, *, dependencia: Dependencia | None = None,
                    documentar: bool = True) -> DesignacionComite | None:
    """Fija el comité de la evaluación (el primero es el coordinador). Retira a
    quien ya no está, conserva la historia y, si `documentar`, genera el
    documento de designación."""
    _validar_miembros(evaluacion, miembros)
    if evaluacion.estado == EstadoEvaluacion.APROBADA:
        raise ErrorEstructura("La evaluación está aprobada: reábrala para cambiar el comité.")
    ahora = timezone.now()
    with transaction.atomic():
        if dependencia is not None:
            evaluacion.dependencia = dependencia
        actuales = {m.usuario_id: m for m in evaluacion.comite.filter(retirado_en__isnull=True)}
        nuevos = {m.id for m in miembros}
        for uid, m in actuales.items():
            if uid not in nuevos:
                m.retirado_en = ahora
                m.save(update_fields=["retirado_en"])
        for m in miembros:
            if m.id not in actuales:
                MiembroComite.objects.create(entidad_id=evaluacion.entidad_id, evaluacion=evaluacion, usuario=m, designado_por=actor)
        evaluacion.responsable = miembros[0]
        evaluacion.asignada_por = actor
        evaluacion.asignada_en = ahora
        evaluacion.save(update_fields=["responsable", "asignada_por", "asignada_en", "dependencia", "actualizada_en"])
        from evaluaciones.servicios import actualizar_estado

        actualizar_estado(evaluacion)
        if not documentar:
            return None
        for _ in range(3):  # dos designaciones simultáneas pueden pedir el mismo consecutivo
            try:
                with transaction.atomic():
                    return _documentar(evaluacion, miembros, actor)
            except IntegrityError:
                continue
        raise ErrorEstructura("No se pudo numerar la designación; inténtelo de nuevo.")


def _documentar(evaluacion: Evaluacion, miembros: list[Usuario], actor: Usuario) -> DesignacionComite:
    version = evaluacion.designaciones.count() + 1
    consecutivo = _consecutivo(evaluacion.entidad_id)
    contenido = documento_designacion(evaluacion, miembros, actor, consecutivo, version)
    d = DesignacionComite(
        entidad_id=evaluacion.entidad_id,
        evaluacion=evaluacion,
        consecutivo=consecutivo,
        version=version,
        dependencia=evaluacion.dependencia.nombre if evaluacion.dependencia_id else evaluacion.get_tipo_display(),
        miembros=[{"nombre": m.nombre_completo, "email": m.email, "coordinador": i == 0} for i, m in enumerate(miembros)],
        designado_por=actor,
        sha256=hashlib.sha256(contenido).hexdigest(),
    )
    d.archivo.save(f"{consecutivo}.docx", ContentFile(contenido), save=False)
    d.save()
    return d


def documento_designacion(evaluacion: Evaluacion, miembros: list[Usuario], actor: Usuario, consecutivo: str, version: int) -> bytes:
    """Designación del comité evaluador como documento controlado (ISO 9001,
    7.5.2 y 7.5.3): identificación (código, versión, consecutivo, fecha),
    responsables, control de cambios y conservación."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    from evaluaciones.reporte import _parrafo, _tabla, _titulo, fecha_larga

    proceso = evaluacion.proceso
    ahora = timezone.now()
    doc = Document()
    doc.styles["Normal"].font.name = "Arial"
    doc.styles["Normal"].font.size = Pt(10)

    # Encabezado de control documental, en cada página.
    encabezado = doc.sections[0].header
    tabla = encabezado.add_table(rows=2, cols=4, width=doc.sections[0].page_width - doc.sections[0].left_margin - doc.sections[0].right_margin)
    tabla.style = "Table Grid"
    for i, (etiqueta, valor) in enumerate([
        ("Entidad", evaluacion.entidad.nombre), ("Código del formato", CODIGO_FORMATO),
        ("Documento", "Designación del comité evaluador"), ("Versión del formato", VERSION_FORMATO),
    ]):
        celda = tabla.cell(i // 2, (i % 2) * 2)
        celda.text = etiqueta
        celda.paragraphs[0].runs[0].bold = True
        celda.paragraphs[0].runs[0].font.size = Pt(8)
        valor_celda = tabla.cell(i // 2, (i % 2) * 2 + 1)
        valor_celda.text = valor
        valor_celda.paragraphs[0].runs[0].font.size = Pt(8)

    _titulo(doc, "Designación del comité evaluador")
    _tabla(doc, ["Dato", "Valor"], [
        ["Consecutivo", consecutivo],
        ["Versión del comité", f"{version}" + (" (reemplaza la designación anterior)" if version > 1 else "")],
        ["Fecha", fecha_larga(ahora)],
        ["Proceso", proceso.codigo],
        ["Objeto", proceso.objeto or (proceso.documento_base or {}).get("objeto_general", "")],
        ["Evaluación", evaluacion.get_tipo_display()],
        ["Dependencia", evaluacion.dependencia.nombre if evaluacion.dependencia_id else "—"],
        ["Designa", f"{actor.nombre_completo} ({actor.get_rol_display()})"],
    ])
    _parrafo(doc, "")
    _parrafo(
        doc,
        f"{actor.nombre_completo} designa a las siguientes personas como comité evaluador de la evaluación "
        f"{evaluacion.get_tipo_display().lower()} del proceso {proceso.codigo}. El comité verifica los requisitos "
        "habilitantes del área con el apoyo de MiEvaluador, revisa contra su soporte lo que el sistema no pudo confirmar, "
        "responde la muestra de control y recomienda el resultado. La decisión es del comité y de quien aprueba; las "
        "verificaciones del sistema son preliminares.",
    )
    _tabla(doc, ["Nombre", "Correo", "Función"], [
        [m.nombre_completo, m.email, "Coordinador(a)" if i == 0 else "Evaluador(a)"] for i, m in enumerate(miembros)
    ])
    _parrafo(doc, "")
    _titulo(doc, "Declaración de ausencia de conflicto de intereses", 2)
    _parrafo(
        doc,
        "Cada integrante declara que no está incurso en inhabilidades o incompatibilidades (artículo 8 de la Ley 80 de "
        "1993) ni en causales de conflicto de intereses (artículo 11 de la Ley 1437 de 2011) frente a los proponentes del "
        "proceso, y que, si sobreviene alguna, la informará de inmediato para ser reemplazado(a).",
    )
    _tabla(doc, ["Integrante", "Firma", "Fecha"], [[m.nombre_completo, "", ""] for m in miembros])
    _parrafo(doc, "")
    _tabla(doc, ["Designa", "Firma", "Fecha"], [[actor.nombre_completo, "", fecha_larga(ahora.date())]])
    _parrafo(doc, "")
    _titulo(doc, "Control del documento", 2)
    _parrafo(
        doc,
        f"Generado por MiEvaluador {settings.MIEVALUADOR_VERSION} el {fecha_larga(ahora)}. La huella SHA-256 de este "
        "archivo queda registrada en la plataforma y en el expediente de la evaluación: cualquier modificación posterior "
        "la cambia. Un cambio en el comité genera una nueva versión con nuevo consecutivo; las anteriores se conservan. "
        "Conservación según las tablas de retención documental de la entidad.",
        tam=9,
    )
    pie = doc.sections[0].footer.paragraphs[0]
    pie.text = f"{CODIGO_FORMATO} · v{VERSION_FORMATO} · {consecutivo} · MiEvaluador by LeMarTek"
    pie.alignment = WD_ALIGN_PARAGRAPH.CENTER
    salida = io.BytesIO()
    doc.save(salida)
    return salida.getvalue()


# --- Bloqueos (colaboración en tiempo real) -------------------------------------
def bloqueos_vigentes(evaluacion: Evaluacion) -> list[BloqueoProponente]:
    limite = timezone.now() - VIGENCIA_BLOQUEO
    return list(evaluacion.bloqueos.filter(latido__gte=limite).select_related("usuario", "proponente"))


def bloqueado_por_otro(evaluacion: Evaluacion, proponente: Proponente, usuario: Usuario) -> Usuario | None:
    limite = timezone.now() - VIGENCIA_BLOQUEO
    b = (evaluacion.bloqueos.filter(proponente=proponente, latido__gte=limite).exclude(usuario=usuario)
         .select_related("usuario").first())
    return b.usuario if b else None


def tomar_bloqueo(evaluacion: Evaluacion, proponente: Proponente, usuario: Usuario) -> tuple[bool, Usuario]:
    """Toma o renueva el bloqueo. Devuelve (lo tiene este usuario, quién lo tiene)."""
    ahora = timezone.now()
    with transaction.atomic():
        b = BloqueoProponente.objects.select_for_update().filter(evaluacion=evaluacion, proponente=proponente).first()
        if b and b.usuario_id != usuario.id and b.latido >= ahora - VIGENCIA_BLOQUEO:
            return False, b.usuario
        if b:
            if b.usuario_id != usuario.id:
                b.usuario = usuario
                b.desde = ahora
            b.latido = ahora
            b.save()
        else:
            BloqueoProponente.objects.create(
                entidad_id=evaluacion.entidad_id, evaluacion=evaluacion, proponente=proponente, usuario=usuario, latido=ahora
            )
    return True, usuario


def soltar_bloqueo(evaluacion: Evaluacion, proponente: Proponente, usuario: Usuario) -> None:
    BloqueoProponente.objects.filter(evaluacion=evaluacion, proponente=proponente, usuario=usuario).delete()
