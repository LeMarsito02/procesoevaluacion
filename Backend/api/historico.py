"""Personas verificadas, certificados aportados por el evaluador, reporte en
Word y expediente permanente de cada evaluación."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

import logging

from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File, Form, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from api.evaluaciones import _evaluacion, router
from cuentas.models import Usuario
from cuentas.seguridad import auditar
from evaluaciones import expediente, servicios
from evaluaciones.models import (
    DocumentoAportado,
    EstadoEvaluacion,
    EstadoExpediente,
    Expediente,
    PersonaVerificada,
    Proponente,
    Resultado,
    RolPersona,
    TipoPersona,
)
from evaluaciones.permisos import exigir_gestion, exigir_trabajo
from evaluaciones.reporte import generar_reporte

log = logging.getLogger(__name__)

MAX_PDF = 20 * 1024 * 1024


class PersonaOut(Schema):
    id: UUID
    rol: str
    rol_nombre: str
    tipo: str
    nombre: str
    documento: str
    fecha_expedicion_documento: date | None
    de_id: UUID | None
    # La detectó el programa en la oferta (no la agregó el evaluador).
    detectada: bool = False


class PersonaIn(Schema):
    rol: Literal["proponente", "representante_legal", "suplente", "integrante"]
    tipo: Literal["natural", "juridica"]
    nombre: str
    documento: str
    fecha_expedicion_documento: date | None = None
    de_id: UUID | None = None


class AportadoOut(Schema):
    id: UUID
    requisito: int
    persona_id: UUID | None
    fecha_expedicion: date
    nombre_original: str
    observacion: str
    subido_por: str | None
    subido_en: datetime


class AntecedentesOut(Schema):
    tipo_proponente: str | None
    representante_legal: str | None
    # Requisitos del grupo "Antecedentes" de la plantilla de la entidad.
    requisitos: list[dict]
    personas: list[PersonaOut]
    aportados: list[AportadoOut]
    # Documento que la oferta trae para cada requisito (si el motor lo encontró).
    encontrados: dict[int, str | None]
    # Estado de cada certificado de cada persona según el programa:
    # {persona_id: {requisito: {"estado": "cumple" | "falta" | "con_novedad" | "vencido" |
    # "no_requerido", "archivo": ...}}}. Sin entrada: el programa no la evaluó
    # (la agregó el evaluador y no está entre las que exige la regla).
    estados: dict[str, dict[int, dict]] = {}


class ExpedienteOut(Schema):
    id: UUID
    version: int
    estado: str
    tamano: int | None
    sha256: str
    avisos: str
    creado_en: datetime
    terminado_en: datetime | None


def _persona_out(p: PersonaVerificada) -> PersonaOut:
    return PersonaOut(
        id=p.id,
        rol=p.rol,
        rol_nombre=p.get_rol_display(),
        tipo=p.tipo,
        nombre=p.nombre,
        documento=p.documento,
        fecha_expedicion_documento=p.fecha_expedicion_documento,
        de_id=p.de_id,
        detectada=p.detectada,
    )


def _estados(personas: list[PersonaVerificada], requisitos: list[dict], datos: dict[int, dict]) -> dict[str, dict[int, dict]]:
    salida: dict[str, dict[int, dict]] = {}
    for req in requisitos:
        lista = (datos.get(req["numero"]) or {}).get("personas_antecedente") or []
        if not lista:
            continue
        por_clave = {servicios.clave_persona(x["nombre"], x.get("documento"), x.get("tipo")): x for x in lista}
        for persona in personas:
            x = por_clave.get(servicios.clave_persona(persona.nombre, persona.documento, persona.tipo))
            estado = {"estado": x["estado"], "archivo": x.get("archivo")} if x else {"estado": "no_requerido", "archivo": None}
            salida.setdefault(str(persona.id), {})[req["numero"]] = estado
    return salida


def _aportado_out(d: DocumentoAportado) -> AportadoOut:
    return AportadoOut(
        id=d.id,
        requisito=d.requisito,
        persona_id=d.persona_id,
        fecha_expedicion=d.fecha_expedicion,
        nombre_original=d.nombre_original,
        observacion=d.observacion,
        subido_por=d.subido_por.nombre_completo if d.subido_por else None,
        subido_en=d.subido_en,
    )


def _proponente(evaluacion, proponente_id: UUID) -> Proponente:
    return get_object_or_404(Proponente, pk=proponente_id, proceso_id=evaluacion.proceso_id)


@router.get("/{evaluacion_id}/proponentes/{proponente_id}/antecedentes", response=AntecedentesOut)
def antecedentes(request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID) -> AntecedentesOut:
    evaluacion = _evaluacion(request.auth, evaluacion_id)
    proponente = _proponente(evaluacion, proponente_id)
    catalogo = servicios.catalogo(servicios.definicion_de(evaluacion))
    requisitos = [c for c in catalogo if c["grupo"] == "antecedentes"]
    datos = {r.requisito: r.datos for r in Resultado.objects.filter(evaluacion=evaluacion, proponente=proponente)}
    personas = list(PersonaVerificada.objects.filter(evaluacion=evaluacion, proponente=proponente))
    return AntecedentesOut(
        tipo_proponente=next((d.get("tipo_proponente") for d in datos.values() if d.get("tipo_proponente")), None),
        representante_legal=next((d.get("representante_legal") for d in datos.values() if d.get("representante_legal")), None),
        requisitos=requisitos,
        personas=[_persona_out(p) for p in personas],
        aportados=[
            _aportado_out(d)
            for d in DocumentoAportado.objects.filter(evaluacion=evaluacion, proponente=proponente).select_related("subido_por")
        ],
        encontrados={c["numero"]: (datos.get(c["numero"]) or {}).get("archivo_evaluado") for c in requisitos},
        estados=_estados(personas, requisitos, datos),
    )


@router.post("/{evaluacion_id}/proponentes/{proponente_id}/personas", response={201: PersonaOut})
def agregar_persona(request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID, datos: PersonaIn):
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    proponente = _proponente(evaluacion, proponente_id)
    nombre = " ".join(datos.nombre.split()).upper()
    documento = "".join(c for c in datos.documento if c.isalnum() or c == "-")
    if len(nombre) < 3 or len(documento) < 4:
        raise HttpError(400, "Escriba el nombre completo y el número de documento (cédula o NIT).")
    if datos.tipo == TipoPersona.JURIDICA and datos.rol in (RolPersona.REPRESENTANTE, RolPersona.SUPLENTE):
        raise HttpError(400, "El representante legal debe ser una persona natural.")
    de = None
    if datos.de_id:
        de = get_object_or_404(PersonaVerificada, pk=datos.de_id, evaluacion=evaluacion, proponente=proponente)
        if de.tipo != TipoPersona.JURIDICA:
            raise HttpError(400, "Solo una persona jurídica tiene representantes.")
    if datos.fecha_expedicion_documento and datos.fecha_expedicion_documento > date.today():
        raise HttpError(400, "La fecha de expedición del documento no puede ser futura.")
    persona = PersonaVerificada.objects.create(
        entidad_id=evaluacion.entidad_id,
        evaluacion=evaluacion,
        proponente=proponente,
        de=de,
        rol=datos.rol,
        tipo=datos.tipo,
        nombre=nombre,
        documento=documento,
        fecha_expedicion_documento=datos.fecha_expedicion_documento,
        creada_por=usuario,
    )
    auditar(request, "persona_verificada.agregada", objeto=evaluacion, hoja=proponente.hoja, persona=nombre, rol=datos.rol)
    return 201, _persona_out(persona)


@router.get("/{evaluacion_id}/proponentes/{proponente_id}/personas/{persona_id}/cedula")
def cedula_de_persona(request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID, persona_id: UUID) -> HttpResponse:
    """La copia de la cédula de esa persona, tal como vino en la oferta, para
    que el evaluador lea la fecha de expedición con sus propios ojos cuando ni
    el lector de texto ni la IA pudieron. Si el programa alcanzó a leer algo,
    lo sugiere en la cabecera X-Fecha-Sugerida."""
    from motor.evaluacion.identidad import cedula_de, leer_fecha_expedicion
    from motor.integrations.drive import download_file_bytes
    from motor.procesamiento.zip_utils import extraer_pdfs

    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    proponente = _proponente(evaluacion, proponente_id)
    persona = get_object_or_404(PersonaVerificada, pk=persona_id, evaluacion=evaluacion, proponente=proponente)
    try:
        pdfs = extraer_pdfs(download_file_bytes(proponente.drive_file_id))
    except Exception as exc:  # noqa: BLE001
        raise HttpError(502, "No se pudieron abrir los documentos de la oferta.") from exc
    archivo = cedula_de(pdfs, persona.nombre, persona.documento)
    if archivo is None:
        raise HttpError(404, f"No se encontró la copia de la cédula de {persona.nombre} en la oferta.")
    respuesta = HttpResponse(pdfs[archivo], content_type="application/pdf")
    lectura = leer_fecha_expedicion(pdfs, persona.nombre, persona.documento)
    if lectura.fecha is not None:
        respuesta["X-Fecha-Sugerida"] = lectura.fecha.isoformat()
    respuesta["X-Archivo"] = archivo.rsplit("/", 1)[-1][:120]
    auditar(request, "cedula.vista", objeto=evaluacion, hoja=proponente.hoja, persona=persona.nombre)
    return respuesta


class FechaDocumentoIn(Schema):
    fecha_expedicion_documento: date | None = None


@router.patch("/{evaluacion_id}/personas/{persona_id}", response=PersonaOut)
def actualizar_persona(request: HttpRequest, evaluacion_id: UUID, persona_id: UUID, datos: FechaDocumentoIn):
    """La fecha de expedición del documento: la piden las páginas de consulta
    (el RNMC y los antecedentes judiciales), así que el evaluador la necesita
    a la mano aunque consulte a mano."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    persona = get_object_or_404(PersonaVerificada, pk=persona_id, evaluacion=evaluacion)
    if datos.fecha_expedicion_documento and datos.fecha_expedicion_documento > date.today():
        raise HttpError(400, "La fecha de expedición del documento no puede ser futura.")
    persona.fecha_expedicion_documento = datos.fecha_expedicion_documento
    persona.save(update_fields=["fecha_expedicion_documento"])
    auditar(request, "persona.actualizada", objeto=evaluacion, persona=persona.nombre,
            fecha_expedicion=str(datos.fecha_expedicion_documento or ""))
    return _persona_out(persona)


