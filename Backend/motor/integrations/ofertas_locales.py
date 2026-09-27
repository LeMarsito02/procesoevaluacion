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


def _entradas_de_primer_nivel(contenido: bytes) -> tuple[list[str], list[str], list[str]]:
    """(archivos comprimidos, carpetas, documentos sueltos) del primer nivel de un zip."""
    comprimidos: list[str] = []
    carpetas: list[str] = []
    sueltos: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            for nombre in z.namelist():
                limpio = nombre.strip("/")
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


def _repartir_contenedor(nombre: str, contenido: bytes) -> list[tuple[str, bytes]] | None:
    """Las ofertas que hay dentro de un zip que las trae todas.

    Hay entidades que publican un solo archivo con las ofertas adentro, ya sea
    cada una en su propio zip o cada una en su carpeta. None si el zip no es un
    contenedor, es decir, si es la oferta de un proponente."""
    # Si el nombre del archivo ya dice de qué proponente es ("p5 GAMMA LTDA.zip"),
    # es su oferta y no un contenedor: lo de dentro son las carpetas en que él
    # organizó sus documentos.
    if _parse_nombre(nombre) is not None:
        return None
    comprimidos, carpetas, sueltos = _entradas_de_primer_nivel(contenido)
    # Si lo de dentro son las secciones de una oferta —vengan en carpetas o
    # comprimidas—, este zip es la oferta de un proponente.
    if _son_partes_de_una_oferta(comprimidos + carpetas):
        return None
    # Un contenedor trae las ofertas y nada más. Si al lado de los comprimidos
    # hay documentos sueltos, son los papeles de un solo proponente que numeró
    # su oferta de 1 a 28 y comprimió un par de puntos ("21. CAPACIDAD
    # FINANCIERA.zip"): repartirlo convertiría una oferta en dos o tres.
    if len(sueltos) >= 3:
        return None
    if len(comprimidos) >= 2:
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            return [(interno, z.read(interno)) for interno in comprimidos]
    # Carpetas cuyo nombre dice de quién es la oferta: cada una se vuelve un zip.
    utiles = list(carpetas)
    con_nombre = [c for c in utiles if _parse_nombre(c) is not None]
    candidatas = con_nombre if len(con_nombre) >= 2 else (utiles if len(utiles) >= 2 else [])
    if not candidatas:
        return None
    sueltas: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        for carpeta in candidatas:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as salida:
                for entrada in z.namelist():
                    limpio = entrada.strip("/")
                    if not limpio.startswith(f"{carpeta}/") or entrada.endswith("/"):
                        continue
                    salida.writestr(limpio[len(carpeta) + 1:], z.read(entrada))
            datos = buffer.getvalue()
            # Una carpeta sin archivos dentro no es una oferta.
            with zipfile.ZipFile(io.BytesIO(datos)) as comprobar:
                if not comprobar.namelist():
                    continue
            sueltas.append((f"{carpeta}.zip", datos))
    return sueltas or None


def desde_archivos(archivos: list[tuple[str, bytes]]) -> OfertasLocales:
    """Las ofertas subidas, convertidas en proponentes. `archivos` es
    [(nombre, contenido)] en el orden en que los eligió el evaluador."""
    resultado = OfertasLocales()
    sin_numero: list[tuple[str, bytes]] = []
    usados: set[int] = set()
    # Un solo zip puede traer todas las ofertas adentro, cada una en su propio
    # zip o en su carpeta: se reparte antes de mirarlas una por una.
    repartidos: list[tuple[str, bytes]] = []
    for nombre, contenido in archivos:
        dentro = _repartir_contenedor(nombre, contenido) if nombre.lower().endswith(".zip") and contenido else None
        if dentro:
            repartidos.extend(dentro)
        else:
            repartidos.append((nombre, contenido))
    archivos = repartidos
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
