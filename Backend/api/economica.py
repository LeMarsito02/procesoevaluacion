"""Factor económico (RF-11) y ofertas artificialmente bajas (RF-13) de un proceso."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.core.files.base import ContentFile
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import File, Form, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from api.evaluaciones import _evaluaciones_qs, _proceso_visible
from cuentas.models import Usuario
from cuentas.seguridad import auditar, sesion_activa
from evaluaciones import economica
from evaluaciones.models import FactorEconomico, OfertaEconomica, Proceso
from evaluaciones.permisos import exigir_compromiso, puede_trabajar
from motor.economica import ponderacion as p
from motor.economica.correccion import revisar_excel

router = Router(auth=sesion_activa, tags=["economica"])


class ParametrosIn(Schema):
    puntaje_maximo: Decimal | None = None
    presupuesto_oficial: Decimal | None = None
    costo_estimado: Decimal | None = None
    tabla_metodos: str | None = None
    trm: Decimal | None = None
    fecha_trm: date | None = None


class OfertaIn(Schema):
    valor_corregido: Decimal | None = None
    confirmar_corregido: bool = False
    estado: str | None = None
    motivo_rechazo: str | None = None
    justificacion: str | None = None
    nota: str | None = None


def _puede_registrar(usuario: Usuario, proceso: Proceso) -> bool:
    return any(puede_trabajar(usuario, e) for e in _evaluaciones_qs(usuario).filter(proceso=proceso))


def _para_registrar(request: HttpRequest, proceso_id: UUID) -> Proceso:
    proceso = _proceso_visible(request.auth, proceso_id)
    if not _puede_registrar(request.auth, proceso):
        raise HttpError(403, "Solo los comités o quien gestiona el proceso registran el factor económico.")
    exigir_compromiso(request.auth)
    return proceso


def _pesos(valor) -> str | None:
    return None if valor is None else str(valor)


def _detalle(proceso: Proceso, usuario: Usuario) -> dict:
    salida = []
    habil = economica.habilitacion(proceso)
    for f in economica.factores(proceso):
        bajas = economica.analisis_bajas(f)
        alertas = {a.clave: a.motivo for a in (bajas.alertas if bajas else [])}
        try:
            m = economica.metodo(f)
        except p.ErrorPonderacion as exc:
            m, error_metodo = None, str(exc)
        else:
            error_metodo = ""
        salida.append({
            "id": str(f.id), "lote": f.lote or "Único", "orden": f.orden,
            "puntaje_maximo": _pesos(f.puntaje_maximo), "presupuesto_oficial": _pesos(f.presupuesto_oficial),
            "costo_estimado": _pesos(f.costo_estimado), "tabla_metodos": f.tabla_metodos,
            "trm": _pesos(f.trm), "fecha_trm": f.fecha_trm.isoformat() if f.fecha_trm else None,
            "metodo": m, "metodo_nombre": p.NOMBRES.get(m, "") if m else "", "error_metodo": error_metodo,
            "rangos": [{"desde": a, "hasta": b, "metodo": p.NOMBRES[x]} for a, b, x in
                       (p.RANGOS_ANTERIORES if f.tabla_metodos == FactorEconomico.ANTERIORES else p.RANGOS_VIGENTES)],
            "bajas": None if bajas is None else {"metodo": bajas.metodo, "explicacion": bajas.explicacion,
                                                  "valor_minimo_aceptable": bajas.valor_minimo_aceptable},
            "ofertas": [
                {"id": str(o.id), "proponente_id": str(o.proponente_id), "proponente": o.proponente.nombre, "hoja": o.proponente.hoja,
                 "valor_ofertado": _pesos(o.valor_ofertado), "valor_corregido": _pesos(o.valor_corregido),
                 "corregido_por": o.corregido_por.nombre_completo if o.corregido_por_id else None,
                 "revision": o.revision, "nombre_archivo": o.nombre_archivo, "estado": o.estado, "motivo_rechazo": o.motivo_rechazo,
                 "alerta_baja": alertas.get(str(o.id)), "habilitacion": habil.get(str(o.proponente_id), "pendiente"), "justificacion": o.justificacion, "nota": o.nota}
                for o in sorted(f.ofertas.all(), key=lambda o: o.proponente.numero_orden)
            ],
            "por_confirmar": economica.por_confirmar(f),
            "calificacion": f.calificacion,
            "confirmada_por": f.confirmada_por.nombre_completo if f.confirmada_por_id else None,
            "confirmada_en": f.confirmada_en.isoformat() if f.confirmada_en else None,
        })
    return {
        "puede_registrar": _puede_registrar(usuario, proceso),
        "proponentes": [{"id": str(x.id), "nombre": x.nombre, "hoja": x.hoja} for x in proceso.proponentes.all()],
        "factores": salida,
    }


def _factor(proceso: Proceso, factor_id: UUID) -> FactorEconomico:
    return get_object_or_404(FactorEconomico, pk=factor_id, proceso=proceso)


@router.get("/procesos/{proceso_id}")
def ver(request: HttpRequest, proceso_id: UUID) -> dict:
    return _detalle(_proceso_visible(request.auth, proceso_id), request.auth)


@router.put("/procesos/{proceso_id}/factores/{factor_id}")
def parametros(request: HttpRequest, proceso_id: UUID, factor_id: UUID, datos: ParametrosIn) -> dict:
    proceso = _para_registrar(request, proceso_id)
    f = _factor(proceso, factor_id)
    cambios = datos.dict(exclude_unset=True)
    if "tabla_metodos" in cambios and datos.tabla_metodos not in (FactorEconomico.VIGENTES, FactorEconomico.ANTERIORES):
        raise HttpError(400, "Tabla de métodos no válida.")
    for campo, valor in cambios.items():
        if isinstance(valor, Decimal) and valor <= 0:
            raise HttpError(400, "Los valores deben ser mayores que cero.")
        setattr(f, campo, valor)
    f.save()
    economica.anular_calificacion(f)
    auditar(request, "economica.parametros", entidad_id=proceso.entidad_id, objeto=f,
            cambios={k: str(v) for k, v in cambios.items()})
    return _detalle(proceso, request.auth)


@router.post("/procesos/{proceso_id}/factores/{factor_id}/ofertas")
def registrar_oferta(
    request: HttpRequest, proceso_id: UUID, factor_id: UUID, proponente_id: Form[UUID], valor_ofertado: Form[str],
    archivo: File[UploadedFile | None] = None,
) -> dict:
    """La oferta económica de un proponente: el valor que declara y, si se sube el
    formulario en Excel, la verificación aritmética que propone el valor corregido."""
    proceso = _para_registrar(request, proceso_id)
    f = _factor(proceso, factor_id)
    proponente = get_object_or_404(proceso.proponentes, pk=proponente_id)
    try:
        valor = Decimal(valor_ofertado.replace(".", "").replace(",", ".") if "," in valor_ofertado else valor_ofertado.replace(".", ""))
    except InvalidOperation as exc:
        raise HttpError(400, "El valor de la oferta no es un número.") from exc
    if valor <= 0:
        raise HttpError(400, "El valor de la oferta debe ser mayor que cero.")
    o, _ = OfertaEconomica.objects.get_or_create(
        factor=f, proponente=proponente, defaults={"entidad_id": proceso.entidad_id, "valor_ofertado": valor},
    )
    o.valor_ofertado, o.valor_corregido, o.corregido_por = valor, None, None
    revision = {"diferencias": [], "sin_verificar": ["Sin formulario en Excel: verifique a mano las operaciones de la oferta."], "propuesto": None}
    if archivo is not None:
        contenido = archivo.read()
        o.nombre_archivo = (archivo.name or "oferta")[:255]
        o.archivo.save(o.nombre_archivo, ContentFile(contenido), save=False)
        if o.nombre_archivo.lower().endswith((".xlsx", ".xlsm")):
            r = revisar_excel(contenido)
            revision = {
                "diferencias": [d.texto for d in r.diferencias], "sin_verificar": r.sin_verificar, "items": r.items,
                "total_declarado": _pesos(r.total_declarado), "propuesto": _pesos(r.total_corregido) if r.completa else None,
            }
            if r.total_declarado is not None and r.total_declarado != valor:
                revision["sin_verificar"].append(
                    f"El total del formulario ({r.total_declarado:,.0f}) no es el valor registrado ({valor:,.0f}).".replace(",", ".")
                )
                revision["propuesto"] = None
        else:
            revision["sin_verificar"] = ["El formulario no está en Excel: verifique a mano las operaciones de la oferta."]
    o.revision = revision
    o.save()
    economica.anular_calificacion(f)
    auditar(request, "economica.oferta", entidad_id=proceso.entidad_id, objeto=o, proponente=proponente.hoja, valor=str(valor),
            diferencias=len(revision["diferencias"]))
    return _detalle(proceso, request.auth)


@router.put("/procesos/{proceso_id}/ofertas/{oferta_id}")
def decidir_oferta(request: HttpRequest, proceso_id: UUID, oferta_id: UUID, datos: OfertaIn) -> dict:
    proceso = _para_registrar(request, proceso_id)
    o = get_object_or_404(OfertaEconomica, pk=oferta_id, factor__proceso=proceso)
    if datos.confirmar_corregido:
        if datos.valor_corregido is None or datos.valor_corregido <= 0:
            raise HttpError(400, "Indique el valor total corregido.")
        o.valor_corregido, o.corregido_por = datos.valor_corregido, request.auth
    if datos.estado is not None:
        if datos.estado not in (OfertaEconomica.VALIDA, OfertaEconomica.RECHAZADA):
            raise HttpError(400, "Estado no válido.")
        if datos.estado == OfertaEconomica.RECHAZADA and not (datos.motivo_rechazo or "").strip():
            raise HttpError(400, "Escriba el motivo del rechazo.")
        o.estado, o.motivo_rechazo = datos.estado, (datos.motivo_rechazo or "").strip()[:2000]
    if datos.justificacion is not None:
        if datos.justificacion not in (OfertaEconomica.SIN_SOLICITAR, OfertaEconomica.SOLICITADA, OfertaEconomica.ACEPTADA, OfertaEconomica.NO_ACEPTADA):
            raise HttpError(400, "Estado de la justificación no válido.")
        o.justificacion = datos.justificacion
        if datos.justificacion == OfertaEconomica.NO_ACEPTADA:
            o.estado, o.motivo_rechazo = OfertaEconomica.RECHAZADA, "Precio artificialmente bajo: no se aceptó la justificación."
    if datos.nota is not None:
        o.nota = datos.nota.strip()[:2000]
    o.save()
    economica.anular_calificacion(o.factor)
    auditar(request, "economica.decision", entidad_id=proceso.entidad_id, objeto=o, cambios={k: str(v) for k, v in datos.dict(exclude_unset=True, exclude_none=True).items()},
            valor_corregido=_pesos(o.valor_corregido), estado=o.estado, justificacion=o.justificacion)
    return _detalle(proceso, request.auth)


@router.post("/procesos/{proceso_id}/factores/{factor_id}/calificar")
def calificar(request: HttpRequest, proceso_id: UUID, factor_id: UUID) -> dict:
    proceso = _para_registrar(request, proceso_id)
    f = _factor(proceso, factor_id)
    try:
        c = economica.calificar(f, request.auth)
    except p.ErrorPonderacion as exc:
        raise HttpError(409, str(exc)) from exc
    auditar(request, "economica.calificada", entidad_id=proceso.entidad_id, objeto=f, metodo=c["metodo"], trm=c["trm"],
            puntajes=[(x["hoja"], x["puntaje"]) for x in c["puntajes"]])
    return _detalle(proceso, request.auth)