@router.delete("/{evaluacion_id}/personas/{persona_id}", response={204: None})
def quitar_persona(request: HttpRequest, evaluacion_id: UUID, persona_id: UUID):
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    persona = get_object_or_404(PersonaVerificada, pk=persona_id, evaluacion=evaluacion)
    if DocumentoAportado.objects.filter(persona__in=[persona, *persona.representantes.all()]).exists():
        raise HttpError(409, "Esta persona tiene certificados aportados. Quítelos primero.")
    auditar(request, "persona_verificada.quitada", objeto=evaluacion, persona=persona.nombre)
    persona.delete()
    return 204, None


@router.post("/{evaluacion_id}/proponentes/{proponente_id}/aportados", response={201: AportadoOut})
def aportar_documento(
    request: HttpRequest,
    evaluacion_id: UUID,
    proponente_id: UUID,
    requisito: Form[int],
    fecha_expedicion: Form[date],
    archivo: File[UploadedFile],
    persona_id: Form[UUID | None] = None,
    observacion: Form[str] = "",
):
    """Certificado que el evaluador consultó en la fuente oficial porque el proponente no lo aportó."""
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    proponente = _proponente(evaluacion, proponente_id)
    numeros = {r.numero for r in servicios.definicion_de(evaluacion).requisitos}
    if requisito not in numeros:
        raise HttpError(400, "Ese requisito no existe en la plantilla de la evaluación.")
    persona = get_object_or_404(PersonaVerificada, pk=persona_id, evaluacion=evaluacion, proponente=proponente) if persona_id else None
    if fecha_expedicion > date.today():
        raise HttpError(400, "La fecha de expedición no puede ser futura.")
    if archivo.size > MAX_PDF:
        raise HttpError(400, "El certificado supera 20 MB.")
    inicio = archivo.read(5)
    archivo.seek(0)
    if inicio != b"%PDF-":
        raise HttpError(400, "El certificado debe ser un PDF.")
    with transaction.atomic():
        doc = DocumentoAportado(
            entidad_id=evaluacion.entidad_id,
            evaluacion=evaluacion,
            proponente=proponente,
            persona=persona,
            requisito=requisito,
            fecha_expedicion=fecha_expedicion,
            nombre_original=(archivo.name or "certificado.pdf")[:255],
            observacion=observacion.strip(),
            subido_por=usuario,
        )
        doc.archivo.save(archivo.name or "certificado.pdf", archivo, save=False)
        doc.save()
        auditar(
            request,
            "antecedente.aportado",
            objeto=evaluacion,
            hoja=proponente.hoja,
            requisito=requisito,
            persona=persona.nombre if persona else None,
            fecha_expedicion=fecha_expedicion.isoformat(),
        )
    _reevaluar(evaluacion, proponente, usuario)
    return 201, _aportado_out(doc)


