"""Lógica de evaluaciones compartida por la API y el trabajador de la fila."""
from __future__ import annotations

import logging
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

log = logging.getLogger(__name__)

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


def proponente_motor(p: Proponente, evaluacion: Evaluacion | None = None) -> ProponenteMotor:
    """El proponente como lo ve el motor. Con `evaluacion` se le suman los
    certificados que el evaluador aportó o que el programa consultó en línea,
    para que el motor los lea como parte de la oferta."""
    return ProponenteMotor(
        numero_orden=p.numero_orden,
        hoja=p.hoja,
        nombre_proponente=p.nombre,
        nombre_archivo=p.nombre_archivo,
        drive_file_id=p.drive_file_id,
        advertencia=p.advertencia or None,
        documentos_aportados=_documentos_aportados(p, evaluacion) if evaluacion is not None else [],
    )


def _documentos_aportados(p: Proponente, evaluacion: Evaluacion) -> list[tuple[str, bytes]]:
    from evaluaciones.models import DocumentoAportado

    documentos = []
    for d in DocumentoAportado.objects.filter(evaluacion=evaluacion, proponente=p):
        try:
            with d.archivo.open("rb") as archivo:
                documentos.append((f"Req {d.requisito} - {d.nombre_original}", archivo.read()))
        except Exception:  # noqa: BLE001
            log.exception("No se pudo leer el documento aportado %s", d.pk)
    return documentos


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


def _clave_integrante(nombre: str, nit: str | None) -> str:
    digitos = "".join(c for c in (nit or "") if c.isdigit()).lstrip("0")
    if len(digitos) == 10 and digitos[0] in "89":
        return digitos[:9]  # NIT de empresa con dígito de verificación
    if len(digitos) >= 6:
        return digitos
    return " ".join(nombre.upper().split())


def revisar_integrantes_compartidos(evaluacion: Evaluacion) -> int:
    """Evaluación financiera: un integrante que está en varias ofertas del
    mismo proceso (para lotes distintos) debe tener capacidad residual para
    la suma de los lotes de todas ellas (pliego 3.11; así lo aplicó el
    evaluador de referencia). Cada oferta se evalúa por separado, así que la
    capacidad residual de esas ofertas pasa a revisión con la explicación.
    Devuelve cuántos resultados se marcaron."""
    residuales = [r for r in definicion_de(evaluacion).requisitos if r.verificacion == "financiera.residual"]
    numeros = {r.numero for r in residuales}
    if not numeros:
        return 0
    filas = list(
        Resultado.objects.filter(evaluacion=evaluacion, requisito__in=numeros).select_related("proponente")
    )
    por_integrante: dict[str, set] = {}
    nombres: dict[str, str] = {}
    lotes: dict = {}
    for f in filas:
        financiera = (f.datos.get("detalle") or {}).get("financiera") or {}
        if financiera.get("no_aplica"):
            continue
        lotes.setdefault(f.proponente_id, set()).add(financiera.get("lote") or "")
        for i in (f.datos.get("detalle") or {}).get("integrantes_financieros") or []:
            clave = _clave_integrante(i.get("nombre") or "", i.get("nit"))
            por_integrante.setdefault(clave, set()).add(f.proponente_id)
            nombres[clave] = i.get("nombre") or clave
    marcados = 0
    with transaction.atomic():
        for f in filas:
            datos = f.datos
            financiera = (datos.get("detalle") or {}).get("financiera") or {}
            if financiera.get("no_aplica") or financiera.get("compartido") or not datos.get("cumple"):
                continue
            otros = {}
            for i in (datos.get("detalle") or {}).get("integrantes_financieros") or []:
                clave = _clave_integrante(i.get("nombre") or "", i.get("nit"))
                for p in por_integrante.get(clave, set()) - {f.proponente_id}:
                    otros.setdefault(p, []).append(nombres[clave])
            if not otros:
                continue
            hojas = {p.id: p for p in Proponente.objects.filter(id__in=otros)}
            partes = [
                f"{', '.join(sorted(set(n)))} también integra {hojas[p].hoja} {hojas[p].nombre_proponente} "
                f"({', '.join(sorted(l.lower() for l in lotes.get(p, set()) if l)) or 'otros lotes'})"
                for p, n in otros.items() if p in hojas
            ]
            aviso = ("; ".join(partes) + ": la capacidad residual de ese integrante debe alcanzar para los lotes de "
                     "todas las ofertas en que participa (pliego 3.11); verifícala en conjunto.")
            datos = {**datos, "cumple": False, "motivo": f"{aviso} {datos.get('motivo') or ''}".strip(),
                     "detalle": {**datos["detalle"], "financiera": {**financiera, "compartido": True}}}
            Resultado.objects.filter(pk=f.pk).update(
                datos=datos, requiere_revision=requiere_revision(ResultadoRequisito.model_validate(datos))
            )
            marcados += 1
    return marcados


