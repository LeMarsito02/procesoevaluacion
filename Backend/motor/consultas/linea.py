"""Certificados que el programa puede consultar en línea por sí mismo.

Hoy la entidad consulta a mano dos certificados que las páginas oficiales
entregan sin ninguna protección contra automatización:

- **RNMC** (Registro Nacional de Medidas Correctivas, Policía Nacional).
- **COPNIA** (certificado de vigencia y antecedentes disciplinarios del
  ingeniero o arquitecto que avala la propuesta).

Los demás (Procuraduría, Contraloría, antecedentes judiciales) piden captcha:
esos los sigue consultando una persona y los sube con el botón de siempre.

Cada consulta abre la página igual que lo haría el abogado, lee lo que dice y
guarda el PDF oficial para el expediente. Nunca decide por su cuenta: si la
página no responde o responde algo que no se entiende, devuelve un error y el
requisito queda para revisión.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date

RNMC_URL = "https://srvcnpc.policia.gov.co/PSC/frm_cnp_consulta.aspx"
COPNIA_URL = "https://tramites.copnia.gov.co/Copnia_Microsite/CertificateOfGoodStanding/CertificateOfGoodStandingStart"

# Códigos del selector "Consultar por" del RNMC.
RNMC_TIPOS = {"cedula": "55", "nit": "1", "cedula_extranjeria": "57", "pasaporte": "58"}

ESPERA = float(os.environ.get("CONSULTA_ESPERA", "90"))  # segundos que se le dan a la página

# Ventana de error del RNMC: "× Error <mensaje> Aceptar".
_AVISO_RNMC_RE = re.compile(r"ERROR\s+(.{10,220}?)\s+ACEPTAR")


class ConsultaError(RuntimeError):
    """La página no respondió o respondió algo que no se puede interpretar."""


class FechaRechazada(ConsultaError):
    """La página dijo explícitamente que la fecha de expedición no corresponde
    a esa cédula. Es el único caso en que la fecha guardada se descarta."""


class PaginaNoDisponible(ConsultaError):
    """La página falló por su cuenta (caída, lenta, error propio): no es culpa
    de los datos de la persona, así que no se toca nada y no se insiste."""


@dataclass
class CertificadoEnLinea:
    """Lo que devolvió la página oficial."""

    fuente: str  # "rnmc" | "copnia"
    texto: str
    pdf: bytes
    nombre_archivo: str
    fecha_expedicion: date
    # True = el certificado dice expresamente que no hay novedades. None = no
    # se pudo afirmar (nunca se aprueba con esto).
    sin_novedades: bool | None
    # Lo que la página dice de la persona, para confirmar que es la correcta.
    nombre: str | None = None
    documento: str | None = None


def _norm(texto: str) -> str:
    return re.sub(r"\s+", " ", texto or "").upper()


def _navegador():
    from playwright.sync_api import sync_playwright

    return sync_playwright()


def consultar_rnmc(numero: str, tipo: str = "cedula", fecha_expedicion: date | None = None) -> CertificadoEnLinea:
    """Medidas correctivas de una persona o empresa. El texto oficial dice
    "NO TIENE MEDIDAS CORRECTIVAS PENDIENTES POR CUMPLIR" y trae un número de
    validación con el que cualquiera puede comprobarlo.

    A una persona la página le pide, además de la cédula, la fecha en que se
    expidió ese documento; a una empresa solo el NIT."""
    codigo = RNMC_TIPOS.get(tipo)
    if not codigo:
        raise ConsultaError(f"Tipo de documento no soportado en el RNMC: {tipo}")
    numero = re.sub(r"\D", "", numero or "")
    if not numero:
        raise ConsultaError("Se necesita el número de documento para consultar el RNMC.")
    if tipo != "nit" and fecha_expedicion is None:
        raise ConsultaError(
            "El RNMC pide la fecha de expedición de la cédula: regístrela en la persona y vuelva a intentarlo."
        )

    with _navegador() as play:
        navegador = play.chromium.launch()
        try:
            pagina = navegador.new_page()
            pagina.goto(RNMC_URL, wait_until="domcontentloaded", timeout=ESPERA * 1000)
            pagina.select_option("#ctl00_ContentPlaceHolder3_ddlTipoDoc", codigo)
            pagina.wait_for_timeout(1500)
            pagina.fill("#ctl00_ContentPlaceHolder3_txtExpediente", numero)
            if fecha_expedicion is not None and pagina.locator("#txtFechaexp").count():
                pagina.fill("#txtFechaexp", fecha_expedicion.strftime("%d/%m/%Y"))
                pagina.click("#ctl00_ContentPlaceHolder3_btnConsultar2")
            else:
                pagina.click("#ctl00_ContentPlaceHolder3_btnConsultar")
            try:
                pagina.wait_for_function(
                    "() => /MEDIDAS CORRECTIVAS PENDIENTES|NO REGISTRA|no se encontr|no existe|no coincide|no corresponde"
                    "|no es correcta|verifique|error/i.test(document.body.innerText)",
                    timeout=ESPERA * 1000,
                )
            except Exception as exc:  # noqa: BLE001
                raise PaginaNoDisponible(
                    f"La página de la Policía (RNMC) no respondió en {int(ESPERA)} segundos. Suele pasar cuando su "
                    "servicio está caído: vuelve a intentarlo más tarde o sube el certificado a mano."
                ) from exc
            texto = pagina.inner_text("body")
            pdf = pagina.pdf(format="Letter", print_background=True)
        finally:
            navegador.close()

    plano = _norm(texto)
    # La página avisa sus propios errores en una ventana: "Error · La fecha de
    # expedición de la Cedula de Ciudadania no es correcta, por favor
    # verifique. · Aceptar". Ese mensaje es el que necesita ver la persona.
    aviso = _AVISO_RNMC_RE.search(plano)
    if aviso and "NO TIENE MEDIDAS CORRECTIVAS PENDIENTES" not in plano:
        mensaje = aviso.group(1).strip()
        if "FECHA DE EXPEDICION" in mensaje or "FECHA DE EXPEDICIÓN" in mensaje:
            raise FechaRechazada(f"La página de la Policía responde: «{mensaje.capitalize()}»")
        # Cualquier otro aviso es un problema de la página, no de los datos.
        raise PaginaNoDisponible(
            f"La página de la Policía respondió con un error propio: «{mensaje.capitalize()}». No es un problema de "
            "los datos de la persona: vuelve a intentarlo en unos minutos o sube el certificado a mano."
        )
    if "NO SE ENCONTR" in plano or "NO EXISTE" in plano:
        raise ConsultaError(
            f"La Policía no encontró el documento {numero} en el RNMC. Verifica el número de identificación de la persona."
        )
    if "NO TIENE MEDIDAS CORRECTIVAS PENDIENTES" in plano:
        sin_novedades: bool | None = True
    elif "NO COINCIDE" in plano or "NO CORRESPONDE" in plano:
        cuando = fecha_expedicion.strftime("%d/%m/%Y") if fecha_expedicion else "—"
        raise FechaRechazada(
            f"La Policía responde que la cédula {numero} y la fecha de expedición {cuando} no corresponden entre sí. "
            "Verifica la fecha en el reverso de la cédula (o el número del documento) y vuelve a intentarlo."
        )
    elif "TIENE MEDIDAS CORRECTIVAS" in plano or "REGISTRA" in plano:
        sin_novedades = False
    else:
        sin_novedades = None
    return CertificadoEnLinea(
        fuente="rnmc",
        texto=texto,
        pdf=pdf,
        nombre_archivo=f"RNMC {numero}.pdf",
        fecha_expedicion=date.today(),
        sin_novedades=sin_novedades,
        documento=numero,
    )


def consultar_copnia(identificacion: str, por: str = "matricula") -> CertificadoEnLinea:
    """Certificado de vigencia y antecedentes disciplinarios del COPNIA, por
    número de matrícula profesional o por cédula. Devuelve el PDF oficial (el
    mismo que descarga una persona), que el motor ya sabe leer."""
    if por not in ("matricula", "cedula"):
        raise ConsultaError(f"Forma de búsqueda no soportada en el COPNIA: {por}")
    identificacion = (identificacion or "").strip()
    if not identificacion:
        raise ConsultaError("Se necesita la matrícula profesional o la cédula para consultar el COPNIA.")

    with _navegador() as play:
        navegador = play.chromium.launch()
        try:
            contexto = navegador.new_context(accept_downloads=True)
            pagina = contexto.new_page()
            pagina.goto(COPNIA_URL, wait_until="networkidle", timeout=ESPERA * 1000)
            pagina.select_option("#ActionCode", label="Generar certificado")
            pagina.wait_for_timeout(600)
            # 1 = número de identificación, 2 = número de matrícula.
            pagina.select_option("#SearchWithCode", index=1 if por == "cedula" else 2)
            pagina.wait_for_timeout(600)
            pagina.fill("#DocumentNumber" if por == "cedula" else "#CertificateNumber", identificacion)
            pagina.click("#btnConsult")
            try:
                pagina.wait_for_selector("text=Generar Certificado de Vigencia", timeout=ESPERA * 1000)
            except Exception as exc:  # noqa: BLE001
                raise ConsultaError(
                    f"El COPNIA no encontró el registro profesional «{identificacion}» "
                    f"(se buscó por {'cédula' if por == 'cedula' else 'número de matrícula'}). "
                    "Verifica el dato o consulta el certificado a mano."
                ) from exc
            with pagina.expect_download(timeout=ESPERA * 1000) as espera:
                pagina.click("text=Generar Certificado de Vigencia")
            descarga = espera.value
            with open(descarga.path(), "rb") as archivo:
                pdf = archivo.read()
        finally:
            navegador.close()

    from motor.procesamiento.pdf_utils import extraer_texto

    texto = extraer_texto(pdf, max_paginas=2)
    plano = _norm(texto)
    vigente = "SE ENCUENTRA VIGENTE" in plano
    sin_antecedentes = "NO TIENE ANTECEDENTES DISCIPLINARIOS" in plano
    # "Que DIANA MARCELA ORTEGA RENGIFO, identificado(a) con CEDULA DE
    # CIUDADANIA 1061732807, se encuentra inscrito(a)…": de quién es de verdad
    # el certificado, para cruzarlo con la persona que se estaba buscando.
    de_quien = re.search(r"QUE\s+([A-ZÑ][A-ZÑ ]{5,80}?),?\s+IDENTIFICAD[OA]\(?A?\)?\s+CON\s+[A-ZÑ ]+?\s*(\d[\d.]{5,})", plano)
    return CertificadoEnLinea(
        fuente="copnia",
        texto=texto,
        pdf=pdf,
        nombre_archivo=f"COPNIA {identificacion}.pdf",
        fecha_expedicion=date.today(),
        sin_novedades=True if (vigente and sin_antecedentes) else (False if plano else None),
        nombre=de_quien.group(1).strip() if de_quien else None,
        documento=re.sub(r"\D", "", de_quien.group(2)) if de_quien else None,
    )
