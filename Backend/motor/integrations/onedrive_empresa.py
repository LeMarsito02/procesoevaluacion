"""Carpetas de ofertas en el OneDrive o el SharePoint de la entidad (Microsoft 365).

Se sigue trabajando con el enlace: la persona pega el enlace de la carpeta,
como con Google Drive o con un OneDrive personal. La diferencia es que en
Microsoft 365 el enlace no es público, así que MiEvaluador lo lee con Microsoft
Graph y un permiso de la propia aplicación (solo lectura de archivos,
Files.Read.All), que el administrador de Microsoft de la entidad aprueba una
sola vez para su directorio.

Seguridad: el directorio del enlace se averigua a partir de su dirección
(contoso-my.sharepoint.com → contoso) y tiene que ser el de la entidad que crea
el proceso. Una entidad no puede leer, con el permiso que aprobó otra, un
enlace del directorio de esa otra.

Los archivos se identifican como "sharepoint!<directorio>!<drive>!<elemento>",
para que el resto del programa (caché de descargas y de resultados) los trate
igual que los de Google Drive. La huella de contenido es el quickXorHash.
"""
from __future__ import annotations

import base64
import os
import re
import threading
import time
from urllib.parse import urlparse

import requests

PREFIJO_ID = "sharepoint!"
GRAPH = "https://graph.microsoft.com/v1.0"
AUTORIDAD = "https://login.microsoftonline.com"
ALCANCE = "https://graph.microsoft.com/.default"
# Permisos de aplicación que alcanzan para leer las carpetas compartidas.
PERMISOS_SUFICIENTES = ("Files.Read.All", "Sites.Read.All", "Files.ReadWrite.All", "Sites.ReadWrite.All")
_TIMEOUT = 60
_DESCARGA_TIMEOUT = 600

_lock = threading.Lock()
_TOKENS: dict[str, tuple[str, float]] = {}  # directorio -> (token, vence)
_DIRECTORIOS: dict[str, str] = {}  # nombre del inquilino -> directorio

SIN_AUTORIZACION = (
    "La entidad aún no autoriza a MiEvaluador a leer su OneDrive. Su administrador de Microsoft 365 debe aprobarlo "
    "una vez (Entidades → Microsoft → «Autorizar OneDrive»)."
)


class OneDriveEmpresaError(RuntimeError):
    pass


def es_enlace(url: str) -> bool:
    host = (urlparse(url.strip()).hostname or "").lower()
    return host.endswith(".sharepoint.com")


def es_id(file_id: str) -> bool:
    return file_id.startswith(PREFIJO_ID)


def _credenciales() -> tuple[str, str]:
    cliente, secreto = os.environ.get("MICROSOFT_CLIENT_ID", ""), os.environ.get("MICROSOFT_CLIENT_SECRET", "")
    if not (cliente and secreto):
        raise OneDriveEmpresaError("MiEvaluador no tiene configurada su aplicación de Microsoft (MICROSOFT_CLIENT_ID).")
    return cliente, secreto


def inquilino_de(url: str) -> str:
    """contoso-my.sharepoint.com y contoso.sharepoint.com → contoso."""
    host = (urlparse(url.strip()).hostname or "").lower()
    nombre = host.removesuffix(".sharepoint.com").removesuffix("-my")
    if not nombre or "." in nombre:
        raise OneDriveEmpresaError("El enlace no parece de OneDrive o SharePoint de Microsoft 365.")
    return nombre


def directorio_de(url: str) -> str:
    """El identificador del directorio (tenant) al que pertenece el enlace."""
    nombre = inquilino_de(url)
    with _lock:
        if nombre in _DIRECTORIOS:
            return _DIRECTORIOS[nombre]
    try:
        r = requests.get(f"{AUTORIDAD}/{nombre}.onmicrosoft.com/v2.0/.well-known/openid-configuration", timeout=_TIMEOUT)
        emisor = r.json().get("issuer", "") if r.ok else ""
    except (requests.RequestException, ValueError) as exc:
        raise OneDriveEmpresaError("No se pudo consultar a Microsoft el directorio del enlace.") from exc
    m = re.search(r"/([0-9a-f-]{36})/", emisor)
    if not m:
        raise OneDriveEmpresaError("No se encontró en Microsoft el directorio de ese enlace.")
    with _lock:
        _DIRECTORIOS[nombre] = m.group(1)
    return m.group(1)


def token(directorio: str, forzar: bool = False) -> str:
    """Token de la aplicación para el directorio de la entidad (flujo de
    credenciales de cliente). Falla si su administrador no lo ha aprobado."""
    with _lock:
        guardado = _TOKENS.get(directorio)
    if guardado and not forzar and guardado[1] > time.time() + 60:
        return guardado[0]
    cliente, secreto = _credenciales()
    try:
        r = requests.post(
            f"{AUTORIDAD}/{directorio}/oauth2/v2.0/token",
            data={"client_id": cliente, "client_secret": secreto, "grant_type": "client_credentials", "scope": ALCANCE},
            timeout=_TIMEOUT,
        )
        datos = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise OneDriveEmpresaError("No se pudo contactar a Microsoft.") from exc
    if not r.ok or "access_token" not in datos:
        # AADSTS65001 / 7000229 / 700016: la aplicación no está aprobada en ese directorio.
        raise OneDriveEmpresaError(SIN_AUTORIZACION)
    with _lock:
        _TOKENS[directorio] = (datos["access_token"], time.time() + int(datos.get("expires_in", 3600)))
    return datos["access_token"]


