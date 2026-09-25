"""Comparar lo que el programa lee de cada pliego con lo que la entidad publicó.

La entidad publica en el SECOP el presupuesto oficial y el plazo de cada proceso,
y eso está en el portal de datos abiertos. Comparar las dos cifras es la forma más
barata de saber si un pliego se está leyendo mal: si el presupuesto que sale del
PDF no es el que la entidad publicó, algo falló, y casi siempre es que hay lotes
que no se reconocieron.

Así se encontraron dos: ICCU-LP-038 (dos lotes leídos como uno) e ICCU-LP-035
(tres leídos como uno). En ambos el presupuesto del proceso quedaba siendo el del
primer lote, y con él se calculaban el capital de trabajo, la capacidad residual y
la experiencia exigida.

    manage.py verificar_lectura_pliegos
    manage.py verificar_lectura_pliegos --solo ICCU-LP-038-2026
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand

DATASET = Path(__file__).resolve().parent.parent.parent.parent.parent / "datasetdepruebas"
RECURSO = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
# Diferencia a partir de la cual se considera que no coincide (el redondeo de los
# centavos no cuenta).
TOLERANCIA = 0.01


class Command(BaseCommand):
    help = "Compara el presupuesto y el plazo leídos de cada pliego con los publicados en el SECOP."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--solo", default="", help="un proceso en concreto")
        parser.add_argument("--sin-red", action="store_true",
                            help="solo lee los pliegos, sin consultar el SECOP")

    def handle(self, *args, **opciones) -> None:
        from motor.parsers.documento_base import build_proceso

        pliegos = sorted(DATASET.glob("*/*/pliego.pdf"))
        if opciones["solo"]:
            pliegos = [p for p in pliegos if opciones["solo"] in p.parent.name]
        if not pliegos:
            self.stdout.write("No hay pliegos en el dataset.")
            return
        self.stdout.write(f"{'PROCESO':22s} {'LEÍDO':>18s} {'PUBLICADO':>18s} {'DIF':>7s} {'PLAZO':>9s}  LOTES")
        iguales = distintos = sin_datos = 0
        for ruta in pliegos:
            codigo = ruta.parent.name
            pub = None if opciones["sin_red"] else self._publicado(codigo)
            cierre = date(2026, 7, 1)
            if pub and pub.get("fecha_de_recepcion_de"):
                cierre = date.fromisoformat(pub["fecha_de_recepcion_de"][:10])
            try:
                proceso = build_proceso(codigo, cierre, ruta.read_bytes())
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"{codigo:22s} no se pudo leer: {exc}"))
                distintos += 1
                continue
            leido = sum(l.valor_presupuesto or 0 for l in proceso.lotes)
            plazo = max((l.plazo_meses or 0) for l in proceso.lotes) if proceso.lotes else 0
            if pub is None:
                sin_datos += 1
                self.stdout.write(f"{codigo:22s} ${leido:>17,.0f} {'(sin datos)':>18s} {'':>7s} {plazo:>6}m   {len(proceso.lotes)}")
                continue
            suyo = float(pub.get("precio_base") or 0)
            dif = abs(leido - suyo) / suyo if suyo else 1
            plazo_suyo = pub.get("duracion") or "?"
            linea = (f"{codigo:22s} ${leido:>17,.0f} ${suyo:>17,.0f} {dif * 100:>6.1f}% "
                     f"{plazo:>4}/{str(plazo_suyo):<4} {len(proceso.lotes)}")
            if dif <= TOLERANCIA:
                iguales += 1
                self.stdout.write(linea)
            else:
                distintos += 1
                self.stdout.write(self.style.WARNING(linea + "  ← REVISAR"))
        self.stdout.write(f"\n{iguales} coinciden · {distintos} no coinciden · {sin_datos} sin datos publicados")
        if distintos:
            self.stdout.write(self.style.WARNING(
                "Lo que no coincide suele ser un pliego por lotes leído como uno solo: revise cuántos lotes "
                "salieron y si la tabla los nombra de una forma que el programa no reconozca."))

    def _publicado(self, codigo: str) -> dict | None:
        consulta = urllib.parse.urlencode({
            "$where": f"referencia_del_proceso like '{codigo}%'", "$limit": 5,
        })
        try:
            with urllib.request.urlopen(f"{RECURSO}?{consulta}", timeout=40) as respuesta:
                filas = json.loads(respuesta.read())
        except Exception:  # noqa: BLE001 — sin red, se sigue sin comparar
            return None
        for fila in filas:
            if float(fila.get("precio_base") or 0) > 0:
                return fila
        return None
