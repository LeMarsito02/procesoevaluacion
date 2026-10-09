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
import io
import json
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from motor import cifrado
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
    meta = CACHE_DIR / f"{_archivo(file_id)}.meta.json"
    # La huella es del contenido: si ya está guardada es la misma oferta y no
    # se vuelve a escribir (reutilizar una carga de 5 GB no la duplica).
    if not (destino.exists() and meta.exists()):
        cifrado.escribir(destino, contenido)
    meta.write_text(json.dumps({"md5Checksum": huella, "name": nombre, "size": len(contenido)}))
    return file_id


def existe(file_id: str) -> bool:
    return (CACHE_DIR / f"{_archivo(file_id)}.zip").exists()


def leer(file_id: str) -> bytes:
    ruta = CACHE_DIR / f"{_archivo(file_id)}.zip"
    if not ruta.exists():
        raise FileNotFoundError(
            f"La oferta subida ya no está en el almacenamiento local ({ruta.name}). Vuelve a subirla."
        )
    return cifrado.leer(ruta)


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


# Una oferta puede llegar en memoria (bytes), en disco (ruta: las subidas de
# hasta 10 GB no caben en memoria) o como una función que la lee cuando hace
# falta (las ofertas que vienen dentro de un contenedor: se lee una a la vez).
Contenido = bytes | Path | Callable[[], bytes]


def _abrir_zip(fuente: bytes | Path) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(fuente) if isinstance(fuente, bytes) else fuente)


def _bytes(contenido: Contenido) -> bytes:
    if isinstance(contenido, bytes):
        return contenido
    if isinstance(contenido, Path):
        return contenido.read_bytes()
    return contenido()


def _vacio(contenido: Contenido) -> bool:
    if isinstance(contenido, bytes):
        return not contenido
    if isinstance(contenido, Path):
        return not contenido.exists() or contenido.stat().st_size == 0
    return False


# Cuántas carpetas envoltorio («OFERTAS_LP-14/») se atraviesan buscando las ofertas.
NIVELES_ENVOLTORIO = 4


def _entradas_de_primer_nivel(contenido: bytes | Path, prefijo: str = "") -> tuple[list[str], list[str], list[str]]:
    """(archivos comprimidos, carpetas, documentos sueltos) del primer nivel de
    un zip, o del nivel que está debajo de `prefijo` («OFERTAS/»)."""
    comprimidos: list[str] = []
    carpetas: list[str] = []
    sueltos: list[str] = []
    try:
        with _abrir_zip(contenido) as z:
            for nombre in z.namelist():
                limpio = nombre.strip("/")
                if not limpio.startswith(prefijo) or limpio.startswith("__MACOSX"):
                    continue
                limpio = limpio[len(prefijo):]
                if not limpio or limpio.startswith("__MACOSX"):
                    continue
                partes = limpio.split("/")
                if len(partes) > 1:
                    if partes[0] not in carpetas:
                        carpetas.append(partes[0])
                elif limpio.lower().endswith(EXTENSIONES_OFERTA):
                    comprimidos.append(limpio)
                else:
                    sueltos.append(limpio)
    except zipfile.BadZipFile:
        return [], [], []
    return comprimidos, carpetas, sueltos


# Cómo se llaman las partes en que un proponente reparte SU propia oferta. Es la
# confusión que hay que evitar: las ofertas que se bajan del SECOP llegan con un
# nombre que no dice de quién son ("CO1.RPL.5801690_20260923.zip") y por dentro
# traen "1. JURIDICO.rar", "2. FINANCIERO.rar", "3. TECNICO.rar"; tomar cada una
# por un proponente convierte una oferta en cinco.
#
# Los términos llevan límite de palabra donde podrían confundirse con el nombre
# de una empresa ("CARTA" no debe calzar "CARTAGENA").
_SECCIONES_DE_UNA_OFERTA = re.compile(
    r"^(?:\d{1,2}\s*[.)\-–]?\s*)?"
    r"(JURIDIC|TECNIC|FINANCIER|ECONOMIC|SOBRE\b|ANEXO|FORMATO|SUBSANAC|DOCUMENTO"
    r"|CARPETA|HABILITANTE|EXPERIENCIA|GARANTIA|RUP\b|CAMARA|ANTECEDENTE|PROPUESTA"
    r"|CARTA\b|PONDERABLE|POLIZA|PARAFISCAL|CONSORCIAL|INDUSTRIA|DISCAPACIDAD"
    r"|MUJER|MIPYME\b|REDAM\b|RNMC\b|COPNIA|PROCURADUR|CONTRALOR|POLICIA"
    r"|SEGURIDAD|PAGOS\b|CALIDAD|SOSTENIBILIDAD|PERSONAL|ESTADOS|BALANCE|CEDULA"
    r"|REGISTRO|CERTIFICAD|MATRICULA|APOYO|EMPRENDIMIENTO)",
    re.IGNORECASE,
)