class ConsultaIn(Schema):
    requisito: int
    persona_id: UUID | None = None
    # El COPNIA se consulta por la matrícula del profesional que avala la
    # propuesta, que no es una de las personas con antecedentes.
    matricula: str | None = None
    # El RNMC pide la fecha de expedición de la cédula: si no está registrada
    # ni se pudo leer del documento, el evaluador la escribe.
    fecha_expedicion_documento: date | None = None


# Certificados que el programa puede traer solo: su página oficial no pide
# captcha. Los demás (Procuraduría, Contraloría, antecedentes judiciales) los
# consulta una persona y los sube con el botón de siempre.
FUENTES_EN_LINEA = {"juridica.rnmc": "rnmc", "juridica.copnia_antecedentes": "copnia", "juridica.aval_ingeniero": "copnia"}


def _consultado_hoy(evaluacion, proponente, requisito: int, persona, matricula: str | None):
    """El certificado que ya se consultó hoy para lo mismo, si existe."""
    hoy = DocumentoAportado.objects.filter(
        evaluacion=evaluacion, proponente=proponente, requisito=requisito,
        fecha_expedicion=date.today(), observacion__startswith="Consultado en línea",
    )
    if persona is not None:
        return hoy.filter(persona=persona).order_by("-subido_en").first()
    if matricula:
        return hoy.filter(persona=None, nombre_original__contains=matricula.strip()).order_by("-subido_en").first()
    return None


