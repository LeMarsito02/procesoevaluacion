"""Subida de ofertas por pedazos: hasta 10 GB por archivo, se retoma si se corta."""
import io
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from cuentas.tests import Cliente
from evaluaciones import preparacion
from evaluaciones.models import PreparacionProceso
from evaluaciones.tests import BaseEvaluaciones
from evaluaciones.tests_preparacion import DOCUMENTO


def _contenedor():
    """Un zip con dos ofertas adentro, cada una en su propio zip."""
    def oferta(nombre):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr(f"{nombre}.pdf", b"%PDF-1.4 " + nombre.encode() * 50)
        return b.getvalue()
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("p1 ALFA S.A.S.zip", oferta("alfa"))
        z.writestr("p2 CONSORCIO BETA.zip", oferta("beta"))
    return b.getvalue()


class SubidasTests(BaseEvaluaciones):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ajustes = override_settings(SUBIDAS_DIR=Path(self.tmp.name))
        self.ajustes.enable()
        # Cada prueba empieza sin cargas registradas (el registro es de la caché de ofertas).
        from evaluaciones import subidas
        subidas._indice().unlink(missing_ok=True)
        self.jefe = Cliente()
        self.jefe.entrar("jefe@entidad.gov.co")

    def tearDown(self):
        self.ajustes.disable()
        self.tmp.cleanup()

    def _pedazo(self, cliente, sid, desde, datos):
        return cliente.http.put(f"/api/procesos/subidas/{sid}?desde={desde}", data=datos, content_type="application/octet-stream",
                                headers={"X-CSRFToken": cliente.csrf})

    def _subir(self, datos, nombre="todas las ofertas.zip", pedazo=1000):
        s = self.jefe.post("/api/procesos/subidas", {"nombre": nombre, "tamano": len(datos)}).json()
        for i in range(0, len(datos), pedazo):
            r = self._pedazo(self.jefe, s["id"], i, datos[i:i + pedazo])
            self.assertEqual(r.status_code, 200, r.content[:200])
        return s["id"]

    def test_por_pedazos_en_orden_y_se_retoma(self):
        datos = b"x" * 2500
        s = self.jefe.post("/api/procesos/subidas", {"nombre": "oferta.zip", "tamano": len(datos)}).json()
        self.assertEqual((s["recibido"], s["completa"]), (0, False))
        self.assertEqual(self._pedazo(self.jefe, s["id"], 0, datos[:1000]).json()["recibido"], 1000)
        # Un pedazo repetido o adelantado no se pega: dice desde dónde seguir.
        r = self._pedazo(self.jefe, s["id"], 2000, datos[2000:])
        self.assertEqual(r.status_code, 409)
        self.assertIn("1000 bytes", r.json()["detail"])
        # Se cortó: al volver, pregunta cuánto llegó y sigue desde ahí.
        self.assertEqual(self.jefe.get(f"/api/procesos/subidas/{s['id']}").json()["recibido"], 1000)
        self._pedazo(self.jefe, s["id"], 1000, datos[1000:2000])
        d = self._pedazo(self.jefe, s["id"], 2000, datos[2000:]).json()
        self.assertEqual((d["recibido"], d["completa"]), (2500, True))
        self.assertEqual(self._pedazo(self.jefe, s["id"], 2500, b"y").status_code, 400)

    def test_solo_de_quien_la_creo_y_con_limite(self):
        s = self.jefe.post("/api/procesos/subidas", {"nombre": "oferta.zip", "tamano": 10}).json()
        otro = Cliente()
        otro.entrar("abogado@entidad.gov.co")
        self.assertEqual(otro.get(f"/api/procesos/subidas/{s['id']}").status_code, 404)
        self.assertEqual(self._pedazo(otro, s["id"], 0, b"1234567890").status_code, 404)
        with override_settings(SUBIDA_MAXIMA_ARCHIVO=100):
            r = self.jefe.post("/api/procesos/subidas", {"nombre": "grande.zip", "tamano": 101})
        self.assertEqual(r.status_code, 413)
        self.assertEqual(self.jefe.get("/api/procesos/subidas/../../etc").status_code, 404)

    def test_incompleta_no_crea_la_preparacion(self):
        s = self.jefe.post("/api/procesos/subidas", {"nombre": "oferta.zip", "tamano": 10}).json()
        r = self.jefe.http.post("/api/procesos/preparaciones", {
            "codigo_proceso": "ENT-LP-1", "fecha_cierre": "2026-08-03", "subidas": [s["id"]],
            "archivo": SimpleUploadedFile("db.pdf", b"%PDF-1.4", content_type="application/pdf")}, headers={"X-CSRFToken": self.jefe.csrf})
        self.assertEqual(r.status_code, 409)

    def test_el_trabajador_reparte_desde_el_disco_y_borra_los_temporales(self):
        sid = self._subir(_contenedor())
        r = self.jefe.http.post("/api/procesos/preparaciones", {
            "codigo_proceso": "ENT-LP-2", "fecha_cierre": "2026-08-03", "subidas": [sid],
            "archivo": SimpleUploadedFile("db.pdf", b"%PDF-1.4", content_type="application/pdf")}, headers={"X-CSRFToken": self.jefe.csrf})
        self.assertEqual(r.status_code, 200, r.content[:300])
        with mock.patch("motor.parsers.documento_base.build_proceso", return_value=DOCUMENTO), \
             mock.patch("evaluaciones.pliego.leer", side_effect=RuntimeError("sin IA")):
            preparacion.atender_pendientes()
        d = self.jefe.get(f"/api/procesos/preparaciones/{r.json()['id']}").json()
        self.assertEqual(d["estado"], "lista")
        self.assertEqual([(x["hoja"], x["nombre_proponente"]) for x in d["resultado"]["proponentes"]],
                         [("P-01", "ALFA S.A.S"), ("P-02", "CONSORCIO BETA")])
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
        self.assertIn("proponentes", PreparacionProceso.objects.get(pk=d["id"]).ofertas_subidas)

    def test_el_mismo_archivo_no_se_vuelve_a_subir(self):
        from evaluaciones import subidas

        datos = _contenedor()
        ruta = Path(self.tmp.name) / "local.zip"
        ruta.write_bytes(datos)
        huella = subidas.huella_rapida(ruta)
        ruta.unlink()

        def preparar(ids):
            r = self.jefe.http.post("/api/procesos/preparaciones", {
                "codigo_proceso": "ENT-LP-3", "fecha_cierre": "2026-08-03", "subidas": ids,
                "archivo": SimpleUploadedFile("db.pdf", b"%PDF-1.4", content_type="application/pdf")}, headers={"X-CSRFToken": self.jefe.csrf})
            self.assertEqual(r.status_code, 200, r.content[:300])
            with mock.patch("motor.parsers.documento_base.build_proceso", return_value=DOCUMENTO), \
                 mock.patch("evaluaciones.pliego.leer", side_effect=RuntimeError("sin IA")):
                preparacion.atender_pendientes()
            return self.jefe.get(f"/api/procesos/preparaciones/{r.json()['id']}").json()["resultado"]["proponentes"]

        # Primera vez: se sube completo y se reparte.
        s1 = self.jefe.post("/api/procesos/subidas", {"nombre": "OFERTAS.zip", "tamano": len(datos), "huella": huella}).json()
        self.assertFalse(s1["reutilizada"])
        for i in range(0, len(datos), 1000):
            self._pedazo(self.jefe, s1["id"], i, datos[i:i + 1000])
        primera = preparar([s1["id"]])
        # Segunda vez, el mismo archivo: no se sube nada y salen las mismas ofertas.
        s2 = self.jefe.post("/api/procesos/subidas", {"nombre": "OFERTAS.zip", "tamano": len(datos), "huella": huella}).json()
        self.assertTrue(s2["reutilizada"])
        self.assertEqual((s2["completa"], s2["ofertas"]), (True, 2))
        self.assertEqual(self._pedazo(self.jefe, s2["id"], 0, datos[:10]).status_code, 409)
        segunda = preparar([s2["id"]])
        self.assertEqual([(x["hoja"], x["drive_file_id"]) for x in segunda], [(x["hoja"], x["drive_file_id"]) for x in primera])
        # Otro archivo del mismo tamaño pero otro contenido: no se confunde.
        otra = self.jefe.post("/api/procesos/subidas", {"nombre": "OFERTAS.zip", "tamano": len(datos), "huella": "0" * 64}).json()
        self.assertFalse(otra["reutilizada"])

    def test_las_cargas_se_listan_por_entidad_y_se_eliminan(self):
        from cuentas.models import EventoAuditoria
        from evaluaciones import subidas
        from evaluaciones.models import Evaluacion
        from motor.integrations import ofertas_locales

        datos = _contenedor()
        ruta = Path(self.tmp.name) / "x.zip"
        ruta.write_bytes(datos)
        huella = subidas.huella_rapida(ruta)
        ruta.unlink()
        sid = self.jefe.post("/api/procesos/subidas", {"nombre": "OFERTAS.zip", "tamano": len(datos), "huella": huella}).json()["id"]
        for i in range(0, len(datos), 1000):
            self._pedazo(self.jefe, sid, i, datos[i:i + 1000])
        r = self.jefe.http.post("/api/procesos/preparaciones", {
            "codigo_proceso": "ENT-LP-4", "fecha_cierre": "2026-08-03", "subidas": [sid],
            "archivo": SimpleUploadedFile("db.pdf", b"%PDF-1.4", content_type="application/pdf")}, headers={"X-CSRFToken": self.jefe.csrf})
        with mock.patch("motor.parsers.documento_base.build_proceso", return_value=DOCUMENTO), \
             mock.patch("evaluaciones.pliego.leer", side_effect=RuntimeError("sin IA")):
            preparacion.atender_pendientes()
        props = self.jefe.get(f"/api/procesos/preparaciones/{r.json()['id']}").json()["resultado"]["proponentes"]
        self.jefe.delete(f"/api/procesos/preparaciones/{r.json()['id']}")

        lista = self.jefe.get("/api/procesos/cargas").json()
        self.assertEqual([(c["nombre"], c["ofertas"], c["completa"]) for c in lista], [("OFERTAS.zip", 2, True)])
        self.assertEqual(self.jefe.get(f"/api/procesos/cargas/{huella}?tamano={len(datos)}").json(), {"guardada": True, "ofertas": 2})
        # Otra entidad no la ve, no la reutiliza ni la elimina.
        otra = Cliente()
        otra.entrar("admin@otraentidad.gov.co")
        self.assertEqual(otra.get("/api/procesos/cargas").json(), [])
        self.assertFalse(otra.post("/api/procesos/subidas", {"nombre": "OFERTAS.zip", "tamano": len(datos), "huella": huella}).json()["reutilizada"])
        self.assertEqual(otra.delete(f"/api/procesos/cargas/{huella}").status_code, 404)
        # Una de las ofertas la usa un proceso: esa se conserva; la otra se borra.
        ev = self.crear(codigo="ENT-CARGA-1")[1]
        from evaluaciones.models import Proponente
        Proponente.objects.filter(proceso_id=Evaluacion.objects.get(pk=ev["id"]).proceso_id, hoja="P-01").update(drive_file_id=props[0]["drive_file_id"])
        d = self.jefe.delete(f"/api/procesos/cargas/{huella}").json()
        self.assertEqual(d["ofertas_borradas"], 1)
        self.assertTrue(ofertas_locales.existe(props[0]["drive_file_id"]))
        self.assertFalse(ofertas_locales.existe(props[1]["drive_file_id"]))
        self.assertEqual(self.jefe.get("/api/procesos/cargas").json(), [])
        self.assertFalse(self.jefe.post("/api/procesos/subidas", {"nombre": "OFERTAS.zip", "tamano": len(datos), "huella": huella}).json()["reutilizada"])
        self.assertTrue(EventoAuditoria.objects.filter(accion="ofertas.carga_eliminada").exists())

