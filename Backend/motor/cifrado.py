"""Cifrado en reposo de los archivos con datos personales (RF-21).

Las ofertas descargadas, los documentos aportados, los expedientes y los
documentos de las OPS (cédulas, certificados) se guardan cifrados con
AES-256-GCM. La clave sale de CLAVE_CIFRADO_ARCHIVOS: una o varias claves de 32
bytes en base64, separadas por comas. La primera cifra; todas descifran, para
poder rotarla (`manage.py cifrar_archivos --rotar` vuelve a cifrar con la nueva).

Formato: MAGIA (8 bytes) + huella de la clave (8) + nonce (12) + texto cifrado
con su etiqueta. La huella dice con qué clave se cifró sin revelarla. Un archivo
sin la marca es de antes del cifrado: se lee tal cual, y `cifrar_archivos` lo
cifra. Si la etiqueta no cuadra (archivo alterado o clave equivocada) se
levanta un error: nunca se devuelve un contenido que no se pudo verificar.

Sin clave configurada no se cifra (desarrollo); en producción el despliegue la
exige (CIFRADO_OBLIGATORIO=1).
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIA = b"MEVCIF1\n"
_CABECERA = len(MAGIA) + 8 + 12


class ErrorCifrado(Exception):
    pass


def _huella(clave: bytes) -> bytes:
    return hashlib.sha256(b"mievaluador-cifrado|" + clave).digest()[:8]


def claves() -> list[bytes]:
    texto = os.environ.get("CLAVE_CIFRADO_ARCHIVOS", "").strip()
    salida = []
    for parte in filter(None, (x.strip() for x in texto.split(","))):
        try:
            clave = base64.b64decode(parte, validate=True)
        except ValueError as exc:
            raise ErrorCifrado("CLAVE_CIFRADO_ARCHIVOS no es base64 válido.") from exc
        if len(clave) != 32:
            raise ErrorCifrado("Cada clave de CLAVE_CIFRADO_ARCHIVOS debe tener 32 bytes (AES-256).")
        salida.append(clave)
    if not salida and os.environ.get("CIFRADO_OBLIGATORIO", "") == "1":
        raise ErrorCifrado("El cifrado en reposo es obligatorio y falta CLAVE_CIFRADO_ARCHIVOS.")
    return salida


def activo() -> bool:
    return bool(claves())


def nueva_clave() -> str:
    return base64.b64encode(AESGCM.generate_key(bit_length=256)).decode()


def cifrado(datos: bytes) -> bool:
    return datos[: len(MAGIA)] == MAGIA


def cifrado_con_actual(datos: bytes) -> bool:
    c = claves()
    return bool(c) and cifrado(datos) and datos[len(MAGIA) : len(MAGIA) + 8] == _huella(c[0])


def cifrar(datos: bytes) -> bytes:
    """Cifra con la clave actual; sin clave, devuelve los datos tal cual."""
    c = claves()
    if not c or cifrado(datos):
        return datos
    nonce = os.urandom(12)
    huella = _huella(c[0])
    return MAGIA + huella + nonce + AESGCM(c[0]).encrypt(nonce, datos, MAGIA + huella)


def descifrar(datos: bytes) -> bytes:
    if not cifrado(datos):
        return datos
    if len(datos) < _CABECERA + 16:
        raise ErrorCifrado("Archivo cifrado incompleto.")
    huella = datos[len(MAGIA) : len(MAGIA) + 8]
    nonce = datos[len(MAGIA) + 8 : _CABECERA]
    clave = next((k for k in claves() if _huella(k) == huella), None)
    if clave is None:
        raise ErrorCifrado("El archivo se cifró con una clave que no está en CLAVE_CIFRADO_ARCHIVOS.")
    try:
        return AESGCM(clave).decrypt(nonce, datos[_CABECERA:], MAGIA + huella)
    except Exception as exc:  # InvalidTag
        raise ErrorCifrado("El archivo cifrado fue alterado o la clave no corresponde.") from exc


def leer(ruta: Path) -> bytes:
    return descifrar(ruta.read_bytes())


def escribir(ruta: Path, datos: bytes) -> None:
    """Escribe cifrado y de una vez (archivo temporal + renombrar): nunca queda
    un archivo a medias ni una copia en claro."""
    temporal = ruta.with_name(f".{ruta.name}.tmp")
    temporal.write_bytes(cifrar(datos))
    temporal.replace(ruta)
