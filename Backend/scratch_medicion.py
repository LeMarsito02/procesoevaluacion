"""Medición final de confiabilidad y tiempo.

Evalúa cada proponente UNA sola vez con la pasada única (los 18 requisitos
juntos, endpoint /evaluar-todos/proponente) y compara contra el Segundo
Informe (.scratch/ground_truth.json). El informe SOLO se usa para medir: nada
de este script alimenta la lógica del programa.

Reanudable: los proponentes ya evaluados sin error no se repiten."""
from __future__ import annotations

import collections
import os
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import requests

sys.path.insert(0, ".")
from motor.integrations.drive import list_proponentes
from motor.parsers.documento_base import build_proceso

# Fecha de cierre del proceso de referencia (formato AAAA-MM-DD en .env).
FECHA_CIERRE = date.fromisoformat(os.environ.get("MEDICION_FECHA_CIERRE", "2026-01-01"))
from scratch_comparar import API, DOC_BASE, DRIVE_FOLDER, emparejar_proponentes, nuestro_veredicto

# Otro proceso: MEDICION_DIR (dónde guardar) y MEDICION_GROUND_TRUTH (el
# informe de los abogados ya convertido; sin él, solo se evalúa y se resume).
DIR = os.environ.get("MEDICION_DIR", ".scratch")
RESULTADOS = f"{DIR}/medicion_resultados.json"
TIEMPOS = f"{DIR}/medicion_tiempos.json"
COMPARACION = f"{DIR}/medicion_comparacion.json"
GROUND_TRUTH = os.environ.get("MEDICION_GROUND_TRUTH", ".scratch/ground_truth.json")
CONCURRENCIA = 2
# RUT (Requisito 13): el abogado indicó ignorarlo; no se evalúa ni se mide.
REQUISITOS_IGNORADOS = {13}


def _cargar(path, defecto):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return defecto


def sesion_medicion() -> requests.Session:
    """Inicia sesión con la cuenta de medición (MEDICION_EMAIL / MEDICION_CLAVE en .env)."""
    import os

    from dotenv import load_dotenv

    load_dotenv(".env")
    http = requests.Session()
    csrf = http.get(f"{API}/api/auth/csrf").json()["csrf"]
    resp = http.post(
        f"{API}/api/auth/login",
        json={"email": os.environ["MEDICION_EMAIL"], "password": os.environ["MEDICION_CLAVE"]},
        headers={"X-CSRFToken": csrf, "Referer": API},
    )
    resp.raise_for_status()
    http.headers.update({"X-CSRFToken": resp.json()["csrf"], "Referer": API})
    return http


