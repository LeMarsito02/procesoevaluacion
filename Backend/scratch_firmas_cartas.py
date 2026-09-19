"""Mide firmas_desubicadas sobre las cartas reales. Solo mide."""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, "."); os.environ["DRIVE_SOLO_CACHE"] = "1"
from dotenv import load_dotenv; load_dotenv(".env")
from motor.evaluacion.formato1 import encontrar_formato1
from motor.evaluacion.formato1_contenido import firmas_desubicadas
from motor.integrations.drive import download_file_bytes, list_proponentes
from scratch_cartas import PROCESOS

def una(args):
    proceso, p = args
    try:
        encontrado = encontrar_formato1(extraer(p))
        return proceso, p.hoja, firmas_desubicadas(encontrado[1]) if encontrado else None
    except Exception as exc:  # noqa: BLE001
        return proceso, p.hoja, f"ERROR {exc}"

def extraer(p):
    from motor.procesamiento.zip_utils import extraer_pdfs
    return extraer_pdfs(download_file_bytes(p.drive_file_id))

if __name__ == "__main__":
    tareas = [(k, p) for k, url in PROCESOS.items() for p in list_proponentes(url).proponentes]
    with ProcessPoolExecutor(4) as ex:
        for proceso, hoja, r in ex.map(una, tareas):
            if r:
                print(proceso, hoja, r, flush=True)