def _ya_cumple(evaluacion, proponente, requisito: int, persona) -> bool:
    """El motor ya dio por cumplido el certificado de esta persona en este
    requisito (lo trajo la oferta o ya se aportó uno que sirve)."""
    resultado = Resultado.objects.filter(evaluacion=evaluacion, proponente=proponente, requisito=requisito).first()
    if resultado is None:
        return False
    clave = servicios.clave_persona(persona.nombre, persona.documento, persona.tipo)
    return any(
        servicios.clave_persona(x["nombre"], x.get("documento"), x.get("tipo")) == clave and x.get("estado") == "cumple"
        for x in (resultado.datos.get("personas_antecedente") or [])
    )


# Cuánto se deja descansar una página oficial que falló antes de volver a
# consultarla.
PAUSA_TRAS_FALLA = 5 * 60


def _pausar_pagina(fuente: str) -> None:
    from django.core.cache import cache

    cache.set(f"consulta_en_pausa_{fuente}", timezone.now().timestamp() + PAUSA_TRAS_FALLA, PAUSA_TRAS_FALLA)


def _pagina_en_pausa(fuente: str) -> str | None:
    """Mensaje si la página falló hace poco (y por eso no se la consulta)."""
    from django.core.cache import cache

    hasta = cache.get(f"consulta_en_pausa_{fuente}")
    if not hasta:
        return None
    minutos = max(1, round((hasta - timezone.now().timestamp()) / 60))
    donde = "la Policía (RNMC)" if fuente == "rnmc" else "el COPNIA"
    return (
        f"La página de {donde} falló hace un momento. Para no insistirle a una plataforma que no está respondiendo, "
        f"el programa espera unos {minutos} min antes de volver a consultarla. Mientras tanto puede subir el "
        "certificado a mano."
    )


