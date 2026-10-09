"""El formato único de hoja de vida de la función pública (SIGEP).

Dos usos:

- Experiencia: la que cuenta debe estar relacionada en esta hoja de vida. Una
  certificación de un periodo que la persona no relacionó aquí no es válida.
  Se cruza por fechas: el periodo certificado debe quedar cubierto por lo
  relacionado en el SIGEP.
- Estudios: es lo que la persona declara, no la prueba. Solo se usan cuando el
  diploma escaneado no se pudo leer, y quedan marcados para confirmarlos.

Cuando la hoja de vida viene escaneada no siempre se leen sus fechas: en ese
caso no se da por bueno ni por malo, y lo confirma una persona.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from motor.ops.honorarios import ESPECIALIZACION, MAESTRIA
from motor.ops.texto import en_una_linea, plano
from motor.ops.titulos import PROFESIONAL, TECNICO, TECNOLOGO, Titulo

_SECCION_RE = re.compile(r"EDUCACION\s+SUPERIOR.*?(?=EDUCACION\s+PARA\s+EL\s+TRABAJO|\bIDIOMAS\b|\Z)", re.S)
# «PREGRADO 10 X INGENIERIA AGRONOMICA 12 1986 1234»: modalidad, semestres, graduado, título, mes y año.
_FILA_RE = re.compile(
    r"^[ \t]*(PREGRADO|POSTGRADO|POSGRADO|UN|ES|MG|DOC|TC|TL|TE)[ \t]+\d{1,2}[ \t]+X[ \t]*(.*?)[ \t]*(\d{1,2})[ \t]+((?:19|20)\d{2})\b[^\n]*$", re.M
)
_MODALIDAD_AL_INICIO_RE = re.compile(r"[ \t]*(?:PREGRADO|POSTGRADO|POSGRADO|UN|ES|MG|DOC|TC|TL|TE)[ \t]+\d")
_ENCABEZADO_RE = re.compile(r"MODALIDAD|ACADEMICA|APROBADOS|SEMESTRES|\bSI\s+NO\b|MES\s+ANO|DILIGENCIE|RELACIONE|\(")
_MODALIDAD = {"UN": PROFESIONAL, "PREGRADO": PROFESIONAL, "ES": ESPECIALIZACION, "MG": MAESTRIA, "DOC": MAESTRIA, "TC": TECNICO, "TL": TECNOLOGO, "TE": TECNOLOGO}


def estudios_declarados(texto: str, archivo: str = "") -> list[Titulo]:
    seccion = _SECCION_RE.search(plano(texto))
    if not seccion:
        return []
    original, t = texto[seccion.start():seccion.end()], seccion.group()
    filas = list(_FILA_RE.finditer(t))
    lineas = [(m.start(), m.end()) for m in re.finditer(r"[^\n]+", t)]
    titulos: list[Titulo] = []
    for fila in filas:
        modalidad, _, mes, anio = fila.groups()
        partes = [original[fila.start(2):fila.end(2)]]
        if len(partes[0].strip()) < 4:
            # El nombre no cupo en la fila: quedó partido en la línea de encima y la de debajo.
            i = next(k for k, (a, b) in enumerate(lineas) if a <= fila.start() < b)
            for k, antes in ((i - 1, True), (i + 1, False)):
                if 0 <= k < len(lineas):
                    a, b = lineas[k]
                    if not _MODALIDAD_AL_INICIO_RE.match(t[a:b]) and not _ENCABEZADO_RE.search(t[a:b]) and re.search(r"[A-Z]{4,}", t[a:b]):
                        partes.insert(0, original[a:b]) if antes else partes.append(original[a:b])
        nombre = en_una_linea(" ".join(partes))
        n = plano(nombre)
        if modalidad in ("POSTGRADO", "POSGRADO"):
            nivel = MAESTRIA if re.search(r"MASTER|MAGISTER|MAESTRIA|DOCTOR", n) else ESPECIALIZACION
        else:
            nivel = _MODALIDAD[modalidad]
        try:
            fecha = date(int(anio), int(mes), calendar.monthrange(int(anio), int(mes))[1])
        except ValueError:
            fecha = None
        titulos.append(Titulo(nivel=nivel, nombre=nombre, fecha=fecha, archivo=archivo, pagina=1, declarado=True))
    return titulos


# --- Experiencia relacionada en la hoja de vida ---
_BLOQUE_RE = re.compile(r"EMPRESA\s+O\s+ENTIDAD\b[^\n]*\n(.*?)(?=EMPRESA\s+O\s+ENTIDAD\b|TIEMPO\s+TOTAL\s+DE\s+EXPERIENCIA|\Z)", re.S)
_DIA_MES_ANIO_RE = re.compile(r"DIA\s*:?\s*(\d{1,2})\s+MES\s*:?\s*(\d{1,2})\s+ANO\s*:?\s*(\d{4})")
_CARGO_RE = re.compile(r"CARGO\s+O\s+CONTRATO[^\n]*\n([^\n]+)")
_PAIS_RE = re.compile(r"\s+[X*]?\s*(?:C?S?OLOMBIA|ESPANA|[A-Z]+)\s*$")
# Un periodo está en el SIGEP si lo relacionado allí cubre al menos esta parte de sus días.
COBERTURA_MINIMA = 0.8
EN_SIGEP, NO_ESTA, ILEGIBLE, SIN_HOJA = "si", "no", "ilegible", "sin_hoja"
_GENERICAS = frozenset(
    "MUNICIPIO ALCALDIA MUNICIPAL DEPARTAMENTO GOBERNACION INSTITUTO CORPORACION EMPRESA EMPRESAS COMPANIA SOCIEDAD LTDA COLOMBIA "
    "NACIONAL REGIONAL AUTONOMA PUBLICAS SERVICIOS GRUPO".split()
)


@dataclass
class Declarada:
    entidad: str
    inicio: date
    fin: date | None  # None: sigue ahí (el empleo o contrato actual)
    cargo: str = ""


@dataclass
class ExperienciaDeclarada:
    experiencias: list[Declarada] = field(default_factory=list)
    # Empleos que trae la hoja de vida, se les hayan leído o no las fechas.
    bloques: int = 0

    @property
    def confiable(self) -> bool:
        """Se leyeron las fechas de todos los empleos: lo que no aparezca aquí, no está."""
        return self.bloques > 0 and len(self.experiencias) == self.bloques


def _fecha(dia: str, mes: str, anio: str) -> date | None:
    try:
        return date(int(anio), int(mes), int(dia))
    except ValueError:
        return None


def experiencia_declarada(texto: str) -> ExperienciaDeclarada:
    t = plano(texto)
    declarada = ExperienciaDeclarada()
    for bloque in _BLOQUE_RE.finditer(t):
        cuerpo, original = bloque.group(1), texto[bloque.start(1):bloque.end(1)]
        primera = cuerpo.split("\n", 1)[0]
        fechas = [f for f in (_fecha(*m.groups()) for m in _DIA_MES_ANIO_RE.finditer(cuerpo)) if f]
        if not re.search(r"[A-Z]{3,}", _PAIS_RE.sub("", primera)) and not fechas:
            continue  # el renglón en blanco que trae el formato al final
        declarada.bloques += 1
        if not fechas:
            continue
        entidad = en_una_linea(_PAIS_RE.sub("", original.split("\n", 1)[0]))
        cargo = _CARGO_RE.search(cuerpo)
        declarada.experiencias.append(Declarada(
            entidad=entidad, inicio=fechas[0], fin=fechas[1] if len(fechas) > 1 and fechas[1] >= fechas[0] else None,
            cargo=en_una_linea(original[cargo.start(1):cargo.end(1)]) if cargo else "",
        ))
    return declarada


def _palabras(nombre: str) -> set[str]:
    return {w for w in re.findall(r"[A-Z]{4,}", plano(nombre))} - _GENERICAS


def en_el_sigep(inicio: date, fin: date, declarada: ExperienciaDeclarada | None, hasta: date | None, entidad: str = "") -> tuple[str, list[Declarada]]:
    """Si un periodo certificado está relacionado en la hoja de vida, y las
    experiencias de allí que lo cubren. `hasta` cierra los empleos que la
    persona relaciona como actuales."""
    if declarada is None:
        return SIN_HOJA, []
    cierre = hasta or date.today()
    cubren = [d for d in declarada.experiencias if d.inicio <= fin and (d.fin or cierre) >= inicio]
    dias = {inicio + timedelta(days=i) for i in range((fin - inicio).days + 1)}
    cubiertos = {d for d in dias if any(x.inicio <= d <= (x.fin or cierre) for x in cubren)}
    if len(cubiertos) >= COBERTURA_MINIMA * len(dias):
        return EN_SIGEP, cubren
    return (NO_ESTA if declarada.confiable else ILEGIBLE), cubren


def misma_entidad(entidad: str, cubren: list[Declarada]) -> bool | None:
    """Si la entidad de la certificación es alguna de las que la cubren en el
    SIGEP (comparten una palabra propia). None si no se puede comparar."""
    propias = _palabras(entidad)
    if not propias or not cubren:
        return None
    declaradas = [_palabras(d.entidad) for d in cubren]
    if not any(declaradas):
        return None
    return any(propias & d for d in declaradas)
