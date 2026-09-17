from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from motor.procesamiento.memoria_proponente import PdfsProponente
from motor.procesamiento.pdf_utils import limpiar_memoria_texto

MAX_PROFUNDIDAD = 6

# Algunos proponentes comprimen sus documentos en .rar en vez de .zip.
# Python no tiene soporte nativo para RAR, así que usamos 7-Zip (que sabe
# leer RAR, incluido RAR5) si está instalado en el servidor.
_SIETE_ZIP = shutil.which("7z") or shutil.which("7za")


def _extraer_rar(contenido: bytes, _profundidad: int, _ruta: str) -> dict[str, bytes]:
    if not _SIETE_ZIP:
        return {}

    pdfs: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        rar_path = Path(tmpdir) / "archivo.rar"
        rar_path.write_bytes(contenido)
        destino = Path(tmpdir) / "extraido"
        destino.mkdir()

        try:
            subprocess.run(
                [_SIETE_ZIP, "x", "-y", f"-o{destino}", str(rar_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
                check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return {}

        for archivo in sorted(destino.rglob("*")):
            if not archivo.is_file():
                continue
            relativo = archivo.relative_to(destino).as_posix()
            ruta_completa = f"{_ruta}/{relativo}" if _ruta else relativo
            lower = archivo.name.lower()
            try:
                data = archivo.read_bytes()
            except OSError:
                continue

            if lower.endswith(".pdf"):
                pdfs[ruta_completa] = data
            elif lower.endswith(".zip"):
                pdfs.update(extraer_pdfs(data, _profundidad + 1, ruta_completa))
            elif lower.endswith(".rar"):
                pdfs.update(_extraer_rar(data, _profundidad + 1, ruta_completa))

    return pdfs


def _deduplicar_por_contenido(pdfs: dict[str, bytes]) -> dict[str, bytes]:
    """Muchos proponentes suben el mismo archivo .rar duplicado varias veces
    (se vio un caso real: 'RUP_1.rar', 'RUP_2.rar' y 'RUP_3.rar' con
    contenido idéntico byte a byte), y sin deduplicar cada evaluador termina
    procesando 3 veces el mismo documento — con documentos grandes
    (certificados de Cámara de Comercio de decenas de páginas con marcas de
    agua/gráficos, que pdfplumber procesa con mucha memoria) esto multiplica
    el uso de RAM y el tiempo sin ninguna ganancia. Se queda con una sola
    copia por contenido, eligiendo la de ruta más corta (o alfabéticamente
    primera) para que el resultado sea determinista entre corridas."""
    por_hash: dict[str, str] = {}
    resultado: dict[str, bytes] = {}
    for ruta in sorted(pdfs.keys(), key=lambda r: (len(r), r)):
        contenido = pdfs[ruta]
        huella = hashlib.md5(contenido).hexdigest()
        if huella in por_hash:
            continue
        por_hash[huella] = ruta
        resultado[ruta] = contenido
    return resultado


# Último zip extraído en este worker: los evaluadores de los 18 requisitos
# de un mismo proponente reciben el mismo PdfsProponente (y comparten su
# memoria de búsquedas) en vez de descomprimir el zip 18 veces. Solo se
# guarda uno para no acumular memoria.
_ULTIMO_ZIP: tuple[bytes, str, PdfsProponente] | None = None


def extraer_pdfs(zip_bytes: bytes, _profundidad: int = 0, _ruta: str = "") -> dict[str, bytes]:
    if _profundidad > 0 or _ruta:
        return _extraer_pdfs(zip_bytes, _profundidad, _ruta)
    global _ULTIMO_ZIP
    if _ULTIMO_ZIP is not None and _ULTIMO_ZIP[0] is zip_bytes:
        return _ULTIMO_ZIP[2]
    huella = hashlib.md5(zip_bytes).hexdigest()
    if _ULTIMO_ZIP is not None and _ULTIMO_ZIP[1] == huella:
        return _ULTIMO_ZIP[2]
    _ULTIMO_ZIP = None
    limpiar_memoria_texto()
    pdfs = PdfsProponente(_extraer_pdfs(zip_bytes))
    _ULTIMO_ZIP = (zip_bytes, huella, pdfs)
    return pdfs


def _extraer_pdfs(zip_bytes: bytes, _profundidad: int = 0, _ruta: str = "") -> dict[str, bytes]:
    """Extrae recursivamente todos los PDF de un zip, incluyendo zips y rars
    anidados dentro de él (a cualquier profundidad, mezclados). El resultado
    del nivel superior queda deduplicado por contenido (ver
    `_deduplicar_por_contenido`)."""
    if _profundidad > MAX_PROFUNDIDAD:
        return {}

    pdfs: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                nombre = info.filename
                ruta_completa = f"{_ruta}/{nombre}" if _ruta else nombre
                try:
                    contenido = zf.read(info)
                except Exception:  # noqa: BLE001
                    continue

                lower = nombre.lower()
                if lower.endswith(".pdf"):
                    pdfs[ruta_completa] = contenido
                elif lower.endswith(".zip"):
                    pdfs.update(_extraer_pdfs(contenido, _profundidad + 1, ruta_completa))
                elif lower.endswith(".rar"):
                    pdfs.update(_extraer_rar(contenido, _profundidad + 1, ruta_completa))
    except zipfile.BadZipFile:
        # El nivel superior también podría venir como .rar en vez de .zip.
        pdfs.update(_extraer_rar(zip_bytes, _profundidad, _ruta))

    if _profundidad == 0:
        pdfs = _deduplicar_por_contenido(pdfs)

    return pdfs
