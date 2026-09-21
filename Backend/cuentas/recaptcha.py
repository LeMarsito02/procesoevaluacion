"""Verificación de reCAPTCHA Enterprise en los formularios públicos.

El navegador pide a Google un token para la acción (``LOGIN``,
``RECUPERAR_CLAVE``) y lo manda con el formulario; aquí se crea una
evaluación ("assessment") con ese token y se exige que sea válido, de la misma
acción y con un puntaje de riesgo aceptable. El token vence a los dos minutos.

Sin ``RECAPTCHA_PROJECT_ID`` y ``RECAPTCHA_API_KEY`` no se verifica (entorno de
desarrollo) y queda un aviso en el registro. Si Google no responde se deja
pasar, salvo con ``RECAPTCHA_ESTRICTO=1``: el inicio de sesión ya tiene su
propio bloqueo por intentos fallidos.
"""
from __future__ import annotations

import logging
import os
import re

import requests
from django.http import HttpRequest
from ninja.errors import HttpError

from cuentas.seguridad import ip_de

log = logging.getLogger(__name__)

SITE_KEY = os.environ.get("RECAPTCHA_SITE_KEY", "6Lecm8ctAAAAAGBlk3npIJqs-cnWZwIdGg3cO3Pm")
PROJECT_ID = os.environ.get("RECAPTCHA_PROJECT_ID", "")
API_KEY = os.environ.get("RECAPTCHA_API_KEY", "")
PUNTAJE_MINIMO = float(os.environ.get("RECAPTCHA_PUNTAJE_MINIMO", "0.5"))
ESTRICTO = os.environ.get("RECAPTCHA_ESTRICTO", "0") == "1"
TIEMPO_MAXIMO = 5

MENSAJE_SIN_TOKEN = "No se pudo comprobar que eres una persona. Recarga la página e inténtalo de nuevo."
MENSAJE_RECHAZADO = "No se pudo comprobar que eres una persona. Espera un momento e inténtalo de nuevo."


def problema_de_configuracion() -> str | None:
    """Errores típicos al llenar el .env (se confunde la clave del sitio con los
    otros dos datos)."""
    if not (PROJECT_ID and API_KEY and SITE_KEY):
        return None
    if PROJECT_ID == SITE_KEY or not re.fullmatch(r"[a-z][a-z0-9-]{4,29}", PROJECT_ID):
        return "RECAPTCHA_PROJECT_ID no parece un ID de proyecto de Google Cloud (minúsculas, números y guiones)"
    if API_KEY == SITE_KEY or not API_KEY.startswith("AIza"):
        return "RECAPTCHA_API_KEY no parece una clave de API de Google Cloud (empieza por «AIza»)"
    return None


def configurado() -> bool:
    return bool(PROJECT_ID and API_KEY and SITE_KEY) and problema_de_configuracion() is None


def verificar(token: str | None, accion: str, request: HttpRequest) -> None:
    """Lanza HttpError si el token no es de una persona haciendo `accion`."""
    if not configurado():
        problema = problema_de_configuracion()
        if problema:
            log.error("reCAPTCHA mal configurado, no se verifica %s: %s", accion, problema)
        else:
            log.warning("reCAPTCHA sin configurar (RECAPTCHA_PROJECT_ID / RECAPTCHA_API_KEY): no se verifica %s", accion)
        return
    if not token:
        raise HttpError(400, MENSAJE_SIN_TOKEN)
    try:
        respuesta = requests.post(
            f"https://recaptchaenterprise.googleapis.com/v1/projects/{PROJECT_ID}/assessments",
            params={"key": API_KEY},
            json={
                "event": {
                    "token": token,
                    "siteKey": SITE_KEY,
                    "expectedAction": accion,
                    "userAgent": request.META.get("HTTP_USER_AGENT", "")[:500],
                    "userIpAddress": _ip(request),
                }
            },
            timeout=TIEMPO_MAXIMO,
        )
        respuesta.raise_for_status()
        evaluacion = respuesta.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("reCAPTCHA no respondió para %s: %s", accion, exc)
        if ESTRICTO:
            raise HttpError(503, "No se pudo verificar la solicitud. Inténtalo de nuevo en unos minutos.") from exc
        return

    propiedades = evaluacion.get("tokenProperties") or {}
    puntaje = (evaluacion.get("riskAnalysis") or {}).get("score")
    if not propiedades.get("valid"):
        log.info("reCAPTCHA rechazó %s: token inválido (%s)", accion, propiedades.get("invalidReason"))
        raise HttpError(400, MENSAJE_SIN_TOKEN)
    if propiedades.get("action") != accion:
        log.info("reCAPTCHA rechazó %s: el token era de la acción %s", accion, propiedades.get("action"))
        raise HttpError(400, MENSAJE_SIN_TOKEN)
    if puntaje is None or puntaje < PUNTAJE_MINIMO:
        log.info("reCAPTCHA rechazó %s: puntaje %s < %s", accion, puntaje, PUNTAJE_MINIMO)
        raise HttpError(403, MENSAJE_RECHAZADO)
    log.info("reCAPTCHA aceptó %s con puntaje %s", accion, puntaje)


def _ip(request: HttpRequest) -> str:
    return ip_de(request) or ""
