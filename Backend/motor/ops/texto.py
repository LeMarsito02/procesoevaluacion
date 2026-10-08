"""Texto «plano» para buscar con expresiones regulares sin perder el original.

`plano` deja el texto en mayúsculas y sin tildes **con la misma longitud**:
lo que se encuentra en una posición del texto plano está en la misma posición
del original. Así se busca sin tildes y se muestra con ellas (un objeto o una
obligación se leen tal como los escribió la entidad).
"""
from __future__ import annotations

import re
import unicodedata

_EQUIVALENTES = {"—": "-", "–": "-", "“": '"', "”": '"', "‘": "'", "’": "'", " ": " ", "\t": " "}
_CID_RE = re.compile(r"\(cid:\d+\)", re.I)


def plano(texto: str) -> str:
    salida = []
    for ch in texto:
        if ch in _EQUIVALENTES:
            salida.append(_EQUIVALENTES[ch])
            continue
        base = unicodedata.normalize("NFKD", ch)[:1].upper()
        salida.append(base if len(base) == 1 and ord(base) < 128 else " ")
    return "".join(salida)


def sin_marcas(texto: str) -> str:
    """Quita las marcas «(cid:9)» que deja la extracción de algunos PDF, sin mover el resto."""
    return _CID_RE.sub(lambda m: " " * len(m.group()), texto)


def en_una_linea(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def frase(texto: str) -> str:
    """Un texto que venía todo en mayúsculas, como frase («Apoyar a la oficina…»)."""
    t = en_una_linea(texto)
    return t[:1].upper() + t[1:].lower() if t.isupper() else t
