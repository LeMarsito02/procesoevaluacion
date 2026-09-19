"""Mide las verificaciones de contenido de la carta sobre las cartas reales:
qué cartas mandaría a revisión y si el abogado las rechazó o aprobó. Solo mide."""
import collections
import json
import sys

sys.path.insert(0, ".")
from motor.evaluacion.formato1_contenido import (avalista_del_parrafo, clausulas_faltantes, composicion_accionaria_vacia,
                                                 representante_de_la_carta)
from motor.evaluacion.formato1 import _nombres_coinciden

MODALIDAD = {"p1": "interventoria_transporte", "p2": "licitacion_social", "p3": "licitacion_transporte", "p4": "menor_cuantia_social"}
GT = {"p1": ".scratch/medicion_comparacion.json", "p3": ".scratch/prueba3/medicion_comparacion.json", "p4": ".scratch/prueba4/medicion_comparacion.json"}
abogado = {}
for p, f in GT.items():
    for c in json.load(open(f)):
        if c["requisito"] == 1:
            abogado[f"{p}/{c['hoja']}"] = c["ground_truth"]
cartas = json.load(open(".scratch/cartas.json"))
cuenta = collections.Counter()
for k, d in sorted(cartas.items()):
    t = d["texto"] or ""
    if not t or t.startswith("ERROR"):
        continue
    motivos = []
    faltan = clausulas_faltantes(t, MODALIDAD[k[:2]])
    if faltan:
        motivos.append(f"faltan {len(faltan)}: " + " | ".join(f[:70] for f in faltan[:2]))
    if composicion_accionaria_vacia(t):
        motivos.append("composición accionaria vacía")
    aval, rl = avalista_del_parrafo(t), representante_de_la_carta(t)
    if aval and rl and _nombres_coinciden(aval, rl):
        motivos.append(f"aval del mismo representante ({aval})")
    gt = abogado.get(k, "?")
    cuenta[(k[:2], gt, bool(motivos))] += 1
    if motivos and (gt != "SI" or "-v" in sys.argv):
        print(k, gt, "|", "; ".join(motivos))
    if not motivos and gt == "NO":
        print("NO DETECTADA:", k)
print()
for (p, gt, marcada), n in sorted(cuenta.items()):
    print(f"{p} abogado={gt:4s} {'a revisión' if marcada else 'pasa':10s} {n}")
