"""Títulos académicos del contratista (actas de grado y diplomas).

De cada página que parece un título se saca el nivel y la fecha de grado. La
fecha de grado del pregrado es desde donde cuenta la experiencia profesional;
el posgrado más alto decide la columna de la tabla de honorarios. El diploma
de bachiller suele venir en el mismo archivo: se reconoce y no cuenta.

Los diplomas casi siempre vienen escaneados y con letra de adorno: si no se
lee la fecha, queda en None y va a revisión. Nunca se toma como fecha de grado
la de una resolución, un decreto o un registro que cite el documento.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date

from motor.ops.honorarios import ESPECIALIZACION, MAESTRIA
from motor.ops.texto import en_una_linea, plano, sin_marcas
from motor.ops.tiempo import fechas_en

PROFESIONAL = "profesional"
TECNOLOGO = "tecnologo"
TECNICO = "tecnico"
BACHILLER = "bachiller"

# Para reconocer el archivo de títulos entre los documentos.
ES_TITULO_RE = re.compile(r"ACTA\s+(?:INDIVIDUAL\s+)?DE\s+(?:GRADO|PREGRADO)|TITULO\s+(?:PROFESIONAL\s+)?DE|CEREMONIA\s+DE\s+GRAD|ACTO\s+DE\s+GRADUACION|OTORGA\s+EL\s+TITULO")
# Para decidir si una página de ese archivo es un título.
_PAGINA_DE_TITULO_RE = re.compile(
    r"ACTA\s+(?:INDIVIDUAL\s+)?DE\s+(?:GRADO|PREGRADO)|TITULO|CONFIERE|CONFIRI|OTORG|GRADUACION|DIPLOMA|\bGRADO\s+DE\b"
)
# Del nivel más alto al más bajo: un acta de especialización también dice «profesional».
_NIVELES = [
    (BACHILLER, re.compile(r"\bBACHILLER")),
    (MAESTRIA, re.compile(r"\b(?:MAESTRIA|MAGISTER|MASTER|DOCTORADO|DOCTORA?\s+EN)\b")),
    (ESPECIALIZACION, re.compile(r"\bESPECIALI(?:ZACION|STA)\b")),
    (TECNOLOGO, re.compile(r"\bTECNOLOG[OA]\b")),
    (TECNICO, re.compile(r"\bTECNIC[OA]\s+(?:PROFESIONAL|LABORAL)\b")),
]
_NOMBRE_POSGRADO_RE = re.compile(r"\b((?:ESPECIALISTA|MAGISTER|MASTER|DOCTORA?)\s+EN\s+[A-Z ]{5,90})")
_PROFESIONES = (
    r"ARQUITECT[OA]|ABOGAD[OA]|ECONOMISTA|CONTADORA?\s+PUBLIC[OA]|PSICOLOG[OA]|MEDIC[OA](?:\s+CIRUJAN[OA])?|ODONTOLOG[OA]|"
    r"POLITOLOG[OA]|SOCIOLOG[OA]|ANTROPOLOG[OA]|BIOLOG[OA]|GEOLOG[OA]|TOPOGRAF[OA]|ENFERMER[OA]|COMUNICADORA?\s+SOCIAL|"
    r"TRABAJADORA?\s+SOCIAL|INGENIER[OA]\s+(?:[A-Z]+\s+){0,2}[A-Z]+|ADMINISTRADORA?\s+(?:[A-Z]+\s+){0,3}[A-Z]+|"
    r"LICENCIAD[OA]\s+EN\s+(?:[A-Z]+\s+){0,3}[A-Z]+|PROFESIONAL\s+EN\s+(?:[A-Z]+\s+){0,3}[A-Z]+|DISENADORA?\s+(?:[A-Z]+\s+){0,2}[A-Z]+"
)
_NOMBRE_PREGRADO_RE = re.compile(rf"TITULO\s+(?:PROFESIONAL\s+)?DE\s*:?\s*\n?\s*((?:{_PROFESIONES}))|^\s*-?\s*({_PROFESIONES})\s*$", re.M)
_PROFESION_SUELTA_RE = re.compile(rf"\b({_PROFESIONES})\b")
# Una fecha precedida de esto es de una norma o un registro, no del grado.
_NO_ES_DEL_GRADO_RE = re.compile(r"RESOLUCION|DECRETO|\bLEY\b|ACUERDO|REGISTRO|PERSONERIA|APROBAD[OA]\s+POR|ICFES|SNIES")
_VENTANA_NORMA = 48


@dataclass
class Titulo:
    nivel: str
    nombre: str
    fecha: date | None
    archivo: str = ""
    pagina: int | None = None
    # Lo declara la persona en su hoja de vida; el diploma no se pudo leer.
    declarado: bool = False


def _fecha_de_grado(t: str) -> date | None:
    """La fecha que más se repite en la página y no pertenece a una norma."""
    candidatas = [f for pos, f in fechas_en(t) if not _NO_ES_DEL_GRADO_RE.search(t, max(0, pos - _VENTANA_NORMA), pos)]
    if not candidatas:
        return None
    veces = Counter(candidatas)
    return max(candidatas, key=lambda f: (veces[f], -candidatas.index(f)))


def leer_titulos(paginas: list[str], archivo: str = "") -> list[Titulo]:
    titulos: list[Titulo] = []
    for i, pagina in enumerate(paginas, 1):
        original = sin_marcas(pagina)
        t = plano(original)
        if not _PAGINA_DE_TITULO_RE.search(t):
            continue
        nivel = next((n for n, patron in _NIVELES if patron.search(t)), PROFESIONAL)
        if nivel in (MAESTRIA, ESPECIALIZACION):
            m = _NOMBRE_POSGRADO_RE.search(t)
        elif nivel == PROFESIONAL:
            m = _NOMBRE_PREGRADO_RE.search(t) or _PROFESION_SUELTA_RE.search(t)
        else:
            m = None
        grupo = next((g for g in range(1, (m.re.groups if m else 0) + 1) if m.group(g)), None)
        nombre = en_una_linea(original[m.start(grupo):m.end(grupo)]) if grupo else ""
        if grupo and nivel in (MAESTRIA, ESPECIALIZACION) and nombre.isupper():
            # El nombre largo sigue en el renglón de abajo («…DE PROYECTOS / PARA EL DESARROLLO»).
            resto = original[m.end(grupo):].split("\n", 2)
            if len(resto) > 1 and not resto[0].strip() and 3 < len(resto[1].strip()) <= 60 and resto[1].strip().isupper():
                nombre = f"{nombre} {en_una_linea(resto[1])}"
        titulos.append(Titulo(nivel=nivel, nombre=nombre, fecha=_fecha_de_grado(t), archivo=archivo, pagina=i))
    return titulos


def fecha_de_grado(titulos: list[Titulo]) -> date | None:
    """El grado más antiguo de pregrado: desde ahí cuenta la experiencia
    profesional. La fecha leída del diploma vale más que la declarada."""
    for declarado in (False, True):
        fechas = [t.fecha for t in titulos if t.nivel == PROFESIONAL and t.fecha and t.declarado == declarado]
        if fechas:
            return min(fechas)
    return None
