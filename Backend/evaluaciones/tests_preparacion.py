"""Proceso a medio crear: la lectura va en segundo plano y sobrevive a recargar la página."""
import io
import zipfile
from datetime import date
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile

from cuentas.tests import Cliente
from evaluaciones import preparacion
from evaluaciones.models import PreparacionProceso
from evaluaciones.tests import DOCUMENTO_BASE, BaseEvaluaciones
from motor.esquemas.proceso import GarantiaSeriedad, Lote, ProcesoDocumentoBase

DOCUMENTO = ProcesoDocumentoBase(
    codigo_proceso="ENT-LP-014-2026", fecha_cierre=date(2026, 8, 3), objeto_general="MEJORAMIENTO DE LA VÍA",
    lotes=[Lote(numero="ÚNICO", objeto="MEJORAMIENTO DE LA VÍA", plazo_meses=8, valor_presupuesto=1_000_000_000.0, lugar_ejecucion="Chaguaní")],
    garantia_seriedad=GarantiaSeriedad(vigencia_meses=3, porcentaje=0.10, valor_asegurado=100_000_000.0, valor_base=1_000_000_000.0,
                                       fecha_cierre=date(2026, 8, 3), fecha_vencimiento=date(2026, 11, 3), base_calculo="presupuesto_total"),
    lote_mayor_valor="ÚNICO", presupuesto_total=1_000_000_000.0,
)


def _zip(nombre):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(f"{nombre}.pdf", b"%PDF-1.4")
    return b.getvalue()


class PreparacionTests(BaseEvaluaciones):
    def setUp(self):
        self.jefe = Cliente()
        self.jefe.entrar("jefe@entidad.gov.co")

    def _crear(self, cliente=None, **extra):
        datos = {"codigo_proceso": "ent-lp-014-2026", "fecha_cierre": "2026-08-03",
                 "archivo": SimpleUploadedFile("Documento base.pdf", b"%PDF-1.4 prueba", content_type="application/pdf"),
                 "ofertas": [SimpleUploadedFile("p1 ALFA S.A.S.zip", _zip("alfa"), content_type="application/zip")], **extra}
        c = cliente or self.jefe
        return c.http.post("/api/procesos/preparaciones", datos, headers={"X-CSRFToken": c.csrf})

    def _leer(self):
        with mock.patch("motor.parsers.documento_base.build_proceso", return_value=DOCUMENTO), \
             mock.patch("evaluaciones.pliego.leer", side_effect=RuntimeError("sin IA en pruebas")):
            return preparacion.atender_pendientes()

    def test_responde_al_instante_y_el_trabajador_la_lee(self):
        r = self._crear()
        self.assertEqual(r.status_code, 200, r.content[:300])
        p = r.json()
        self.assertEqual((p["estado"], p["codigo"], p["ofertas_subidas"]), ("pendiente", "ENT-LP-014-2026", True))
        self.assertIsNone(p["resultado"])
        self.assertEqual(self._leer(), 1)
        d = self.jefe.get(f"/api/procesos/preparaciones/{p['id']}").json()
        self.assertEqual((d["estado"], d["progreso"]), ("lista", 100))
        self.assertEqual(d["resultado"]["documento_base"]["lotes"][0]["plazo_meses"], 8)
        self.assertEqual([x["hoja"] for x in d["resultado"]["proponentes"]], ["P-01"])
        # El pliego falló, pero eso no tumba la lectura: queda dicho.
        self.assertIn("sin IA en pruebas", d["resultado"]["pliego_error"])
        # Recargar la página: la lista la sigue mostrando.
        self.assertEqual([x["id"] for x in self.jefe.get("/api/procesos/preparaciones").json()], [p["id"]])

    def test_solo_la_ve_quien_la_creo_y_se_elimina(self):
        p = self._crear().json()
        otro = Cliente()
        otro.entrar("abogado@entidad.gov.co")
        self.assertEqual(otro.get(f"/api/procesos/preparaciones/{p['id']}").status_code, 404)
        self.assertEqual(otro.get("/api/procesos/preparaciones").json(), [])
        self.assertEqual(self.jefe.delete(f"/api/procesos/preparaciones/{p['id']}").status_code, 204)
        self.assertFalse(PreparacionProceso.objects.filter(pk=p["id"]).exists())

    def test_error_y_reintento(self):
        p = self._crear().json()
        with mock.patch("motor.parsers.documento_base.build_proceso", side_effect=ValueError("PDF dañado")):
            preparacion.atender_pendientes()
        d = self.jefe.get(f"/api/procesos/preparaciones/{p['id']}").json()
        self.assertEqual(d["estado"], "error")
        self.assertIn("PDF dañado", d["error"])
        d = self.jefe.post(f"/api/procesos/preparaciones/{p['id']}/reintentar").json()
        self.assertEqual(d["estado"], "pendiente")
        self._leer()
        self.assertEqual(self.jefe.get(f"/api/procesos/preparaciones/{p['id']}").json()["estado"], "lista")

    def test_al_crear_el_proceso_se_borra(self):
        p = self._crear().json()
        self._leer()
        r = self.jefe.post("/api/evaluaciones/procesos", {
            "documento_base": {**DOCUMENTO_BASE, "codigo_proceso": "ENT-LP-014-2026"}, "carpeta_drive": "",
            "proponentes": [{"numero_orden": 1, "hoja": "P-01", "nombre_proponente": "ALFA", "nombre_archivo": "p1.zip", "drive_file_id": "a1"}],
            "preparacion_id": p["id"]})
        self.assertEqual(r.status_code, 201, r.content[:300])
        self.assertFalse(PreparacionProceso.objects.filter(pk=p["id"]).exists())

    def test_sin_ofertas_tambien_se_puede(self):
        r = self._crear(ofertas=[])
        self.assertEqual(r.status_code, 200, r.content[:300])
        self._leer()
        self.assertEqual(self.jefe.get(f"/api/procesos/preparaciones/{r.json()['id']}").json()["resultado"]["proponentes"], [])
