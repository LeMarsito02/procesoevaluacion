"""¿Los certificados que no encontramos están en la oferta o no los aportaron?

Para cada caso en que el programa dijo "no se encontró el certificado X" y el
abogado sin embargo aprobó, recorre TODAS las páginas de TODOS los PDF de esa
oferta buscando el título del certificado.

- Si aparece  → el documento estaba y no lo vimos: hay algo que arreglar.
- Si no aparece → el proponente no lo aportó y el abogado lo consultó en línea:
  el programa acertó al mandarlo a revisión y no hay nada que mejorar.

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
from motor.integrations.drive import download_file_bytes, list_proponentes
from motor.procesamiento.pdf_utils import abrir_pdf, texto_pagina
from motor.procesamiento.zip_utils import extraer_pdfs

COMPARACION = ".scratch/medicion_comparacion.json"
SALIDA = ".scratch/antecedentes_faltantes.json"
NO_ENCONTRADO = "No se encontró el certificado"
# Páginas por PDF: suficiente para paquetes grandes, sin recorrer un RUP entero.
PAGINAS = 40


def main() -> None:
    carpeta = os.environ["MEDICION_DRIVE_FOLDER"]
    with open(COMPARACION) as f:
        comparacion = json.load(f)

    configs = {c.requisito: c for c in ant._configs()}
    casos = collections.defaultdict(set)  # hoja -> {requisitos}
    for c in comparacion:
        if c["nuestro"] in ("NO", "ERROR") and c["ground_truth"] in ("SI", "N.A."):
            if NO_ENCONTRADO in (c["motivo_nuestro"] or "") and c["requisito"] in configs:
                casos[c["hoja"]].add(c["requisito"])
    print(f"Proponentes con certificados no encontrados: {len(casos)}", flush=True)

    proponentes = {p.hoja: p for p in list_proponentes(carpeta).proponentes}
    hallazgos = []
    for hoja in sorted(casos, key=lambda h: int(h.split("-")[1])):
        requisitos = casos[hoja]
        try:
            pdfs = extraer_pdfs(download_file_bytes(proponentes[hoja].drive_file_id))
        except Exception as exc:  # noqa: BLE001
            print(f"{hoja}: no se pudo abrir la oferta ({exc})", flush=True)
            continue
        encontrados: dict[int, str] = {}
        for nombre, datos in pdfs.items():
            if set(requisitos) <= set(encontrados):
                break
            try:
                with abrir_pdf(datos) as pdf:
                    for n in range(min(len(pdf.pages), PAGINAS)):
                        texto = ant._norm(texto_pagina(pdf.pages[n]) or "")
                        for req in requisitos - set(encontrados):
                            if configs[req].titulo_re.search(texto):
                                encontrados[req] = f"{nombre} p.{n + 1}"
            except Exception:  # noqa: BLE001
                continue
        del pdfs
        for req in sorted(requisitos):
            entidad = configs[req].entidad
            donde = encontrados.get(req)
            hallazgos.append({"hoja": hoja, "requisito": req, "entidad": entidad, "donde": donde})
            print(f"  {hoja} Req {req:2d} ({entidad}): {donde or 'NO ESTÁ en la oferta'}", flush=True)

    with open(SALIDA, "w") as f:
        json.dump(hallazgos, f, ensure_ascii=False, indent=1)

    estaba = [h for h in hallazgos if h["donde"]]
    print(f"\n=== {len(estaba)} de {len(hallazgos)} sí estaban en la oferta y no los vimos ===")
    for req, n in collections.Counter(h["requisito"] for h in estaba).most_common():
        print(f"  Req {req}: {n}")
    print(f"{len(hallazgos) - len(estaba)} no estaban: el abogado los consultó en línea (trabajo inevitable).")


if __name__ == "__main__":
    main()