def _son_partes_de_una_oferta(entradas: list[str]) -> bool:
    """Las entradas de este zip son las secciones de una sola oferta."""
    sin_extension = [re.sub(r"\.(zip|rar|7z)$", "", e.strip(), flags=re.IGNORECASE) for e in entradas]
    return any(_SECCIONES_DE_UNA_OFERTA.match(e) for e in sin_extension)


def _repartir_contenedor(nombre: str, contenido: bytes | Path) -> list[tuple[str, Contenido]] | None:
    """Las ofertas que hay dentro de un zip que las trae todas.

    Hay entidades que publican un solo archivo con las ofertas adentro, ya sea
    cada una en su propio zip o cada una en su carpeta. None si el zip no es un
    contenedor, es decir, si es la oferta de un proponente."""
    # Si el nombre del archivo ya dice de qué proponente es ("p5 GAMMA LTDA.zip"),
    # es su oferta y no un contenedor: lo de dentro son las carpetas en que él
    # organizó sus documentos.
    if _parse_nombre(nombre) is not None:
        return None
    # Muchas veces todo viene dentro de una sola carpeta («OFERTAS_LP-14/»): se
    # baja por esas carpetas envoltorio hasta donde están las ofertas. Pasó con
    # un .zip de 5,6 GB con 83 ofertas que se tomó por un solo proponente.
    prefijo = ""
    comprimidos, carpetas, sueltos = _entradas_de_primer_nivel(contenido)
    for _ in range(NIVELES_ENVOLTORIO):
        if len(carpetas) == 1 and not comprimidos and not sueltos:
            prefijo += carpetas[0] + "/"
            comprimidos, carpetas, sueltos = _entradas_de_primer_nivel(contenido, prefijo)
        else:
            break
    # Dos o más comprimidos con nombre de proponente que no es una sección
    # («01. CONSORCIO ROHI.zip», no «1. JURIDICO.rar») son un paquete de
    # ofertas, aunque al lado venga una carpeta como «ANTECEDENTES
    # CONSULTADOS» (la entidad la agrega; no es de ningún proponente).
    sin_ext = lambda e: re.sub(r"\.(zip|rar|7z)$", "", e.strip(), flags=re.IGNORECASE)  # noqa: E731
    de_proponentes = [c for c in comprimidos if _parse_nombre(c) is not None and not _SECCIONES_DE_UNA_OFERTA.match(sin_ext(c))]
    es_paquete = len(de_proponentes) >= 2
    # Si lo de dentro son las secciones de una oferta —vengan en carpetas o
    # comprimidas—, este zip es la oferta de un proponente.
    if not es_paquete and _son_partes_de_una_oferta(comprimidos + carpetas):
        return None
    # Un contenedor trae las ofertas y nada más. Si al lado de los comprimidos
    # hay documentos sueltos, son los papeles de un solo proponente que numeró
    # su oferta de 1 a 28 y comprimió un par de puntos ("21. CAPACIDAD
    # FINANCIERA.zip"): repartirlo convertiría una oferta en dos o tres.
    if len(sueltos) >= 3:
        return None
    if len(comprimidos) >= 2:
        # Cada oferta se lee del contenedor cuando toca guardarla, no todas a la vez.
        def leer_interno(interno: str) -> Callable[[], bytes]:
            def leer() -> bytes:
                with _abrir_zip(contenido) as z:
                    return z.read(prefijo + interno)
            return leer
        return [(interno, leer_interno(interno)) for interno in comprimidos]
    # Carpetas cuyo nombre dice de quién es la oferta: cada una se vuelve un zip.
    utiles = list(carpetas)
    con_nombre = [c for c in utiles if _parse_nombre(c) is not None]
    candidatas = con_nombre if len(con_nombre) >= 2 else (utiles if len(utiles) >= 2 else [])
    if not candidatas:
        return None
    sueltas: list[tuple[str, Contenido]] = []
    with _abrir_zip(contenido) as z:
        # Los nombres relativos al nivel donde están las ofertas.
        nombres = [n[len(prefijo):] if n.startswith(prefijo) else "" for n in (x.strip("/") + ("/" if x.endswith("/") else "") for x in z.namelist())]
        reales = dict(zip(nombres, z.namelist()))

    def empacar(carpeta: str) -> Callable[[], bytes]:
        # La carpeta se vuelve un zip cuando toca guardarla, una a la vez.
        def leer() -> bytes:
            buffer = io.BytesIO()
            with _abrir_zip(contenido) as z, zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as salida:
                for entrada in nombres:
                    limpio = entrada.strip("/")
                    if limpio.startswith(f"{carpeta}/") and not entrada.endswith("/"):
                        salida.writestr(limpio[len(carpeta) + 1:], z.read(reales[entrada]))
            return buffer.getvalue()
        return leer

    for carpeta in candidatas:
        # Una carpeta sin archivos dentro no es una oferta.
        if not any(e.strip("/").startswith(f"{carpeta}/") and not e.endswith("/") for e in nombres):
            continue
        sueltas.append((f"{carpeta}.zip", empacar(carpeta)))
    return sueltas or None


