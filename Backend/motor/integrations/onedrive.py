"""Carpetas de ofertas compartidas por OneDrive (cuentas personales) con un
enlace público ("Cualquier persona con el vínculo").

No hace falta cuenta ni credenciales: se usa el mismo acceso anónimo que la
página web de OneDrive. Se pide un token anónimo, se "redime" el enlace con
ese token (desde ahí el token puede leer la carpeta compartida) y con él se
listan las subcarpetas y se descargan los archivos. El token dura unos días;
se guarda por enlace y se renueva si OneDrive lo rechaza.

Los archivos se identifican como "onedrive!<id del elemento>" para que el
resto del programa (caché de descargas, caché de resultados) los trate igual
que los de Google Drive. La huella de contenido es el quickXorHash de OneDrive.
"""
from __future__ import annotations

import base64
import json
import threading
from pathlib import Path

import requests

PREFIJO_ID = "onedrive!"
_API = "https://my.microsoftpersonalcontent.com/_api/v2.0"
_TOKEN_URL = "https://api-badgerp.svc.ms/v1.0/token"
# Identificador público de la aplicación web de OneDrive para el acceso anónimo.
_APP_ID = "5cbed6ac-a083-4e14-b191-b4ba07653de2"
_TIMEOUT = 60
_DESCARGA_TIMEOUT = 600

_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "drive_listados"
_ENLACES = _DIR / "onedrive_elementos.json"  # id de archivo -> enlace compartido
_lock = threading.Lock()
_TOKENS: dict[str, str] = {}  # enlace -> token ya redimido (en este proceso)


class OneDriveError(RuntimeError):
    pass


def es_enlace(url: str) -> bool:
    url = url.strip().lower()
    return any(d in url for d in ("1drv.ms/", "onedrive.live.com/", "my.microsoftpersonalcontent.com/"))


def es_id(file_id: str) -> bool:
    return file_id.startswith(PREFIJO_ID)


def _token_de_enlace(enlace: str) -> str:
    codificado = base64.urlsafe_b64encode(enlace.strip().encode()).decode().rstrip("=")
    return f"u!{codificado}"


