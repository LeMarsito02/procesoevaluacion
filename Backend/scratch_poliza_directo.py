"""Requisito 11 evaluado directo (sin caché ni servidor) sobre todas las
ofertas de un proceso, para comparar con la última medición. Solo mide."""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date

sys.path.insert(0, ".")
os.environ.setdefault("DRIVE_SOLO_CACHE", "1")
from dotenv import load_dotenv

load_dotenv(".env")
from motor.evaluacion.garantia import evaluar_requisito11
from motor.integrations.drive import download_file_bytes, list_proponentes
from motor.parsers.documento_base import build_proceso
from motor.procesamiento.zip_utils import extraer_pdfs

DIR = os.environ["MEDICION_DIR"]
_PROCESO = None


def _proceso():
    global _PROCESO
    if _PROCESO is None:
        with open(os.environ["MEDICION_DOCUMENTO_BASE"], "rb") as f:
            _PROCESO = build_proceso(os.environ["MEDICION_CODIGO_PROCESO"], date.fromisoformat(os.environ["MEDICION_FECHA_CIERRE"]), f.read())
    return _PROCESO


def uno(p):
    try:
        r = evaluar_requisito11(extraer_pdfs(download_file_bytes(p.drive_file_id)), _proceso())
        return p.hoja, r.cumple, r.motivo, r.archivo
    except Exception as exc:  # noqa: BLE001
        return p.hoja, False, f"ERROR {exc}", None


def main():
    anteriores = {h: next(x for x in l if x["requisito"] == 11) for h, l in json.load(open(f"{DIR}/medicion_resultados.json")).items()}
    props = list_proponentes(os.environ["MEDICION_DRIVE_FOLDER"]).proponentes
    with ProcessPoolExecutor(int(os.environ.get("HILOS", "4"))) as ex:
        nuevos = sorted(ex.map(uno, props), key=lambda r: int(r[0].split("-")[1]))
    json.dump(nuevos, open(f"{DIR}/poliza_directo.json", "w"), ensure_ascii=False, indent=1)
    cambios = {"ganó": 0, "perdió": 0}
    for hoja, cumple, motivo, archivo in nuevos:
        antes = anteriores.get(hoja, {})
        if antes.get("cumple") != cumple:
            cambios["ganó" if cumple else "perdió"] += 1
            print(f"{hoja}: {'REV→SI' if cumple else 'SI→REV'} {(archivo or '').rsplit('/', 1)[-1][:40]} | {motivo or antes.get('motivo')}")
    n = sum(1 for r in nuevos if r[1])
    print(f"\nAprobadas: {n}/{len(nuevos)} (antes {sum(1 for a in anteriores.values() if a['cumple'])}) · {cambios}")
    for hoja, cumple, motivo, _ in nuevos:
        if not cumple:
            print(f"  sigue a revisión {hoja}: {motivo}")


if __name__ == "__main__":
    main()
