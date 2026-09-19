"""Contenido de la carta de presentación (Formato 1) frente al formato que
exige el pliego.

El Formato 1 es un formato tipo de Colombia Compra Eficiente y cambia según
la modalidad (interventoría, obra de infraestructura de transporte, obra de
infraestructura social, menor cuantía). El abogado rechaza cartas a las que
el proponente les quitó o cambió una declaración (ej. el numeral 5 sin
"asumo la responsabilidad de su revisión con la presentación de esta
oferta") o dejó sin diligenciar un cuadro (composición accionaria vacía).
Aquí se verifica que la carta traiga TODAS las cláusulas esenciales de la
modalidad del pliego (las que aparecen en al menos el 90 % de las cartas
reales de esa modalidad, ver scratch_clausulas_formato1.py), sin depender de
la numeración, que los proponentes suelen correr.

Ante la duda la carta va a revisión: es preferible revisar una carta buena
que aprobar una con un defecto.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

_CLAUSULAS = Path(__file__).resolve().parent / "formato1_clausulas.json"

PARADAS = frozenset(
    "DE LA EL LOS LAS DEL Y O EN QUE A AL POR CON PARA SE SU SUS UN UNA LO ES COMO NO SI MI ME HE ESTE ESTA "
    "ESTAS ESTOS SOBRE CUANDO SIN ENTRE LE LES NI YA".split()
)
# Una cláusula está si, en un tramo de la carta, aparece al menos esta
# fracción de sus palabras (tolera errores de OCR y cambios menores de
# redacción, no que falte una frase entera).
COBERTURA_MINIMA = 0.85


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.upper())
    return "".join(c for c in t if not unicodedata.combining(c))


def _secuencia(texto: str) -> list[str]:
    return [w for w in re.findall(r"[A-Z]{3,}", _norm(texto)) if w not in PARADAS]


def palabras_clave(texto: str) -> frozenset[str]:
    return frozenset(_secuencia(texto))


def oraciones(texto: str) -> list[str]:
    """Oraciones de la carta (las cláusulas del formato), con su texto
    original para citarlas."""
    plano = re.sub(r"\s+", " ", texto)
    partes = re.split(r"(?<=[.;:])\s+|\s(?=\d{1,2}\s?[.)]\s+[A-ZÁÉÍÓÚ])", plano)
    return [p.strip(" -") for p in partes if 40 <= len(p.strip()) <= 500]


def _presente_en(clave: list[str], secuencia: list[str], conjunto: frozenset[str]) -> bool:
    objetivo = set(clave)
    necesarias = COBERTURA_MINIMA * len(objetivo)
    if len(objetivo & conjunto) < necesarias:
        return False
    ancho = int(len(clave) * 1.8) + 4
    for i, w in enumerate(secuencia):
        if w in objetivo and len(objetivo & set(secuencia[i : i + ancho])) >= necesarias:
            return True
    return False


@lru_cache(maxsize=1)
def _plantillas() -> dict[str, list[dict]]:
    try:
        return json.loads(_CLAUSULAS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def modalidad_de(texto_pliego: str) -> str | None:
    """Modalidad del Formato 1 que exige el pliego, por su encabezado."""
    t = _norm(texto_pliego)
    if "INTERVENTORIA DE OBRA PUBLICA" in t or "CCE-EICP-GI-11" in t:
        return "interventoria"
    if "MENOR CUANTIA" in t:
        return "menor_cuantia"
    if re.search(r"INFRAESTRUCTURA\s+SOCIAL", t):
        return "obra_social"
    if re.search(r"INFRAESTRUCTURA\s+DE\s+TRANSPORTE", t):
        return "obra_transporte"
    return None


def clausulas_de(modalidad: str | None) -> list[dict]:
    """Cláusulas esenciales ({texto, claves}) de la modalidad; sin modalidad
    conocida, las que comparten todas las modalidades (el núcleo común del
    Formato 1)."""
    plantillas = _plantillas()
    if modalidad in plantillas:
        return plantillas[modalidad]
    if not plantillas:
        return []
    listas = list(plantillas.values())
    return [
        c for c in listas[0]
        if all(any(COBERTURA_MINIMA * len(set(c["claves"])) <= len(set(c["claves"]) & set(o["claves"])) for o in otra) for otra in listas[1:])
    ]


def clausulas_faltantes(texto_carta: str, modalidad: str | None) -> list[str]:
    """Texto de las cláusulas esenciales que la carta no trae."""
    secuencia = _secuencia(texto_carta)
    conjunto = frozenset(secuencia)
    return [c["texto"] for c in clausulas_de(modalidad) if not _presente_en(c["claves"], secuencia, conjunto)]


# --- Cuadro de composición accionaria (numeral "Declaro que…") -------------
# Encabezado de la tabla: "Porcentaje participación | NIT, Cédula o Documento
# de Identificación | Nombre o Razón social del Accionista". Debajo debe haber
# al menos una fila (un porcentaje o un número de documento) antes del
# numeral siguiente.
_ENCABEZADO_COMPOSICION_RE = re.compile(r"RAZON\s+SOCIAL(?:\s+\S+){0,6}?\s+ACCIONISTA|IDENTIFICACION\s+DEL\s+ACCIONISTA")
_FILA_COMPOSICION_RE = re.compile(r"\d{1,3}(?:[.,]\d+)?\s?%|\b\d{1,3}(?:\.\d{3}){2,}\b|\b\d{6,}\b|\bN\.?\s?A\b|NO\s+APLICA")
_SIGUIENTE_NUMERAL_RE = re.compile(r"(?:^|\n)\s*\d{1,2}\s?[.)]\s")


def composicion_accionaria_vacia(texto_carta: str) -> bool:
    """El cuadro de composición accionaria está en la carta y no trae
    ninguna fila (ni un "no aplica")."""
    t = _norm(texto_carta)
    m = _ENCABEZADO_COMPOSICION_RE.search(t)
    if m is None:
        return False
    resto = t[m.end() :]
    fin = _SIGUIENTE_NUMERAL_RE.search(resto)
    tramo = resto[: fin.start()] if fin else resto[:1500]
    return _FILA_COMPOSICION_RE.search(tramo) is None


# --- Aval del ingeniero -----------------------------------------------------
# "…debido a que el suscriptor de la presente propuesta no es ingeniero
# matriculado, yo <NOMBRE> ingeniero con matrícula profesional No. … avalo la
# presente propuesta". Si quien avala es el mismo representante legal que
# suscribe, el párrafo se contradice (el abogado lo rechazó en una oferta real).
_AVAL_RE = re.compile(
    r"SUSCRIPTOR\s+DE\s+LA\s+PRESENTE\s+(?:PROPUESTA|OFERTA)\s+NO\s+ES\s+(?:INGENIERO|ARQUITECTO)[^,]{0,40},?\s*"
    r"YO,?\s+([A-ZÑ][A-ZÑ\s]{5,80}?)\s*,?\s+(?:INGENIERO|ARQUITECTO|IDENTIFICAD|CON\s+MATRICULA|MAYOR)"
)
_REPRESENTANTE_EN_CARTA_RE = re.compile(r"NOMBRE\s+DEL\s+REPRESENTANTE\s+LEGAL\s*:?\s*([A-ZÑ][A-ZÑ\s]{5,80}?)\s*(?:\n|C\.?\s?C|CEDULA|$)")


def avalista_del_parrafo(texto_carta: str) -> str | None:
    m = _AVAL_RE.search(re.sub(r"\s+", " ", _norm(texto_carta)))
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def representante_de_la_carta(texto_carta: str) -> str | None:
    m = _REPRESENTANTE_EN_CARTA_RE.search(_norm(texto_carta))
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


# --- Posición de las firmas ------------------------------------------------
# En un PDF digital la firma escaneada es una imagen con posición conocida.
# Cada raya "(Firma del representante legal)" debe tener una firma encima; si
# una raya quedó vacía y hay una firma puesta en otra parte de la página
# (encima del texto), la carta está mal firmada (oferta real rechazada por el
# abogado: "la firma queda sobrepuesta en el texto, muy alejada de donde debe
# ir"). Solo se juzga lo que se puede medir: páginas con texto y firmas como
# imagen; una página escaneada entera o una firma digital sin imagen no se
# juzgan aquí.
# Rótulos entre paréntesis con la palabra firma: "(Firma del representante
# legal)", "(Nombre y firma de quien avala la propuesta)".
_RAYA_FIRMA_RE = re.compile(r"^\(.{0,40}\bFIRMA\b")
ALTO_FIRMA = (12, 160)
ANCHO_FIRMA = (8, 320)
# Una firma "está sobre la raya" si su imagen toca la franja que va de este
# alto por encima del rótulo "(Firma…)" hasta un poco por debajo: las firmas
# altas suelen montarse sobre la raya y el rótulo.
ARRIBA_DE_LA_RAYA = 110
DEBAJO_DE_LA_RAYA = 10


def _rotulos_de_firma(palabras: list[dict]) -> list[dict]:
    """Líneas de texto que son el rótulo de una raya de firma, con su
    posición (top, x0, x1)."""
    lineas: dict[int, list[dict]] = {}
    for p in palabras:
        lineas.setdefault(round(p["top"] / 3), []).append(p)
    rotulos = []
    for grupo in lineas.values():
        grupo.sort(key=lambda p: p["x0"])
        texto = _norm(" ".join(p["text"] for p in grupo))
        for i, p in enumerate(grupo):
            if p["text"].startswith("(") and _RAYA_FIRMA_RE.match(_norm(" ".join(x["text"] for x in grupo[i:]))):
                fin = next((j for j in range(i, len(grupo)) if ")" in grupo[j]["text"]), len(grupo) - 1)
                rotulos.append({"top": p["top"], "x0": p["x0"], "x1": grupo[fin]["x1"], "texto": texto})
    return rotulos


def firmas_desubicadas(contenido_pdf: bytes, max_paginas: int = 10) -> list[int]:
    """Páginas (desde 1) con una raya de firma vacía y una firma puesta en
    otro lugar de la página."""
    from motor.procesamiento.pdf_utils import abrir_pdf

    paginas = []
    with abrir_pdf(contenido_pdf) as pdf:
        for numero, page in enumerate(pdf.pages[:max_paginas], start=1):
            try:
                rayas = _rotulos_de_firma(page.extract_words())
                if not rayas or len(page.chars) < 200:
                    continue
                firmas = [
                    im for im in page.images
                    if ALTO_FIRMA[0] <= im["bottom"] - im["top"] <= ALTO_FIRMA[1]
                    and ANCHO_FIRMA[0] <= im["x1"] - im["x0"] <= ANCHO_FIRMA[1]
                ]
                if not firmas:
                    continue

                def sobre(im, raya) -> bool:
                    return im["bottom"] >= raya["top"] - ARRIBA_DE_LA_RAYA and im["top"] <= raya["top"] + DEBAJO_DE_LA_RAYA \
                        and im["x1"] >= raya["x0"] - 200 and im["x0"] <= raya["x1"] + 200

                # La raya del aval queda vacía con razón cuando el representante
                # es ingeniero: solo cuentan como vacías las demás.
                rayas_vacias = [r for r in rayas if "AVALA" not in r["texto"] and not any(sobre(im, r) for im in firmas)]
                sueltas = [im for im in firmas if not any(sobre(im, r) for r in rayas)]
                if rayas_vacias and sueltas:
                    paginas.append(numero)
            finally:
                page.flush_cache()
    return paginas
