"""Dónde está el trabajo que el programa todavía le deja a la persona.

Lee `.scratch/medicion_comparacion.json` (lo escribe scratch_medicion.py) y
responde tres preguntas, en este orden de importancia:

1. ¿El programa aprobó algo que el abogado rechazó? (nunca debería pasar)
2. ¿Qué requisitos mandan más casos a revisión humana?
3. Dentro de cada uno, ¿qué motivo se repite? Ahí está el trabajo por hacer.

Solo mide: nada de aquí alimenta la lógica del programa.
"""
from __future__ import annotations

import collections
import json
import re
import sys

COMPARACION = ".scratch/medicion_comparacion.json"
# Veredictos que obligan a que una persona abra el documento.
A_REVISION = {"NO", "ERROR", "?"}


def patron(motivo: str) -> str:
    """Motivo sin los datos del caso concreto, para poder agruparlos."""
    t = (motivo or "sin motivo").strip()
    t = re.sub(r"\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}", "<fecha>", t)
    t = re.sub(r"\b\d[\d.,]*\b", "<número>", t)
    t = re.sub(r"«[^»]*»|\"[^\"]*\"", "«…»", t)
    return t[:110]


def main() -> None:
    with open(COMPARACION) as f:
        comparacion = json.load(f)
    if not comparacion:
        sys.exit("No hay comparación: corra primero run_medicion.sh")

    total = len(comparacion)
    aciertos = sum(c["coincide"] for c in comparacion)
    revision = [c for c in comparacion if c["nuestro"] in A_REVISION]
    print(f"Verificaciones medidas: {total} · coincidencia {100 * aciertos / total:.1f}% "
          f"· a revisión humana {len(revision)} ({100 * len(revision) / total:.1f}%)\n")

    # 1. Lo más grave: aprobado por el programa, rechazado por el abogado.
    peligrosos = [c for c in comparacion if c["nuestro"] in ("SI", "N.A.") and c["ground_truth"] == "NO"]
    print(f"APROBADOS QUE EL ABOGADO RECHAZÓ: {len(peligrosos)}")
    for c in peligrosos:
        print(f"  {c['hoja']} Req {c['requisito']}: {c['nota_gt'][:110]}")

    # 2. Revisión humana que el informe confirma innecesaria: el abogado sí lo
    #    aprobó. Cada uno de estos es trabajo que el programa podría ahorrar.
    evitables = [c for c in revision if c["ground_truth"] in ("SI", "N.A.")]
    print(f"\nREVISIONES EVITABLES (el abogado lo aprobó): {len(evitables)} de {len(revision)}")
    print("\nPor requisito:")
    por_req = collections.Counter(c["requisito"] for c in evitables)
    del_req = collections.Counter(c["requisito"] for c in comparacion)
    for req, n in por_req.most_common():
        print(f"  Req {req:2d}: {n:3d} evitables de {del_req[req]} proponentes ({100 * n / del_req[req]:.0f}%)")

    # 3. El motivo concreto, que es lo que hay que arreglar.
    print("\nMotivos más repetidos (requisito · veces · ejemplo):")
    motivos = collections.Counter((c["requisito"], patron(c["motivo_nuestro"])) for c in evitables)
    ejemplos = {}
    for c in evitables:
        ejemplos.setdefault((c["requisito"], patron(c["motivo_nuestro"])), c)
    for (req, mot), n in motivos.most_common(15):
        ej = ejemplos[(req, mot)]
        print(f"  Req {req:2d} · {n:3d} · {mot}")
        print(f"          ej. {ej['hoja']} → {(ej['archivo_nuestro'] or 'sin archivo')[:90]}")

    # 4. Errores duros (el programa no pudo ni evaluar).
    errores = [c for c in comparacion if c["nuestro"] == "ERROR"]
    if errores:
        print(f"\nERRORES DE EJECUCIÓN: {len(errores)}")
        for (req, mot), n in collections.Counter((c["requisito"], patron(c["motivo_nuestro"])) for c in errores).most_common(8):
            print(f"  Req {req:2d} · {n:3d} · {mot}")


if __name__ == "__main__":
    main()
