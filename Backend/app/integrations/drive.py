from __future__ import annotations

import io
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from app.models.proceso import Proponente

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

DEFAULT_CREDENTIALS_PATH = Path(__file__).resolve().parent.parent.parent / "credentials" / "service_account.json"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "drive_files"

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

# "p1 JJAB SAS", "P-2 SIMO SAS", "p 3 - INGESCOR S.A.S." (extensión ya removida)
PROPONENTE_NAME_RE = re.compile(r"^[Pp]\s*-?\s*(\d+)\s*[-–.]?\s+(.+)$")


class DriveConfigError(RuntimeError):
    """Faltan o son inválidas las credenciales de la cuenta de servicio."""


class DriveAccessError(RuntimeError):
    """La carpeta no existe o no es accesible para la cuenta de servicio."""


def _credentials_path() -> Path:
    return Path(os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", DEFAULT_CREDENTIALS_PATH))


def service_account_email() -> str | None:
    path = _credentials_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data.get("client_email")
    except (json.JSONDecodeError, OSError):
        return None


def get_drive_service():
    path = _credentials_path()
    if not path.exists():
        raise DriveConfigError(
            f"No se encontraron las credenciales de Google Drive en '{path}'. "
            "Crea una cuenta de servicio en Google Cloud, descarga el JSON y colócalo en esa ruta "
            "(o define la variable de entorno GOOGLE_SERVICE_ACCOUNT_FILE)."
        )
    credentials = service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _cache_paths(file_id: str) -> tuple[Path, Path]:
    return CACHE_DIR / f"{file_id}.zip", CACHE_DIR / f"{file_id}.meta.json"


def get_file_metadata(file_id: str) -> dict:
    service = get_drive_service()
    return service.files().get(fileId=file_id, fields="md5Checksum,size,name", supportsAllDrives=True).execute()


def download_file_bytes(file_id: str, metadata: dict | None = None) -> bytes:
    """Descarga un archivo de Drive, cacheándolo en disco por checksum
    (md5Checksum) para no volver a bajarlo si no ha cambiado en Drive."""
    cache_zip, cache_meta = _cache_paths(file_id)

    if metadata is None:
        try:
            metadata = get_file_metadata(file_id)
        except HttpError:
            metadata = None

    md5 = metadata.get("md5Checksum") if metadata else None
    if md5 and cache_zip.exists() and cache_meta.exists():
        try:
            cached = json.loads(cache_meta.read_text())
            if cached.get("md5Checksum") == md5:
                return cache_zip.read_bytes()
        except (json.JSONDecodeError, OSError):
            pass

    service = get_drive_service()
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    data = buffer.getvalue()

    if md5:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_zip.write_bytes(data)
            cache_meta.write_text(json.dumps(metadata))
        except OSError:
            pass

    return data


def extract_folder_id(url_or_id: str) -> str:
    value = url_or_id.strip()

    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", value)
    if match:
        return match.group(1)

    match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", value)
    if match:
        return match.group(1)

    if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", value):
        return value

    raise ValueError(f"No se pudo interpretar '{url_or_id}' como un link o ID de carpeta de Google Drive.")


def _parse_nombre(nombre_archivo: str) -> tuple[int, str] | None:
    base = nombre_archivo
    if base.lower().endswith(".zip"):
        base = base[: -len(".zip")]
    match = PROPONENTE_NAME_RE.match(base.strip())
    if not match:
        return None
    return int(match.group(1)), match.group(2).strip()


@dataclass
class ProponentesResult:
    proponentes: list[Proponente] = field(default_factory=list)
    no_reconocidos: list[str] = field(default_factory=list)


MAX_PROFUNDIDAD_CARPETAS = 4


def _listar_hijos(service, folder_id: str) -> list[dict]:
    archivos: list[dict] = []
    page_token = None
    while True:
        response = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType)",
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        archivos.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return archivos


def _listar_archivos_recursivo(service, folder_id: str, _profundidad: int = 0) -> list[dict]:
    """Lista los archivos de una carpeta de Drive, bajando también a las
    subcarpetas (ej. cuando los zips de los proponentes están dentro de una
    subcarpeta como "Propuestas" en vez de estar sueltos en la raíz)."""
    if _profundidad > MAX_PROFUNDIDAD_CARPETAS:
        return []

    hijos = _listar_hijos(service, folder_id)
    archivos: list[dict] = []
    for hijo in hijos:
        if hijo.get("mimeType") == FOLDER_MIME_TYPE:
            archivos.extend(_listar_archivos_recursivo(service, hijo["id"], _profundidad + 1))
        else:
            archivos.append(hijo)
    return archivos


def list_proponentes(carpeta_drive: str) -> ProponentesResult:
    folder_id = extract_folder_id(carpeta_drive)
    service = get_drive_service()

    try:
        archivos = _listar_archivos_recursivo(service, folder_id)
    except HttpError as exc:
        email = service_account_email()
        pista = f" Verifica que la carpeta esté compartida con {email}." if email else ""
        if exc.resp.status == 404:
            raise DriveAccessError(f"No se encontró la carpeta de Drive.{pista}") from exc
        if exc.resp.status == 403:
            raise DriveAccessError(f"Sin permiso para leer la carpeta de Drive.{pista}") from exc
        raise DriveAccessError(f"Error consultando Google Drive: {exc}") from exc

    result = ProponentesResult()
    for archivo in archivos:
        parsed = _parse_nombre(archivo["name"])
        if parsed is None:
            result.no_reconocidos.append(archivo["name"])
            continue
        numero_orden, nombre_proponente = parsed
        result.proponentes.append(
            Proponente(
                numero_orden=numero_orden,
                hoja=f"P-{numero_orden:02d}",
                nombre_proponente=nombre_proponente,
                nombre_archivo=archivo["name"],
                drive_file_id=archivo["id"],
            )
        )

    result.proponentes.sort(key=lambda p: p.numero_orden)
    return result