def clave_persona(nombre: str, documento: str | None, tipo: str | None = None) -> str:
    """Una misma persona se reconoce por su documento; sin él, por su nombre.

    Del NIT de una empresa cuentan los 9 dígitos (el décimo es el de
    verificación). De una cédula cuentan TODOS: las cédulas nuevas tienen 10
    dígitos y dos personas con cédulas consecutivas (1.020.304.050 y
    1.020.304.051) comparten los 9 primeros; cortarlas las fundía en una sola
    y los antecedentes de una tapaban los de la otra."""
    digitos = "".join(c for c in (documento or "") if c.isdigit()).lstrip("0")
    if len(digitos) >= 5:
        return digitos[:9] if tipo == "juridica" and len(digitos) >= 9 else digitos
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
            clave = clave_persona(per["nombre"], per.get("documento"), per.get("tipo"))
            # Entre varios resultados de la misma persona gana el que trae la
            # fecha de expedición de su documento.
            if clave not in detectadas or (per.get("fecha_expedicion_documento") and not detectadas[clave].get("fecha_expedicion_documento")):
                detectadas[clave] = per
    existentes = {
        clave_persona(x.nombre, x.documento, x.tipo): x for x in PersonaVerificada.objects.filter(evaluacion=evaluacion, proponente=proponente)
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
        # Una evaluación aprobada es el registro oficial: sus requisitos no
        # cambian aunque después mejoren las reglas del pliego.
        definicion = aplicar_ajustes(
            definicion, evaluacion.proceso.ajustes_pliego, revalidar=evaluacion.estado != EstadoEvaluacion.APROBADA
        )
    if evaluacion.tipo == "tecnica":
        parametros = parametros_tecnicos_de(evaluacion.proceso) or {}
        definicion = criterios.expandir_lotes(definicion, [l["nombre"] for l in parametros.get("lotes", [])])
    if evaluacion.tipo == "financiera":
        parametros = parametros_financieros_de(evaluacion.proceso) or {}
        definicion = criterios.expandir_lotes(definicion, [l["nombre"] for l in parametros.get("lotes", [])])
    # El salario mínimo del año del cierre, salvo que la entidad fije otro.
    if not definicion.parametros.get("smmlv"):
        salario = salario_minimo(evaluacion.proceso.fecha_cierre.year)
        if salario:
            definicion = definicion.model_copy(update={"parametros": {**definicion.parametros, "smmlv": salario}})
    return definicion


def _fundir_con_la_ia(parametros, analisis, *, tecnicos: bool) -> None:
    """Completa los parámetros que leyeron las reglas con los que la IA leyó
    del pliego, y deja anotado lo que nadie ha confirmado todavía: mientras
    eso esté ahí, ningún lote se aprueba solo (motor/pliego/fusion.py)."""
    from evaluaciones.pliego import parametros_leidos
    from motor.pliego import fusion

    ia = parametros_leidos(analisis)
    if ia is None:
        return
    confirmados = (analisis.parametros_confirmados or {}) if analisis is not None else {}
    aplicar = fusion.aplicar_a_tecnicos if tecnicos else fusion.aplicar_a_financieros
    resultado = aplicar(parametros, ia, confirmados)
    parametros.sin_confirmar = [p.explicacion() for p in resultado.sin_confirmar]
    # Lo que el pliego exige y el motor no sabe verificar: se nombra y manda
    # el lote a revisión, nunca se da por cumplido.
    parametros.requisitos_sin_verificar = fusion.sin_verificar(ia)


def parametros_tecnicos_de(proceso) -> dict | None:
    """Parámetros de la evaluación técnica leídos del pliego del proceso. Se
    calculan una vez y quedan guardados; None si el proceso no tiene el
    pliego o falta el salario mínimo del año del cierre."""
    import dataclasses

    from motor.tecnica.parametros import ParametrosTecnicos

    campos = {f.name for f in dataclasses.fields(ParametrosTecnicos)}
    # Guardados con una versión anterior del motor (p. ej. sin los puntos
    # que da el pliego a cada factor): se vuelven a leer del pliego.
    if proceso.parametros_tecnicos and campos <= set(proceso.parametros_tecnicos):
        return proceso.parametros_tecnicos
    analisis = proceso.analisis_pliego
    salario = salario_minimo(proceso.fecha_cierre.year)
    if analisis is None or not analisis.archivo or not salario:
        return None
    from motor.esquemas.proceso import ProcesoDocumentoBase
    from motor.tecnica.evaluador import parametros_a_dict
    from motor.tecnica.parametros import leer_parametros

    try:
        with analisis.archivo.open("rb") as f:
            contenido = f.read()
    except OSError:
        return None
    base = ProcesoDocumentoBase.model_validate(proceso.documento_base)
    leidos = leer_parametros(contenido, [(l.numero, l.valor_presupuesto) for l in base.lotes], salario)
    _fundir_con_la_ia(leidos, analisis, tecnicos=True)
    parametros = parametros_a_dict(leidos)
    type(proceso).objects.filter(pk=proceso.pk).update(parametros_tecnicos=parametros)
    proceso.parametros_tecnicos = parametros
    return parametros


def parametros_financieros_de(proceso) -> dict | None:
    """Parámetros de la evaluación financiera: presupuesto de cada lote (el
    mismo que lee la técnica), plazo y anticipo del pliego y los umbrales de
    la Matriz 2 si el pliego los trae. Se calculan una vez y quedan
    guardados (los umbrales que registre una persona no se pisan)."""
    if proceso.parametros_financieros:
        return proceso.parametros_financieros
    tecnicos = parametros_tecnicos_de(proceso)
    analisis = proceso.analisis_pliego
    salario = salario_minimo(proceso.fecha_cierre.year)
    if tecnicos is None or analisis is None or not analisis.archivo or not salario:
        return None
    from motor.financiera.evaluador import parametros_a_dict
    from motor.financiera.parametros import leer_parametros

    try:
        with analisis.archivo.open("rb") as f:
            contenido = f.read()
    except OSError:
        return None
    lotes = [(l["nombre"], l.get("presupuesto")) for l in tecnicos.get("lotes", [])]
    # La Matriz 2 del proceso, si la subieron: de ahí salen los umbrales de los
    # indicadores, que el pliego casi nunca trae.
    matriz2 = None
    if getattr(proceso, "matriz2", None):
        try:
            with proceso.matriz2.open("rb") as f:
                matriz2 = f.read()
        except OSError:
            matriz2 = None
    leidos = leer_parametros(contenido, lotes, salario, matriz2)
    _fundir_con_la_ia(leidos, analisis, tecnicos=False)
    parametros = parametros_a_dict(leidos)
    type(proceso).objects.filter(pk=proceso.pk).update(parametros_financieros=parametros)
    proceso.parametros_financieros = parametros
    return parametros


def parametros_del_pliego(proceso, tipo: str) -> list[dict]:
    """Lo que el programa entendió del pliego, para que una persona lo revise
    antes de dar la evaluación por buena: cada parámetro con su valor, de
    dónde salió y la frase del pliego que lo respalda.

    Mientras haya parámetros sin confirmar, ningún lote se aprueba solo (ver
    motor/pliego/fusion.py). Confirmarlos es lo que devuelve el automatismo."""
    from evaluaciones.pliego import parametros_leidos
    from motor.pliego import fusion
    from motor.tecnica.evaluador import parametros_de_dict as tecnicos_de_dict

    analisis = proceso.analisis_pliego
    ia = parametros_leidos(analisis)
    if ia is None:
        return []
    confirmados = (analisis.parametros_confirmados or {}) if analisis is not None else {}
    if tipo == "financiera":
        from motor.financiera.evaluador import parametros_de_dict

        datos = parametros_financieros_de(proceso)
        if datos is None:
            return []
        resultado = fusion.aplicar_a_financieros(parametros_de_dict(datos), ia, {})
    else:
        datos = parametros_tecnicos_de(proceso)
        if datos is None:
            return []
        resultado = fusion.aplicar_a_tecnicos(tecnicos_de_dict(datos), ia, {})
    salida = []
    for campo, procedencia in sorted(resultado.procedencias.items()):
        salida.append({
            "campo": campo,
            "valor_reglas": procedencia.valor_regla,
            "valor_ia": procedencia.valor_ia,
            "origen": procedencia.origen,
            "en_firme": procedencia.en_firme or campo in confirmados,
            "confirmado": confirmados.get(campo),
            "cita": procedencia.cita,
            "seccion": procedencia.seccion,
        })
    return salida


def confirmar_parametros_del_pliego(proceso, valores: dict, usuario) -> dict:
    """Guarda lo que una persona confirmó o corrigió de los parámetros que se
    leyeron del pliego. A partir de ahí valen como si los hubieran leído las
    reglas, y los lotes vuelven a poder aprobarse solos."""
    from django.utils import timezone as _tz

    analisis = proceso.analisis_pliego
    if analisis is None:
        raise ValueError("El proceso no tiene pliego analizado.")
    limpios = {str(k)[:120]: v for k, v in (valores or {}).items()
               if isinstance(v, (str, int, float, list)) and str(v).strip() != ""}
    if not limpios:
        raise ValueError("No se recibió ningún parámetro para confirmar.")
    confirmados = {**(analisis.parametros_confirmados or {}), **limpios}
    analisis.parametros_confirmados = confirmados
    analisis.confirmados_por, analisis.confirmados_en = usuario, _tz.now()
    analisis.save(update_fields=["parametros_confirmados", "confirmados_por", "confirmados_en"])
    # Los parámetros guardados del proceso se vuelven a calcular con lo
    # confirmado la próxima vez que se pidan.
    type(proceso).objects.filter(pk=proceso.pk).update(parametros_tecnicos={}, parametros_financieros={})
    proceso.parametros_tecnicos, proceso.parametros_financieros = {}, {}
    return confirmados


UMBRALES_FINANCIEROS = ("liquidez_min", "endeudamiento_max", "cobertura_min", "roa_min", "roe_min")


def registrar_umbrales_financieros(proceso, valores: dict, usuario) -> dict:
    """Umbrales de la Matriz 2 que registra una persona (la matriz es un
    anexo aparte del pliego). Quedan con quién y cuándo los registró; para
    que cuenten hay que volver a evaluar."""
    parametros = parametros_financieros_de(proceso)
    if parametros is None:
        raise ValueError("El proceso no tiene los parámetros financieros del pliego (falta el pliego o el salario mínimo).")
    umbrales = {}
    for clave in UMBRALES_FINANCIEROS:
        v = valores.get(clave)
        if v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or v > 1000:
            raise ValueError(f"Falta o no es válido el umbral «{clave}».")
        umbrales[clave] = float(v)
    nombre = usuario.nombre_completo or usuario.email
    umbrales["fuente"] = f"Matriz 2, registrada por {nombre} el {timezone.localdate():%d/%m/%Y}"
    parametros = {**parametros, "umbrales": umbrales}
    type(proceso).objects.filter(pk=proceso.pk).update(parametros_financieros=parametros)
    proceso.parametros_financieros = parametros
    return parametros


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
    if elegida is None and evaluacion.tipo == "tecnica":
        return generar_informe_tecnico(evaluacion)
    if elegida is None and evaluacion.tipo == "financiera":
        return generar_informe_financiero(evaluacion)
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


def generar_informe_tecnico(evaluacion: Evaluacion) -> tuple[bytes, str]:
    """Consolidado técnico por lote (sin plantilla de la entidad)."""
    from motor.tecnica.informe import ResultadoInforme, generar_informe

    proceso = evaluacion.proceso
    definicion = definicion_de(evaluacion)
    revisiones = {(r.proponente_id, r.requisito): r for r in Revision.objects.filter(evaluacion=evaluacion)}
    hojas = {p.id: p.hoja for p in proceso.proponentes.all()}
    resultados = {}
    for r in Resultado.objects.filter(evaluacion=evaluacion):
        revision = revisiones.get((r.proponente_id, r.requisito))
        resultados[(hojas[r.proponente_id], r.requisito)] = ResultadoInforme(aplicar_revision(r.datos, revision), revision is not None)
    experiencia = [r for r in definicion.requisitos if r.verificacion == "tecnica.experiencia"]
    lotes = [(r.lote or 0, r.titulo.split("—")[-1].strip() if "—" in r.titulo else "Lote único") for r in experiencia]
    contenido = generar_informe(
        proceso.codigo,
        proceso.objeto,
        lotes,
        [(p.hoja, p.nombre_proponente) for p in proceso.proponentes.order_by("numero_orden")],
        resultados,
        {r.lote or 0: r.numero for r in experiencia},
        borrador=evaluacion.estado != EstadoEvaluacion.APROBADA,
        titulos={r.numero: r.titulo for r in definicion.requisitos},
    )
    borrador = "" if evaluacion.estado == EstadoEvaluacion.APROBADA else " (BORRADOR)"
    return contenido, f"INFORME EVALUACION TECNICA {proceso.codigo}{borrador}.xlsx"


def generar_informe_financiero(evaluacion: Evaluacion) -> tuple[bytes, str]:
    """Resumen financiero por lote (sin plantilla de la entidad)."""
    from motor.financiera.informe import generar_informe
    from motor.tecnica.informe import ResultadoInforme

    proceso = evaluacion.proceso
    definicion = definicion_de(evaluacion)
    revisiones = {(r.proponente_id, r.requisito): r for r in Revision.objects.filter(evaluacion=evaluacion)}
    hojas = {p.id: p.hoja for p in proceso.proponentes.all()}
    resultados = {}
    for r in Resultado.objects.filter(evaluacion=evaluacion):
        revision = revisiones.get((r.proponente_id, r.requisito))
        resultados[(hojas[r.proponente_id], r.requisito)] = ResultadoInforme(aplicar_revision(r.datos, revision), revision is not None)
    por_lote: dict[int, list[int]] = {}
    generales = []
    for r in definicion.requisitos:
        if r.verificacion in criterios.POR_LOTE:
            por_lote.setdefault(r.lote or 0, []).append(r.numero)
        else:
            generales.append(r.numero)
    parametros = parametros_financieros_de(proceso) or {}
    lotes = [(i, l["nombre"]) for i, l in enumerate(parametros.get("lotes", []))] or [(0, "Lote único")]
    contenido = generar_informe(
        proceso.codigo,
        proceso.objeto,
        lotes,
        [(p.hoja, p.nombre_proponente) for p in proceso.proponentes.order_by("numero_orden")],
        resultados,
        generales,
        por_lote,
        borrador=evaluacion.estado != EstadoEvaluacion.APROBADA,
        titulos={r.numero: r.titulo for r in definicion.requisitos},
    )
    borrador = "" if evaluacion.estado == EstadoEvaluacion.APROBADA else " (BORRADOR)"
    return contenido, f"INFORME EVALUACION FINANCIERA {proceso.codigo}{borrador}.xlsx"


def _resultados_para_informe(evaluacion: Evaluacion) -> dict[tuple[str, int], "ResultadoInforme"]:
    from motor.tecnica.informe import ResultadoInforme

    revisiones = {(r.proponente_id, r.requisito): r for r in Revision.objects.filter(evaluacion=evaluacion)}
    hojas = {p.id: p.hoja for p in evaluacion.proceso.proponentes.all()}
    resultados = {}
    for r in Resultado.objects.filter(evaluacion=evaluacion):
        revision = revisiones.get((r.proponente_id, r.requisito))
        resultados[(hojas[r.proponente_id], r.requisito)] = ResultadoInforme(
            aplicar_revision(r.datos, revision), revision is not None
        )
    return resultados


def _requisitos_por_lote(evaluacion: Evaluacion) -> dict[str, list[int]]:
    """Requisitos que habilitan, separados en los generales y los de cada
    lote. Los factores de puntaje no habilitan: solo suman puntos."""
    reparto: dict[str, list[int]] = {"generales": []}
    for r in definicion_de(evaluacion).requisitos:
        if r.grupo == "puntaje":
            continue
        if r.verificacion in criterios.POR_LOTE:
            reparto.setdefault(f"lote_{r.lote or 0}", []).append(r.numero)
        else:
            reparto["generales"].append(r.numero)
    return reparto


def lotes_del_proceso(proceso) -> list[tuple[int, str]]:
    """(índice, nombre) de los lotes del pliego; "Lote único" si no tiene."""
    parametros = parametros_tecnicos_de(proceso) or parametros_financieros_de(proceso) or {}
    lotes = [(i, l["nombre"]) for i, l in enumerate(parametros.get("lotes", []))]
    return lotes or [(0, "Lote único")]


def generar_informe_consolidado(proceso) -> tuple[bytes, str]:
    """Las tres áreas en un solo informe: habilitación por lote, el puntaje
    que asigna el programa y el orden de elegibilidad."""
    from motor.consolidado import generar_informe

    evaluaciones = {e.tipo: e for e in proceso.evaluaciones.all()}
    if not evaluaciones:
        raise ValueError("El proceso no tiene evaluaciones.")
    resultados = {tipo: _resultados_para_informe(e) for tipo, e in evaluaciones.items()}
    requisitos = {tipo: _requisitos_por_lote(e) for tipo, e in evaluaciones.items()}
    aprobadas = all(e.estado == EstadoEvaluacion.APROBADA for e in evaluaciones.values())
    contenido = generar_informe(
        proceso.codigo,
        proceso.objeto,
        lotes_del_proceso(proceso),
        [(p.hoja, p.nombre_proponente) for p in proceso.proponentes.order_by("numero_orden")],
        resultados,
        requisitos,
        borrador=not aprobadas,
    )
    borrador = "" if aprobadas else " (BORRADOR)"
    return contenido, f"INFORME CONSOLIDADO {proceso.codigo}{borrador}.xlsx"


def eliminar_proceso(proceso) -> dict[str, int]:
    """Borra el proceso con todo lo suyo: evaluaciones, proponentes,
    resultados, revisiones, personas, certificados aportados y expedientes,
    y sus archivos en disco. El análisis del pliego se conserva (se reutiliza
    si otro proceso usa el mismo pliego). Devuelve cuánto se borró.

    Los archivos se borran solo si la base de datos confirma el borrado: si
    algo falla a mitad de camino, no quedan registros apuntando a archivos
    que ya no existen."""
    from evaluaciones.models import DocumentoAportado, EstadoEvaluacion, Expediente, Trabajo

    if proceso.evaluaciones.filter(estado=EstadoEvaluacion.APROBADA).exists():
        raise ValueError(
            "Este proceso tiene evaluaciones aprobadas: son el registro oficial de la decisión y no se pueden eliminar."
        )
    with transaction.atomic():
        evaluaciones = list(proceso.evaluaciones.all())
        aportados = DocumentoAportado.objects.filter(evaluacion__in=evaluaciones)
        expedientes = Expediente.objects.filter(evaluacion__in=evaluaciones)
        archivos = [d.archivo for d in aportados if d.archivo] + [e.archivo for e in expedientes if e.archivo]
        conteo = {
            "evaluaciones": len(evaluaciones),
            "proponentes": proceso.proponentes.count(),
            "certificados_aportados": aportados.count(),
            "expedientes": expedientes.count(),
        }
        # Lo que tiene protección contra borrado en cascada va primero.
        Trabajo.objects.filter(evaluacion__in=evaluaciones).delete()
        aportados.delete()
        expedientes.delete()
        proceso.delete()

        def borrar_archivos() -> None:
            for archivo in archivos:
                try:
                    archivo.storage.delete(archivo.name)
                except Exception:  # noqa: BLE001
                    log.warning("No se pudo borrar el archivo %s del proceso eliminado", archivo.name)

        transaction.on_commit(borrar_archivos)
    return conteo


def depurar_requisitos_retirados(evaluacion: Evaluacion) -> int:
    """Borra los resultados y revisiones de requisitos que ya no están en la
    evaluación (p. ej. un formato del pliego que se dejó de exigir): si no,
    seguirían contando como pendientes. Una evaluación aprobada no se toca."""
    if evaluacion.estado == EstadoEvaluacion.APROBADA:
        return 0
    numeros = {r.numero for r in definicion_de(evaluacion).requisitos}
    borrados, _ = Resultado.objects.filter(evaluacion=evaluacion).exclude(requisito__in=numeros).delete()
    Revision.objects.filter(evaluacion=evaluacion).exclude(requisito__in=numeros).delete()
    return borrados
