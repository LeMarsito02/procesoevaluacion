"""Auditoría automática de accesibilidad (WCAG 2.1 nivel AA, la que exige
MinTIC en la Resolución 1519 de 2020, anexo 1).

    python scripts/auditar_accesibilidad.py [--url http://localhost:5173] [--salida informe.json]

Abre cada pantalla en Chromium (Playwright), le inyecta axe-core y lista las
infracciones por regla. Revisa las pantallas que no exigen sesión: el ingreso y
el banco de previsualización (#/previsualizacion, solo en desarrollo), que
muestra los componentes de revisión con datos inventados. Así la auditoría no
necesita cuentas ni saltarse el segundo factor.

Sale con código 1 si hay infracciones graves o críticas: sirve en la
integración continua.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

AXE = Path(__file__).resolve().parents[2] / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
ETIQUETAS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]
PANTALLAS = {
    "Ingreso": "/",
    "Previsualización de la revisión": "/#/previsualizacion",
}
BLOQUEANTES = {"serious", "critical"}


def auditar(url_base: str) -> dict:
    informe: dict = {"norma": "WCAG 2.1 AA", "pantallas": {}}
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        for nombre, ruta in PANTALLAS.items():
            for ancho, dispositivo in ((1366, "escritorio"), (390, "celular")):
                pagina = navegador.new_page(viewport={"width": ancho, "height": 900})
                pagina.goto(url_base.rstrip("/") + ruta, wait_until="networkidle")
                pagina.wait_for_timeout(800)
                pagina.add_script_tag(path=str(AXE))
                resultado = pagina.evaluate(
                    "async (etiquetas) => await axe.run(document, {runOnly: {type: 'tag', values: etiquetas}})",
                    ETIQUETAS,
                )
                informe["pantallas"][f"{nombre} ({dispositivo})"] = {
                    "aprobadas": len(resultado["passes"]),
                    "infracciones": [
                        {
                            "regla": v["id"],
                            "impacto": v["impact"],
                            "descripcion": v["help"],
                            "criterios": [t for t in v["tags"] if t.startswith("wcag") and t[4:5].isdigit()],
                            "elementos": [n["target"][0] for n in v["nodes"]][:5],
                            "ocurrencias": len(v["nodes"]),
                        }
                        for v in resultado["violations"]
                    ],
                }
                pagina.close()
        navegador.close()
    return informe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:5173")
    parser.add_argument("--salida")
    args = parser.parse_args()
    informe = auditar(args.url)
    graves = 0
    for pantalla, datos in informe["pantallas"].items():
        print(f"\n{pantalla}: {datos['aprobadas']} reglas aprobadas, {len(datos['infracciones'])} con infracciones")
        for v in datos["infracciones"]:
            graves += v["impacto"] in BLOQUEANTES
            print(f"  [{v['impacto']}] {v['regla']} ({v['ocurrencias']}): {v['descripcion']} — {', '.join(v['elementos'])}")
    if args.salida:
        Path(args.salida).write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nInfracciones graves o críticas: {graves}")
    return 1 if graves else 0


if __name__ == "__main__":
    sys.exit(main())
