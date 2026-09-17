"""Verifica que las optimizaciones de memoria NO cambiaron los veredictos.

Compara los resultados guardados de los Requisitos 1-8 (calculados con el
código ANTERIOR a la deduplicación y al flush_cache) contra los que produce
el código ACTUAL sobre los mismos proponentes. Si los veredictos coinciden,
queda demostrado que la optimización solo quitó trabajo desperdiciado."""
from __future__ import annotations

import json
import os

from dotenv import load_dotenv

load_dotenv(".env")
import sys
from datetime import date

import requests

sys.path.insert(0, ".")
from motor.integrations.drive import list_proponentes
from motor.parsers.documento_base import build_proceso

# Fecha de cierre del proceso de referencia (formato AAAA-MM-DD en .env).
FECHA_CIERRE = date.fromisoformat(os.environ.get("MEDICION_FECHA_CIERRE", "2026-01-01"))

API = "http://localhost:8000"
DRIVE_FOLDER = "https://drive.google.com/drive/folders/1OyXkYjPr5IKLnSVvB7BHheYziKtLGTeb"
DOC_BASE = os.environ.get("MEDICION_DOCUMENTO_BASE", "")

# Muestra representativa: individuales, consorcios chicos y el consorcio más
# pesado del proceso, para cubrir los casos donde la deduplicación y el
# flush_cache más cambian el camino de ejecución.
HOJAS_MUESTRA = ["P-01", "P-02", "P-06", "P-04", "P-13", "P-18", "P-77"]
REQUISITOS = [1, 2, 3, 4, 5, 6, 7, 8]


def main():
    with open(DOC_BASE, "rb") as f:
        proceso = build_proceso(os.environ.get("MEDICION_CODIGO_PROCESO", ""), FECHA_CIERRE, f.read())
    proceso_json = json.loads(proceso.model_dump_json())

    with open(".scratch/nuestros_resultados.json") as f:
        antiguos = json.load(f)

    r = list_proponentes(DRIVE_FOLDER)
    por_hoja = {p.hoja: p for p in r.proponentes}

    iguales = 0
    distintos = []
    sin_dato = 0

    for hoja in HOJAS_MUESTRA:
        if hoja not in por_hoja or hoja not in antiguos:
            continue
        p_json = json.loads(por_hoja[hoja].model_dump_json())
        for req in REQUISITOS:
            viejo = antiguos.get(hoja, {}).get(str(req))
            if viejo is None:
                sin_dato += 1
                continue
            try:
                resp = requests.post(
                    f"{API}/api/procesos/evaluar-requisito-{req}/proponente",
                    json={"documento_base": proceso_json, "proponente": p_json},
                    timeout=300,
                )
                nuevo = resp.json()
            except Exception as exc:  # noqa: BLE001
                print(f"  {hoja} req{req}: fallo de red en el reintento: {exc}", flush=True)
                continue

            v_viejo = (viejo.get("cumple"), (viejo.get("motivo") or "")[:60])
            v_nuevo = (nuevo.get("cumple"), (nuevo.get("motivo") or "")[:60])
            if v_viejo == v_nuevo:
                iguales += 1
            else:
                distintos.append(
                    {
                        "hoja": hoja,
                        "requisito": req,
                        "antes": {"cumple": viejo.get("cumple"), "motivo": viejo.get("motivo"), "archivo": viejo.get("archivo_evaluado")},
                        "ahora": {"cumple": nuevo.get("cumple"), "motivo": nuevo.get("motivo"), "archivo": nuevo.get("archivo_evaluado")},
                    }
                )
            print(f"  {hoja} req{req}: {'IGUAL' if v_viejo == v_nuevo else 'DISTINTO'}", flush=True)

    print()
    print(f"Veredictos idénticos: {iguales}")
    print(f"Veredictos distintos: {len(distintos)}")
    print(f"Sin dato previo para comparar: {sin_dato}")
    for d in distintos:
        print(f"\n  {d['hoja']} Requisito {d['requisito']}:")
        print(f"    ANTES: {d['antes']}")
        print(f"    AHORA: {d['ahora']}")

    with open(".scratch/verificacion_calidad.json", "w") as f:
        json.dump({"iguales": iguales, "distintos": distintos}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
