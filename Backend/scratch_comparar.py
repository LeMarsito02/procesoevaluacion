"""Corre los 18 requisitos contra los proponentes reales (vía el backend
real, HTTP) y compara contra el ground truth (Segundo Informe, ya
parseado en .scratch/ground_truth.json). SOLO para medir qué tan confiable es
el programa -- los resultados de este script no deben usarse para ajustar
la lógica sin verificar antes contra los documentos fuente reales."""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import date

import requests

sys.path.insert(0, ".")
from app.integrations.drive import list_proponentes
from app.parsers.documento_base import build_proceso

API = "http://localhost:8000"
DRIVE_FOLDER = "https://drive.google.com/drive/folders/1OyXkYjPr5IKLnSVvB7BHheYziKtLGTeb"
DOC_BASE = "/home/lemarsito/Documents/NICOLASPENA/ProcesoEvaluacion/Documento Base v3 - definitivos apertura.pdf"


def _norm_tokens(s: str) -> set[str]:
    s = re.sub(r"[^A-Za-zÑÁÉÍÓÚñáéíóú0-9\s]", " ", s.upper())
    return {t for t in s.split() if len(t) > 2 and t not in ("SAS", "LTDA", "ICCU")}


def emparejar_proponentes(proponentes, ground_truth):
    gt_tokens = [(i, _norm_tokens(d["nombre"] or "")) for i, d in enumerate(ground_truth)]
    mapeo = {}
    for p in proponentes:
        tk_drive = _norm_tokens(p.nombre_proponente)
        mejor_idx, mejor_score = None, 0.0
        for idx, tk_gt in gt_tokens:
            if not tk_drive or not tk_gt:
                continue
            score = len(tk_drive & tk_gt) / max(1, min(len(tk_drive), len(tk_gt)))
            if score > mejor_score:
                mejor_score, mejor_idx = score, idx
        if mejor_score >= 0.5:
            mapeo[p.hoja] = mejor_idx
    return mapeo


def nuestro_veredicto(resultado: dict) -> str:
    if resultado.get("error"):
        return "ERROR"
    motivo = resultado.get("motivo") or ""
    if motivo.startswith("N.A."):
        return "N.A."
    if resultado.get("cumple") is True:
        return "SI"
    if resultado.get("cumple") is False:
        return "NO"
    return "?"


