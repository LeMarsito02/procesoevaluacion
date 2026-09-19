"""Requisito 18 (S.A. abierta o cerrada) evaluado directo en los 4 procesos, frente al
abogado. Solo mide."""
import collections, json, os, sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date
sys.path.insert(0, "."); os.environ["DRIVE_SOLO_CACHE"] = "1"
from dotenv import load_dotenv; load_dotenv(".env")
from motor.evaluacion.camara_comercio import evaluar_requisito18
from motor.evaluacion.formato1 import obtener_tipo_proponente
from motor.integrations.drive import download_file_bytes, list_proponentes
from motor.parsers.documento_base import build_proceso
from motor.procesamiento.zip_utils import extraer_pdfs
from scratch_cartas import PROCESOS
BASES = {"p1": "../Documento Base v3 - definitivos apertura.pdf", "p2": "../PRUEBASMIEVALUADOR/Prueba2/4. Pliego Definitivo IED Tibacuy.pdf",
         "p3": "../PRUEBASMIEVALUADOR/Prueba3/Documento base def.pdf",
         "p4": "../PRUEBASMIEVALUADOR/Prueba4/Documento Base o Documento Tipo CCE-EICP-GI-02 Menor Cuantia-DEFINITIVO (1).pdf"}
GT = {"p1": ".scratch/medicion_comparacion.json", "p3": ".scratch/prueba3/medicion_comparacion.json", "p4": ".scratch/prueba4/medicion_comparacion.json"}
OBJETOS = {k: build_proceso("X", date(2026, 1, 1), open(v, "rb").read()).objeto_general for k, v in BASES.items()}

def una(args):
    proceso, p = args
    pdfs = extraer_pdfs(download_file_bytes(p.drive_file_id))
    r = evaluar_requisito18(pdfs, obtener_tipo_proponente(pdfs))
    return proceso, p.hoja, r.cumple, r.motivo

if __name__ == "__main__":
    abogado = {f"{p}/{c['hoja']}": c["ground_truth"] for p, f in GT.items() for c in json.load(open(f)) if c["requisito"] == 18}
    tareas = [(k, p) for k, url in PROCESOS.items() for p in list_proponentes(url).proponentes]
    cuenta = collections.Counter()
    with ProcessPoolExecutor(4) as ex:
        for proceso, hoja, cumple, motivo in ex.map(una, tareas):
            gt = abogado.get(f"{proceso}/{hoja}", "?")
            cuenta[(proceso, gt, "SI" if cumple else "REV")] += 1
            if cumple and gt == "NO":
                print("APROBACIÓN INDEBIDA:", proceso, hoja)
            if not cumple or (motivo or "").startswith("N.A.") is False:
                print("  revisión:", proceso, hoja, gt, (motivo or "")[:120])
    for k, n in sorted(cuenta.items()): print(k, n)
