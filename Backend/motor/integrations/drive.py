from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from motor.esquemas.proceso import Proponente
from motor.integrations import onedrive

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

DEFAULT_CREDENTIALS_PATH = Path(__file__).resolve().parent.parent.parent / "credentials" / "service_account.json"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "drive_files"
CACHE_LISTADOS_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "drive_listados"

# Con DRIVE_SOLO_CACHE=1 no se consulta Drive en absoluto: se usa lo que ya
# está en disco (zips, metadatos y listado de la carpeta). Pensado para
# re-evaluar un proceso cuyos archivos ya no cambian (ej. las pruebas de
# confiabilidad) sin depender de la red. Sin esta variable igual se cae a
# la caché cuando Drive no responde (sin internet, DNS caído).
def _solo_cache() -> bool:
    return os.environ.get("DRIVE_SOLO_CACHE", "0") == "1"

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

# "p1 EMPRESA UNO SAS", "P-2 EMPRESA DOS SAS", "p 3 - EMPRESA TRES S.A.S." (extensión ya removida)
# "P1 Nombre", "P-01 - Nombre" o, como las descarga el SECOP II y las numera
# la entidad, "110. CONSORCIO ASF.zip". Sin la "P" solo se acepta un
# comprimido, para que un PDF como "2026 informe.pdf" no pase por oferta.
PROPONENTE_NAME_RE = re.compile(r"^[Pp]\s*-?\s*(\d+)\s*[-–.]?\s+(.+)$")
PROPONENTE_NUMERADO_RE = re.compile(r"^(\d{1,3})\s*[.)\-–]\s*(.+)$")
EXTENSIONES_OFERTA = (".zip", ".rar", ".7z")


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


def _metadata_en_cache(file_id: str) -> dict | None:
    cache_zip, cache_meta = _cache_paths(file_id)
    if not (cache_zip.exists() and cache_meta.exists()):
        return None
    try:
        return json.loads(cache_meta.read_text())
    except (json.JSONDecodeError, OSError):
        return None


# Memoria corta en el worker: los 18 requisitos de un proponente consultan
# los mismos metadatos y leen el mismo zip; no tiene sentido pedirlos a
# Drive (o leer cientos de MB del disco) 18 veces seguidas.
_METADATA_MEMORIA: dict[str, tuple[float, dict]] = {}
_METADATA_TTL_SEGUNDOS = 600
_ULTIMO_ZIP_LEIDO: tuple[str, str | None, bytes] | None = None


def get_file_metadata(file_id: str) -> dict:
    guardada = _METADATA_MEMORIA.get(file_id)
    if guardada is not None and time.monotonic() - guardada[0] < _METADATA_TTL_SEGUNDOS:
        return guardada[1]
    metadata = _get_file_metadata(file_id)
    _METADATA_MEMORIA[file_id] = (time.monotonic(), metadata)
    return metadata


def _get_file_metadata(file_id: str) -> dict:
    if _solo_cache():
        cacheada = _metadata_en_cache(file_id)
        if cacheada is not None:
            return cacheada
    try:
        if onedrive.es_id(file_id):
            return onedrive.metadatos(file_id)
        service = get_drive_service()
        return service.files().get(fileId=file_id, fields="md5Checksum,size,name", supportsAllDrives=True).execute()
    except Exception:
        cacheada = _metadata_en_cache(file_id)
        if cacheada is not None:
            return cacheada
        raise


def download_file_bytes(file_id: str, metadata: dict | None = None) -> bytes:
    """Descarga un archivo de Drive, cacheándolo en disco por checksum
    (md5Checksum) para no volver a bajarlo si no ha cambiado en Drive. Si
    Drive no responde y el archivo ya está en caché, se usa el de caché."""
    global _ULTIMO_ZIP_LEIDO
    cache_zip, cache_meta = _cache_paths(file_id)

    md5_pedido = metadata.get("md5Checksum") if metadata else None
    if _ULTIMO_ZIP_LEIDO is not None and _ULTIMO_ZIP_LEIDO[0] == file_id and _ULTIMO_ZIP_LEIDO[1] == md5_pedido:
        return _ULTIMO_ZIP_LEIDO[2]
    _ULTIMO_ZIP_LEIDO = None
    data = _download_file_bytes(file_id, metadata)
    _ULTIMO_ZIP_LEIDO = (file_id, md5_pedido, data)
    return data


def _download_file_bytes(file_id: str, metadata: dict | None) -> bytes:
    cache_zip, cache_meta = _cache_paths(file_id)

    if metadata is None:
        try:
            metadata = get_file_metadata(file_id)
        except Exception:
            metadata = None

    md5 = metadata.get("md5Checksum") if metadata else None
    cacheada = _metadata_en_cache(file_id)
    if cacheada is not None and (md5 is None or cacheada.get("md5Checksum") == md5):
        # md5 None = no se pudo consultar Drive: la copia local es lo mejor
        # disponible (antes esto terminaba en error de descarga).
        try:
            return cache_zip.read_bytes()
        except OSError:
            pass

    if onedrive.es_id(file_id):
        data = onedrive.descargar(file_id)
    else:
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
    base = nombre_archivo.strip()
    comprimido = base.lower().endswith(EXTENSIONES_OFERTA)
    if comprimido:
        base = base.rsplit(".", 1)[0]
    match = PROPONENTE_NAME_RE.match(base.strip())
    if not match and comprimido:
        match = PROPONENTE_NUMERADO_RE.match(base.strip())
    if not match:
        return None
    return int(match.group(1)), match.group(2).strip(" .")


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


