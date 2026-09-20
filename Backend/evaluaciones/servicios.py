"""Lógica de evaluaciones compartida por la API y el trabajador de la fila."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.utils import timezone

from evaluaciones.models import (
    EstadoEvaluacion,
    EstadoTrabajo,
    Evaluacion,
    PlantillaEvaluacion,
    Proponente,
    Resultado,
    Revision,
    Trabajador,
    Trabajo,
)
from motor import criterios
from motor.esquemas.proceso import Proponente as ProponenteMotor
from motor.esquemas.proceso import ResultadoRequisito

PENDIENTES = (EstadoTrabajo.EN_FILA, EstadoTrabajo.PROCESANDO)
# Sin datos todavía: estimación conservadora por proponente (medición real ~45 s en frío).
DURACION_POR_DEFECTO = 45.0
LATIDO_VIGENTE = timedelta(seconds=90)


@dataclass
class Avance:
    proponentes: int = 0
    evaluados: int = 0
    con_error: int = 0
    pendientes: int = 0
    revisados: int = 0
    en_fila: int = 0
    procesando: int = 0

    def dict(self) -> dict:
        return asdict(self)


def avances(ids: list[UUID]) -> dict[UUID, Avance]:
    """Avance de varias evaluaciones con pocas consultas."""
    if not ids:
        return {}
    salida = {i: Avance() for i in ids}
    for e in Evaluacion.objects.filter(id__in=ids).annotate(n=Count("proceso__proponentes", distinct=True)):
        salida[e.id].proponentes = e.n
    base = Resultado.objects.filter(evaluacion_id__in=ids)
    for ev, n in base.values("evaluacion_id").annotate(n=Count("proponente_id", distinct=True)).values_list("evaluacion_id", "n"):
        salida[ev].evaluados = n
    for ev, n in (
        base.exclude(datos__error=None)
        .values("evaluacion_id")
        .annotate(n=Count("proponente_id", distinct=True))
        .values_list("evaluacion_id", "n")
    ):
        salida[ev].con_error = n
    revisadas = set(Revision.objects.filter(evaluacion_id__in=ids).values_list("evaluacion_id", "proponente_id", "requisito"))
    for ev, prop, req in base.filter(requiere_revision=True).values_list("evaluacion_id", "proponente_id", "requisito"):
        if (ev, prop, req) not in revisadas:
            salida[ev].pendientes += 1
    for ev, _, _req in revisadas:
        salida[ev].revisados += 1
    for ev, estado, n in (
        Trabajo.objects.filter(evaluacion_id__in=ids, estado__in=PENDIENTES)
        .values("evaluacion_id", "estado")
        .annotate(n=Count("id"))
        .values_list("evaluacion_id", "estado", "n")
    ):
        if estado == EstadoTrabajo.EN_FILA:
            salida[ev].en_fila = n
        else:
            salida[ev].procesando = n
    return salida


def requiere_revision(r: ResultadoRequisito) -> bool:
    return bool(r.error) or (r.cumple is not True and not (r.motivo or "").startswith("N.A."))


def actualizar_estado(evaluacion: Evaluacion) -> None:
    if evaluacion.estado == EstadoEvaluacion.APROBADA:
        return
    avance = avances([evaluacion.id])[evaluacion.id]
    if avance.en_fila or avance.procesando:
        nuevo = EstadoEvaluacion.EVALUANDO
    elif avance.evaluados == 0:
        nuevo = EstadoEvaluacion.ASIGNADA if evaluacion.responsable_id else EstadoEvaluacion.SIN_ASIGNAR
    elif avance.evaluados < avance.proponentes:
        nuevo = EstadoEvaluacion.EVALUANDO
    else:
        nuevo = EstadoEvaluacion.EN_REVISION
    if nuevo != evaluacion.estado:
        evaluacion.estado = nuevo
        evaluacion.save(update_fields=["estado", "actualizada_en"])


def aplicar_revision(datos: dict, revision: Revision | None) -> ResultadoRequisito:
    r = ResultadoRequisito.model_validate(datos)
    if revision is None:
        return r
    if revision.cumple:
        return r.model_copy(update={"cumple": True, "motivo": None, "error": None})
    motivo = revision.nota or r.motivo or r.error or "Revisado: no cumple"
    return r.model_copy(update={"cumple": False, "error": None, "motivo": motivo})


def proponente_motor(p: Proponente) -> ProponenteMotor:
    return ProponenteMotor(
        numero_orden=p.numero_orden,
        hoja=p.hoja,
        nombre_proponente=p.nombre,
        nombre_archivo=p.nombre_archivo,
        drive_file_id=p.drive_file_id,
        advertencia=p.advertencia or None,
    )


def guardar_resultados(evaluacion: Evaluacion, proponente: Proponente, resultados: list[ResultadoRequisito]) -> None:
    with transaction.atomic():
        for r in resultados:
            Resultado.objects.update_or_create(
                evaluacion=evaluacion,
                proponente=proponente,
                requisito=r.requisito,
                defaults={
                    "entidad_id": evaluacion.entidad_id,
                    "datos": r.model_dump(mode="json"),
                    "requiere_revision": requiere_revision(r),
                },
            )
        sincronizar_personas(evaluacion, proponente)


def clave_persona(nombre: str, documento: str | None) -> str:
    """Una misma persona se reconoce por su documento; sin él, por su nombre."""
    digitos = "".join(c for c in (documento or "") if c.isdigit())
    if len(digitos) >= 5:
        return digitos[:9] if len(digitos) >= 9 else digitos
    return " ".join(sorted(nombre.upper().split()))


def sincronizar_personas(evaluacion: Evaluacion, proponente: Proponente) -> None:
    """Las personas y empresas a las que el programa les exigió antecedentes
    quedan en la tabla del proponente, para que el evaluador vea y complete el
    certificado de cada una. Las que agregó el evaluador no se tocan; las
    detectadas que ya no aplican se quitan si no tienen certificados aportados."""
    from evaluaciones.models import PersonaVerificada, RolPersona, TipoPersona

    # Todos los resultados guardados del proponente, no solo los recién
    # evaluados: si se reevalúa un requisito, las personas de los demás siguen.
    detectadas: dict[str, dict] = {}
    for datos in Resultado.objects.filter(evaluacion=evaluacion, proponente=proponente).values_list("datos", flat=True):
        for per in datos.get("personas_antecedente") or []:
            clave = clave_persona(per["nombre"], per.get("documento"))
            # Entre varios resultados de la misma persona gana el que trae la
            # fecha de expedición de su documento.
            if clave not in detectadas or (per.get("fecha_expedicion_documento") and not detectadas[clave].get("fecha_expedicion_documento")):
                detectadas[clave] = per
    existentes = {
        clave_persona(x.nombre, x.documento): x for x in PersonaVerificada.objects.filter(evaluacion=evaluacion, proponente=proponente)
    }
    roles = set(RolPersona.values)
    for clave, per in detectadas.items():
        if clave in existentes:
            # La fecha de expedición se completa si el motor la leyó después
            # (la trae el reverso de la cédula y la pide el RNMC).
            persona = existentes[clave]
            if per.get("fecha_expedicion_documento") and not persona.fecha_expedicion_documento:
                persona.fecha_expedicion_documento = per["fecha_expedicion_documento"]
                persona.save(update_fields=["fecha_expedicion_documento"])
            continue
        PersonaVerificada.objects.create(
            entidad_id=evaluacion.entidad_id,
            evaluacion=evaluacion,
            proponente=proponente,
            rol=per["rol"] if per["rol"] in roles else RolPersona.REPRESENTANTE,
            tipo=TipoPersona.JURIDICA if per["tipo"] == "juridica" else TipoPersona.NATURAL,
            nombre=per["nombre"].upper()[:300],
            documento=(per["documento"] or "")[:30],
            fecha_expedicion_documento=per.get("fecha_expedicion_documento"),
            detectada=True,
        )
    for clave, persona in existentes.items():
        if persona.detectada and clave not in detectadas and not persona.documentos.exists():
            persona.delete()


# --- Fila ---
def encolar(evaluacion: Evaluacion, proponente_ids: list[UUID] | None, usuario) -> int:
    """Pone en la fila los proponentes indicados (o los que faltan o tienen
    error). Devuelve cuántos trabajos nuevos se crearon."""
    proponentes = Proponente.objects.filter(proceso_id=evaluacion.proceso_id)
    if proponente_ids is not None:
        proponentes = proponentes.filter(id__in=proponente_ids)
    else:
        con_resultado_sano = (
            Resultado.objects.filter(evaluacion=evaluacion)
            .values("proponente_id")
            .annotate(errores=Count("id", filter=~Q(datos__error=None)))
            .filter(errores=0)
            .values_list("proponente_id", flat=True)
        )
        proponentes = proponentes.exclude(id__in=con_resultado_sano)
    with transaction.atomic():
        ya_pendientes = set(
            Trabajo.objects.filter(evaluacion=evaluacion, estado__in=PENDIENTES).values_list("proponente_id", flat=True)
        )
        nuevos = [p for p in proponentes.order_by("numero_orden") if p.id not in ya_pendientes]
        base = Trabajo.objects.filter(evaluacion=evaluacion, estado__in=PENDIENTES).aggregate(m=Max("turno"))["m"]
        inicio = 0 if base is None else base + 1
        Trabajo.objects.bulk_create(
            Trabajo(
                entidad_id=evaluacion.entidad_id,
                evaluacion=evaluacion,
                proponente=p,
                turno=inicio + i,
                solicitado_por=usuario,
            )
            for i, p in enumerate(nuevos)
        )
        actualizar_estado(evaluacion)
    return len(nuevos)


def cancelar(evaluacion: Evaluacion) -> int:
    """Saca de la fila lo que aún no empezó (lo que se está procesando termina)."""
    with transaction.atomic():
        n = Trabajo.objects.filter(evaluacion=evaluacion, estado=EstadoTrabajo.EN_FILA).update(
            estado=EstadoTrabajo.CANCELADO, terminado_en=timezone.now()
        )
        actualizar_estado(evaluacion)
    return n


@dataclass
class EstadoFila:
    en_fila: int
    procesando: int
    por_delante: int
    capacidad: int
    segundos_por_proponente: float
    eta_segundos: int | None

    def dict(self) -> dict:
        return asdict(self)


def capacidad_activa() -> int:
    limite = timezone.now() - LATIDO_VIGENTE
    return sum(Trabajador.objects.filter(latido__gte=limite).values_list("capacidad", flat=True))


# Por debajo de esto el resultado salió de la caché (no refleja una evaluación nueva).
MINIMO_DURACION_REAL = 3.0


def segundos_por_proponente() -> float:
    """Mediana de las últimas evaluaciones reales (sin las respondidas desde caché)."""
    ultimos = (
        Trabajo.objects.filter(estado=EstadoTrabajo.TERMINADO, iniciado_en__isnull=False, terminado_en__isnull=False)
        .order_by("-terminado_en")
        .values_list("iniciado_en", "terminado_en")[:300]
    )
    recientes = [d for ini, fin in ultimos if (d := (fin - ini).total_seconds()) >= MINIMO_DURACION_REAL][:100]
    duraciones = sorted(recientes)
    if len(duraciones) < 5:
        return DURACION_POR_DEFECTO
    return duraciones[len(duraciones) // 2]


def estado_fila(evaluacion_ids: list[UUID]) -> dict[UUID, EstadoFila]:
    """Posición y tiempo estimado de cada evaluación en la fila compartida."""
    if not evaluacion_ids:
        return {}
    capacidad = capacidad_activa()
    media = segundos_por_proponente()
    pendientes = {
        ev: (en_fila, procesando, turno_max)
        for ev, en_fila, procesando, turno_max in Trabajo.objects.filter(evaluacion_id__in=evaluacion_ids, estado__in=PENDIENTES)
        .values("evaluacion_id")
        .annotate(
            en_fila=Count("id", filter=Q(estado=EstadoTrabajo.EN_FILA)),
            procesando=Count("id", filter=Q(estado=EstadoTrabajo.PROCESANDO)),
            turno_max=Max("turno", filter=Q(estado=EstadoTrabajo.EN_FILA)),
        )
        .values_list("evaluacion_id", "en_fila", "procesando", "turno_max")
    }
    salida = {}
    for ev in evaluacion_ids:
        en_fila, procesando, turno_max = pendientes.get(ev, (0, 0, None))
        por_delante = 0
        if en_fila:
            # Trabajos de otras evaluaciones que se atienden antes de terminar esta.
            por_delante = Trabajo.objects.filter(estado=EstadoTrabajo.EN_FILA, turno__lte=turno_max).exclude(evaluacion_id=ev).count()
            por_delante += Trabajo.objects.filter(estado=EstadoTrabajo.PROCESANDO).exclude(evaluacion_id=ev).count()
        restantes = en_fila + procesando
        eta = None
        if restantes and capacidad:
            eta = int((por_delante + restantes) * media / capacidad)
        salida[ev] = EstadoFila(en_fila, procesando, por_delante, capacidad, round(media, 1), eta)
    return salida


def reclamar(trabajador_id: str) -> Trabajo | None:
    """Toma el siguiente trabajo (sin bloquear a los demás trabajadores)."""
    with transaction.atomic():
        trabajo = (
            Trabajo.objects.select_for_update(skip_locked=True)
            .filter(estado=EstadoTrabajo.EN_FILA, entidad__activa=True)
            .order_by("turno", "creado_en", "id")
            .first()
        )
        if trabajo is None:
            return None
        ahora = timezone.now()
        Trabajo.objects.filter(pk=trabajo.pk).update(
            estado=EstadoTrabajo.PROCESANDO,
            iniciado_en=ahora,
            latido=ahora,
            trabajador=trabajador_id,
            intentos=F("intentos") + 1,
        )
    return Trabajo.objects.select_related("evaluacion__proceso", "evaluacion__plantilla", "proponente").get(pk=trabajo.pk)


def recuperar_huerfanos(max_intentos: int = 3, sin_latido: timedelta = timedelta(minutes=5)) -> int:
    """Trabajos cuyo trabajador dejó de latir: vuelven a la fila o quedan en error."""
    limite = timezone.now() - sin_latido
    huerfanos = Trabajo.objects.filter(estado=EstadoTrabajo.PROCESANDO, latido__lt=limite)
    n = 0
    for t in huerfanos.select_related("evaluacion"):
        if t.intentos >= max_intentos:
            t.estado = EstadoTrabajo.ERROR
            t.error = "El proponente detuvo el trabajador varias veces (posible falta de memoria)."
            t.terminado_en = timezone.now()
        else:
            t.estado = EstadoTrabajo.EN_FILA
        t.save(update_fields=["estado", "error", "terminado_en"])
        n += 1
    return n


# --- Plantillas de evaluación ---
def plantilla_activa(entidad_id: UUID, tipo: str) -> PlantillaEvaluacion | None:
    return PlantillaEvaluacion.objects.filter(entidad_id=entidad_id, tipo=tipo, activa=True).first()


def definicion_de(evaluacion: Evaluacion) -> criterios.DefinicionEvaluacion:
    """La evaluación de la entidad (su plantilla) con los ajustes del pliego de
    este proceso que una persona aceptó."""
    from evaluaciones.pliego import aplicar_ajustes

    if evaluacion.plantilla_id:
        definicion = criterios.DefinicionEvaluacion.model_validate(evaluacion.plantilla.definicion)
    else:
        definicion = criterios.definicion_sistema(evaluacion.tipo)
    if evaluacion.tipo == "juridica" and evaluacion.proceso.ajustes_pliego:
        definicion = aplicar_ajustes(definicion, evaluacion.proceso.ajustes_pliego)
    # El salario mínimo del año del cierre, salvo que la entidad fije otro.
    if not definicion.parametros.get("smmlv"):
        salario = salario_minimo(evaluacion.proceso.fecha_cierre.year)
        if salario:
            definicion = definicion.model_copy(update={"parametros": {**definicion.parametros, "smmlv": salario}})
    return definicion


def salario_minimo(ano: int) -> int | None:
    from evaluaciones.models import SalarioMinimo

    return SalarioMinimo.objects.filter(ano=ano).values_list("valor", flat=True).first()


def catalogo(definicion: criterios.DefinicionEvaluacion) -> list[dict]:
    """Requisitos tal como los muestra la interfaz (nombre, grupo, qué se verifica, pistas de archivo)."""
    salida = []
    for r in definicion.requisitos:
        v = criterios.VERIFICACIONES.get(r.verificacion)
        pistas = list(v.pistas) if v else [f.lower() for f in (r.config.frases_documento if r.config else [])][:5]
        salida.append(
            {
                "numero": r.numero,
                "corto": r.corto,
                "titulo": r.titulo,
                "verifica": r.verifica or (v.verifica if v else ""),
                "grupo": r.grupo,
                "pistas": pistas,
                "personalizado": r.verificacion == criterios.PERSONALIZADO,
                "manual": r.verificacion == criterios.MANUAL,
            }
        )
    return salida


def nueva_version(entidad_id: UUID, tipo: str, nombre: str, definicion: criterios.DefinicionEvaluacion, usuario, nota: str = "") -> PlantillaEvaluacion:
    with transaction.atomic():
        ultima = PlantillaEvaluacion.objects.filter(entidad_id=entidad_id, tipo=tipo).aggregate(m=Max("version"))["m"] or 0
        PlantillaEvaluacion.objects.filter(entidad_id=entidad_id, tipo=tipo, activa=True).update(activa=False)
        return PlantillaEvaluacion.objects.create(
            entidad_id=entidad_id,
            tipo=tipo,
            version=ultima + 1,
            nombre=nombre.strip()[:200],
            definicion=definicion.model_dump(mode="json"),
            nota=nota.strip(),
            creada_por=usuario,
        )


def definicion_base_para(tipo: str, sigla: str, nombre_entidad: str) -> criterios.DefinicionEvaluacion:
    """Base del sistema adaptada a la entidad: su sigla en el código del proceso
    y como beneficiario de la póliza."""
    definicion = criterios.definicion_sistema(tipo)
    if tipo == "juridica" and sigla.strip():
        definicion.parametros = {
            "prefijo_codigo": sigla.strip().upper(),
            "beneficiario_claves": [sigla.strip().upper(), nombre_entidad.strip().upper()],
        }
    return criterios.DefinicionEvaluacion.model_validate(definicion.model_dump())


# --- Informe Excel ---
class SinPlantillaInforme(Exception):
    pass


def plantilla_para_informe(entidad_id: UUID, tipo: str):
    """Plantilla activa de la entidad o, si no tiene, la de ejemplo del sistema."""
    from pathlib import Path

    from evaluaciones.models import PlantillaInforme
    from evaluaciones.tipos import TIPOS
    from motor.excel.filler import MAPEO_POR_DEFECTO, MapeoPlantilla

    propia = PlantillaInforme.objects.filter(entidad_id=entidad_id, tipo=tipo, activa=True).first()
    if propia is not None:
        return Path(propia.archivo.path), MapeoPlantilla.model_validate(propia.mapeo)
    del_sistema = TIPOS[tipo].plantilla
    if del_sistema is not None and del_sistema.exists():
        return del_sistema, MAPEO_POR_DEFECTO
    return None


def resultados_con_decisiones(evaluacion: Evaluacion) -> list[ResultadoRequisito]:
    revisiones = {(r.proponente_id, r.requisito): r for r in Revision.objects.filter(evaluacion=evaluacion)}
    return [
        aplicar_revision(r.datos, revisiones.get((r.proponente_id, r.requisito)))
        for r in Resultado.objects.filter(evaluacion=evaluacion)
    ]


def generar_informe_excel(evaluacion: Evaluacion) -> tuple[bytes, str]:
    from motor.esquemas.proceso import ProcesoDocumentoBase
    from motor.excel.filler import fill_template

    elegida = plantilla_para_informe(evaluacion.entidad_id, evaluacion.tipo)
    if elegida is None:
        raise SinPlantillaInforme()
    plantilla, mapeo = elegida
    # Filas del Excel definidas en la plantilla de evaluación (si las trae).
    filas = {r.numero: r.fila_excel for r in definicion_de(evaluacion).requisitos if r.fila_excel}
    if filas:
        mapeo = mapeo.model_copy(update={"filas_por_requisito": {**mapeo.filas_por_requisito, **filas}})
    proceso = evaluacion.proceso
    contenido = fill_template(
        str(plantilla),
        ProcesoDocumentoBase.model_validate(proceso.documento_base),
        [proponente_motor(p) for p in proceso.proponentes.all()],
        resultados_con_decisiones(evaluacion),
        mapeo=mapeo,
        tipo=evaluacion.get_tipo_display(),
    )
    borrador = "" if evaluacion.estado == EstadoEvaluacion.APROBADA else " (BORRADOR)"
    # Mismo nombre que usa la plantilla oficial ("INFORME EVALUACION JURIDICA …"), sin tildes.
    return contenido, f"INFORME EVALUACION {evaluacion.tipo.upper()} {proceso.codigo}{borrador}.xlsx"
