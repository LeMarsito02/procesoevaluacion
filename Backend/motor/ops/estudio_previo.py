"""Lo que el estudio previo de una prestación de servicios dice del contrato y
del perfil: objeto, plazo, valor, honorarios mensuales, experiencia y posgrado
exigidos y obligaciones específicas. Y el valor del CDP, que debe cubrirlo.

El perfil se toma de la frase del «análisis que soporta el valor estimado»
(«…requiere un arquitecto con experiencia profesional entre veinte (20) y
treinta (30) años, con especialización en… y una experiencia calificada entre
uno (01) y dos (02) años en…»). Cada dato que no se lee queda en None y se
avisa: lo completa una persona.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from motor.ops.honorarios import ESPECIALIZACION, MAESTRIA, SIN_POSGRADO
from motor.ops.idoneidad import Perfil
from motor.ops.relacion import obligaciones_especificas
from motor.ops.texto import en_una_linea, plano

# Encabezado del formato, que se repite en cada página y parte las frases.
_ENCABEZADO_RE = re.compile(
    r"FORMATO\s+CODIGO|GESTION\s+CONTRACTUAL\s+VERSION|ESTUDIOS\s+PREVIOS\s+FECHA|PAGINA\s+\d+\s+DE\s+\d+|^\s*MS-GC-FR-?\s*\d*\s*$"
)
_OBJETO_RE = re.compile(r"OBJETO(?:\s+PARA\s+CONTRATAR)?\s*:\s*(.+?)(?=\n\s*\n|\n\s*\d+\.\s|\n\s*ALCANCE\b)", re.S)
# Un número como lo escriben: «10», «(10)», «DIEZ (10)», «10 (DIEZ)», «UN (01)».
_N = r"(?:[A-Z]+\s*)?\(?(\d{1,2})\)?(?:\s*\([A-Z]+\))?"
_ENTRE = rf"ENTRE\s+{_N}\s+(?:A|Y)\s+{_N}\s+ANOS?"
_PROFESIONAL_RE = re.compile(rf"EXPERIENCIA\s+(?!CALIFICADA|ESPECIFICA|RELACIONADA)(?:[A-Z]+\s+){{0,3}}?{_ENTRE}")
_PROFESIONAL_MINIMA_RE = re.compile(rf"EXPERIENCIA\s+(?!CALIFICADA|ESPECIFICA|RELACIONADA)(?:[A-Z]+\s+){{0,3}}?(?:MINIMA\s+)?DE\s+{_N}\s+ANOS?")
_ESPECIFICA_RE = re.compile(rf"EXPERIENCIA\s+(?:CALIFICADA|ESPECIFICA|RELACIONADA)\s+(?:[A-Z]+\s+){{0,2}}?{_ENTRE}")
_ANALISIS_RE = re.compile(r"ANALISIS\s+QUE\s+SOPORTA\s+EL\s+VALOR")
_INICIO_FRASE_RE = re.compile(r"REQUIERE\s+(?:CONTRATAR\s+)?(?:LOS\s+SERVICIOS\s+DE\s+)?|[.:;]\s*\n|,\s*\n(?=PROFESIONAL)")
_FIN_FRASE_RE = re.compile(r"\.(?=\s)|\n\s*EXPERIENCIA\s+PROFESIONAL\s*\n|\n\s*LOS\s+HONORARIOS\b|\n\s*\n")
_PLAZO_RE = re.compile(rf"PLAZO\s+DE\s+EJECUCION\s*:?\s*\(?\s*{_N}\s*\)?\s*MES")
_PESOS = r"\$?\s*(\d{1,3}(?:\.\d{3})+)(?:[.,]\d{2})?"
_VALOR_RE = re.compile(rf"VALOR\s+ESTIMADO\s+DEL\s+CONTRATO\s*:.{{0,320}}?(?<![\d.]){_PESOS.replace('+', '{2,}')}", re.S)
# Tabla del análisis del valor: «VR MENSUAL  TIEMPO  VR TOTAL» y debajo los dos valores.
_TABLA_VALOR_RE = re.compile(rf"VR\s+MENSUAL\s+TIEMPO\s+VR\s+TOTAL(.{{0,200}}?)(?:TOTAL|\*|\n\s*\n|\Z)", re.S)
_DINERO_RE = re.compile(rf"\${_PESOS[3:]}")
_MESES_RE = re.compile(r"\(?(\d{1,2})\)?\s*\)?\s*(?:\n\s*)?(?:[\d$., ]+\n\s*)?MESES")
_CDP_RE = re.compile(r"TOTAL\s+CDP\s+([\d.,]+)")
# Cuánto antes de la experiencia puede empezar la frase del perfil.
_VENTANA_FRASE = 320


def _pesos(texto: str) -> int:
    return int(re.sub(r"\D", "", texto))


def _sin_encabezados(texto: str) -> str:
    return "\n".join(linea for linea in texto.splitlines() if not _ENCABEZADO_RE.search(plano(linea)))


@dataclass
class EstudioPrevio:
    objeto: str = ""
    plazo_meses: int | None = None
    valor: int | None = None
    perfil: Perfil | None = None
    avisos: list[str] = field(default_factory=list)


def _frase_del_perfil(t: str, experiencia: re.Match[str]) -> tuple[int, int]:
    inicios = list(_INICIO_FRASE_RE.finditer(t, max(0, experiencia.start() - _VENTANA_FRASE), experiencia.start()))
    inicio = inicios[-1].end() if inicios else t.rfind("\n", 0, experiencia.start()) + 1
    fin = _FIN_FRASE_RE.search(t, experiencia.end())
    return inicio, min(fin.start() if fin else len(t), experiencia.end() + 500)


def leer_estudio_previo(texto: str) -> EstudioPrevio:
    original = _sin_encabezados(texto)
    t = plano(original)
    estudio = EstudioPrevio()
    if m := _OBJETO_RE.search(t):
        estudio.objeto = en_una_linea(original[m.start(1):m.end(1)])
    if m := _PLAZO_RE.search(t):
        estudio.plazo_meses = int(m.group(1))
    if m := _VALOR_RE.search(t):
        estudio.valor = _pesos(m.group(1))

    mensual = None
    if (tabla := _TABLA_VALOR_RE.search(t)) and len(valores := [_pesos(v) for v in _DINERO_RE.findall(tabla.group(1))]) >= 2:
        mensual, total = valores[0], valores[1]
        meses = int(m.group(1)) if (m := _MESES_RE.search(tabla.group(1))) else estudio.plazo_meses
        estudio.plazo_meses = estudio.plazo_meses or meses
        estudio.valor = estudio.valor or total
        # Las entidades redondean la mensualidad: se tolera un peso por mes.
        if meses and abs(mensual * meses - total) > meses:
            estudio.avisos.append(f"El análisis del valor no cuadra: ${mensual:,} por {meses} meses no da ${total:,}.".replace(",", "."))
    elif estudio.valor and estudio.plazo_meses:
        mensual = estudio.valor // estudio.plazo_meses

    desde = m.end() if (m := _ANALISIS_RE.search(t)) else 0
    experiencia = (
        _PROFESIONAL_RE.search(t, desde) or _PROFESIONAL_RE.search(t)
        or _PROFESIONAL_MINIMA_RE.search(t, desde) or _PROFESIONAL_MINIMA_RE.search(t)
    )
    if experiencia is None:
        estudio.avisos.append("No se leyó la experiencia que exige el perfil.")
    else:
        inicio, fin = _frase_del_perfil(t, experiencia)
        oracion = t[inicio:fin]
        posgrado = MAESTRIA if re.search(r"MAESTRIA|MAGISTER|DOCTORADO", oracion) else ESPECIALIZACION if "ESPECIALIZACION" in oracion else SIN_POSGRADO
        especifica = _ESPECIFICA_RE.search(oracion)
        estudio.perfil = Perfil(
            anios_minimos=float(experiencia.group(1)),
            anios_maximos=float(experiencia.group(2)) if experiencia.re is _PROFESIONAL_RE else None,
            posgrado=posgrado,
            honorarios_mensuales=mensual or 0,
            obligaciones=obligaciones_especificas(texto),
            especifica_minima=float(especifica.group(1)) if especifica else 0,
            especifica_maxima=float(especifica.group(2)) if especifica else None,
            descripcion=en_una_linea(original[inicio:fin]),
        )
    for dato, nombre in ((estudio.objeto, "el objeto"), (estudio.plazo_meses, "el plazo"), (estudio.valor, "el valor del contrato")):
        if not dato:
            estudio.avisos.append(f"No se leyó {nombre}.")
    if estudio.perfil and not estudio.perfil.honorarios_mensuales:
        estudio.avisos.append("No se leyeron los honorarios mensuales.")
    if estudio.perfil and not estudio.perfil.obligaciones:
        estudio.avisos.append("No se leyeron las obligaciones específicas.")
    return estudio


def valor_del_cdp(texto: str) -> int | None:
    """Total del certificado de disponibilidad presupuestal («TOTAL CDP 90,000,000.00»)."""
    m = _CDP_RE.search(plano(texto))
    if not m:
        return None
    entero = re.split(r"[.,]\d{2}$", m.group(1))[0]
    return _pesos(entero) if re.search(r"\d", entero) else None


def problema_con_el_cdp(estudio: EstudioPrevio, cdp: int | None) -> str | None:
    if cdp is None:
        return "No se leyó el valor del CDP."
    if estudio.valor and estudio.valor > cdp:
        return f"El valor del contrato (${estudio.valor:,}) supera el del CDP (${cdp:,}).".replace(",", ".")
    return None
