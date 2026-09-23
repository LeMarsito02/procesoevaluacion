"""El pliego de cada proceso: análisis (reutilizado por huella), hallazgos
frente a la evaluación de la entidad y ajustes que una persona aceptó."""
from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from evaluaciones.models import AnalisisPliego
from motor import criterios
from motor.pliego import analisis as motor_analisis
from motor.pliego import lector_ia, lectura, parametros_ia

log = logging.getLogger("mievaluador.pliego")
# Una lectura "leyendo" sin terminar en este tiempo se da por caída (el
# trabajador se detuvo) y vuelve a quedar pendiente.
LECTURA_CAIDA = timedelta(minutes=45)

DECISIONES = ("aceptado", "rechazado")


def vigente(entidad_id: UUID, sha: str) -> AnalisisPliego | None:
    """El análisis ya guardado de este mismo PDF para la entidad, si se hizo
    con la versión vigente del analizador."""
    existente = AnalisisPliego.objects.filter(entidad_id=entidad_id, sha256=sha).first()
    if existente is not None and existente.version == motor_analisis.VERSION_ANALISIS:
        desactualizado = (existente.version_ia != lector_ia.VERSION
                          or existente.version_parametros_ia != parametros_ia.VERSION)
        if desactualizado and existente.estado_ia not in ("pendiente", "leyendo"):
            # La forma de leer con IA mejoró: se vuelve a leer en el trabajador.
            existente.estado_ia, existente.progreso_ia = "pendiente", 0
            existente.save(update_fields=["estado_ia", "progreso_ia"])
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
            if (existente.version_ia != lector_ia.VERSION
                    or existente.version_parametros_ia != parametros_ia.VERSION):
                existente.estado_ia, existente.progreso_ia = "pendiente", 0
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


def requisitos_ia(analisis: AnalisisPliego) -> list[lector_ia.RequisitoPliego]:
    if analisis.estado_ia != "listo":
        return []
    return [lector_ia.RequisitoPliego.model_validate(r) for r in analisis.requisitos_ia]


def parametros_leidos(analisis: AnalisisPliego | None) -> parametros_ia.ParametrosIA | None:
    """Lo que la IA leyó del pliego, o None si no se ha leído."""
    if analisis is None or analisis.estado_ia != "listo" or not analisis.parametros_ia:
        return None
    try:
        return parametros_ia.ParametrosIA.model_validate(analisis.parametros_ia)
    except Exception:  # noqa: BLE001 — una lectura vieja con otra forma no debe romper la evaluación
        return None


def hallazgos(analisis: AnalisisPliego, tipo: str = "juridica") -> list[motor_analisis.Hallazgo]:
    extraccion = motor_analisis.Extraccion.model_validate(analisis.extraccion)
    return motor_analisis.comparar(extraccion, definicion_plantilla(analisis.entidad_id, tipo), requisitos_ia(analisis))


def mapa(analisis: AnalisisPliego, tipo: str = "juridica") -> list[dict]:
    """Cada requisito jurídico que el pliego exige y cómo se verificará."""
    return motor_analisis.mapa_de_requisitos(requisitos_ia(analisis), definicion_plantilla(analisis.entidad_id, tipo))


def estado_lectura(analisis: AnalisisPliego) -> dict:
    return {
        "estado": analisis.estado_ia,
        "progreso": analisis.progreso_ia,
        "modelo": analisis.modelo_ia or lector_ia.MODELO,
        "requisitos": len(analisis.requisitos_ia or []),
        "error": analisis.error_ia,
    }


# --- Lectura profunda con IA (la hace el trabajador de la fila) -------------
def reclamar_lectura() -> AnalisisPliego | None:
    limite = timezone.now() - LECTURA_CAIDA
    with transaction.atomic():
        analisis = (
            AnalisisPliego.objects.select_for_update(skip_locked=True)
            .filter(Q(estado_ia="pendiente") | Q(estado_ia="leyendo", ia_iniciada__lt=limite))
            .order_by("creado_en")
            .first()
        )
        if analisis is None:
            return None
        analisis.estado_ia, analisis.progreso_ia, analisis.error_ia = "leyendo", 0, ""
        analisis.ia_iniciada, analisis.modelo_ia = timezone.now(), lector_ia.MODELO
        analisis.save(update_fields=["estado_ia", "progreso_ia", "error_ia", "ia_iniciada", "modelo_ia"])
        return analisis


