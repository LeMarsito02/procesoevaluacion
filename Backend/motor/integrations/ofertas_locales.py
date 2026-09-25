"""Ofertas que el evaluador sube a mano, en vez de traerlas de Drive.

Las ofertas normalmente están en una carpeta compartida de Drive o de OneDrive,
pero para probar —o cuando la entidad las bajó del SECOP una por una— lo que hay
son los zips en el disco. Para que el resto del programa no note la diferencia se
guardan en la misma caché que las de Drive y se les da un identificador propio
(«local:<huella>»): el evaluador, el trabajador y el motor siguen pidiendo la
oferta igual, y `download_file_bytes` sabe de dónde sacarla.

El nombre del archivo se lee con las mismas reglas que en Drive («p1 NOMBRE»,
«1. NOMBRE»). Si no calza ninguna, el proponente no se descarta: se numera por el
orden en que llegó y se deja dicho, para que quien sube los archivos vea que el
nombre no decía de quién era la oferta.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from motor.esquemas.proceso import Proponente
from motor.integrations.drive import CACHE_DIR, EXTENSIONES_OFERTA, _parse_nombre

PREFIJO = "local:"


@dataclass
class OfertasLocales:
    proponentes: list[Proponente] = field(default_factory=list)
    no_reconocidos: list[str] = field(default_factory=list)


def es_id_local(file_id: str) -> bool:
    return file_id.startswith(PREFIJO)


def guardar(nombre: str, contenido: bytes) -> str:
    """Guarda la oferta en la caché y devuelve su identificador.

    La huella es del contenido, así que subir dos veces el mismo archivo no lo
    duplica y la evaluación ya hecha se reaprovecha."""
    huella = hashlib.sha256(contenido).hexdigest()[:32]
    file_id = f"{PREFIJO}{huella}"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    destino = CACHE_DIR / f"{_archivo(file_id)}.zip"
    if not destino.exists() or destino.stat().st_size != len(contenido):
        destino.write_bytes(contenido)
    meta = CACHE_DIR / f"{_archivo(file_id)}.meta.json"
    meta.write_text(json.dumps({"md5Checksum": huella, "name": nombre, "size": len(contenido)}))
    return file_id


def leer(file_id: str) -> bytes:
    ruta = CACHE_DIR / f"{_archivo(file_id)}.zip"
    if not ruta.exists():
        raise FileNotFoundError(
            f"La oferta subida ya no está en el almacenamiento local ({ruta.name}). Vuelve a subirla."
        )
    return ruta.read_bytes()


def metadatos(file_id: str) -> dict | None:
    ruta = CACHE_DIR / f"{_archivo(file_id)}.meta.json"
    if not ruta.exists():
        return None
    try:
        return json.loads(ruta.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _archivo(file_id: str) -> str:
    """El nombre en disco: sin los dos puntos, que no son buenos en un archivo."""
    return file_id.replace(":", "_")


def desde_archivos(archivos: list[tuple[str, bytes]]) -> OfertasLocales:
    """Las ofertas subidas, convertidas en proponentes. `archivos` es
    [(nombre, contenido)] en el orden en que los eligió el evaluador."""
    resultado = OfertasLocales()
    sin_numero: list[tuple[str, bytes]] = []
    usados: set[int] = set()
    for nombre, contenido in archivos:
        if not nombre.lower().endswith(EXTENSIONES_OFERTA):
            resultado.no_reconocidos.append(f"{nombre} (no es un .zip, .rar ni .7z)")
            continue
        if not contenido:
            resultado.no_reconocidos.append(f"{nombre} (archivo vacío)")
            continue
        leido = _parse_nombre(nombre)
        if leido is None:
            sin_numero.append((nombre, contenido))
            continue
        numero, nombre_proponente = leido
        if numero in usados:
            sin_numero.append((nombre, contenido))
            continue
        usados.add(numero)
        resultado.proponentes.append(Proponente(
            numero_orden=numero,
            hoja=f"P-{numero:02d}",
            nombre_proponente=nombre_proponente,
            nombre_archivo=nombre,
            drive_file_id=guardar(nombre, contenido),
        ))
    # Los que no traen número en el nombre van después, en el orden en que
    # llegaron y ocupando los números libres.
    siguiente = 1
    for nombre, contenido in sin_numero:
        while siguiente in usados:
            siguiente += 1
        usados.add(siguiente)
        base = nombre.rsplit(".", 1)[0].strip()
        resultado.proponentes.append(Proponente(
            numero_orden=siguiente,
            hoja=f"P-{siguiente:02d}",
            nombre_proponente=base,
            nombre_archivo=nombre,
            drive_file_id=guardar(nombre, contenido),
            advertencia=("el nombre del archivo no dice el número del proponente "
                         f"(se esperaba algo como «p{siguiente} {base}»): se numeró por el orden en que se subió"),
        ))
    resultado.proponentes.sort(key=lambda p: p.numero_orden)
    return resultado
