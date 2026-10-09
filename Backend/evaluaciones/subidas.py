"""Subida de ofertas por pedazos (hasta 10 GB por archivo).

Una sola petición de 10 GB no sirve: se pierde entera si el wifi parpadea, no
cabe en memoria y el proxy la corta (client_max_body_size). Aquí cada archivo
se anuncia con su tamaño, llega en pedazos que se pegan al final en disco y,
si se corta, se retoma desde lo que ya llegó.

Cada subida es de quien la creó (se guarda su id con ella) y vive en
SUBIDAS_DIR hasta que el trabajador reparte las ofertas en la caché, o hasta
que se vence (DIAS_DE_VIDA).
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

DIAS_DE_VIDA = 2
# Se deja libre al menos esto en el disco después de recibir una subida.
MARGEN_DISCO = 2 * 1024**3


class ErrorSubida(Exception):
    def __init__(self, mensaje: str, codigo: int = 400):
        super().__init__(mensaje)
        self.codigo = codigo


@dataclass
class Subida:
    id: str
    usuario_id: str
    nombre: str
    tamano: int
    recibido: int
    # Una carga que ya estaba repartida en el servidor: sus ofertas, sin subir nada.
    reuso: dict | None = None

    @property
    def completa(self) -> bool:
        return self.recibido == self.tamano

    @property
    def ruta(self) -> Path:
        return _ruta(self.id)


def _dir() -> Path:
    d = Path(settings.SUBIDAS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ruta(subida_id: str) -> Path:
    return _dir() / f"{subida_id}.parte"


def _meta(subida_id: str) -> Path:
    return _dir() / f"{subida_id}.json"


# --- Huella rápida: reconocer una carga que ya se subió, sin volver a subirla ---
# Se calcula igual en el navegador (frontend/src/huella.ts): el principio, ocho
# muestras repartidas y los últimos 8 MB. Al final de un zip está su índice, con
# el CRC y el tamaño de cada archivo de adentro: dos zips distintos no comparten
# huella. El tamaño entra también.
HUELLA_INICIO = 1024 * 1024
HUELLA_FINAL = 8 * 1024 * 1024
HUELLA_MUESTRA = 256 * 1024
HUELLA_MUESTRAS = 8


def _tramos(tamano: int) -> list[tuple[int, int]]:
    tramos = [(0, min(HUELLA_INICIO, tamano))]
    for i in range(1, HUELLA_MUESTRAS + 1):
        desde = (tamano * i) // (HUELLA_MUESTRAS + 1)
        tramos.append((desde, min(tamano, desde + HUELLA_MUESTRA)))
    tramos.append((max(0, tamano - HUELLA_FINAL), tamano))
    return tramos


def huella_rapida(ruta: Path) -> str:
    import hashlib

    tamano = ruta.stat().st_size
    h = hashlib.sha256(f"mievaluador-huella-v1|{tamano}|".encode())
    with open(ruta, "rb") as f:
        for desde, hasta in _tramos(tamano):
            f.seek(desde)
            h.update(f.read(hasta - desde))
    return h.hexdigest()


def _indice() -> Path:
    from motor.integrations.drive import CACHE_DIR

    return Path(CACHE_DIR) / "cargas_repartidas.json"


def _leer_indice() -> dict:
    try:
        return json.loads(_indice().read_text())
    except (OSError, ValueError):
        return {}


def _escribir_indice(indice: dict) -> None:
    ruta = _indice()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(indice, ensure_ascii=False))
    temporal.replace(ruta)


def buscar_carga(huella: str, tamano: int, entidad_id=None) -> dict | None:
    """Lo que salió de una carga ya repartida con esa huella en esa entidad, si
    sus ofertas siguen todas en la caché. Cada entidad ve solo sus cargas."""
    from motor.integrations import ofertas_locales

    carga = _leer_indice().get(huella)
    if not carga or carga.get("tamano") != tamano or not carga.get("partes"):
        return None
    if entidad_id is not None and carga.get("entidad") != str(entidad_id):
        return None
    if not all(ofertas_locales.existe(x["file_id"]) for x in carga["partes"]):
        return None
    return carga


def registrar_carga(huella: str, tamano: int, nombre: str, partes: list[dict], no_reconocidos: list[str], entidad_id=None) -> None:
    indice = _leer_indice()
    indice[huella] = {"tamano": tamano, "nombre": nombre, "partes": partes, "no_reconocidos": no_reconocidos,
                      "registrada": time.time(), "entidad": str(entidad_id) if entidad_id else None}
    _escribir_indice(indice)


def cargas_de(entidad_id) -> list[dict]:
    """Las cargas guardadas de la entidad, las más recientes primero."""
    from motor.integrations import ofertas_locales

    salida = []
    for huella, c in _leer_indice().items():
        if c.get("entidad") != str(entidad_id):
            continue
        salida.append({"huella": huella, "nombre": c["nombre"], "tamano": c["tamano"], "ofertas": len(c["partes"]),
                       "registrada": c.get("registrada"), "completa": all(ofertas_locales.existe(x["file_id"]) for x in c["partes"])})
    return sorted(salida, key=lambda x: -(x["registrada"] or 0))


def eliminar_carga(huella: str, entidad_id) -> int:
    """Quita la carga del servidor y borra las ofertas suyas que ningún proceso
    ni preparación usa (las que usa un proceso se conservan: son su evidencia).
    Devuelve cuántas ofertas se borraron."""
    from evaluaciones.models import PreparacionProceso, Proponente
    from motor.integrations.drive import CACHE_DIR

    indice = _leer_indice()
    carga = indice.get(huella)
    if not carga or carga.get("entidad") != str(entidad_id):
        raise ErrorSubida("No existe esa carga.", 404)
    del indice[huella]
    _escribir_indice(indice)
    en_uso = set(Proponente.objects.filter(drive_file_id__in=[x["file_id"] for x in carga["partes"]]).values_list("drive_file_id", flat=True))
    for p in PreparacionProceso.objects.exclude(ofertas_subidas=None).values_list("ofertas_subidas", flat=True):
        en_uso |= {x.get("drive_file_id") for x in (p or {}).get("proponentes", [])}
        for x in (p or {}).get("pendientes", []):
            en_uso |= {y["file_id"] for y in ((x.get("reuso") or {}).get("partes", []))}
    otras = {y["file_id"] for c in indice.values() for y in c.get("partes", [])}
    borradas = 0
    for x in carga["partes"]:
        fid = x["file_id"]
        if fid in en_uso or fid in otras or not fid.startswith("local:"):
            continue
        base = fid.replace(":", "_")
        for ruta in (Path(CACHE_DIR) / f"{base}.zip", Path(CACHE_DIR) / f"{base}.meta.json"):
            ruta.unlink(missing_ok=True)
        borradas += 1
    return borradas


def crear(usuario_id, nombre: str, tamano: int, huella: str | None = None, entidad_id=None) -> Subida:
    nombre = Path(nombre or "oferta.zip").name[:250]
    if tamano <= 0:
        raise ErrorSubida(f"«{nombre}» está vacío.")
    if tamano > settings.SUBIDA_MAXIMA_ARCHIVO:
        raise ErrorSubida(f"«{nombre}» pesa {tamano / 1024**3:.1f} GB; el máximo por archivo es "
                          f"{settings.SUBIDA_MAXIMA_ARCHIVO / 1024**3:.0f} GB.", 413)
    libre = shutil.disk_usage(_dir()).free
    if tamano + MARGEN_DISCO > libre:
        raise ErrorSubida(f"El servidor no tiene espacio para «{nombre}» ({tamano / 1024**3:.1f} GB): quedan "
                          f"{libre / 1024**3:.1f} GB libres. Use una carpeta compartida o avise al administrador.", 507)
    subida_id = uuid.uuid4().hex
    meta = {"usuario": str(usuario_id), "nombre": nombre, "tamano": tamano, "creada": time.time(), "entidad": str(entidad_id) if entidad_id else None}
    carga = buscar_carga(huella, tamano, entidad_id) if huella and len(huella) == 64 else None
    if carga is not None:
        # Ya se subió y se repartió: no hace falta volver a subirla.
        meta["reuso"] = {"partes": carga["partes"], "no_reconocidos": carga.get("no_reconocidos", [])}
    else:
        _ruta(subida_id).touch()
        meta["huella"] = huella or ""
    _meta(subida_id).write_text(json.dumps(meta))
    return ver(subida_id, usuario_id)


def ver(subida_id: str, usuario_id) -> Subida:
    if not subida_id.isalnum() or len(subida_id) != 32:
        raise ErrorSubida("No existe esa subida.", 404)
    try:
        meta = json.loads(_meta(subida_id).read_text())
    except (OSError, ValueError) as exc:
        raise ErrorSubida("No existe esa subida (o ya se venció).", 404) from exc
    if meta["usuario"] != str(usuario_id):
        raise ErrorSubida("No existe esa subida.", 404)
    if meta.get("reuso"):
        s = Subida(subida_id, meta["usuario"], meta["nombre"], meta["tamano"], meta["tamano"])
        s.reuso = meta["reuso"]
        return s
    ruta = _ruta(subida_id)
    return Subida(subida_id, meta["usuario"], meta["nombre"], meta["tamano"], ruta.stat().st_size if ruta.exists() else 0)


def agregar(subida_id: str, usuario_id, desde: int, datos: bytes) -> Subida:
    """Pega un pedazo al final. Solo si encaja donde iba: un pedazo repetido o
    fuera de orden se rechaza y se dice desde dónde seguir."""
    s = ver(subida_id, usuario_id)
    if s.reuso is not None:
        raise ErrorSubida("Este archivo ya estaba en el servidor: no hace falta subirlo.", 409)
    if len(datos) > settings.SUBIDA_PEDAZO_MAXIMO:
        raise ErrorSubida("Pedazo demasiado grande.", 413)
    if desde != s.recibido:
        raise ErrorSubida(f"El servidor tiene {s.recibido} bytes de «{s.nombre}»: continúe desde ahí.", 409)
    if s.recibido + len(datos) > s.tamano:
        raise ErrorSubida("Llegó más de lo anunciado para este archivo.", 400)
    with open(s.ruta, "ab") as f:
        f.write(datos)
    s.recibido += len(datos)
    return s


def borrar(subida_id: str) -> None:
    for ruta in (_ruta(subida_id), _meta(subida_id)):
        ruta.unlink(missing_ok=True)


def borrar_vencidas() -> int:
    limite = time.time() - DIAS_DE_VIDA * 86400
    n = 0
    for meta in _dir().glob("*.json"):
        try:
            vieja = json.loads(meta.read_text()).get("creada", 0) < limite
        except (OSError, ValueError):
            vieja = True
        if vieja:
            borrar(meta.stem)
            n += 1
    return n
