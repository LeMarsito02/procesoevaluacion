"""Auditoría: cuando el programa dice "No se encontró <documento>", ¿está de
verdad ausente? Busca palabras clave del documento en el texto de las
primeras páginas de TODOS los PDFs de la oferta. Si aparecen, el programa
pudo no reconocerlo (falla nuestra); si no, falta en la oferta o es un
escaneo sin texto. Solo mide."""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, ".")
os.environ.setdefault("DRIVE_SOLO_CACHE", "1")
from dotenv import load_dotenv

load_dotenv(".env")
from motor.integrations.drive import download_file_bytes, list_proponentes
from motor.procesamiento.pdf_utils import extraer_texto
from motor.procesamiento.zip_utils import extraer_pdfs

DIR = os.environ.get("MEDICION_DIR", ".scratch/prueba2_pliego")
CLAVES = {
    2: r"CONSEJO PROFESIONAL NACIONAL DE INGENIERIA|COPNIA",
    3: r"CONSEJO PROFESIONAL NACIONAL DE INGENIERIA|COPNIA",
    4: r"CONFORMACION DE PROPONENTE PLURAL|DOCUMENTO DE CONFORMACION|CONSORCIO.{0,40}(CONSTITU|CONFORM)",
    9: r"REGISTRO UNICO DE PROPONENTES",
    10: r"REGISTRO UNICO DE PROPONENTES",
    11: r"SERIEDAD",
    14: r"CONTRALORIA|RESPONSABLES FISCALES",
    15: r"PROCURADURIA",
    16: r"ANTECEDENTES (JUDICIALES|PENALES)|POLICIA NACIONAL.{0,60}ANTECEDENTES|NO TIENE ASUNTOS PENDIENTES",
    17: r"MEDIDAS CORRECTIVAS|RNMC",
}


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.upper())
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c)))


def main() -> None:
    resultados = json.load(open(f"{DIR}/medicion_resultados.json"))
    casos: dict[str, list[int]] = {}
    for hoja, items in resultados.items():
        for x in items:
            if x["requisito"] in CLAVES and not x["cumple"] and (x.get("motivo") or "").startswith("No se encontr"):
                casos.setdefault(hoja, []).append(x["requisito"])
    props = {p.hoja: p for p in list_proponentes(os.environ["MEDICION_DRIVE_FOLDER"]).proponentes}
    salida = []
    for hoja in sorted(casos, key=lambda h: int(h.split("-")[1])):
        pdfs = extraer_pdfs(download_file_bytes(props[hoja].drive_file_id))
        textos = {}
        for nombre, contenido in pdfs.items():
            try:
                textos[nombre] = norm(extraer_texto(contenido, max_paginas=3))
            except Exception:  # noqa: BLE001
                textos[nombre] = ""
        sin_texto = [n for n, t in textos.items() if len(t) < 50]
        for req in casos[hoja]:
            hallados = [n.rsplit("/", 1)[-1] for n, t in textos.items() if re.search(CLAVES[req], t)]
            salida.append({"hoja": hoja, "requisito": req, "hallados": hallados, "pdfs_sin_texto": len(sin_texto)})
            marca = "¿LO PASAMOS?" if hallados else "ausente"
            print(f"{hoja} Req {req:2d}: {marca} {hallados[:3]} (sin texto: {len(sin_texto)}/{len(pdfs)})", flush=True)
        del pdfs
    json.dump(salida, open(f"{DIR}/auditoria_faltantes.json", "w"), ensure_ascii=False, indent=1)
    pasados = [s for s in salida if s["hallados"]]
    print(f"\n{len(salida)} casos 'no se encontró': {len(salida) - len(pasados)} sin rastro en el texto, "
          f"{len(pasados)} con palabras clave presentes (a revisar a mano)")


if __name__ == "__main__":
    main()
