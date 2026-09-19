"""Fecha de expedición de los certificados de antecedentes reales, frente
al cierre de cada proceso. Solo mide."""
import collections, json, os, sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date
sys.path.insert(0, "."); os.environ["DRIVE_SOLO_CACHE"] = "1"
from dotenv import load_dotenv; load_dotenv(".env")
from motor.evaluacion import antecedentes as ant
from motor.evaluacion.personalizado import _FECHA_RE, _fecha
from motor.integrations.drive import download_file_bytes, list_proponentes
from motor.procesamiento.zip_utils import extraer_pdfs
from scratch_cartas import PROCESOS
CIERRE = {"p1": date(2026, 7, 23), "p2": date(2026, 7, 24), "p3": date(2026, 8, 3), "p4": date(2026, 5, 25)}
ENT = {5: "REDAM", 14: "Contraloría", 15: "Procuraduría", 16: "Policía", 17: "RNMC"}

def una(args):
    proceso, p = args
    filas = []
    try:
        for c in ant.leer_certificados(extraer_pdfs(download_file_bytes(p.drive_file_id))):
            t = ant._norm(c.texto)
            fechas = [f for m in _FECHA_RE.finditer(t) if (f := _fecha(m))]
            validas = [f for f in fechas if f <= CIERRE[proceso].replace(year=CIERRE[proceso].year) and (CIERRE[proceso] - f).days < 3650] + [f for f in fechas if 0 < (f - CIERRE[proceso]).days <= 40]
            exp = max(validas) if validas else None
            filas.append((proceso, p.hoja, sorted(c.requisitos), c.archivo.rsplit("/", 1)[-1][:40], exp.isoformat() if exp else None, (CIERRE[proceso] - exp).days if exp else None))
    except Exception as exc:  # noqa: BLE001
        filas.append((proceso, p.hoja, [], f"ERROR {exc}", None, None))
    return filas

if __name__ == "__main__":
    tareas = [(k, p) for k, url in PROCESOS.items() for p in list_proponentes(url).proponentes]
    with ProcessPoolExecutor(4) as ex:
        filas = [f for fs in ex.map(una, tareas) for f in fs]
    json.dump(filas, open(".scratch/fechas_antecedentes.json", "w"), ensure_ascii=False)
    c = collections.Counter()
    for proceso, hoja, reqs, arch, exp, dias in filas:
        for r in reqs:
            c[(proceso, ENT.get(r, r), "sin fecha" if dias is None else ("después del cierre" if dias < 0 else ("<=31 días" if dias <= 31 else ">31 días")))] += 1
    for k, n in sorted(c.items()): print(k, n)
