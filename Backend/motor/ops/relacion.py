"""Experiencia relacionada: la de contratos o cargos con las mismas
obligaciones del contrato que se va a celebrar.

Se compara cada obligación específica del estudio previo con las obligaciones
o funciones que trae la certificación. «Iguales» es casi palabra por palabra:
las entidades copian la obligación de un contrato al siguiente y cambian, si
acaso, un par de términos. Es una propuesta: la confirma una persona.
"""
from __future__ import annotations

import re

from motor.ops.texto import en_una_linea, plano
from motor.tecnica.rup import normalizar

# Parecido mínimo (palabras en común sobre palabras de las dos) para dar dos
# obligaciones por iguales.
PARECIDO_MINIMO = 0.75
_PALABRA_RE = re.compile(r"[A-Z]{4,}")
_VACIAS = frozenset(
    "PARA COMO ESTE ESTA ESTOS ESTAS SOBRE ENTRE DESDE HASTA CADA TODO TODOS TODAS DEMAS CUANDO DONDE "
    "ACUERDO CONFORMIDAD GENERAL DICHO DICHA MISMO MISMA SEAN SEGUN".split()
)
_ITEM_RE = re.compile(r"(?:^|\n)\s*(?:\d{1,2}|[A-Z])\s*[.)]\s*")
_ESPECIFICAS_RE = re.compile(r"OBLIGACIONES\s+ESPECIFICAS\s*:?(.*?)(?=OBLIGACIONES\s+DE(?:L|\s+LA)\b|\Z)", re.S)
# Encabezado del formato que se repite en cada página y parte la lista.
_ENCABEZADO_RE = re.compile(r"FORMATO\s+CODIGO|GESTION\s+CONTRACTUAL\s+VERSION|ESTUDIOS\s+PREVIOS\s+FECHA|PAGINA\s+\d+\s+DE\s+\d+|^\s*MS-GC-FR-?\s*\d*\s*$")


def _palabras(texto_norm: str) -> frozenset[str]:
    return frozenset(_PALABRA_RE.findall(texto_norm)) - _VACIAS


def _items(texto_norm: str) -> list[str]:
    return [re.sub(r"\s+", " ", i).strip() for i in _ITEM_RE.split(texto_norm) if len(i.strip()) > 40]


def obligaciones_especificas(texto: str) -> list[str]:
    """Las obligaciones específicas del contratista en el estudio previo, como las escribió la entidad."""
    original = "\n".join(linea for linea in texto.splitlines() if not _ENCABEZADO_RE.search(plano(linea)))
    t = plano(original)
    m = _ESPECIFICAS_RE.search(t)
    if not m:
        return []
    cortes = [m.start(1), *(c.end() for c in _ITEM_RE.finditer(t, m.start(1), m.end(1))), m.end(1)]
    inicios = [c.start() for c in _ITEM_RE.finditer(t, m.start(1), m.end(1))] + [m.end(1)]
    items = [original[cortes[i + 1]:inicios[i + 1]] for i in range(len(inicios) - 1)] if len(inicios) > 1 else []
    return [en_una_linea(i) for i in items if len(i.strip()) > 40]


def obligaciones_iguales(obligaciones: list[str], texto_certificacion: str) -> list[int]:
    """Números (desde 1) de las obligaciones del estudio previo que la
    certificación trae casi palabra por palabra."""
    propias = [_palabras(i) for i in _items(normalizar(texto_certificacion))]
    iguales = []
    for n, obligacion in enumerate(obligaciones, 1):
        buscada = _palabras(normalizar(obligacion))
        if buscada and any(len(buscada & p) / len(buscada | p) >= PARECIDO_MINIMO for p in propias if p):
            iguales.append(n)
    return iguales