def main():
    with open(DOC_BASE, "rb") as f:
        pdf_bytes = f.read()
    proceso = build_proceso("CM-037-2026", date(2026, 7, 23), pdf_bytes)
    proceso_json = json.loads(proceso.model_dump_json())
    del pdf_bytes

    # La conexión se ha caído varias veces a mitad de corrida; sin reintento
    # aquí, un corte de pocos segundos tumba todo el trabajo pendiente.
    r = None
    for intento in range(1, 11):
        try:
            r = list_proponentes(DRIVE_FOLDER)
            break
        except Exception as exc:  # noqa: BLE001
            print(f"  fallo al listar proponentes (intento {intento}): {exc}", flush=True)
            time.sleep(15)
    if r is None:
        print("No se pudo listar proponentes tras 10 intentos, abortando.")
        return

    with open(".scratch/ground_truth.json") as f:
        ground_truth = json.load(f)

    mapeo = emparejar_proponentes(r.proponentes, ground_truth)
    print(f"Proponentes emparejados: {len(mapeo)} / {len(r.proponentes)}")

    proponentes_por_hoja = {p.hoja: p for p in r.proponentes}
    proponentes_a_evaluar = [proponentes_por_hoja[h] for h in mapeo]
    proponentes_json = [json.loads(p.model_dump_json()) for p in proponentes_a_evaluar]

    resultados_todos: dict[str, dict[int, dict]] = {h: {} for h in mapeo}
    try:
        with open(".scratch/nuestros_resultados.json") as f:
            previos = json.load(f)
        for hoja, por_requisito in previos.items():
            if hoja in resultados_todos:
                resultados_todos[hoja].update({int(k): v for k, v in por_requisito.items()})
        requisitos_ya_hechos = {int(k) for v in previos.values() for k in v}
        print(f"Reanudando: ya hechos {sorted(requisitos_ya_hechos)}")
    except FileNotFoundError:
        requisitos_ya_hechos = set()

    solo_requisito = int(sys.argv[1]) if len(sys.argv) > 1 else None
    rango = [solo_requisito] if solo_requisito else range(1, 19)

    for requisito in rango:
        if requisito in requisitos_ya_hechos:
            print(f"--- Requisito {requisito} ya estaba hecho, se salta ---", flush=True)
            continue
        print(f"--- Evaluando Requisito {requisito} ({len(proponentes_a_evaluar)} proponentes) ---", flush=True)
        try:
            resp = requests.post(
                f"{API}/api/procesos/evaluar-requisito-{requisito}",
                json={"documento_base": proceso_json, "proponentes": proponentes_json},
                timeout=7200,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR de conexión: {exc}")
            continue
        if resp.status_code != 200:
            print(f"  ERROR HTTP {resp.status_code}: {resp.text[:300]}")
            continue
        items = resp.json()
        for item in items:
            resultados_todos[item["hoja"]][requisito] = item
        con_error_red = [
            it["hoja"] for it in items if it.get("error") and "descargar" in (it.get("error") or "")
        ]
        print(f"  OK, {len(items)} resultados recibidos ({len(con_error_red)} con error de descarga)", flush=True)

        for intento in range(1, 4):
            if not con_error_red:
                break
            print(f"  Reintentando {len(con_error_red)} proponentes con error de red (intento {intento})...", flush=True)
            time.sleep(5)
            aun_con_error = []
            for hoja in con_error_red:
                p_json = next(pj for pj in proponentes_json if pj["hoja"] == hoja)
                try:
                    r2 = requests.post(
                        f"{API}/api/procesos/evaluar-requisito-{requisito}/proponente",
                        json={"documento_base": proceso_json, "proponente": p_json},
                        timeout=120,
                    )
                    item2 = r2.json()
                except Exception as exc:  # noqa: BLE001
                    print(f"    {hoja}: excepción en reintento: {exc}")
                    aun_con_error.append(hoja)
                    continue
                resultados_todos[hoja][requisito] = item2
                if item2.get("error") and "descargar" in (item2.get("error") or ""):
                    aun_con_error.append(hoja)
            con_error_red = aun_con_error

        if con_error_red:
            print(f"  ADVERTENCIA: {len(con_error_red)} proponentes siguen con error de red tras 3 reintentos: {con_error_red}")

        # guardar progreso incremental por si algo falla despues
        with open(".scratch/nuestros_resultados.json", "w") as f:
            json.dump(resultados_todos, f, ensure_ascii=False)

    print("\nComparando contra ground truth...")
    comparacion = []
    for hoja, idx_gt in mapeo.items():
        gt_proponente = ground_truth[idx_gt]
        for requisito in range(1, 19):
            nuestro = resultados_todos.get(hoja, {}).get(requisito)
            gt_req = gt_proponente["requisitos"].get(str(requisito)) or gt_proponente["requisitos"].get(requisito)
            if nuestro is None or gt_req is None:
                continue
            v_nuestro = nuestro_veredicto(nuestro)
            v_gt = (gt_req.get("veredicto") or "?").replace(".", "").strip()
            v_nuestro_cmp = v_nuestro.replace(".", "")
            comparacion.append(
                {
                    "hoja": hoja,
                    "nombre": proponentes_por_hoja[hoja].nombre_proponente,
                    "requisito": requisito,
                    "nuestro": v_nuestro,
                    "ground_truth": gt_req.get("veredicto"),
                    "coincide": v_nuestro_cmp == v_gt,
                    "nota_gt": gt_req.get("nota", "")[:150],
                    "archivo_nuestro": nuestro.get("archivo_evaluado"),
                    "motivo_nuestro": (nuestro.get("motivo") or "")[:150],
                }
            )

    with open(".scratch/comparacion.json", "w") as f:
        json.dump(comparacion, f, ensure_ascii=False, indent=1)

    total = len(comparacion)
    coinciden = sum(1 for c in comparacion if c["coincide"])
    print(f"\nTotal comparaciones: {total}")
    print(f"Coinciden: {coinciden} ({100*coinciden/total:.1f}%)")
    print(f"No coinciden: {total - coinciden}")

    print("\nPor requisito:")
    for requisito in range(1, 19):
        items = [c for c in comparacion if c["requisito"] == requisito]
        if not items:
            continue
        ok = sum(1 for c in items if c["coincide"])
        print(f"  Req {requisito}: {ok}/{len(items)} ({100*ok/len(items):.0f}%)")


if __name__ == "__main__":
    main()