def leer_con_ia(analisis: AnalisisPliego) -> None:
    if not lector_ia.disponible():
        AnalisisPliego.objects.filter(pk=analisis.pk).update(
            estado_ia="no_disponible",
            error_ia="La IA local no está disponible (Ollama apagado o deshabilitado): se usa solo la lectura por reglas.",
        )
        return
    contenido = analisis.archivo.read()
    paginas = lectura.leer_paginas(contenido)
    extraccion = motor_analisis.Extraccion.model_validate(analisis.extraccion)
    ambitos = {s.numero: s.ambito for s in extraccion.secciones}

    def progreso(hechos: int, total: int) -> None:
        AnalisisPliego.objects.filter(pk=analisis.pk).update(progreso_ia=min(99, int(100 * hechos / max(total, 1))))

    secciones = lectura.secciones(paginas)
    # Dos lecturas en la misma pasada: los requisitos jurídicos y los
    # parámetros del proceso (experiencia, umbrales, anticipo, puntajes…).
    # La barra de progreso las cuenta juntas.
    partes_juridicas = len(lector_ia.trozos(secciones, ambitos))
    partes_parametros = len(parametros_ia.trozos(secciones, ambitos))
    total = max(partes_juridicas + partes_parametros, 1)

    def progreso_juridico(hechos: int, _total: int) -> None:
        progreso(hechos, total)

    def progreso_parametros(hechos: int, _total: int) -> None:
        progreso(partes_juridicas + hechos, total)

    requisitos = lector_ia.leer(secciones, ambitos, paginas, progreso_juridico)
    leidos = (parametros_ia.leer(secciones, ambitos, progreso_parametros)
              if parametros_ia.HABILITADO else parametros_ia.ParametrosIA())
    AnalisisPliego.objects.filter(pk=analisis.pk).update(
        estado_ia="listo", progreso_ia=100, requisitos_ia=[r.model_dump(mode="json") for r in requisitos],
        parametros_ia=leidos.model_dump(mode="json"), version_parametros_ia=parametros_ia.VERSION,
        version_ia=lector_ia.VERSION, ia_terminada=timezone.now(),
    )
    log.info("Pliego %s leído con IA: %d requisitos jurídicos, %d fragmentos de parámetros (%d sin respuesta)",
             analisis.nombre_archivo, len(requisitos), leidos.leidas, leidos.fallidas)


def atender_lecturas_pendientes() -> int:
    """Lee con IA los pliegos pendientes (lo llama el trabajador de la fila)."""
    n = 0
    while (analisis := reclamar_lectura()) is not None:
        try:
            leer_con_ia(analisis)
        except Exception as exc:  # noqa: BLE001
            log.exception("Falló la lectura con IA del pliego %s", analisis.pk)
            AnalisisPliego.objects.filter(pk=analisis.pk).update(estado_ia="error", error_ia=str(exc)[:2000])
        n += 1
    return n


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


def _ya_no_se_evalua(hallazgo: dict, verificacion: str, presentes: set[str]) -> bool:
    """Un requisito agregado desde la lectura del pliego que con las reglas de
    hoy sobra: un formato de puntaje o implícito (discapacidad, tratamiento
    de datos…) o algo que el motor ya verifica (el revisor fiscal de las
    sociedades anónimas es el requisito 18, que da N.A. a las S.A.S.)."""
    if verificacion not in (criterios.MANUAL, criterios.PERSONALIZADO):
        return False
    from motor.pliego.catalogo import verificacion_de
    from motor.pliego.lector_ia import _NO_ES_REQUISITO_RE, RequisitoPliego, _norm

    propuesto = hallazgo.get("requisito_propuesto") or {}
    titulo = propuesto.get("titulo") or hallazgo.get("titulo") or ""
    if _NO_ES_REQUISITO_RE.search(_norm(f"{titulo} {hallazgo.get('cita') or ''}")):
        return True
    frases = ((propuesto.get("config") or {}).get("frases_documento")) or []
    requisito = RequisitoPliego(
        id="revision", requisito=titulo, titulo_documento=frases, cita=hallazgo.get("cita") or "",
        seccion=hallazgo.get("seccion") or "", pagina=int(hallazgo.get("pagina") or 1),
    )
    del_motor = verificacion_de(requisito)
    return del_motor is not None and del_motor in presentes


def aplicar_ajustes(
    definicion: criterios.DefinicionEvaluacion, ajustes: list[dict], revalidar: bool = True
) -> criterios.DefinicionEvaluacion:
    """La definición de la entidad con los ajustes del pliego que se aceptaron:
    parámetros que cambian y requisitos que se agregan (con una verificación
    del motor si existe, o como verificación manual)."""
    aceptados = [a["hallazgo"] for a in ajustes if a.get("decision") == "aceptado"]
    if not aceptados:
        return definicion
    quitar = {h["verificacion"] for h in aceptados if h["tipo"] == "requisito_no_exigido" and h.get("verificacion")}
    datos = definicion.model_dump()
    parametros = dict(datos.get("parametros") or {})
    requisitos = [r for r in (datos.get("requisitos") or []) if r["verificacion"] not in quitar]
    presentes = {r["verificacion"] for r in requisitos}
    siguiente = max((r["numero"] for r in requisitos), default=0) + 1
    for h in aceptados:
        if h["tipo"] == "ajuste_parametro" and h.get("parametro"):
            parametros[h["parametro"]] = h["valor_pliego"]
        elif h["tipo"] == "requisito_nuevo" and h.get("requisito_propuesto"):
            propuesto = h["requisito_propuesto"]
            verificacion = propuesto.get("verificacion") or criterios.MANUAL
            if verificacion not in (criterios.MANUAL, criterios.PERSONALIZADO) and verificacion in presentes:
                continue
            # Lo que se aceptó con reglas anteriores y hoy se sabe que sobra
            # (no es habilitante, o ya lo verifica el motor) se deja de
            # evaluar. Su número queda reservado: los resultados se guardan
            # por número y correr los demás les cambiaría el resultado.
            if revalidar and _ya_no_se_evalua(h, verificacion, presentes):
                siguiente += 1
                continue
            requisitos.append({
                "numero": siguiente,
                "titulo": propuesto["titulo"][:200],
                "corto": propuesto["corto"][:20],
                "grupo": "adicionales",
                "verificacion": verificacion,
                "verifica": propuesto.get("verifica", "")[:1000],
                **({"config": propuesto["config"]} if propuesto.get("config") else {}),
            })
            presentes.add(verificacion)
            siguiente += 1
    datos["parametros"] = parametros
    datos["requisitos"] = requisitos
    return criterios.DefinicionEvaluacion.model_validate(datos)
