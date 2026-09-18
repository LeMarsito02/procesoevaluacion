"""El pliego de cada proceso: análisis (reutilizado por huella), hallazgos
frente a la evaluación de la entidad y ajustes que una persona aceptó."""
from __future__ import annotations

from uuid import UUID

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from evaluaciones.models import AnalisisPliego
from motor import criterios
from motor.pliego import analisis as motor_analisis
from motor.pliego import lectura

DECISIONES = ("aceptado", "rechazado")


def vigente(entidad_id: UUID, sha: str) -> AnalisisPliego | None:
    """El análisis ya guardado de este mismo PDF para la entidad, si se hizo
    con la versión vigente del analizador."""
    existente = AnalisisPliego.objects.filter(entidad_id=entidad_id, sha256=sha).first()
    if existente is not None and existente.version == motor_analisis.VERSION_ANALISIS:
        return existente
    return None


def leer(contenido: bytes) -> motor_analisis.Extraccion:
    """La parte pesada (lectura completa, OCR donde haga falta). No toca la
    base de datos: puede correr en otro hilo."""
    return motor_analisis.extraer(lectura.leer_paginas(contenido))


def guardar(
    entidad_id: UUID, contenido: bytes, nombre_archivo: str, extraccion: motor_analisis.Extraccion, usuario
) -> AnalisisPliego:
    sha = lectura.huella(contenido)
    datos = {
        "nombre_archivo": nombre_archivo[:300],
        "paginas": extraccion.paginas,
        "documento_tipo": extraccion.documento_tipo or "",
        "extraccion": extraccion.model_dump(mode="json"),
        "version": motor_analisis.VERSION_ANALISIS,
    }
    with transaction.atomic():
        existente = AnalisisPliego.objects.select_for_update().filter(entidad_id=entidad_id, sha256=sha).first()
        if existente is not None:  # el analizador cambió: se relee el mismo PDF
            for campo, valor in datos.items():
                setattr(existente, campo, valor)
            existente.save()
            return existente
        nuevo = AnalisisPliego(entidad_id=entidad_id, sha256=sha, creado_por=usuario, **datos)
        nuevo.archivo.save(f"{sha}.pdf", ContentFile(contenido), save=False)
        nuevo.save()
        return nuevo


def analizar(entidad_id: UUID, contenido: bytes, nombre_archivo: str, usuario) -> tuple[AnalisisPliego, bool]:
    """(análisis, reutilizado). Lee el pliego completo, o reutiliza la lectura
    si la entidad ya subió ese mismo PDF (misma huella)."""
    existente = vigente(entidad_id, lectura.huella(contenido))
    if existente is not None:
        return existente, True
    return guardar(entidad_id, contenido, nombre_archivo, leer(contenido), usuario), False


def definicion_plantilla(entidad_id: UUID, tipo: str = "juridica") -> criterios.DefinicionEvaluacion:
    from evaluaciones.servicios import plantilla_activa

    plantilla = plantilla_activa(entidad_id, tipo)
    if plantilla is not None:
        return criterios.DefinicionEvaluacion.model_validate(plantilla.definicion)
    return criterios.definicion_sistema(tipo)


def hallazgos(analisis: AnalisisPliego, tipo: str = "juridica") -> list[motor_analisis.Hallazgo]:
    extraccion = motor_analisis.Extraccion.model_validate(analisis.extraccion)
    return motor_analisis.comparar(extraccion, definicion_plantilla(analisis.entidad_id, tipo))


def decidir(analisis: AnalisisPliego, decisiones: dict[str, dict], usuario) -> list[dict]:
    """Lo que la persona decidió sobre cada hallazgo, listo para guardar en el
    proceso. Todo hallazgo que cambia la evaluación debe tener decisión, y un
    rechazo necesita su razón (queda en el reporte). Si algo falta, no se
    guarda nada: ValueError con lo que falta."""
    lista = {h.id: h for h in hallazgos(analisis)}
    pendientes = [h.titulo for h in lista.values() if h.requiere_decision and h.id not in decisiones]
    if pendientes:
        raise ValueError("Falta decidir sobre: " + "; ".join(pendientes) + ".")
    ajustes = []
    for hid, h in lista.items():
        if not h.requiere_decision:
            continue
        decision = decisiones[hid]
        estado = decision.get("decision")
        if estado not in DECISIONES:
            raise ValueError(f"Decisión no válida para «{h.titulo}».")
        nota = " ".join(str(decision.get("nota") or "").split())
        if estado == "rechazado" and len(nota) < 5:
            raise ValueError(f"Explique por qué no se aplica «{h.titulo}»: queda en el reporte.")
        ajustes.append({
            "id": hid,
            "decision": estado,
            "nota": nota,
            "por": usuario.nombre_completo,
            "por_id": str(usuario.id),
            "en": timezone.now().isoformat(),
            "hallazgo": h.model_dump(mode="json"),
        })
    return ajustes


def aplicar_ajustes(definicion: criterios.DefinicionEvaluacion, ajustes: list[dict]) -> criterios.DefinicionEvaluacion:
    """La definición de la entidad con los ajustes del pliego que se aceptaron:
    parámetros que cambian y requisitos que se agregan (con una verificación
    del motor si existe, o como verificación manual)."""
    aceptados = [a["hallazgo"] for a in ajustes if a.get("decision") == "aceptado"]
    if not aceptados:
        return definicion
    datos = definicion.model_dump()
    parametros = dict(datos.get("parametros") or {})
    requisitos = list(datos.get("requisitos") or [])
    presentes = {r["verificacion"] for r in requisitos}
    siguiente = max((r["numero"] for r in requisitos), default=0) + 1
    for h in aceptados:
        if h["tipo"] == "ajuste_parametro" and h.get("parametro"):
            parametros[h["parametro"]] = h["valor_pliego"]
        elif h["tipo"] == "requisito_nuevo" and h.get("requisito_propuesto"):
            propuesto = h["requisito_propuesto"]
            verificacion = propuesto.get("verificacion") or criterios.MANUAL
            if verificacion != criterios.MANUAL and verificacion in presentes:
                continue
            requisitos.append({
                "numero": siguiente,
                "titulo": propuesto["titulo"][:200],
                "corto": propuesto["corto"][:20],
                "grupo": "adicionales",
                "verificacion": verificacion,
                "verifica": propuesto.get("verifica", "")[:1000],
            })
            presentes.add(verificacion)
            siguiente += 1
    datos["parametros"] = parametros
    datos["requisitos"] = requisitos
    return criterios.DefinicionEvaluacion.model_validate(datos)
