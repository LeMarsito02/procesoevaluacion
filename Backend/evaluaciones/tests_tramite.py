"""Traslado del informe: días hábiles y matriz de observaciones (RF-16)."""
from __future__ import annotations

import io
from datetime import date
from unittest import mock

import openpyxl
from django.test import SimpleTestCase

from cuentas.models import EventoAuditoria
from cuentas.tests import Cliente
from evaluaciones.calendario import dias_habiles_entre, es_habil, festivos, sumar_dias_habiles
from evaluaciones.tests import BaseEvaluaciones


class CalendarioTests(SimpleTestCase):
    def test_festivos_de_colombia(self):
        f = festivos(2026)
        # Fijos, trasladados al lunes y los que dependen de la Pascua (5 de abril de 2026).
        for dia in (date(2026, 1, 1), date(2026, 1, 12), date(2026, 3, 23), date(2026, 4, 2), date(2026, 4, 3), date(2026, 5, 1),
                    date(2026, 5, 18), date(2026, 6, 8), date(2026, 6, 15), date(2026, 6, 29), date(2026, 7, 20), date(2026, 8, 7),
                    date(2026, 8, 17), date(2026, 10, 12), date(2026, 11, 2), date(2026, 11, 16), date(2026, 12, 8), date(2026, 12, 25)):
            self.assertIn(dia, f, dia)
        self.assertEqual(len(f), 18)
        self.assertFalse(es_habil(date(2026, 10, 10)))  # sábado

    def test_los_terminos_se_cuentan_en_dias_habiles_desde_el_dia_siguiente(self):
        # Publicado el viernes 9 de octubre de 2026; el lunes 12 es festivo.
        self.assertEqual(sumar_dias_habiles(date(2026, 10, 9), 1), date(2026, 10, 13))
        self.assertEqual(sumar_dias_habiles(date(2026, 10, 9), 5), date(2026, 10, 19))
        self.assertEqual(dias_habiles_entre(date(2026, 10, 9), date(2026, 10, 19)), 5)
        self.assertEqual(dias_habiles_entre(date(2026, 10, 19), date(2026, 10, 9)), -5)


class TrasladoTests(BaseEvaluaciones):
    def setUp(self):
        self.jefe, self.ev = self.crear()
        self.jefe.post(f"/api/evaluaciones/{self.ev['id']}/asignar", {"responsable_id": str(self.evaluador.id)})
        self.abogado = Cliente()
        self.abogado.entrar("abogado@entidad.gov.co")
        self.url = f"/api/tramite/{self.ev['id']}"
        self.proponente = self.abogado.get(self.url).json()["proponentes"][0]["id"]

    def test_traslado_en_dias_habiles_sin_subsanaciones(self):
        d = self.abogado.put(f"{self.url}/traslado", {"publicado_en": "2026-10-09", "dias_habiles": 5}).json()
        self.assertEqual(d["traslado"]["vence_en"], "2026-10-19")
        with mock.patch("api.tramite.timezone.localdate", return_value=date(2026, 10, 21)):
            d = self.abogado.get(self.url).json()
        self.assertTrue(d["traslado"]["vencido"])
        self.assertNotIn("requerimientos", d)
        self.assertEqual(self.abogado.post(f"{self.url}/requerimientos", {}).status_code, 404)

    def test_observaciones_con_respuesta_trazable_y_matriz(self):
        self.abogado.put(f"{self.url}/traslado", {"publicado_en": "2026-10-09", "dias_habiles": 3})
        self.abogado.post(f"{self.url}/observaciones", {"observante": "Proponente 2", "recibida_en": "2026-10-14", "texto": "El proponente 1 no aportó la póliza.", "proponente_id": self.proponente, "requisito": 7})
        d = self.abogado.post(f"{self.url}/observaciones", {"observante": "Veeduría", "recibida_en": "2026-10-20", "texto": "Revisar el RUP."}).json()
        self.assertEqual([(o["consecutivo"], o["extemporanea"], o["decision"]) for o in d["observaciones"]], [(1, False, "pendiente"), (2, True, "pendiente")])
        self.assertEqual(d["resumen"]["sin_responder"], 2)
        oid = d["observaciones"][0]["id"]
        self.assertEqual(self.abogado.put(f"{self.url}/observaciones/{oid}", {"respuesta": "x", "decision": "pendiente"}).status_code, 400)
        self.abogado.put(f"{self.url}/observaciones/{oid}", {"respuesta": "Sí la aportó, folio 30.", "decision": "no_acoge"})
        d = self.abogado.put(f"{self.url}/observaciones/{oid}", {"respuesta": "Se revisó de nuevo: falta.", "decision": "acoge", "modifica_resultado": True}).json()
        o = d["observaciones"][0]
        self.assertEqual((o["decision"], o["modifica_resultado"], o["respondida_por"]), ("acoge", True, "Abogado Uno"))
        # La respuesta anterior no se pierde: queda en la auditoría.
        cambio = EventoAuditoria.objects.filter(accion="tramite.observacion_respuesta").latest("id")
        self.assertEqual(cambio.detalles["anterior"], {"respuesta": "Sí la aportó, folio 30.", "decision": "no_acoge"})
        r = self.abogado.get(f"{self.url}/matriz")
        libro = openpyxl.load_workbook(io.BytesIO(b"".join(r.streaming_content)))
        filas = list(libro["Observaciones"].iter_rows(min_row=4, values_only=True))
        self.assertEqual([f[8] for f in filas], ["Se acoge", "Pendiente"])
        self.assertEqual(filas[1][6], "Sí")

    def test_solo_el_comite_registra_y_nadie_de_fuera_ve(self):
        consulta = Cliente()
        consulta.entrar("abogado2@entidad.gov.co")
        self.assertEqual(consulta.get(self.url).status_code, 404)
        otra = Cliente()
        otra.entrar("admin@otraentidad.gov.co")
        self.assertEqual(otra.get(self.url).status_code, 404)
        admin = Cliente()
        admin.entrar("admin@entidad.gov.co")
        self.assertEqual(admin.get(self.url).status_code, 200)
        r = self.abogado.post(f"{self.url}/observaciones", {"observante": " ", "recibida_en": "2026-10-14", "texto": "algo"})
        self.assertEqual(r.status_code, 400)
