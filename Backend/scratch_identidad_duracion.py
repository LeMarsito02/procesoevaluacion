"""Duración de la sociedad y copia de la cédula, evaluadas directo en los 4
procesos. Solo mide."""
import collections, os, sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date
sys.path.insert(0, "."); os.environ["DRIVE_SOLO_CACHE"] = "1"
from dotenv import load_dotenv; load_dotenv(".env")
from motor.evaluacion.camara_comercio import evaluar_duracion_sociedad, evaluar_requisito18
from motor.evaluacion.formato1 import obtener_tipo_proponente
from motor.evaluacion.identidad import evaluar_identidad
from motor.integrations.drive import download_file_bytes, list_proponentes
from motor.parsers.documento_base import build_proceso
from motor.procesamiento.zip_utils import extraer_pdfs
from scratch_cartas import PROCESOS
DATOS = {"p1": ("../Documento Base v3 - definitivos apertura.pdf", "ICCU-CM-037-2026", date(2026, 7, 23)),
         "p2": ("../PRUEBASMIEVALUADOR/Prueba2/4. Pliego Definitivo IED Tibacuy.pdf", "ICCU-LP-027-2026", date(2026, 7, 24)),
         "p3": ("../PRUEBASMIEVALUADOR/Prueba3/Documento base def.pdf", "ICCU-LP-022-2026", date(2026, 8, 3)),
         "p4": ("../PRUEBASMIEVALUADOR/Prueba4/Documento Base o Documento Tipo CCE-EICP-GI-02 Menor Cuantia-DEFINITIVO (1).pdf", "ICCU-MC-019-2026", date(2026, 5, 25))}
_PROCESOS = {}

def proceso(k):
    if k not in _PROCESOS:
        f, cod, cierre = DATOS[k]
        _PROCESOS[k] = build_proceso(cod, cierre, open(f, "rb").read())
    return _PROCESOS[k]

def una(args):
    k, p = args
    pdfs = extraer_pdfs(download_file_bytes(p.drive_file_id))
    tipo = obtener_tipo_proponente(pdfs)
    d = evaluar_duracion_sociedad(pdfs, proceso(k), tipo)
    i = evaluar_identidad(pdfs, proceso(k), tipo)
    r = evaluar_requisito18(pdfs, tipo)
    return k, p.hoja, d.cumple, d.motivo, i.cumple, i.motivo, r.cumple, r.motivo

if __name__ == "__main__":
    import json
    GT = {"p1": ".scratch/medicion_comparacion.json", "p3": ".scratch/prueba3/medicion_comparacion.json", "p4": ".scratch/prueba4/medicion_comparacion.json"}
    abogado = {}
    for pr, f in GT.items():
        for x in json.load(open(f)):
            abogado[(pr, x["hoja"], x["requisito"])] = x["ground_truth"]
    tareas = [(k, p) for k, url in PROCESOS.items() for p in list_proponentes(url).proponentes]
    c = collections.Counter()
    with ProcessPoolExecutor(3, max_tasks_per_child=20) as ex:
        for k, hoja, dc, dm, ic, im, rc, rm in ex.map(una, tareas):
            c[(k, "duración", dc)] += 1; c[(k, "identidad", ic)] += 1
            g18 = abogado.get((k, hoja, 18), "?"); g6 = abogado.get((k, hoja, 6), "?")
            c[(k, "req18", "SI" if rc and not (rm or "").startswith("N.A.") else ("N.A." if rc else "REV"), "abogado " + g18)] += 1
            if not dc: print("DUR", k, hoja, (dm or "")[:150], flush=True)
            if not ic: print("ID ", k, hoja, "abogado req6:", g6, "|", (im or "")[:150], flush=True)
            if (rc and g18 == "NO") or (not rc): print("R18", k, hoja, "abogado:", g18, "|", (rm or "")[:150], flush=True)
    for x, n in sorted(c.items()): print(x, n)
