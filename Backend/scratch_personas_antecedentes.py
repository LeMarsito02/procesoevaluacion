"""Cuando decimos "no se aportó el certificado de <persona>", ¿es verdad?

Para cada caso en que el abogado aprobó y nosotros pedimos revisión por falta
del certificado de alguien, compara las personas que exigimos con los nombres
que aparecen en los certificados de esa entidad dentro de la oferta.

- Ningún certificado a ese nombre → el proponente no lo aportó: el abogado lo
  consultó en línea y el programa acertó al pedir revisión.
- Hay uno con un nombre parecido → lo estamos emparejando mal: eso sí se
  arregla.

Solo mide: no alimenta la lógica del programa.
"""
from __future__ import annotations

import collections
import json
import os
import sys

sys.path.insert(0, ".")
os.environ.setdefault("DRIVE_SOLO_CACHE", "1")

from dotenv import load_dotenv

load_dotenv(".env")

from motor.evaluacion import antecedentes as ant
from motor.evaluacion.formato1 import _nombres_coinciden, obtener_tipo_proponente
from motor.evaluacion.proponente_plural import obtener_personas_a_verificar
from motor.integrations.drive import download_file_bytes, list_proponentes
from motor.procesamiento.zip_utils import extraer_pdfs

COMPARACION = ".scratch/medicion_comparacion.json"
SALIDA = ".scratch/personas_antecedentes.json"


def main() -> None:
    with open(COMPARACION) as f:
        comparacion = json.load(f)

    configs = {c.requisito: c for c in ant._configs()}
    casos = collections.defaultdict(set)
    for c in comparacion:
        if (
            c["nuestro"] in ("NO", "ERROR")
            and c["ground_truth"] in ("SI", "N.A.")
            and "no se aportó" in (c["motivo_nuestro"] or "")
            and c["requisito"] in configs
        ):
            casos[c["hoja"]].add(c["requisito"])
    print(f"Proponentes con personas sin certificado: {len(casos)}", flush=True)

    proponentes = {p.hoja: p for p in list_proponentes(os.environ["MEDICION_DRIVE_FOLDER"]).proponentes}
    hallazgos = []
    for hoja in sorted(casos, key=lambda h: int(h.split("-")[1])):
        try:
            pdfs = extraer_pdfs(download_file_bytes(proponentes[hoja].drive_file_id))
        except Exception as exc:  # noqa: BLE001
            print(f"{hoja}: no se pudo abrir la oferta ({exc})", flush=True)
            continue
        tipo = obtener_tipo_proponente(pdfs)
        personas = obtener_personas_a_verificar(pdfs, tipo)
        certificados = ant.leer_certificados(pdfs)
        print(f"\n{hoja} ({tipo}) · exige {len(personas)}: {', '.join(n for n, _ in personas)}", flush=True)
        for req in sorted(casos[hoja]):
            config = configs[req]
            mios = [c for c in certificados if req in c.requisitos]
            nombres = []
            for cert in mios:
                nombre, cedula = config.extraer_identidad(ant._norm(cert.texto))  # igual que el motor
                nombres.append((nombre or "¿?", cedula or ""))
            faltan = [
                (nombre, cedula)
                for nombre, cedula in personas
                if not any(n != "¿?" and _nombres_coinciden(nombre, n) for n, _ in nombres)
            ]
            parecidos = [
                (falta, n)
                for falta, _ in faltan
                for n, _ in nombres
                if n != "¿?" and _parecido(falta, n)
            ]
            hallazgos.append({
                "hoja": hoja, "requisito": req, "entidad": config.entidad,
                "personas": [n for n, _ in personas],
                "certificados": [f"{n} {c}".strip() for n, c in nombres],
                "faltan": [n for n, _ in faltan],
                "parecidos": [f"{a} ≈ {b}" for a, b in parecidos],
            })
            print(f"  Req {req:2d} {config.entidad[:22]:22s} certificados: "
                  f"{', '.join(n for n, _ in nombres) or 'ninguno'}", flush=True)
            print(f"     falta el de: {', '.join(n for n, _ in faltan) or '—'}"
                  f"{'  ¡PARECIDO! ' + '; '.join(f'{a} ≈ {b}' for a, b in parecidos) if parecidos else ''}", flush=True)
        del pdfs

    with open(SALIDA, "w") as f:
        json.dump(hallazgos, f, ensure_ascii=False, indent=1)

    con_parecido = [h for h in hallazgos if h["parecidos"]]
    sin_certificado = [h for h in hallazgos if not h["certificados"]]
    print(f"\n=== {len(hallazgos)} casos ===")
    print(f"  sin ningún certificado de esa entidad en la oferta: {len(sin_certificado)}")
    print(f"  con un nombre parecido (posible error de emparejamiento): {len(con_parecido)}")
    for h in con_parecido:
        print(f"    {h['hoja']} Req {h['requisito']}: {'; '.join(h['parecidos'])}")


def _parecido(a: str, b: str) -> bool:
    """Mismo apellido y nombre: sirve para detectar emparejamientos perdidos por
    tildes, segundos nombres o abreviaturas."""
    pa, pb = set(a.split()), set(b.split())
    return len(pa & pb) >= 2


if __name__ == "__main__":
    main()