def _reevaluar(evaluacion, proponente, usuario) -> None:
    """Pone al proponente en la fila para que el motor lea el certificado que
    se acaba de adjuntar: así el requisito deja de estar pendiente solo, sin
    que nadie tenga que decidirlo a mano."""
    if evaluacion.estado in (EstadoEvaluacion.APROBADA,):
        return
    try:
        servicios.encolar(evaluacion, [proponente.id], usuario)
    except Exception:  # noqa: BLE001
        log.exception("No se pudo volver a evaluar %s tras adjuntar un certificado", proponente.hoja)


def _fecha_de_expedicion(persona: PersonaVerificada, proponente, indicada: date | None = None) -> date:
    """La fecha de expedición de la cédula, que el RNMC pide: la que escribió
    el evaluador, la registrada, o la que dice el reverso de la cédula que el
    proponente aportó. Si no hay ninguna, explica por qué y la pide."""
    # Ojo: aquí no se guarda nada. La fecha solo se guarda cuando la página
    # oficial la acepta; si se guardara antes, una fecha equivocada quedaría
    # pegada a la persona y todas las consultas siguientes fallarían.
    if indicada is not None:
        if indicada > date.today():
            raise HttpError(400, "La fecha de expedición de la cédula no puede ser futura.")
        return indicada
    if persona.fecha_expedicion_documento:
        return persona.fecha_expedicion_documento
    from motor.evaluacion.identidad import cedula_de, leer_fecha_expedicion
    from motor.integrations.drive import download_file_bytes
    from motor.procesamiento.zip_utils import extraer_pdfs

    porque = "no se encontró la copia de su cédula en la oferta"
    sugerencia = ""
    try:
        pdfs = extraer_pdfs(download_file_bytes(proponente.drive_file_id))
        lectura = leer_fecha_expedicion(pdfs, persona.nombre, persona.documento)
        if lectura.fecha is not None and not lectura.confiable:
            # Con una fecha dudosa no se consulta: la página la rechazaría y
            # se gastaría una consulta a una plataforma del Estado para nada.
            porque = "su cédula no se deja leer con claridad"
            sugerencia = f" Parece decir {lectura.fecha.strftime('%d/%m/%Y')}, pero no es seguro."
        elif lectura.fecha is None and cedula_de(pdfs, persona.nombre, persona.documento) is not None:
            porque = "su cédula está en la oferta, pero ni el lector de texto ni la IA pudieron leer la fecha"
    except Exception:  # noqa: BLE001
        log.exception("No se pudo leer la cédula de %s para sacar su fecha de expedición", persona.nombre)
        lectura, porque = None, "no se pudieron abrir los documentos de la oferta"
    if lectura is None or not lectura.confiable:
        raise HttpError(
            400,
            f"La página de la Policía pide la fecha de expedición de la cédula de {persona.nombre} y {porque}."
            f"{sugerencia} Escríbela aquí (está en el reverso del documento) y se consulta de una vez.",
        )
    return lectura.fecha