def _listar_archivos_recursivo(service, folder_id: str, _profundidad: int = 0, _ruta: str = "") -> list[dict]:
    """Lista los archivos de una carpeta de Drive, bajando también a las
    subcarpetas (ej. cuando los zips de los proponentes están dentro de una
    subcarpeta como "Propuestas" en vez de estar sueltos en la raíz). Cada
    archivo lleva su profundidad y la subcarpeta donde está."""
    if _profundidad > MAX_PROFUNDIDAD_CARPETAS:
        return []

    hijos = _listar_hijos(service, folder_id)
    archivos: list[dict] = []
    for hijo in hijos:
        if hijo.get("mimeType") == FOLDER_MIME_TYPE:
            ruta = f"{_ruta}/{hijo['name']}" if _ruta else hijo["name"]
            archivos.extend(_listar_archivos_recursivo(service, hijo["id"], _profundidad + 1, ruta))
        else:
            archivos.append({**hijo, "profundidad": _profundidad, "carpeta": _ruta})
    return archivos


def list_proponentes(carpeta_drive: str) -> ProponentesResult:
    """Ofertas de la carpeta: un enlace de Google Drive o uno público de
    OneDrive."""
    if onedrive.es_enlace(carpeta_drive):
        return _list_proponentes_onedrive(carpeta_drive.strip())
    folder_id = extract_folder_id(carpeta_drive)
    cache_listado = CACHE_LISTADOS_DIR / f"{folder_id}.json"

    archivos = None
    if _solo_cache() and cache_listado.exists():
        archivos = json.loads(cache_listado.read_text())
    if archivos is None:
        try:
            service = get_drive_service()
            archivos = _listar_archivos_recursivo(service, folder_id)
            try:
                CACHE_LISTADOS_DIR.mkdir(parents=True, exist_ok=True)
                cache_listado.write_text(json.dumps(archivos))
            except OSError:
                pass
        except HttpError as exc:
            email = service_account_email()
            pista = f" Verifica que la carpeta esté compartida con {email}." if email else ""
            if exc.resp.status == 404:
                raise DriveAccessError(f"No se encontró la carpeta de Drive.{pista}") from exc
            if exc.resp.status == 403:
                raise DriveAccessError(f"Sin permiso para leer la carpeta de Drive.{pista}") from exc
            raise DriveAccessError(f"Error consultando Google Drive: {exc}") from exc
        except DriveConfigError:
            raise
        except Exception as exc:
            if not cache_listado.exists():
                raise DriveAccessError(f"No se pudo consultar Google Drive y no hay copia local: {exc}") from exc
            archivos = json.loads(cache_listado.read_text())

    return _proponentes_de(archivos)


def _list_proponentes_onedrive(enlace: str) -> ProponentesResult:
    cache_listado = CACHE_LISTADOS_DIR / f"onedrive_{hashlib.sha1(enlace.encode()).hexdigest()[:16]}.json"
    if _solo_cache() and cache_listado.exists():
        return _proponentes_de(json.loads(cache_listado.read_text()))
    try:
        archivos = onedrive.listar(enlace, MAX_PROFUNDIDAD_CARPETAS)
    except onedrive.OneDriveError as exc:
        raise DriveAccessError(str(exc)) from exc
    except Exception as exc:
        if not cache_listado.exists():
            raise DriveAccessError(f"No se pudo consultar OneDrive y no hay copia local: {exc}") from exc
        archivos = json.loads(cache_listado.read_text())
    else:
        try:
            CACHE_LISTADOS_DIR.mkdir(parents=True, exist_ok=True)
            cache_listado.write_text(json.dumps(archivos))
            # Los metadatos ya vienen en el listado: se guardan para no pedirlos uno a uno.
            for a in archivos:
                _METADATA_MEMORIA[a["id"]] = (time.monotonic(), {k: a[k] for k in ("md5Checksum", "size", "name")})
        except OSError:
            pass
    return _proponentes_de(archivos)


def _proponentes_de(archivos: list[dict]) -> ProponentesResult:
    result = ProponentesResult()
    # Las ofertas son las del nivel más alto que tenga alguna: si están en la
    # raíz, las subcarpetas (sobre económico, subsanaciones…) no se mezclan.
    niveles = [a.get("profundidad", 0) for a in archivos if _parse_nombre(a["name"]) is not None]
    nivel = min(niveles) if niveles else 0
    for archivo in archivos:
        parsed = _parse_nombre(archivo["name"])
        if parsed is None:
            result.no_reconocidos.append(archivo["name"])
            continue
        if archivo.get("profundidad", 0) != nivel:
            result.no_reconocidos.append(f"{archivo.get('carpeta') or ''}/{archivo['name']} (subcarpeta: no se usa)".lstrip("/"))
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
