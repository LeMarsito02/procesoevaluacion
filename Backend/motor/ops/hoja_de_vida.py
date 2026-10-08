"""Estudios que la persona declara en el formato único de hoja de vida de la
función pública (SIGEP). Es un documento digital y se lee bien, pero es lo que
ella declara, no la prueba: solo se usa cuando el diploma escaneado no se pudo
leer, y queda marcado para que alguien lo confirme contra el diploma."""
from __future__ import annotations

import calendar
import re
from datetime import date

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
