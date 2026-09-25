"""Que los pliegos reales se sigan leyendo completos.

Las pruebas de los otros archivos usan textos inventados o recortes de un pliego,
que es lo que permite fijar un caso concreto sin depender de material que no está
en el repositorio. Esta hace lo contrario: abre los pliegos del dataset y
comprueba que de cada uno se leen los lotes, el presupuesto, el plazo y la
garantía. Es la red que avisa si una mejora futura rompe un pliego que ya
funcionaba —que es justo lo que pasó con «Lote No. 1»—.

No corre en la suite de siempre, porque necesita el dataset (que no se sube) y
porque uno de los pliegos es un escaneo de 95 páginas. Para correrla:

    PLIEGOS_REALES=1 manage.py test evaluaciones.tests_pliegos_reales
"""
from __future__ import annotations

import glob
import os
import unittest
from datetime import date
from pathlib import Path

from django.test import SimpleTestCase

DATASET = Path(__file__).resolve().parent.parent.parent / "datasetdepruebas"
PLIEGOS = sorted(glob.glob(str(DATASET / "*" / "*" / "pliego.pdf")))
# Cierre con el que se leen: solo importa para convertir a meses un plazo que el
# pliego dé como fecha límite.
CIERRE = date(2026, 7, 1)

razon = "necesita el dataset de pliegos y PLIEGOS_REALES=1 (uno de ellos es un escaneo de 95 páginas)"


@unittest.skipUnless(PLIEGOS and os.environ.get("PLIEGOS_REALES") == "1", razon)
class PliegosRealesTests(SimpleTestCase):
    def test_de_cada_pliego_se_lee_lo_que_hace_falta_para_evaluar(self):
        from motor.parsers.documento_base import build_proceso

        problemas: list[str] = []
        for ruta in PLIEGOS:
            nombre = Path(ruta).parent.name
            proceso = build_proceso(nombre, CIERRE, Path(ruta).read_bytes())
            if not proceso.lotes:
                problemas.append(f"{nombre}: no se identificó ningún lote")
                continue
            for lote in proceso.lotes:
                if not lote.valor_presupuesto:
                    problemas.append(f"{nombre} · {lote.numero}: sin presupuesto")
                if not lote.plazo_meses:
                    problemas.append(f"{nombre} · {lote.numero}: sin plazo")
                if not lote.objeto:
                    problemas.append(f"{nombre} · {lote.numero}: sin objeto")
            garantia = proceso.garantia_seriedad
            if not garantia.vigencia_meses:
                problemas.append(f"{nombre}: sin vigencia de la garantía")
            if not garantia.porcentaje:
                problemas.append(f"{nombre}: sin porcentaje de la garantía")
            if not garantia.valor_asegurado:
                problemas.append(f"{nombre}: sin valor asegurado")
        self.assertEqual(problemas, [], f"\n{len(PLIEGOS)} pliegos leídos:\n  " + "\n  ".join(problemas))

    def test_los_lotes_de_un_pliego_por_lotes_no_se_confunden(self):
        """Lo que se rompió una vez: un pliego de varios lotes leído como uno
        solo se evalúa con el presupuesto del primero."""
        from motor.parsers.documento_base import build_proceso

        esperados = {"ICCU-CM-030-2026": 2, "ICCU-CM-043-2026": 2, "ICCU-LP-035-2026": 3}
        for nombre, cuantos in esperados.items():
            rutas = [r for r in PLIEGOS if Path(r).parent.name == nombre]
            if not rutas:
                continue
            proceso = build_proceso(nombre, CIERRE, Path(rutas[0]).read_bytes())
            self.assertEqual(len(proceso.lotes), cuantos, f"{nombre}: {[l.numero for l in proceso.lotes]}")
            # Cada lote con su propio presupuesto, no el mismo repetido.
            presupuestos = {l.valor_presupuesto for l in proceso.lotes}
            self.assertEqual(len(presupuestos), cuantos, f"{nombre}: presupuestos {presupuestos}")
