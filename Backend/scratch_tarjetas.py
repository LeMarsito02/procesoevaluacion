"""¿Se encuentra la copia de la tarjeta profesional del ingeniero? Frente
al abogado (Req 2). Solo mide."""
import collections, json, os, sys
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, "."); os.environ["DRIVE_SOLO_CACHE"] = "1"
from dotenv import load_dotenv; load_dotenv(".env")
from motor.evaluacion.copnia import encontrar_copnias, extraer_datos_copnia, tarjeta_profesional
from motor.integrations.drive import download_file_bytes, list_proponentes
from motor.procesamiento.zip_utils import extraer_pdfs
from scratch_cartas import PROCESOS
GT = {"p1": ".scratch/medicion_comparacion.json", "p3": ".scratch/prueba3/medicion_comparacion.json", "p4": ".scratch/prueba4/medicion_comparacion.json"}

def una(args):
    proceso, p = args
    pdfs = extraer_pdfs(download_file_bytes(p.drive_file_id))
    copnias = encontrar_copnias(pdfs)
    if not copnias:
        return proceso, p.hoja, "sin copnia", None
    encontrada = None
    for _, texto in copnias:
        d = extraer_datos_copnia(texto)
        encontrada = encontrada or tarjeta_profesional(pdfs, d.nombre, d.matricula)
    return proceso, p.hoja, "tarjeta" if encontrada else "SIN TARJETA", encontrada

if __name__ == "__main__":
    abogado = {f"{p}/{c['hoja']}": c["ground_truth"] for p, f in GT.items() for c in json.load(open(f)) if c["requisito"] == 2}
    solo = os.environ.get("SOLO", "")
    tareas = [(k, p) for k, url in PROCESOS.items() if not solo or k == solo for p in list_proponentes(url).proponentes]
    cuenta = collections.Counter()
    with ProcessPoolExecutor(4) as ex:
        for proceso, hoja, estado, archivo in ex.map(una, tareas):
            gt = abogado.get(f"{proceso}/{hoja}", "?")
            cuenta[(proceso, gt, estado)] += 1
            if estado == "SIN TARJETA" or gt == "NO":
                print(proceso, hoja, gt, estado, (archivo or "")[-50:], flush=True)
    for k, n in sorted(cuenta.items()): print(k, n)