@router.post("/{evaluacion_id}/proponentes/{proponente_id}/consultar", response={201: AportadoOut})
def consultar_en_linea(request: HttpRequest, evaluacion_id: UUID, proponente_id: UUID, datos: ConsultaIn):
    """Consulta el certificado en la página oficial y lo adjunta al expediente,
    igual que si el evaluador lo hubiera descargado y subido."""
    from motor.consultas.linea import (
        ConsultaError,
        FechaRechazada,
        PaginaNoDisponible,
        consultar_copnia,
        consultar_rnmc,
    )

    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    proponente = _proponente(evaluacion, proponente_id)
    requisito = next((r for r in servicios.definicion_de(evaluacion).requisitos if r.numero == datos.requisito), None)
    if requisito is None:
        raise HttpError(400, "Ese requisito no existe en la plantilla de la evaluación.")
    fuente = FUENTES_EN_LINEA.get(requisito.verificacion)
    if fuente is None:
        raise HttpError(400, "Este certificado no se puede consultar en línea: su página pide captcha.")
    persona = get_object_or_404(PersonaVerificada, pk=datos.persona_id, evaluacion=evaluacion, proponente=proponente) if datos.persona_id else None
    if persona is None and not (fuente == "copnia" and datos.matricula):
        raise HttpError(400, "Indique de quién es el certificado.")

    # Nada de consultas que no hacen falta:
    # 1) ya se consultó hoy a esta persona para este requisito → se devuelve eso;
    ya_consultado = _consultado_hoy(evaluacion, proponente, datos.requisito, persona, datos.matricula)
    if ya_consultado is not None:
        return 201, _aportado_out(ya_consultado)
    # 2) ya tiene un certificado que sirve (en la oferta o aportado) → no se consulta.
    if persona is not None and _ya_cumple(evaluacion, proponente, datos.requisito, persona):
        raise HttpError(
            409,
            f"{persona.nombre} ya tiene un certificado válido para este requisito; no hace falta consultar la página oficial.",
        )
    # 3) la página falló hace un momento → no se le insiste.
    enfriando = _pagina_en_pausa(fuente)
    if enfriando:
        raise HttpError(503, enfriando)

    fecha_usada = None
    # En un proceso de demostración las personas son inventadas: nada de
    # consultarlas en las páginas oficiales.
    if evaluacion.proceso.codigo.upper().startswith("DEMO-"):
        from motor.consultas.linea import simular

        certificado = simular(fuente, persona.nombre if persona else None, persona.documento if persona else None, datos.matricula)
        return _guardar_consultado(request, evaluacion, proponente, datos, persona, fuente, certificado, None, usuario)
    try:
        if fuente == "rnmc":
            es_empresa = persona.tipo == "juridica"
            fecha_usada = None if es_empresa else _fecha_de_expedicion(persona, proponente, datos.fecha_expedicion_documento)
            certificado = consultar_rnmc(
                persona.documento,
                tipo="nit" if es_empresa else "cedula",
                fecha_expedicion=fecha_usada,
            )
        elif datos.matricula:
            certificado = consultar_copnia(datos.matricula.strip(), por="matricula")
        elif persona.tipo == "juridica":
            raise HttpError(400, "El COPNIA certifica personas naturales, no empresas.")
        else:
            certificado = consultar_copnia(persona.documento, por="cedula")
    except FechaRechazada as exc:
        # Solo cuando la página dice explícitamente que la fecha no es la de
        # esa cédula se descarta la guardada, para volver a pedirla.
        PersonaVerificada.objects.filter(pk=persona.pk).update(fecha_expedicion_documento=None)
        raise HttpError(400, str(exc)) from exc
    except PaginaNoDisponible as exc:
        # Falla de la página, no de los datos: nada se borra y se pausan las
        # consultas a esa página un rato.
        _pausar_pagina(fuente)
        raise HttpError(503, str(exc)) from exc
    except ConsultaError as exc:
        # Algo que la persona puede resolver (falta un dato, no existe el registro).
        raise HttpError(400, str(exc)) from exc
    except HttpError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("Falló la consulta en línea de %s", fuente)
        _pausar_pagina(fuente)
        donde = "la Policía (RNMC)" if fuente == "rnmc" else "el COPNIA"
        raise HttpError(
            502,
            f"La página de {donde} no respondió o cambió de forma ({type(exc).__name__}). "
            "Vuelva a intentarlo en unos minutos; si sigue igual, consúltelo usted y súbalo con el botón «Subir».",
        ) from exc

    return _guardar_consultado(request, evaluacion, proponente, datos, persona, fuente, certificado, fecha_usada, usuario)


