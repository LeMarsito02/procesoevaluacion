"""Junta el texto de la carta de presentación (Formato 1) de cada oferta de
los procesos de prueba, para armar y probar la verificación del contenido
de la carta. Solo mide."""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, ".")
os.environ["DRIVE_SOLO_CACHE"] = "1"
from dotenv import load_dotenv

load_dotenv(".env")
from motor.evaluacion.formato1 import encontrar_formato1
from motor.integrations.drive import download_file_bytes, list_proponentes
from motor.procesamiento.pdf_utils import extraer_texto
from motor.procesamiento.zip_utils import extraer_pdfs

PROCESOS = {
    "p1": os.environ.get("MEDICION_DRIVE_FOLDER"),
    "p2": "https://drive.google.com/drive/folders/1k6QaO1v0bEbnhKnT2edkavswCpK3zzYc",
    "p3": "https://1drv.ms/f/c/eab364599c2236b8/IgA7wxAx8fSNR60t6e2j0TbuAeaQpUrlGBJ8dZEXB8xLeM8?e=JN0ZAR",
    "p4": "https://1drv.ms/f/c/d09ede0cd2e6118e/IgBXSGkuRU2QR6ag50US4RkbAa8WG_6S5MVmXcbP_joZkHI?e=hPgliQ",
}
SALIDA = ".scratch/cartas.json"


def una(args):
    proceso, p = args
    try:
        pdfs = extraer_pdfs(download_file_bytes(p.drive_file_id))
        encontrado = encontrar_formato1(pdfs)
        if encontrado is None:
            return proceso, p.hoja, None, None
        nombre, contenido = encontrado
        return proceso, p.hoja, nombre, extraer_texto(contenido, max_paginas=8)
    except Exception as exc:  # noqa: BLE001
        return proceso, p.hoja, None, f"ERROR {exc}"


def main():
    tareas = [(k, p) for k, url in PROCESOS.items() for p in list_proponentes(url).proponentes]
    with ProcessPoolExecutor(4) as ex:
        filas = list(ex.map(una, tareas))
    datos = {f"{pr}/{h}": {"archivo": n, "texto": t} for pr, h, n, t in filas}
    json.dump(datos, open(SALIDA, "w"), ensure_ascii=False)
    print(len(datos), "ofertas;", sum(1 for d in datos.values() if d["texto"] and not d["texto"].startswith("ERROR")), "cartas leídas")


if __name__ == "__main__":
    main()
