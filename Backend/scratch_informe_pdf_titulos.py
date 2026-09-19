"""Veredictos de un informe de evaluación jurídica en PDF (una ficha por
proponente) emparejando cada requisito por su NOMBRE con la numeración del
programa: hay informes con otro orden (ICCU-LP-022-2026: 13 Procuraduría,
16 RNMC, 17 REDAM, sin RUT). Guarda la nota del abogado bajo cada requisito
("Validado por la entidad", "Documento subsanado"). SOLO para medir."""
import collections
import json
import re
import sys
import unicodedata

import pdfplumber

# Nombre en el informe -> número del requisito en el programa (el orden importa).
TITULOS = [
    (r"CARTA DE PRESENTACION", 1), (r"SUSCRITA O AVALADA", 2), (r"ANTECEDENTES DISCIPLINARIOS PROFESIONALES", 3),
    (r"PROPONENTE PLURAL", 4), (r"REDAM|ALIMENTARIOS", 5), (r"EXISTENCIA Y REPRESENTACION", 6),
    (r"OBJETO SOCIAL", 7), (r"FACULTADES", 8), (r"REGISTRO UNICO DE PROPONENTES|\bRUP\b", 9), (r"^SANCIONES", 10),
    (r"GARANTIA DE SERIEDAD", 11), (r"SEGURIDAD SOCIAL", 12), (r"REGISTRO UNICO TRIBUTARIO|\bRUT\b", 13),
    (r"CONTRALORIA", 14), (r"PROCURADURIA", 15), (r"JUDICIALES", 16), (r"MULTAS|MEDIDAS CORRECTIVAS", 17),
    (r"REVISOR FISCAL", 18),
]
FILA_RE = re.compile(r"^(\d{1,2})\s+(.*?)\s*\b(SI|NO|N\.A\.?)(?=\s|$)(.*)$")
NOTAS_RE = re.compile(r"VALIDADO POR LA ENTIDAD|DOCUMENTO SUBSANADO|SUBSAN\w*|NO APORT\w*|NO CUMPLE[^.]*")


def norm(t):
    t = unicodedata.normalize("NFKD", t.upper())
    return "".join(c for c in t if not unicodedata.combining(c))


def numero_programa(titulo):
    t = norm(titulo)
    return next((n for patron, n in TITULOS if re.search(patron, t)), None)


def main(ruta, salida):
    with pdfplumber.open(ruta) as pdf:
        lineas = [l for p in pdf.pages for l in (p.extract_text() or "").splitlines()]
    proponentes, actual, ultimo = [], None, None
    for linea in lineas:
        m = re.match(r"^PROPONENTE\s+(\d+)\s*$", linea.strip())
        if m:
            hoja = f"P-{int(m.group(1)):02d}"
            # Fichas de dos páginas repiten el encabezado: es el mismo proponente.
            actual = next((p for p in proponentes if p["hoja"] == hoja), None)
            if actual is None:
                actual = {"hoja": hoja, "nombre": "", "requisitos": {}}
                proponentes.append(actual)
            ultimo = None
            continue
        if actual is None:
            continue
        if linea.startswith("Proponente:"):
            actual["nombre"] = linea.split(":", 1)[1].strip()
            continue
        fila = FILA_RE.match(linea.strip())
        if fila:
            n = numero_programa(fila.group(2))
            ultimo = None
            if n is not None and str(n) not in actual["requisitos"]:
                ver = fila.group(3).replace("N.A", "N.A.").replace("N.A..", "N.A.")
                actual["requisitos"][str(n)] = {"veredicto": ver, "nota": ""}
                ultimo = actual["requisitos"][str(n)]
            continue
        if norm(linea).startswith(("NOTA", "UNA VEZ REVISADOS")):
            ultimo = None
            continue
        if ultimo is not None and (nota := NOTAS_RE.search(norm(linea))):
            ultimo["nota"] = (ultimo["nota"] + " " + nota.group(0)).strip()
    json.dump(proponentes, open(salida, "w"), ensure_ascii=False, indent=1)
    conteo = collections.Counter(r["veredicto"] for p in proponentes for r in p["requisitos"].values())
    incompletos = [p["hoja"] for p in proponentes if len(p["requisitos"]) < 17]
    notas = collections.Counter(r["nota"] for p in proponentes for r in p["requisitos"].values() if r["nota"])
    print(f"{len(proponentes)} proponentes · veredictos {dict(conteo)} · incompletos {incompletos[:10]}")
    print("notas:", dict(notas.most_common(6)))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