def _guardar_consultado(request, evaluacion, proponente, datos, persona, fuente, certificado, fecha_usada, usuario):
    """Guarda el certificado consultado (o simulado, en una demostración) como
    documento aportado y vuelve a evaluar al proponente."""
    # Si la página no dice claramente que la persona está sin novedades, el
    # certificado igual se guarda: lo revisa el evaluador, nunca se aprueba solo.
    # Si la página no dijo nada concluyente, no se adjunta un PDF que no
    # prueba nada: se explica y el evaluador decide.
    if certificado.sin_novedades is None:
        raise HttpError(
            502,
            f"La página respondió algo que no se pudo interpretar para {persona.nombre if persona else datos.matricula}. "
            "Revísela usted y suba el certificado con el botón «Subir».",
        )
    de_quien = f" a nombre de {certificado.nombre}" if certificado.nombre else ""
    nota = f"Consultado en línea por MiEvaluador en la página oficial ({'RNMC' if fuente == 'rnmc' else 'COPNIA'}){de_quien}."
    if evaluacion.proceso.codigo.upper().startswith("DEMO-"):
        nota = f"Consulta simulada de la demostración ({'RNMC' if fuente == 'rnmc' else 'COPNIA'}){de_quien}: sin validez."
    if certificado.sin_novedades is True:
        nota += (
            " La matrícula está vigente y sin antecedentes disciplinarios."
            if fuente == "copnia"
            else " No tiene medidas correctivas pendientes por cumplir."
        )
    else:
        nota += " La página no confirmó que esté libre de novedades: revíselo."
    # La página aceptó estos datos: ahora sí vale la pena guardar la fecha.
    if fecha_usada is not None and persona.fecha_expedicion_documento != fecha_usada:
        persona.fecha_expedicion_documento = fecha_usada
        persona.save(update_fields=["fecha_expedicion_documento"])
    with transaction.atomic():
        doc = DocumentoAportado(
            entidad_id=evaluacion.entidad_id,
            evaluacion=evaluacion,
            proponente=proponente,
            persona=persona,
            requisito=datos.requisito,
            fecha_expedicion=certificado.fecha_expedicion,
            nombre_original=certificado.nombre_archivo[:255],
            observacion=nota,
            subido_por=usuario,
        )
        doc.archivo.save(certificado.nombre_archivo, ContentFile(certificado.pdf), save=False)
        doc.save()
        auditar(
            request,
            "antecedente.consultado",
            objeto=evaluacion,
            hoja=proponente.hoja,
            requisito=datos.requisito,
            persona=persona.nombre if persona else datos.matricula,
            fuente=fuente,
            sin_novedades=certificado.sin_novedades,
        )
    _reevaluar(evaluacion, proponente, usuario)
    return 201, _aportado_out(doc)

@router.get("/{evaluacion_id}/pliego")
def ver_pliego(request: HttpRequest, evaluacion_id: UUID) -> FileResponse:
    """El pliego con el que se creó el proceso (se conserva, como el expediente)."""
    evaluacion = _evaluacion(request.auth, evaluacion_id)
    analisis = evaluacion.proceso.analisis_pliego
    if analisis is None:
        raise HttpError(404, "Este proceso se creó sin analizar el pliego.")
    return FileResponse(analisis.archivo.open("rb"), content_type="application/pdf", filename=analisis.nombre_archivo)


