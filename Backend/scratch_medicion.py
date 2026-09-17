"""Medición final de confiabilidad y tiempo.

Evalúa cada proponente UNA sola vez con la pasada única (los 18 requisitos
juntos, endpoint /evaluar-todos/proponente) y compara contra el Segundo
Informe (.scratch/ground_truth.json). El informe SOLO se usa para medir: nada
de este script alimenta la lógica del programa.

Reanudable: los proponentes ya evaluados sin error no se repiten."""
from __future__ import annotations

import collections
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import requests

sys.path.insert(0, ".")
from motor.integrations.drive import list_proponentes
from motor.parsers.documento_base import build_proceso
from scratch_comparar import API, DOC_BASE, DRIVE_FOLDER, emparejar_proponentes, nuestro_veredicto

RESULTADOS = ".scratch/medicion_resultados.json"
TIEMPOS = ".scratch/medicion_tiempos.json"
COMPARACION = ".scratch/medicion_comparacion.json"
CONCURRENCIA = 2
# RUT (Requisito 13): el abogado indicó ignorarlo; no se evalúa ni se mide.
REQUISITOS_IGNORADOS = {13}


def _cargar(path, defecto):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return defecto


def evaluar(proceso_json, proponentes, mapeo):
    resultados = _cargar(RESULTADOS, {})
    tiempos = _cargar(TIEMPOS, {})
    pendientes = [
        p for p in proponentes
        if p.hoja in mapeo and (p.hoja not in resultados or any(r.get("error") for r in resultados[p.hoja]))
    ]
    print(f"Proponentes a evaluar: {len(pendientes)} (ya hechos: {len(mapeo) - len(pendientes)})", flush=True)

    def uno(p):
        t0 = time.time()
        resp = requests.post(
            f"{API}/api/procesos/evaluar-todos/proponente",
            json={"documento_base": proceso_json, "proponente": json.loads(p.model_dump_json())},
            timeout=3600,
        )
        resp.raise_for_status()
        return p.hoja, resp.json(), time.time() - t0

    inicio = time.time()
    with ThreadPoolExecutor(max_workers=CONCURRENCIA) as ex:
        futuros = [ex.submit(uno, p) for p in pendientes]
        for i, fut in enumerate(as_completed(futuros), 1):
            try:
                hoja, items, seg = fut.result()
            except Exception as exc:  # noqa: BLE001
                print(f"  ERROR: {exc}", flush=True)
                continue
            resultados[hoja] = items
            tiempos[hoja] = seg
            errores = sum(1 for r in items if r.get("error"))
            print(f"  [{i}/{len(pendientes)}] {hoja} {seg:.0f}s ({errores} errores)", flush=True)
            with open(RESULTADOS, "w") as f:
                json.dump(resultados, f, ensure_ascii=False)
            with open(TIEMPOS, "w") as f:
                json.dump(tiempos, f)
    print(f"Tiempo de esta corrida: {(time.time() - inicio) / 60:.1f} min", flush=True)
    return resultados, tiempos


def comparar(resultados, ground_truth, mapeo, nombres):
    comparacion = []
    for hoja, idx_gt in mapeo.items():
        for item in resultados.get(hoja, []):
            req = item["requisito"]
            if req in REQUISITOS_IGNORADOS:
                continue
            gt_req = ground_truth[idx_gt]["requisitos"].get(str(req))
            if gt_req is None:
                continue
            nuestro = nuestro_veredicto(item)
            gt = (gt_req.get("veredicto") or "?").strip()
            comparacion.append({
                "hoja": hoja, "nombre": nombres[hoja], "requisito": req,
                "nuestro": nuestro, "ground_truth": gt,
                "coincide": nuestro.replace(".", "") == gt.replace(".", ""),
                "nota_gt": (gt_req.get("nota") or "")[:150],
                "archivo_nuestro": item.get("archivo_evaluado"),
                "motivo_nuestro": (item.get("motivo") or item.get("error") or "")[:300],
            })
    with open(COMPARACION, "w") as f:
        json.dump(comparacion, f, ensure_ascii=False, indent=1)
    return comparacion


def resumen(comparacion, tiempos):
    total = len(comparacion)
    ok = sum(c["coincide"] for c in comparacion)
    print(f"\n=== ACIERTO GENERAL: {ok}/{total} ({100 * ok / total:.1f}%) ===")
    print("\nPor requisito:")
    for req in range(1, 19):
        items = [c for c in comparacion if c["requisito"] == req]
        if items:
            k = sum(c["coincide"] for c in items)
            print(f"  Req {req:2d}: {k}/{len(items)} ({100 * k / len(items):.0f}%)")
    print("\nMatriz (nuestro -> informe):", dict(collections.Counter((c["nuestro"], c["ground_truth"]) for c in comparacion)))

    # Confianza: lo que el programa aprueba sin revisión humana.
    aprobados = [c for c in comparacion if c["nuestro"] in ("SI", "N.A.")]
    aprobados_ok = sum(c["coincide"] for c in aprobados)
    a_revision = [c for c in comparacion if c["nuestro"] in ("NO", "ERROR")]
    print(f"\nCuando el programa dice SI/N.A. (sin revisión): {aprobados_ok}/{len(aprobados)} correctos "
          f"({100 * aprobados_ok / max(len(aprobados), 1):.1f}%)")
    peligrosos = [c for c in comparacion if c["nuestro"] in ("SI", "N.A.") and c["ground_truth"] == "NO"]
    print(f"Aprobados por el programa que el abogado marcó NO (lo más grave): {len(peligrosos)}")
    for c in peligrosos:
        print(f"   {c['hoja']} Req {c['requisito']}: {c['nota_gt'][:100]}")
    print(f"Enviados a revisión humana: {len(a_revision)}/{total} ({100 * len(a_revision) / total:.1f}%)")
    if tiempos:
        seg = list(tiempos.values())
        print(f"\nTiempo por proponente: promedio {sum(seg) / len(seg):.0f}s, máximo {max(seg):.0f}s")


def main():
    with open(DOC_BASE, "rb") as f:
        proceso = build_proceso("CM-037-2026", date(2026, 7, 23), f.read())
    proceso_json = json.loads(proceso.model_dump_json())
    r = list_proponentes(DRIVE_FOLDER)
    with open(".scratch/ground_truth.json") as f:
        ground_truth = json.load(f)
    mapeo = emparejar_proponentes(r.proponentes, ground_truth)
    nombres = {p.hoja: p.nombre_proponente for p in r.proponentes}
    print(f"Proponentes emparejados con el informe: {len(mapeo)} / {len(r.proponentes)}", flush=True)
    if "--solo-comparar" not in sys.argv:
        resultados, tiempos = evaluar(proceso_json, r.proponentes, mapeo)
    else:
        resultados, tiempos = _cargar(RESULTADOS, {}), _cargar(TIEMPOS, {})
    resumen(comparar(resultados, ground_truth, mapeo, nombres), tiempos)


if __name__ == "__main__":
    main()