def _ofertas_adentro(contenido: Contenido) -> int:
    """Cuántos comprimidos con nombre de proponente («07. CONSORCIO EDEN.zip»)
    trae un zip a cualquier profundidad. Muchos en un zip que no se repartió
    quiere decir que se tomó por una oferta lo que es un paquete de ofertas."""
    if not isinstance(contenido, (bytes, Path)):
        return 0
    try:
        with _abrir_zip(contenido) as z:
            internos = [n.strip("/").rsplit("/", 1)[-1] for n in z.namelist() if n.lower().endswith(EXTENSIONES_OFERTA)]
    except (zipfile.BadZipFile, OSError):
        return 0
    if _son_partes_de_una_oferta(internos):
        return 0
    return sum(1 for n in internos if _parse_nombre(n) is not None)


def desde_archivos(archivos: list[tuple[str, Contenido]]) -> OfertasLocales:
    """Las ofertas subidas, convertidas en proponentes. `archivos` es
    [(nombre, contenido)] en el orden en que los eligió el evaluador; el
    contenido puede ser una ruta en disco (subidas grandes): se lee una oferta
    a la vez, al guardarla."""
    resultado = OfertasLocales()
    sin_numero: list[tuple[str, Contenido]] = []
    usados: set[int] = set()
    # Un solo zip puede traer todas las ofertas adentro, cada una en su propio
    # zip o en su carpeta: se reparte antes de mirarlas una por una.
    repartidos: list[tuple[str, Contenido]] = []
    # Zips que no se repartieron pero traen varias ofertas adentro: se avisa.
    sospechosos: dict[str, int] = {}
    for nombre, contenido in archivos:
        es_zip = nombre.lower().endswith(".zip") and isinstance(contenido, (bytes, Path)) and not _vacio(contenido)
        dentro = _repartir_contenedor(nombre, contenido) if es_zip else None
        if dentro:
            repartidos.extend(dentro)
        else:
            repartidos.append((nombre, contenido))
            if es_zip and (n := _ofertas_adentro(contenido)) >= 3:
                sospechosos[nombre] = n
    archivos = repartidos
    for nombre, contenido in archivos:
        if not nombre.lower().endswith(EXTENSIONES_OFERTA):
            resultado.no_reconocidos.append(f"{nombre} (no es un .zip, .rar ni .7z)")
            continue
        if _vacio(contenido):
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
            drive_file_id=guardar(nombre, _bytes(contenido)),
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
            drive_file_id=guardar(nombre, _bytes(contenido)),
            advertencia=("el nombre del archivo no dice el número del proponente "
                         f"(se esperaba algo como «p{siguiente} {base}»): se numeró por el orden en que se subió"),
        ))
    for prop in resultado.proponentes:
        if prop.nombre_archivo in sospechosos:
            aviso = (f"este archivo trae {sospechosos[prop.nombre_archivo]} ofertas adentro y no se pudo repartir: "
                     "revise cómo está organizado y súbalas por separado")
            prop.advertencia = f"{prop.advertencia}; {aviso}" if prop.advertencia else aviso
            resultado.no_reconocidos.append(f"{prop.nombre_archivo} (parece traer {sospechosos[prop.nombre_archivo]} ofertas adentro)")
    resultado.proponentes.sort(key=lambda p: p.numero_orden)
    return resultado