def permisos(directorio: str) -> list[str]:
    """Los permisos de aplicación que la entidad aprobó (los dice el propio token)."""
    import jwt

    try:
        datos = jwt.decode(token(directorio, forzar=True), options={"verify_signature": False})
    except jwt.PyJWTError:
        return []
    return list(datos.get("roles") or [])


def url_autorizacion(directorio: str, redirect_uri: str, estado: str = "") -> str:
    """Página de Microsoft en la que el administrador de la entidad aprueba el
    permiso de lectura de archivos para su directorio."""
    from urllib.parse import urlencode

    cliente, _ = _credenciales()
    consulta = {"client_id": cliente, "scope": ALCANCE, "redirect_uri": redirect_uri}
    if estado:
        consulta["state"] = estado
    return f"{AUTORIDAD}/{directorio}/v2.0/adminconsent?{urlencode(consulta)}"


def _get(url: str, directorio: str, **kwargs) -> requests.Response:
    r = requests.get(url, headers={"Authorization": f"Bearer {token(directorio)}"}, timeout=kwargs.pop("timeout", _TIMEOUT), **kwargs)
    if r.status_code == 401:
        r = requests.get(url, headers={"Authorization": f"Bearer {token(directorio, forzar=True)}"}, timeout=_TIMEOUT, **kwargs)
    if r.status_code in (401, 403):
        raise OneDriveEmpresaError(SIN_AUTORIZACION)
    if r.status_code == 404:
        raise OneDriveEmpresaError("No se encontró la carpeta de OneDrive: revise el enlace.")
    r.raise_for_status()
    return r


def _id_compartido(enlace: str) -> str:
    return "u!" + base64.urlsafe_b64encode(enlace.strip().encode()).decode().rstrip("=")


def comprobar_directorio(enlace: str, directorio_entidad: str | None) -> str:
    """El directorio del enlace, si es el de la entidad; si no, un error claro."""
    if not directorio_entidad:
        raise OneDriveEmpresaError(
            "Para leer enlaces de OneDrive de Microsoft 365, la entidad debe tener registrado su directorio de Microsoft "
            "(Entidades → Microsoft)."
        )
    directorio = directorio_de(enlace)
    if directorio.lower() != directorio_entidad.lower():
        raise OneDriveEmpresaError("El enlace es de un OneDrive de otra organización: solo se leen los del directorio de la entidad.")
    return directorio


def _metadatos(item: dict) -> dict:
    hashes = (item.get("file") or {}).get("hashes") or {}
    huella = hashes.get("quickXorHash") or hashes.get("sha256Hash") or hashes.get("sha1Hash")
    if not huella:
        huella = f"{item.get('lastModifiedDateTime')}:{item.get('size')}"
    return {"md5Checksum": huella, "size": str(item.get("size", "")), "name": item.get("name", "")}


def listar(enlace: str, directorio_entidad: str | None, max_profundidad: int) -> list[dict]:
    """Archivos de la carpeta compartida y sus subcarpetas, con el mismo formato
    que el listado de Google Drive."""
    directorio = comprobar_directorio(enlace, directorio_entidad)
    raiz = _get(f"{GRAPH}/shares/{_id_compartido(enlace)}/driveItem", directorio).json()
    if "folder" not in raiz:
        raise OneDriveEmpresaError("El enlace es de un archivo, no de una carpeta: comparta la carpeta de las ofertas.")
    archivos: list[dict] = []

    def hijos(drive: str, item: str) -> list[dict]:
        salida, siguiente = [], f"{GRAPH}/drives/{drive}/items/{item}/children?$top=200"
        while siguiente:
            pagina = _get(siguiente, directorio).json()
            salida += pagina.get("value", [])
            siguiente = pagina.get("@odata.nextLink")
        return salida

    def recorrer(drive: str, item: str, profundidad: int, ruta: str) -> None:
        if profundidad > max_profundidad:
            return
        for hijo in hijos(drive, item):
            if "folder" in hijo:
                recorrer(drive, hijo["id"], profundidad + 1, f"{ruta}/{hijo['name']}" if ruta else hijo["name"])
            elif "file" in hijo:
                archivos.append({
                    "id": f"{PREFIJO_ID}{directorio}!{drive}!{hijo['id']}",
                    "name": hijo["name"], "profundidad": profundidad, "carpeta": ruta, **_metadatos(hijo),
                })

    recorrer(raiz["parentReference"]["driveId"], raiz["id"], 0, "")
    return archivos


def partes(file_id: str) -> tuple[str, str, str]:
    """(directorio, drive, elemento). El identificador del drive puede llevar «!»."""
    directorio, resto = file_id[len(PREFIJO_ID):].split("!", 1)
    drive, item = resto.rsplit("!", 1)
    return directorio, drive, item


def metadatos(file_id: str) -> dict:
    directorio, drive, item = partes(file_id)
    return _metadatos(_get(f"{GRAPH}/drives/{drive}/items/{item}", directorio).json())


def descargar(file_id: str) -> bytes:
    directorio, drive, item = partes(file_id)
    # Graph responde con una redirección a una dirección de descarga ya firmada.
    return _get(f"{GRAPH}/drives/{drive}/items/{item}/content", directorio, timeout=_DESCARGA_TIMEOUT).content