def evaluar(proceso_json, proponentes, mapeo):
    resultados = _cargar(RESULTADOS, {})
    tiempos = _cargar(TIEMPOS, {})
    pendientes = [
        p for p in proponentes
        if p.hoja in mapeo and (p.hoja not in resultados or any(r.get("error") for r in resultados[p.hoja]))
    ]
    print(f"Proponentes a evaluar: {len(pendientes)} (ya hechos: {len(mapeo) - len(pendientes)})", flush=True)

    http = sesion_medicion()

    def uno(p):
        t0 = time.time()
        resp = http.post(
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
        proceso = build_proceso(os.environ.get("MEDICION_CODIGO_PROCESO", ""), FECHA_CIERRE, f.read())
    proceso_json = json.loads(proceso.model_dump_json())
    if os.environ.get("MEDICION_PLIEGO"):
        proceso_json["criterios"] = definicion_con_pliego(os.environ["MEDICION_PLIEGO"])
    r = list_proponentes(DRIVE_FOLDER)
    ground_truth = _cargar(GROUND_TRUTH, None) if os.environ.get("MEDICION_SIN_REFERENCIA") != "1" else None
    if ground_truth is None:
        mapeo = {p.hoja: i for i, p in enumerate(r.proponentes)}
    elif ground_truth and "hoja" in ground_truth[0]:
        # Informes sin nombres: se empareja por la hoja (P-01, P-02…).
        por_hoja = {g["hoja"]: i for i, g in enumerate(ground_truth)}
        mapeo = {p.hoja: por_hoja[p.hoja] for p in r.proponentes if p.hoja in por_hoja}
    else:
        mapeo = emparejar_proponentes(r.proponentes, ground_truth)
    nombres = {p.hoja: p.nombre_proponente for p in r.proponentes}
    print(f"Proponentes emparejados con el informe: {len(mapeo)} / {len(r.proponentes)}", flush=True)
    if "--solo-comparar" not in sys.argv:
        resultados, tiempos = evaluar(proceso_json, r.proponentes, mapeo)
    else:
        resultados, tiempos = _cargar(RESULTADOS, {}), _cargar(TIEMPOS, {})
    if ground_truth is None:
        resumen_sin_referencia(resultados, tiempos)
    else:
        resumen(comparar(resultados, ground_truth, mapeo, nombres), tiempos)


def requisitos_leidos_con_ia() -> list:
    """Los requisitos que la IA leyó del pliego (MEDICION_REQUISITOS_IA con el
    JSON de scratch_lector_ia.py), para medir el analizador completo."""
    import json

    ruta = os.environ.get("MEDICION_REQUISITOS_IA")
    if not ruta or not os.path.exists(ruta):
        return []
    from motor.pliego.catalogo import verificacion_de
    from motor.pliego.lector_ia import RequisitoPliego, _NO_ES_REQUISITO_RE, _norm

    requisitos = []
    for d in json.load(open(ruta)):
        r = RequisitoPliego(**d)
        if "CAUSALES" in _norm(r.seccion) or _NO_ES_REQUISITO_RE.search(_norm(f"{r.requisito} {r.cita}")):
            continue
        r.verificacion = verificacion_de(r)
        requisitos.append(r)
    print(f"Requisitos leídos del pliego con IA: {len(requisitos)}", flush=True)
    return requisitos


def definicion_con_pliego(ruta: str) -> dict:
    """La definición del sistema con TODOS los ajustes que propone el análisis
    del pliego aceptados, como si la persona los hubiera aplicado."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from evaluaciones.pliego import aplicar_ajustes
    from motor import criterios
    from motor.pliego import analisis, lectura

    with open(ruta, "rb") as f:
        extraccion = analisis.extraer(lectura.leer_paginas(f.read()))
    definicion = criterios.definicion_sistema("juridica")
    ajustes = [
        {"decision": "aceptado", "hallazgo": h.model_dump(mode="json")}
        for h in analisis.comparar(extraccion, definicion, requisitos_leidos_con_ia())
        if h.requiere_decision
    ]
    for a in ajustes:
        print(f"Ajuste del pliego aplicado: {a['hallazgo']['titulo']}", flush=True)
    return aplicar_ajustes(definicion, ajustes).model_dump(mode="json")


def resumen_sin_referencia(resultados, tiempos):
    """Sin informe de los abogados: qué dijo el programa, cuánto tardó y dónde falló."""
    items = [x for lista in resultados.values() for x in lista if x["requisito"] not in REQUISITOS_IGNORADOS]
    conteo = collections.Counter(nuestro_veredicto(x) for x in items)
    total = max(len(items), 1)
    print(f"\n=== {len(resultados)} proponentes · {len(items)} verificaciones ===")
    print("Veredictos del programa:", dict(conteo))
    print(f"A revisión humana: {conteo['NO'] + conteo['ERROR']} ({100 * (conteo['NO'] + conteo['ERROR']) / total:.1f}%)")
    print("\nA revisión por requisito:")
    for req in range(1, 30):
        del_req = [x for x in items if x["requisito"] == req]
        if del_req:
            n = sum(nuestro_veredicto(x) in ("NO", "ERROR") for x in del_req)
            print(f"  Req {req:2d}: {n}/{len(del_req)} ({100 * n / len(del_req):.0f}%)")
    errores = [(h, x["requisito"], (x.get("error") or "")[:90]) for h, lista in resultados.items() for x in lista if x.get("error")]
    print(f"\nErrores de ejecución: {len(errores)}")
    for e in errores[:15]:
        print("  ", e)
    if tiempos:
        seg = list(tiempos.values())
        print(f"\nTiempo por proponente: promedio {sum(seg) / len(seg):.0f}s, máximo {max(seg):.0f}s")


if __name__ == "__main__":
    main()
