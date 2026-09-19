"""Genera las cláusulas esenciales del Formato 1 (carta de presentación) por
modalidad, a partir de las cartas reales de los procesos de prueba: una
cláusula es esencial si aparece en al menos el 90 % de las cartas del proceso
de esa modalidad. De cada cláusula se guardan solo las palabras comunes a
casi todas las cartas (se van nombres, correos) y se descartan las que
dependen del proceso (objeto, entidad, código). Salida:
motor/evaluacion/formato1_clausulas.json. Se corre de nuevo cuando llegan
cartas de una modalidad nueva."""
from __future__ import annotations

import collections
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, ".")
from motor.evaluacion.formato1_contenido import _norm, _presente_en, _secuencia, oraciones
from motor.parsers.documento_base import build_proceso

CARTAS = ".scratch/cartas.json"
PROCESOS = {
    "p1": ("interventoria_transporte", "../Documento Base v3 - definitivos apertura.pdf"),
    "p2": ("licitacion_social", "../PRUEBASMIEVALUADOR/Prueba2/4. Pliego Definitivo IED Tibacuy.pdf"),
    "p3": ("licitacion_transporte", "../PRUEBASMIEVALUADOR/Prueba3/Documento base def.pdf"),
    "p4": ("menor_cuantia_social", "../PRUEBASMIEVALUADOR/Prueba4/Documento Base o Documento Tipo CCE-EICP-GI-02 Menor Cuantia-DEFINITIVO (1).pdf"),
}
# Modalidades sin cartas reales: el Formato 1 oficial de Colombia Compra.
FORMATOS_CCE = "motor/evaluacion/formatos_cce"
UMBRAL_ESENCIAL = 0.9
MINIMO_CLAVES = 6
# Partes de la carta que no son declaraciones: encabezado, introducción con
# el nombre del proponente, cuadro de composición y sus casillas, bloque de
# firma, línea de referencia del proceso. Los proponentes las adaptan (borran
# filas que no aplican) y el abogado lo acepta; el cuadro tiene su propia
# verificación (composicion_accionaria_vacia).
ESTRUCTURA_RE = re.compile(
    r"PORCENTAJE|ACCIONISTA|SUBORDINADA|SUBSIDIARIA|FILIAL|MATRIZ|ATENTAMENTE|NOMBRE DEL PROPONENTE|CARTA DE PRESENTACION"
    r"|EN MI CALIDAD|CALIDAD DE REPRESENTANTE|EN ADELANTE EL|COMPOSICION ACCIONARIA|DILIGENCIAR POR CADA|PERSONA JURIDICA EXTRANJERA"
    r"|GRUPO EMPRESARIAL|COTIZA EN BOLSA|PERSONA NATURAL\s*_|MARQUE CON UNA X|REFERENCIA:|PROCESO DE CONTRATACION [A-Z]{2,6}-"
)
ENTIDAD = set("INSTITUTO CAMINOS CONSTRUCCIONES CUNDINAMARCA ICCU SENORES CALLE BOGOTA SEDE ADMINISTRATIVA TORRE CENTRAL PISO".split())
SALIDA = "motor/evaluacion/formato1_clausulas.json"


def _recortar(texto: str, claves: list[str]) -> str:
    """El texto de la cláusula desde su primera palabra común hasta la
    última: sin nombres ni datos del proponente que la rodeaban."""
    from motor.evaluacion.formato1_contenido import _norm

    palabras = texto.split()
    dentro = [i for i, p in enumerate(palabras) if re.sub(r"[^A-Z]", "", _norm(p)) in set(claves)]
    return " ".join(palabras[dentro[0] : dentro[-1] + 1]) if dentro else texto


def main():
    cartas = json.load(open(CARTAS))
    resultado = {}
    for proceso, (modalidad, documento_base) in PROCESOS.items():
        textos = [d["texto"] for k, d in cartas.items() if k.startswith(proceso + "/") and d["texto"] and not d["texto"].startswith("ERROR")]
        base = build_proceso("X", date(2026, 1, 1), open(documento_base, "rb").read())
        propias = ENTIDAD | set(_secuencia(base.objeto_general + " " + " ".join(l.numero for l in base.lotes)))
        secuencias = [_secuencia(t) for t in textos]
        conjuntos = [frozenset(s) for s in secuencias]
        frecuencia = collections.Counter(w for c in conjuntos for w in c)
        comunes = {w for w, f in frecuencia.items() if f >= UMBRAL_ESENCIAL * len(textos)}

        candidatas, vistas = [], set()
        for t in textos[:20]:  # de 20 cartas basta: una esencial está en casi todas
            for o in oraciones(t):
                if "@" in o or re.search(r"\d{4,}", o) or ESTRUCTURA_RE.search(_norm(o)):
                    continue
                claves = [w for w in _secuencia(o) if w in comunes]
                if len(claves) < MINIMO_CLAVES or sum(w in propias for w in set(claves)) >= 2:
                    continue
                llave = frozenset(claves)
                if llave not in vistas:
                    vistas.add(llave)
                    candidatas.append((re.sub(r"^\d{1,2}\s+", "", o), claves))
        esenciales = []
        for texto, claves in candidatas:
            presentes = sum(_presente_en(claves, s, c) for s, c in zip(secuencias, conjuntos))
            if presentes >= UMBRAL_ESENCIAL * len(textos):
                esenciales.append((texto, claves))
        elegidas = []
        for texto, claves in sorted(esenciales, key=lambda x: -len(set(x[1]))):
            if not any(set(claves) <= set(c) for _, c in elegidas):
                elegidas.append((texto, claves))
        resultado[modalidad] = [{"texto": _recortar(t, c)[:300], "claves": c} for t, c in elegidas]
        print(f"{modalidad}: {len(textos)} cartas, {len(candidatas)} candidatas, {len(elegidas)} esenciales")
    for archivo in sorted(Path(FORMATOS_CCE).glob("formato1_*.docx")):
        modalidad = archivo.stem.removeprefix("formato1_")
        if modalidad in resultado:
            continue  # ya hay cartas reales de esta modalidad: mandan ellas
        resultado[modalidad] = clausulas_oficiales(archivo)
        print(f"{modalidad}: formato oficial, {len(resultado[modalidad])} esenciales")
    json.dump(resultado, open(SALIDA, "w"), ensure_ascii=False, indent=1)


def clausulas_oficiales(archivo: Path) -> list[dict]:
    """Declaraciones del Formato 1 oficial: sin instrucciones ni campos por
    llenar ("[…]"), sin partes estructurales (cuadros, firma)."""
    import docx

    d = docx.Document(str(archivo))
    texto = "\n".join(p.text for p in d.paragraphs)
    elegidas = []
    for o in oraciones(texto):
        o = re.sub(r"^\d{1,2}\s*[.)]\s*", "", o)
        if "[" in o or "]" in o or "__" in o or ESTRUCTURA_RE.search(_norm(o)):
            continue
        claves = _secuencia(o)
        if len(set(claves)) >= MINIMO_CLAVES and not any(set(claves) <= set(c["claves"]) for c in elegidas):
            elegidas.append({"texto": o[:300], "claves": claves})
    return elegidas


if __name__ == "__main__":
    main()