@router.get("/{evaluacion_id}/aportados/{documento_id}/archivo")
def ver_aportado(request: HttpRequest, evaluacion_id: UUID, documento_id: UUID) -> FileResponse:
    evaluacion = _evaluacion(request.auth, evaluacion_id)
    doc = get_object_or_404(DocumentoAportado, pk=documento_id, evaluacion=evaluacion)
    return FileResponse(doc.archivo.open("rb"), content_type="application/pdf", filename=doc.nombre_original)


@router.delete("/{evaluacion_id}/aportados/{documento_id}", response={204: None})
def quitar_aportado(request: HttpRequest, evaluacion_id: UUID, documento_id: UUID):
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_trabajo(usuario, evaluacion)
    doc = get_object_or_404(DocumentoAportado, pk=documento_id, evaluacion=evaluacion)
    auditar(request, "antecedente.quitado", objeto=evaluacion, requisito=doc.requisito, archivo=doc.nombre_original)
    doc.archivo.delete(save=False)
    doc.delete()
    return 204, None


@router.get("/{evaluacion_id}/reporte")
def reporte_word(request: HttpRequest, evaluacion_id: UUID) -> HttpResponse:
    evaluacion = _evaluacion(request.auth, evaluacion_id)
    contenido, nombre = generar_reporte(evaluacion)
    auditar(request, "reporte.descargado", objeto=evaluacion, borrador=evaluacion.estado != EstadoEvaluacion.APROBADA)
    respuesta = HttpResponse(contenido, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


def _expediente_out(e: Expediente) -> ExpedienteOut:
    return ExpedienteOut(
        id=e.id,
        version=e.version,
        estado=e.estado,
        tamano=e.tamano,
        sha256=e.sha256,
        avisos=e.error,
        creado_en=e.creado_en,
        terminado_en=e.terminado_en,
    )


@router.get("/{evaluacion_id}/expedientes", response=list[ExpedienteOut])
def expedientes(request: HttpRequest, evaluacion_id: UUID) -> list[ExpedienteOut]:
    evaluacion = _evaluacion(request.auth, evaluacion_id)
    return [_expediente_out(e) for e in evaluacion.expedientes.all()]


@router.post("/{evaluacion_id}/expedientes", response={201: ExpedienteOut})
def regenerar_expediente(request: HttpRequest, evaluacion_id: UUID):
    usuario: Usuario = request.auth
    evaluacion = _evaluacion(usuario, evaluacion_id)
    exigir_gestion(usuario, evaluacion)
    if evaluacion.estado != EstadoEvaluacion.APROBADA:
        raise HttpError(409, "El expediente se genera cuando la evaluación está aprobada.")
    if evaluacion.expedientes.filter(estado__in=[EstadoExpediente.PENDIENTE, EstadoExpediente.GENERANDO]).exists():
        raise HttpError(409, "Ya se está generando un expediente.")
    nuevo = expediente.solicitar(evaluacion, usuario)
    auditar(request, "expediente.solicitado", objeto=evaluacion, version=nuevo.version)
    return 201, _expediente_out(nuevo)


@router.get("/{evaluacion_id}/expedientes/{expediente_id}/archivo")
def descargar_expediente(request: HttpRequest, evaluacion_id: UUID, expediente_id: UUID) -> FileResponse:
    evaluacion = _evaluacion(request.auth, evaluacion_id)
    exp = get_object_or_404(Expediente, pk=expediente_id, evaluacion=evaluacion, estado=EstadoExpediente.LISTO)
    auditar(request, "expediente.descargado", objeto=evaluacion, version=exp.version)
    nombre = f"EXPEDIENTE {evaluacion.proceso.codigo} {evaluacion.tipo.upper()} v{exp.version}.zip"
    return FileResponse(exp.archivo.open("rb"), as_attachment=True, filename=nombre, content_type="application/zip")

