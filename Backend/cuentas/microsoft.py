"""Inicio de sesión con Microsoft (Entra ID), por entidad.

Cada entidad registra el identificador de su directorio de Microsoft. Una
persona entra con Microsoft solo si:
- la respuesta viene firmada por Microsoft para esta aplicación;
- su cuenta es del directorio de la entidad a la que pertenece su usuario de
  MiEvaluador (una cuenta de otro directorio, o personal, no sirve aunque
  tenga el mismo correo);
- ya existe su usuario en MiEvaluador: Microsoft identifica, no crea cuentas
  ni da permisos.

Flujo de código de autorización con PKCE, del lado del servidor: el secreto de
la aplicación nunca llega al navegador. Solo se piden los datos de quien entra
(`openid profile email`), no acceso al directorio de la entidad.
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import jwt
import requests
from django.conf import settings

AUTORIDAD = "https://login.microsoftonline.com"
ALCANCE = "openid profile email"
CLAVES_URL = f"{AUTORIDAD}/common/discovery/v2.0/keys"
TIEMPO_MAXIMO = 15
GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

_claves: jwt.PyJWKClient | None = None


class ErrorMicrosoft(Exception):
    """La respuesta de Microsoft no se pudo obtener o no es válida."""


@dataclass(frozen=True)
class Identidad:
    directorio: str  # identificador del directorio (tenant) que autenticó a la persona
    correos: tuple[str, ...]  # nombre de usuario y correo que informa ese directorio
    nombre: str


def activo() -> bool:
    return bool(settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET)


def directorio_valido(valor: str) -> bool:
    return bool(GUID.match(valor))


def url_retorno() -> str:
    # Pasa por el mismo origen del frontend (proxy de /api): la cookie de sesión
    # que guarda el estado del flujo es la misma al volver de Microsoft.
    return f"{settings.FRONTEND_URL}/api/auth/microsoft/retorno"


def preparar() -> tuple[str, dict[str, str]]:
    """Dirección de Microsoft a la que se envía a la persona y los valores que
    hay que guardar en su sesión para validar el retorno."""
    flujo = {
        "estado": secrets.token_urlsafe(32),
        "nonce": secrets.token_urlsafe(32),
        "verificador": secrets.token_urlsafe(64),
    }
    reto = base64.urlsafe_b64encode(hashlib.sha256(flujo["verificador"].encode()).digest()).rstrip(b"=").decode()
    consulta = urlencode({
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": url_retorno(),
        "response_mode": "query",
        "scope": ALCANCE,
        "state": flujo["estado"],
        "nonce": flujo["nonce"],
        "code_challenge": reto,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    return f"{AUTORIDAD}/{settings.MICROSOFT_DIRECTORIO}/oauth2/v2.0/authorize?{consulta}", flujo


def canjear(codigo: str, verificador: str) -> str:
    """Cambia el código de autorización por el token de identidad."""
    try:
        respuesta = requests.post(
            f"{AUTORIDAD}/{settings.MICROSOFT_DIRECTORIO}/oauth2/v2.0/token",
            data={
                "client_id": settings.MICROSOFT_CLIENT_ID,
                "client_secret": settings.MICROSOFT_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": codigo,
                "redirect_uri": url_retorno(),
                "code_verifier": verificador,
                "scope": ALCANCE,
            },
            timeout=TIEMPO_MAXIMO,
        )
        datos = respuesta.json()
    except (requests.RequestException, ValueError) as exc:
        raise ErrorMicrosoft("No se pudo contactar a Microsoft.") from exc
    token = datos.get("id_token") if respuesta.ok else None
    if not token:
        raise ErrorMicrosoft(f"Microsoft rechazó el código: {datos.get('error', respuesta.status_code)}.")
    return token


def validar(id_token: str, nonce: str) -> Identidad:
    """Comprueba firma, destinatario, vigencia, emisor y nonce del token."""
    global _claves
    if _claves is None:
        _claves = jwt.PyJWKClient(CLAVES_URL, cache_keys=True, timeout=TIEMPO_MAXIMO)
    try:
        clave = _claves.get_signing_key_from_jwt(id_token)
        datos = jwt.decode(
            id_token,
            clave.key,
            algorithms=["RS256"],
            audience=settings.MICROSOFT_CLIENT_ID,
            options={"require": ["exp", "iat", "iss", "aud", "tid"]},
            leeway=60,
        )
    except jwt.PyJWTError as exc:
        raise ErrorMicrosoft("El token de Microsoft no es válido.") from exc
    return identidad_de(datos, nonce)


def identidad_de(datos: dict, nonce: str) -> Identidad:
    directorio = str(datos.get("tid", "")).lower()
    # Las claves son comunes a todos los directorios: el emisor debe ser el del
    # mismo directorio que dice el token.
    if not directorio_valido(directorio) or datos.get("iss") != f"{AUTORIDAD}/{directorio}/v2.0":
        raise ErrorMicrosoft("El emisor del token no corresponde a su directorio.")
    if not nonce or not secrets.compare_digest(str(datos.get("nonce", "")), nonce):
        raise ErrorMicrosoft("El token no corresponde a este inicio de sesión.")
    correos = tuple(dict.fromkeys(
        str(datos[c]).strip().lower() for c in ("preferred_username", "email") if datos.get(c) and "@" in str(datos[c])
    ))
    if not correos:
        raise ErrorMicrosoft("Microsoft no informó el correo de la cuenta.")
    return Identidad(directorio=directorio, correos=correos, nombre=str(datos.get("name", "")))
