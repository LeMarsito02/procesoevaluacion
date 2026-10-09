"""Motor de OCR: PaddleOCR por un servicio local, con Tesseract de respaldo."""
import importlib.util
import pathlib
from unittest import mock

import requests
from django.test import SimpleTestCase
from PIL import Image

from motor.procesamiento import ocr_motor

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def _servidor():
    spec = importlib.util.spec_from_file_location("ocr_servidor", RAIZ / "ocr_servicio" / "servidor.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class OcrMotorTests(SimpleTestCase):
    imagen = Image.new("L", (20, 10), 255)

    def test_con_paddle_lee_el_servicio(self):
        respuesta = mock.Mock(json=lambda: {"texto": "OCHO (08) MESES"}, raise_for_status=lambda: None)
        with mock.patch.object(ocr_motor, "MOTOR", "paddle"), mock.patch.object(ocr_motor.requests, "post", return_value=respuesta) as post, \
                mock.patch.object(ocr_motor, "tesseract") as tess:
            self.assertEqual(ocr_motor.leer(self.imagen, psm="6"), "OCHO (08) MESES")
        self.assertTrue(post.call_args.args[0].endswith("/ocr"))
        tess.assert_not_called()

    def test_si_el_servicio_no_responde_usa_tesseract_y_lo_registra(self):
        with mock.patch.object(ocr_motor, "MOTOR", "paddle"), \
                mock.patch.object(ocr_motor.requests, "post", side_effect=requests.ConnectionError("caído")), \
                mock.patch.object(ocr_motor, "tesseract", return_value="texto de respaldo") as tess, \
                self.assertLogs("motor.procesamiento.ocr_motor", "ERROR") as registro:
            self.assertEqual(ocr_motor.leer(self.imagen, psm="6"), "texto de respaldo")
        tess.assert_called_once()
        self.assertIn("no respondió", registro.output[0])

    def test_por_defecto_tesseract_y_cache_aparte_por_motor(self):
        base = pathlib.Path("/x/cache/ocr")
        with mock.patch.object(ocr_motor, "MOTOR", "tesseract"), mock.patch.object(ocr_motor.requests, "post") as post, \
                mock.patch.object(ocr_motor, "tesseract", return_value="t"):
            self.assertEqual(ocr_motor.leer(self.imagen), "t")
            self.assertEqual(ocr_motor.directorio_cache(base), base)
        post.assert_not_called()
        with mock.patch.object(ocr_motor, "MOTOR", "paddle"):
            self.assertEqual(ocr_motor.directorio_cache(base), pathlib.Path("/x/cache/ocr_paddle"))

    def test_la_o_por_cero_solo_dentro_de_codigos_y_cifras(self):
        casos = {
            "proceso de contratación No. ICCU-LP-O14-2026.": "proceso de contratación No. ICCU-LP-014-2026.",
            "vigencia 2O26 y NIT 9OO.258.711-1": "vigencia 2026 y NIT 900.258.711-1",
            "Contrato 1O5 de 2O25": "Contrato 105 de 2025",
            "OCHO (08) MESES de OBRA en ICCU": "OCHO (08) MESES de OBRA en ICCU",
            "RESOLUCIÓN No. 0045 del CONSORCIO VIAS 2026": "RESOLUCIÓN No. 0045 del CONSORCIO VIAS 2026",
            # Con un solo dígito legible: porcentajes, cifras entre paréntesis y valores en pesos.
            # «TREINTA POR CIENTO (3O%)» dejó a la financiera de ICCU-LP-014-2026 sin anticipo.
            "anticipo del TREINTA POR CIENTO (3O%) del valor": "anticipo del TREINTA POR CIENTO (30%) del valor",
            "TREINTA (3O) DIAS y DIEZ (1O) PUNTOS": "TREINTA (30) DIAS y DIEZ (10) PUNTOS",
            "por $ 1.OOO.OOO y el 1O %": "por $ 1.000.000 y el 10 %",
            "NIT 900.258.7l1-1 del 11/O9/2026": "NIT 900.258.711-1 del 11/09/2026",
            "CERO PUNTO VEINTICINCO (O.25) PUNTOS y (O,5)": "CERO PUNTO VEINTICINCO (0.25) PUNTOS y (0,5)",
            # Lo que es letra se queda: literales, palabras y ordinales.
            "(OBRA) (O) (a) (II) UNO (l) AÑO, ARTICULO 2O, MODELO l5, $ OBRA": "(OBRA) (O) (a) (II) UNO (l) AÑO, ARTICULO 2O, MODELO l5, $ OBRA",
        }
        for leido, esperado in casos.items():
            self.assertEqual(ocr_motor.corregir_digitos(leido), esperado, leido)

    def test_renglones_juntan_la_fila_de_una_tabla(self):
        servidor = _servidor()
        cajas = [[400, 100, 700, 130], [10, 102, 150, 128], [10, 160, 150, 190], [400, 158, 900, 192]]
        textos = ["3 meses contados a partir del cierre", "Vigencia", "Valor asegurado", "Diez por ciento (10%) del presupuesto oficial"]
        self.assertEqual(servidor.renglones(cajas, textos), [
            "Vigencia 3 meses contados a partir del cierre",
            "Valor asegurado Diez por ciento (10%) del presupuesto oficial",
        ])