def _token_anonimo() -> str:
    r = requests.post(_TOKEN_URL, json={"appId": _APP_ID}, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()["token"]


def _redimir(enlace: str, forzar: bool = False) -> tuple[str, dict]:
    """(token, elemento raíz con sus hijos). El token queda autorizado para
    leer lo compartido por el enlace."""
    with _lock:
        token = None if forzar else _TOKENS.get(enlace)
    token = token or _token_anonimo()
    r = requests.get(
        f"{_API}/shares/{_token_de_enlace(enlace)}/driveitem",
        params={"$expand": "children"},
        headers={"Authorization": f"Badger {token}", "Prefer": "autoredeem"},
        timeout=_TIMEOUT,
    )
    if r.status_code in (401, 403) and not forzar:
        return _redimir(enlace, forzar=True)
    if r.status_code == 404:
        raise OneDriveError("No se encontró la carpeta de OneDrive: revise el enlace.")
    if r.status_code in (401, 403):
        raise OneDriveError(
            "OneDrive no permite leer la carpeta: compártala con «Cualquier persona con el vínculo»."
        )
    r.raise_for_status()
    with _lock:
        _TOKENS[enlace] = token
    return token, r.json()


def _get(url: str, token: str, **kwargs) -> requests.Response:
    r = requests.get(url, headers={"Authorization": f"Badger {token}"}, timeout=_TIMEOUT, **kwargs)
    r.raise_for_status()
    return r


def _hijos(elemento: dict, token: str) -> list[dict]:
    """Todos los hijos de una carpeta (el listado viene por páginas)."""
    hijos = list(elemento.get("children") or [])
    siguiente = elemento.get("children@odata.nextLink")
    if "children" not in elemento:
        drive = elemento["parentReference"]["driveId"] if elemento.get("parentReference") else elemento["id"].split("!")[0]
        respuesta = _get(f"{_API}/drives/{drive}/items/{elemento['id']}/children", token).json()
        hijos, siguiente = respuesta.get("value", []), respuesta.get("@odata.nextLink")
    while siguiente:
        respuesta = _get(siguiente, token).json()
        hijos.extend(respuesta.get("value", []))
        siguiente = respuesta.get("@odata.nextLink")
    return hijos


def _guardar_enlaces(nuevos: dict[str, str]) -> None:
    with _lock:
        try:
            actuales = json.loads(_ENLACES.read_text()) if _ENLACES.exists() else {}
        except (OSError, json.JSONDecodeError):
            actuales = {}
        actuales.update(nuevos)
        _DIR.mkdir(parents=True, exist_ok=True)
        _ENLACES.write_text(json.dumps(actuales))


def _enlace_de(file_id: str) -> str:
    try:
        enlace = json.loads(_ENLACES.read_text()).get(file_id)
    except (OSError, json.JSONDecodeError):
        enlace = None
    if not enlace:
        raise OneDriveError("No se sabe de qué carpeta de OneDrive es este archivo: vuelva a cargar la carpeta.")
    return enlace


def listar(enlace: str, max_profundidad: int) -> list[dict]:
    """Archivos de la carpeta compartida (y sus subcarpetas), con el mismo
    formato que el listado de Google Drive: id, name, profundidad, carpeta,
    más md5Checksum (la huella de OneDrive) y size."""
    token, raiz = _redimir(enlace)
    archivos: list[dict] = []

    def recorrer(elemento: dict, profundidad: int, ruta: str) -> None:
        if profundidad > max_profundidad:
            return
        for hijo in _hijos(elemento, token):
            if "folder" in hijo:
                recorrer(hijo, profundidad + 1, f"{ruta}/{hijo['name']}" if ruta else hijo["name"])
            else:
                archivos.append({
                    "id": PREFIJO_ID + hijo["id"],
                    "name": hijo["name"],
                    "profundidad": profundidad,
                    "carpeta": ruta,
                    **_metadatos(hijo),
                })

    recorrer(raiz, 0, "")
    _guardar_enlaces({a["id"]: enlace for a in archivos})
    return archivos


def _metadatos(item: dict) -> dict:
    hashes = (item.get("file") or {}).get("hashes") or {}
    huella = hashes.get("quickXorHash") or hashes.get("sha256Hash") or hashes.get("sha1Hash")
    if not huella:  # sin huella de contenido: la fecha de modificación y el tamaño
        huella = f"{item.get('lastModifiedDateTime')}:{item.get('size')}"
    return {"md5Checksum": huella, "size": str(item.get("size", "")), "name": item.get("name", "")}


def _con_token(file_id: str, accion):
    """Ejecuta accion(token, drive, item) redimiendo el enlace del archivo;
    si el token caducó, se renueva una vez."""
    enlace = _enlace_de(file_id)
    item = file_id[len(PREFIJO_ID):]
    drive = item.split("!")[0]
    token, _ = _redimir(enlace)
    try:
        return accion(token, drive, item)
    except requests.HTTPError as exc:
        if exc.response is None or exc.response.status_code not in (401, 403):
            raise
    token, _ = _redimir(enlace, forzar=True)
    return accion(token, drive, item)


def metadatos(file_id: str) -> dict:
    return _con_token(file_id, lambda token, drive, item: _metadatos(_get(f"{_API}/drives/{drive}/items/{item}", token).json()))


def descargar(file_id: str) -> bytes:
    def bajar(token: str, drive: str, item: str) -> bytes:
        r = requests.get(
            f"{_API}/drives/{drive}/items/{item}/content",
            headers={"Authorization": f"Badger {token}"},
            timeout=_DESCARGA_TIMEOUT,
        )
        r.raise_for_status()
        return r.content

    return _con_token(file_id, bajar)
