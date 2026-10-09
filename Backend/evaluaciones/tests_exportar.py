"""Exportación de la evaluación en XLSX, CSV y PDF (RF-22)."""
import csv
import io
import shutil
import unittest
from unittest import mock

import openpyxl
from django.test import SimpleTestCase

from cuentas.models import EventoAuditoria, Usuario
from evaluaciones import exportar
from evaluaciones.models import Evaluacion, Resultado, Revision
from evaluaciones.tests import BaseEvaluaciones


class PdfTests(SimpleTestCase):
    @unittest.skipUnless(shutil.which("soffice") or shutil.which("libreoffice"), "sin LibreOffice")
    def test_convierte_un_excel_a_pdf(self):
        libro = openpyxl.Workbook()
        libro.active.append(["Proponente", "Resultado"])
        libro.active.append(["P1 ALFA S.A.S.", "Cumple"])
        salida = io.BytesIO()
        libro.save(salida)
        pdf = exportar.a_pdf(salida.getvalue(), "informe.xlsx")
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_sin_libreoffice_da_un_error_claro(self):
        with mock.patch("evaluaciones.exportar.shutil.which", return_value=None), self.assertRaises(exportar.ErrorExportacion):
            exportar.a_pdf(b"x", "informe.xlsx")


class ExportarTests(BaseEvaluaciones):
    def setUp(self):
        self.jefe, self.ev = self.crear()
        ev = Evaluacion.objects.get(pk=self.ev["id"])
        p1, p2 = list(ev.proceso.proponentes.order_by("hoja"))[:2]

        def datos(p, requisito, **extra):
            return {"hoja": p.hoja, "numero_orden": p.numero_orden, "nombre_proponente": p.nombre, "requisito": requisito, **extra}
        Resultado.objects.create(entidad_id=ev.entidad_id, evaluacion=ev, proponente=p1, requisito=1,
                                 datos=datos(p1, 1, cumple=True, archivo_evaluado="carta.pdf"), requiere_revision=False)
        Resultado.objects.create(entidad_id=ev.entidad_id, evaluacion=ev, proponente=p2, requisito=1,
                                 datos=datos(p2, 1, cumple=False, motivo="Sin firma"), requiere_revision=True)
        Resultado.objects.create(entidad_id=ev.entidad_id, evaluacion=ev, proponente=p2, requisito=2,
                                 datos=datos(p2, 2, cumple=False, motivo="Falta"), requiere_revision=True)
        Revision.objects.create(entidad_id=ev.entidad_id, evaluacion=ev, proponente=p2, requisito=1, cumple=True, nota="Firma digital",
                                usuario=Usuario.objects.get(email="jefe@entidad.gov.co"))

    def test_csv_con_la_decision_final(self):
        r = self.jefe.get(f"/api/evaluaciones/{self.ev['id']}/resultados.csv")
        self.assertEqual(r.status_code, 200)
        texto = r.content.decode("utf-8")
        self.assertTrue(texto.startswith("﻿"))
        filas = list(csv.reader(io.StringIO(texto.lstrip("﻿")), delimiter=";"))
        self.assertEqual(filas[0][8], "Decisión final")
        decisiones = [(f[4], f[6], f[8], f[9]) for f in filas[1:]]
        self.assertEqual(decisiones, [("1", "Cumple", "Cumple", "Sistema"), ("1", "No cumple", "Cumple", "Jefe Jurídico"),
                                      ("2", "No cumple", "Pendiente de revisión", "")])
        self.assertTrue(EventoAuditoria.objects.filter(accion="informe.csv_descargado").exists())

    def test_informe_en_pdf_y_formato_no_valido(self):
        url = f"/api/evaluaciones/{self.ev['id']}/informe"
        self.assertEqual(self.jefe.get(f"{url}?formato=docx").status_code, 400)
        with mock.patch("evaluaciones.exportar.a_pdf", return_value=b"%PDF-1.7 prueba"):
            r = self.jefe.get(f"{url}?formato=pdf")
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "application/pdf"))
        self.assertIn('.pdf"', r["Content-Disposition"])
        self.assertEqual(r.content, b"%PDF-1.7 prueba")
        self.assertTrue(EventoAuditoria.objects.filter(accion="informe.descargado", detalles__formato="pdf").exists())
