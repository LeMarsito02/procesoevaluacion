"""El nombre del proponente leído de sus propios documentos.

Las ofertas que se bajan del SECOP no dicen de quién son: el portal las nombra
«p100 Download.zip» o «CO1.RPL.5801690_20260923122433.zip». Cuando el nombre
del archivo no identifica a nadie, el proponente aparecería en la pantalla y en
el informe como «Download», así que hay que leerlo de la oferta.

Dónde está el nombre de un proponente plural:

- la carta de presentación: «en mi calidad de representante legal del CONSORCIO
  MARANATHA, en adelante el Consorcio»;
- el Formato 2: «el Consorcio se denomina CONSORCIO MARANATHA».

Un nombre equivocado en un informe oficial es un problema, y estas frases se
leen de documentos escaneados donde la tabla de al lado deja basura pegada
(«CONSORCIO RR 3»). Por eso, cuando los dos documentos declaran el nombre se
exige que coincidan y se toma el más corto; cuando solo uno lo declara se usa
ese, y quien evalúa lo ve con la advertencia de dónde salió.

El Formato 2 se busca exigiendo el código del proceso: los proponentes adjuntan
como experiencia los documentos consorciales de contratos anteriores, y sin esa
condición el proponente terminaría bautizado con el nombre de otro consorcio.
"""
from __future__ import annotations

import re
import unicodedata

from motor.evaluacion.formato1 import encontrar_formato1
from motor.evaluacion.proponente_plural import encontrar_formato2
from motor.procesamiento.pdf_utils import texto_completo

PAGINAS_A_REVISAR = 3

# Hasta dónde llega el nombre: lo que sigue en la frase («, en adelante el
# Consorcio», «identificado con NIT…») no es parte del nombre.
_FIN = r"(?:,|\.|;|\(|EN\s+ADELANTE|IDENTIFICAD[OA]|CON\s+NIT|NIT\b|CONFORMAD[OA]|Y\s+ESTA|$)"
_CUERPO = r"[A-Z0-9Ñ&'\-\. ]{2,60}?"

# «en mi calidad de representante legal del CONSORCIO MARANATHA».
EN_LA_CARTA_RE = re.compile(
    rf"REPRESENTANTE\s+LEGAL\s+DE\s*(?:L|LA)?\s+((?:CONSORCIO|UNION\s+TEMPORAL)\s+{_CUERPO})\s*{_FIN}"
)
# «1. El Consorcio se denomina CONSORCIO MARANATHA».
SE_DENOMINA_RE = re.compile(
    rf"(?:EL\s+CONSORCIO|LA\s+UNION\s+TEMPORAL)\s+SE\s+DENOMINA[:\s]+((?:CONSORCIO|UNION\s+TEMPORAL)?\s*{_CUERPO})\s*{_FIN}"
)


def _norm(texto: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sin_tildes.upper())


def _limpiar(nombre: str) -> str | None:
    limpio = re.sub(r"\s+", " ", nombre).strip(" .,-'")
    # Solo la forma jurídica no es un nombre («CONSORCIO», «UNION TEMPORAL»).
    if limpio in {"CONSORCIO", "UNION TEMPORAL"} or len(limpio) < 5:
        return None
    return limpio[:300]


def de_la_carta(pdfs: dict[str, bytes]) -> str | None:
    """El nombre que el representante declara en la carta de presentación."""
    encontrado = encontrar_formato1(pdfs)
    if encontrado is None:
        return None
    try:
        texto = texto_completo(encontrado[1], max_paginas=PAGINAS_A_REVISAR)
    except Exception:  # noqa: BLE001
        return None
    hallado = EN_LA_CARTA_RE.search(_norm(texto))
    return _limpiar(hallado.group(1)) if hallado else None


def del_formato2(pdfs: dict[str, bytes], codigo_proceso: str | None) -> str | None:
    """El nombre con que el proponente plural se denomina en el Formato 2."""
    encontrado = encontrar_formato2(pdfs, codigo_proceso)
    if encontrado is None:
        return None
    hallado = SE_DENOMINA_RE.search(_norm(encontrado[1]))
    return _limpiar(hallado.group(1)) if hallado else None


def _uno_es_el_otro(a: str, b: str) -> str | None:
    """El nombre común a los dos documentos, si uno empieza como el otro.

    El más corto es el bueno: el largo trae pegado lo que había al lado en la
    página («CONSORCIO EDUCATIVO 26» y «CONSORCIO EDUCATIVO 26 3»)."""
    corto, largo = sorted((a, b), key=len)
    return corto if largo.startswith(corto) else None


def leer(pdfs: dict[str, bytes], codigo_proceso: str | None = None) -> tuple[str, str] | None:
    """(nombre, de dónde salió) del proponente, o None si sus documentos no lo dicen."""
    carta = de_la_carta(pdfs)
    formato2 = del_formato2(pdfs, codigo_proceso)
    if carta and formato2:
        comun = _uno_es_el_otro(carta, formato2)
        if comun:
            return comun, "la carta de presentación y el Formato 2"
        # Dos nombres distintos: no se elige por el evaluador.
        return None
    if carta:
        return carta, "la carta de presentación"
    if formato2:
        return formato2, "el Formato 2"
    return None
