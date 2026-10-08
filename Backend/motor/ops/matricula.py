"""Matrícula o tarjeta profesional, leída del certificado de vigencia y
antecedentes que expide el consejo de cada profesión (COPNIA, CPNAA, CONALPE,
Comisión de Disciplina Judicial…). Es un documento digital y se lee bien: de
ahí salen la profesión y la fecha de la matrícula, que sirven de referencia
cuando el diploma escaneado no se deja leer."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from motor.ops.texto import en_una_linea, plano
from motor.ops.tiempo import FECHA, fecha_de

ES_CERTIFICADO_RE = re.compile(
    r"REGISTRA\s+MATRICULA\s+PROFESIONAL|CERTIFICADO\s+DE\s+VIGENCIA\s+Y\s+ANTECEDENTES|CERTIFICADO\s+DE\s+SANCIONES\s+VIGENTES|"
    r"SE\s+ENCUENTRA\s+INSCRIT|MATRICULA\s+PROFESIONAL\s+ESTA\s+VIGENTE|ANTECEDENTES\s+DISCIPLINARIOS\s+(?:DE\s+LA\s+)?(?:PROFESION|ABOGAD)"
)
_PROFESION_RE = re.compile(
    r"EN\s+LA\s+PROFESION\s+DE\s+([A-Z ]{4,60}?)\s+CON\s+MATRICULA|MATRICULA\s+PROFESIONAL\s+DE\s+([A-Z ]{4,40}?)\s+NO\b|"
    r"INSCRIT[OA]\s*(?:\(A\))?\s+COMO\s+([A-Z ]{4,40}?)\s*,|QUE\s+(?:EL|LA)\s+(ARQUITECT[OA]|INGENIER[OA]|ABOGAD[OA])\b|"
    r"PARA\s+(ABOGAD)OS"
)
_NUMERO_RE = re.compile(r"(?:MATRICULA\s+PROFESIONAL(?:\s+DE\s+[A-Z ]+?)?|TARJETA\s+PROFESIONAL)\s+(?:NO\.?\s*)?([A-Z]?\d[\w-]{3,})")
_FECHA_RE = re.compile(rf"(?:DESDE\s+EL|EXPEDIDA\s+EL|RESOLUCION\s+NO\.?\s*\d+\s+DEL)\s+({FECHA})")
_SIN_SANCIONES_RE = re.compile(
    r"NO\s+REGISTRA\s+(?:ANTECEDENTES|SANCIONES)|NO\s+HA\s+SIDO\s+SANCIONAD|NO\s+TIENE\s+(?:ANTECEDENTES|SANCIONES)|SIN\s+ANTECEDENTES"
)


@dataclass
class Matricula:
    profesion: str = ""
    numero: str = ""
    fecha: date | None = None
    # El certificado dice que no registra sanciones ni antecedentes.
    sin_sanciones: bool = False


def leer_matricula(texto: str) -> Matricula | None:
    original = texto
    t = plano(original)
    if not ES_CERTIFICADO_RE.search(t):
        return None
    matricula = Matricula(sin_sanciones=bool(_SIN_SANCIONES_RE.search(t)))
    if m := _PROFESION_RE.search(t):
        grupo = next(g for g in range(1, m.re.groups + 1) if m.group(g))
        matricula.profesion = en_una_linea(original[m.start(grupo):m.end(grupo)]).capitalize()
        if matricula.profesion.lower() == "abogad":
            matricula.profesion = "Abogado"
    if m := _NUMERO_RE.search(t):
        matricula.numero = m.group(1)
    if m := _FECHA_RE.search(t):
        matricula.fecha = fecha_de(m.group(1))
    return matricula
