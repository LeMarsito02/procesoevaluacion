"""Proceso 2: lo que dijo el programa frente al acta de adjudicación, a nivel
de proponente. El acta no dice en qué área se descalificó a cada uno y ya
hubo subsanaciones, así que esto NO mide acierto por requisito: responde
dos preguntas de seguridad. Solo mide."""
import collections
import json
import sys

sys.path.insert(0, ".")
from scratch_comparar import nuestro_veredicto

DESCALIFICADOS = {3, 38, 59, 75, 79, 85, 102, 104, 105, 106, 109}
SIN_DATO = {25}
IGNORADOS = {13}

resultados = json.load(open(".scratch/prueba2/medicion_resultados.json"))
filas = []
for hoja, items in sorted(resultados.items(), key=lambda x: int(x[0][2:])):
    n = int(hoja[2:])
    items = [x for x in items if x["requisito"] not in IGNORADOS]
    revision = [x for x in items if nuestro_veredicto(x) in ("NO", "ERROR")]
    acta = "descalificado" if n in DESCALIFICADOS else "sin dato" if n in SIN_DATO else "habilitado"
    filas.append((hoja, acta, len(revision), [x["requisito"] for x in revision], items[0]["nombre_proponente"] if items else ""))

print(f"{len(filas)} proponentes evaluados\n")
print("1) Descalificados en el acta: ¿el programa les marcó algo en lo jurídico?")
for hoja, acta, n, reqs, nombre in filas:
    if acta == "descalificado":
        marca = f"{n} requisito(s) a revisión: {reqs}" if n else "TODO LO JURÍDICO APROBADO → confirmar si la causa fue técnica o financiera"
        print(f"   {hoja} {nombre[:34]:34s} {marca}")
hab = [f for f in filas if f[1] == "habilitado"]
limpios = sum(1 for f in hab if f[2] == 0)
print(f"\n2) Habilitados en el acta (ya subsanados): {len(hab)}")
print(f"   el programa aprobó todo lo jurídico en {limpios} ({100 * limpios / max(len(hab), 1):.0f}%);"
      f" los demás tienen requisitos a revisión (pudieron subsanarse después)")
c = collections.Counter(r for f in hab for r in f[3])
print("   requisitos más enviados a revisión entre los habilitados:", ", ".join(f"Req {r}: {k}" for r, k in c.most_common(8)))
