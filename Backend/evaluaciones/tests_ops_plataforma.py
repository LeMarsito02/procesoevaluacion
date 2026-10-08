"""Prestación de servicios en la plataforma: licencia, permisos, análisis en
el trabajador, decisiones de la persona y certificado. Datos inventados."""
from __future__ import annotations

import io
import shutil
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from docx import Document

from cuentas.models import EventoAuditoria
from cuentas.tests import Cliente
from evaluaciones import ops
from evaluaciones.models import ContratacionOps, EstadoOps, TablaHonorariosOps
from evaluaciones.tests import BaseEvaluaciones
from evaluaciones.tests_ops import ACTA_POSGRADO, ACTA_PREGRADO, CONTRACTUAL, ESTUDIO_COMPLETO, LABORAL, TERMINADO

NOMBRE, CEDULA = "Ana Inventada Pérez", "1000000001"
PAGINAS = {
    b"estudio": [ESTUDIO_COMPLETO],
    b"cdp": ["CERTIFICADO DE DISPONIBILIDAD PRESUPUESTAL\nTOTAL CDP 90,000,000.00"],
    b"certificaciones": [CONTRACTUAL.replace("ANA INVENTADA PÉREZ", f"ANA INVENTADA PÉREZ, cédula {CEDULA},"), LABORAL, TERMINADO],
    b"titulos": [ACTA_PREGRADO, ACTA_POSGRADO],
    b"rut": [f"Formulario del Registro Único Tributario {CEDULA}"],
    b"otra": ["CORPORACIÓN DE RÍO INVENTADO\nCERTIFICA\nFECHA DE INICIO: 01/01/2022\nFECHA DE TERMINACIÓN: 30/06/2022"],
}


def _paginas(contenido: bytes, max_paginas: int | None = None) -> list[str]:
    return PAGINAS[contenido][:max_paginas]


def _pdf(nombre: str, contenido: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(nombre, contenido, content_type="application/pdf")


class OpsPlataformaTests(BaseEvaluaciones):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.carpeta = tempfile.mkdtemp()
        cls.ajustes = override_settings(MEDIA_ROOT=cls.carpeta)
        cls.ajustes.enable()

    @classmethod
    def tearDownClass(cls):
        cls.ajustes.disable()
        shutil.rmtree(cls.carpeta, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        call_command("honorarios_iccu", nit=self.entidad1.nit, stdout=io.StringIO())
        self.entidad1.refresh_from_db()
        self.abogado = Cliente()
        self.abogado.entrar("abogado@entidad.gov.co")

    def _crear(self, c=None, **campos):
        c = c or self.abogado
        datos = {
            "contratista_nombre": NOMBRE, "contratista_cedula": "1.000.000.001", "fecha_referencia": "2026-01-22", "exige_libreta": "no",
            "documentos_entidad": [_pdf("estudio previo.pdf", b"estudio"), _pdf("cdp.pdf", b"cdp")],
            "documentos_contratista": [_pdf("14. certificaciones.pdf", b"certificaciones"), _pdf("19. titulos.pdf", b"titulos"),
                                       _pdf("9. RUT.pdf", b"rut"), _pdf("otra certificacion.pdf", b"otra")],
            **campos,
        }
        return c.http.post("/api/ops", datos, headers=c._h())

    def _analizar(self):
        cumple = mock.Mock(cumple=True, archivo=None)
        with (
            mock.patch("motor.ops.expediente.paginas_de_texto", _paginas),
            mock.patch("motor.ops.documentos.paginas_de_texto", _paginas),
            mock.patch("motor.ops.documentos.antecedentes.evaluar_antecedente", return_value=cumple),
        ):
            return ops.atender_pendientes()

    def _lista(self):
        r = self._crear()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["estado"], "pendiente")
        self.assertEqual(self._analizar(), 1)
        return r.json()["id"]

    def test_sin_licencia_la_opcion_queda_con_candado(self):
        self.entidad1.modulo_ops = False
        self.entidad1.save(update_fields=["modulo_ops"])
        self.assertEqual(self.abogado.get("/api/ops").json()["licenciado"], False)
        r = self._crear()
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "La entidad no tiene la licencia del módulo de prestación de servicios."))
        self.assertEqual(ContratacionOps.objects.count(), 0)

    def test_crear_exige_rol_nombre_cedula_y_un_pdf(self):
        control = Cliente()
        control.entrar("control@entidad.gov.co")
        self.assertEqual(self._crear(control).status_code, 403)
        self.assertEqual(self._crear(contratista_cedula="12").status_code, 400)
        r = self._crear(documentos_contratista=[SimpleUploadedFile("hoja.docx", b"texto")])
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "«hoja.docx» no es un PDF ni un .zip."))
        self.assertEqual(ContratacionOps.objects.count(), 0)

    def test_analisis_lee_perfil_experiencia_y_documentos(self):
        d = self.abogado.get(f"/api/ops/{self._lista()}").json()
        self.assertEqual((d["estado"], d["contratista_cedula"], d["cdp"]["valor"], d["estudio"]["plazo_meses"]), ("lista", CEDULA, 90_000_000, 10))
        self.assertEqual((d["perfil"]["anios_minimos"], d["perfil"]["anios_maximos"], d["perfil"]["posgrado"], d["perfil"]["honorarios_mensuales"]),
                         (10, 15, "especializacion", 9_000_000))
        self.assertEqual((d["grado"], d["posgrado"]), ("2004-06-11", "especializacion"))
        # 2009-2010: 540 · 2012-2019: 2837 · 2020-2021: 508 · 2022 (archivo suelto): 180 · 2024: 285
        self.assertEqual([(f["inicio"][:4], f["estado"], f["dias"]) for f in d["experiencia"]],
                         [("2009", "cuenta", 540), ("2012", "cuenta", 2837), ("2020", "cuenta", 508), ("2022", "cuenta", 180), ("2024", "cuenta", 285)])
        self.assertEqual((d["total_dias"], d["franja"], d["tope"], d["relacionada_dias"]), (4350, "entre 10 y 15 años", 9_588_365, 285))
        self.assertEqual(d["experiencia"][-1]["obligaciones_iguales"], [1])
        estados = {x["clave"]: x["estado"] for x in d["documentos"]}
        self.assertEqual((estados["rut"], estados["titulos"], estados["certificaciones_laborales"], estados["disciplinarios"], estados["cedula"]),
                         ("cumple", "cumple", "cumple", "cumple", "falta"))
        self.assertIsNone(d["cumple"])
        self.assertGreater(d["documentos_pendientes"], 10)

    def test_la_persona_retira_un_periodo_corrige_el_perfil_y_un_analisis_nuevo_no_lo_pisa(self):
        cid = self._lista()
        d = self.abogado.get(f"/api/ops/{cid}").json()
        viejo = d["experiencia"][0]["id"]
        r = self.abogado.put(f"/api/ops/{cid}/decisiones", {
            "periodos": {viejo: {"incluir": False}}, "grado": "2013-01-01",
            "perfil": {"anios_minimos": 5, "anios_maximos": 10, "posgrado": "maestria", "honorarios_mensuales": 9_000_000},
        })
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual([(f["inicio"][:4], f["estado"]) for f in d["experiencia"]][:2], [("2009", "retirado"), ("2012", "cuenta")])
        # Desde el grado de 2013: 2520 (2013-2019) + 508 + 180 + 285
        self.assertEqual((d["total_dias"], d["franja"], d["perfil"]["corregido"], d["grado_corregido"]), (3493, "entre 5 y 10 años", True, True))
        self.assertIn("Los honorarios ($9.000.000) superan el tope de la franja entre 5 y 10 años ($8.045.300).", d["revisiones"])
        self.assertEqual(self.abogado.put(f"/api/ops/{cid}/decisiones", {"periodos": {"p99": {"incluir": False}}}).status_code, 400)
        self.assertEqual(self.abogado.post(f"/api/ops/{cid}/reanalizar").json()["estado"], "pendiente")
        self._analizar()
        self.assertEqual(self.abogado.get(f"/api/ops/{cid}").json()["total_dias"], 3493)
        self.assertTrue(EventoAuditoria.objects.filter(accion="ops.decision", objeto_id=cid).exists())

    def test_sobra_experiencia_se_propone_retirar_y_la_persona_puede_conservarla(self):
        cid = self._lista()
        perfil = {"anios_minimos": 5, "anios_maximos": 10, "posgrado": "especializacion", "honorarios_mensuales": 8_000_000}
        d = self.abogado.put(f"/api/ops/{cid}/decisiones", {"perfil": perfil}).json()
        # Sobran los más antiguos que no dejan la experiencia por debajo del mínimo; la relacionada se conserva.
        self.assertEqual([(f["inicio"][:4], f["estado"]) for f in d["experiencia"]],
                         [("2009", "sobra"), ("2012", "cuenta"), ("2020", "sobra"), ("2022", "cuenta"), ("2024", "cuenta")])
        self.assertEqual(d["total_dias"], 4350 - 540 - 508)
        todos = {f["id"]: {"incluir": True} for f in d["experiencia"]}
        d = self.abogado.put(f"/api/ops/{cid}/decisiones", {"periodos": todos}).json()
        self.assertEqual((d["experiencia"][0]["estado"], d["experiencia"][0]["fijo"], d["total_dias"]), ("cuenta", True, 4350))
        self.assertIn("pasa de los 10 años del perfil con los periodos que se conservan.", d["revisiones"][-1])

    def test_confirmar_exige_decidir_los_documentos_y_bloquea_los_cambios(self):
        cid = self._lista()
        r = self.abogado.post(f"/api/ops/{cid}/confirmar")
        self.assertEqual(r.status_code, 409)
        self.assertIn("documentos por revisar", r.json()["detail"])
        d = self.abogado.get(f"/api/ops/{cid}").json()
        pendientes = {x["clave"]: {"estado": "cumple", "nota": "Verificado en el expediente físico"} for x in d["documentos"] if x["estado_final"] != "cumple"}
        d = self.abogado.put(f"/api/ops/{cid}/decisiones", {"documentos": pendientes}).json()
        self.assertEqual((d["documentos_pendientes"], d["cumple"]), (0, True))
        d = self.abogado.post(f"/api/ops/{cid}/confirmar").json()
        self.assertEqual((d["estado"], d["confirmada_por"]), ("confirmada", "Abogado Uno"))
        self.assertEqual(self.abogado.put(f"/api/ops/{cid}/decisiones", {"grado": "2010-01-01"}).status_code, 409)
        self.assertEqual(self.abogado.delete(f"/api/ops/{cid}").status_code, 409)
        self.assertEqual(self.abogado.post(f"/api/ops/{cid}/reabrir").json()["estado"], "lista")

    def test_certificado_en_word(self):
        cid = self._lista()
        r = self.abogado.get(f"/api/ops/{cid}/certificado")
        self.assertEqual(r.status_code, 200)
        doc = Document(io.BytesIO(b"".join(r.streaming_content)))
        texto = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("Total de experiencia: 12 años, 1 meses y 0 días.", texto)
        self.assertIn("Experiencia exigida: entre 10 y 15 años.", texto)
        self.assertIn("Tope de la franja entre 10 y 15 años según Resolución 1750 de 2025: $ 9.588.365.", texto)
        filas = [[c.text for c in f.cells] for f in doc.tables[2].rows]
        self.assertEqual(filas[-1], ["INSTITUTO DE OBRAS DE VILLA FICTICIA", "IOVF-045-2024", "01/02/2024", "30/11/2024", "9 meses y 15 días", "Relacionada"])

    def test_solo_la_ven_quien_la_creo_y_el_administrador(self):
        cid = self._lista()
        archivo = ContratacionOps.objects.get(pk=cid).documentos.first()
        for email, ve in (("admin@entidad.gov.co", True), ("abogado2@entidad.gov.co", False), ("control@entidad.gov.co", False),
                          ("admin@otraentidad.gov.co", False)):
            c = Cliente()
            c.entrar(email)
            self.assertEqual(c.get(f"/api/ops/{cid}").status_code, 200 if ve else 404, email)
            self.assertEqual(len(c.get("/api/ops").json()["contrataciones"]), 1 if ve else 0, email)
            self.assertEqual(c.get(f"/api/ops/{cid}/documentos/{archivo.id}").status_code, 200 if ve else 404, email)

    def test_tabla_de_honorarios_la_registra_el_administrador(self):
        tabla = {"vigencia": 2027, "norma": "Resolución 9 de 2026", "reconocimiento": [],
                 "profesional": [{"desde": 0, "hasta": 5, "sin_especializacion": 1, "con_especializacion": 2, "con_maestria": 3},
                                 {"desde": 5, "hasta": None, "sin_especializacion": 4, "con_especializacion": 5, "con_maestria": 6}]}
        self.assertEqual(self.abogado.put("/api/ops/honorarios", tabla).status_code, 403)
        admin = Cliente()
        admin.entrar("admin@entidad.gov.co")
        r = admin.put("/api/ops/honorarios", tabla)
        self.assertEqual((r.status_code, sorted(r.json()["vigencias"])), (200, [2026, 2027]))
        cruzada = {**tabla, "profesional": [{**tabla["profesional"][0], "hasta": None}, tabla["profesional"][1]]}
        self.assertEqual(admin.put("/api/ops/honorarios", cruzada).status_code, 400)
        self.assertEqual(TablaHonorariosOps.objects.filter(entidad=self.entidad1).count(), 2)

    def test_nombre_y_cedula_se_leen_de_los_antecedentes_si_no_se_escriben(self):
        r = self._crear(contratista_nombre="", contratista_cedula="")
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()["id"]
        with mock.patch("evaluaciones.ops.identificar", return_value=("ANA INVENTADA PEREZ", CEDULA)):
            self._analizar()
        d = self.abogado.get(f"/api/ops/{cid}").json()
        self.assertEqual((d["estado"], d["contratista_nombre"], d["contratista_cedula"]), ("lista", "Ana Inventada Perez", CEDULA))
        self.assertEqual(self._crear(contratista_nombre="Ana", contratista_cedula="").status_code, 400)

    def test_si_no_se_pueden_leer_se_piden_y_al_corregirlos_se_vuelve_a_leer(self):
        cid = self._crear(contratista_nombre="", contratista_cedula="").json()["id"]
        self._analizar()
        d = self.abogado.get(f"/api/ops/{cid}").json()
        self.assertEqual(d["estado"], "error")
        self.assertIn("No se pudo leer el nombre y la cédula del contratista", d["error"])
        d = self.abogado.put(f"/api/ops/{cid}/datos", {"contratista_nombre": NOMBRE, "contratista_cedula": CEDULA}).json()
        self.assertEqual(d["estado"], "pendiente")
        self._analizar()
        self.assertEqual(self.abogado.get(f"/api/ops/{cid}").json()["estado"], "lista")
        # Cambiar solo el número del proceso no obliga a leer todo otra vez.
        self.assertEqual(self.abogado.put(f"/api/ops/{cid}/datos", {"referencia": "CPS-9-2026"}).json()["estado"], "lista")

    def test_antecedentes_de_otra_cedula_se_avisan(self):
        cid = self._crear().json()["id"]
        with mock.patch("evaluaciones.ops.identificar", return_value=("PEDRO OTRO RUIZ", "2000000002")):
            self._analizar()
        d = self.abogado.get(f"/api/ops/{cid}").json()
        self.assertIn("Los certificados de antecedentes son de la cédula 2000000002 (PEDRO OTRO RUIZ), no de la 1000000001", d["revisiones"][0])

    def test_la_persona_agrega_un_periodo_corrige_fechas_y_el_posgrado(self):
        cid = self._lista()
        nuevo = {"inicio": "2005-01-01", "fin": "2005-12-31", "entidad": "Municipio de Pueblo Nuevo", "referencia": "Jefe de planeación", "relacionada": True}
        d = self.abogado.put(f"/api/ops/{cid}/decisiones", {"agregar": nuevo}).json()
        fila = d["experiencia"][0]
        self.assertEqual((fila["id"], fila["manual"], fila["dias"], fila["relacionada"], d["total_dias"], d["relacionada_dias"]),
                         ("m1", True, 360, True, 4350 + 360, 285 + 360))
        self.assertEqual(self.abogado.put(f"/api/ops/{cid}/decisiones", {"agregar": {**nuevo, "fin": "2004-01-01"}}).status_code, 400)
        # Corrige la terminación de un periodo leído: ya no trae la nota de lectura dudosa.
        leido = next(f for f in d["experiencia"] if f["inicio"].startswith("2022"))
        d = self.abogado.put(f"/api/ops/{cid}/decisiones", {"periodos": {leido["id"]: {"fin": "2022-12-30"}}}).json()
        corregido = next(f for f in d["experiencia"] if f["id"] == leido["id"])
        self.assertEqual((corregido["fin"], corregido["corregido"], corregido["dias"]), ("2022-12-30", True, 360))
        self.assertEqual(self.abogado.put(f"/api/ops/{cid}/decisiones", {"periodos": {leido["id"]: {"fin": "2021-01-01"}}}).status_code, 400)
        d = self.abogado.put(f"/api/ops/{cid}/decisiones", {"quitar": "m1", "posgrado": "maestria"}).json()
        self.assertEqual((d["experiencia"][0]["id"] != "m1", d["posgrado"], d["posgrado_corregido"], d["tope"]), (True, "maestria", True, 10_234_769))
        self.assertEqual(self.abogado.put(f"/api/ops/{cid}/decisiones", {"quitar": leido["id"]}).status_code, 400)

    def test_un_analisis_que_falla_queda_en_error_y_se_puede_repetir(self):
        r = self._crear()
        with mock.patch("evaluaciones.ops.analizar", side_effect=RuntimeError("PDF dañado")):
            ops.atender_pendientes()
        c = ContratacionOps.objects.get(pk=r.json()["id"])
        self.assertEqual((c.estado, c.error), (EstadoOps.ERROR, "No se pudo analizar: PDF dañado"))
        self.assertEqual(self.abogado.post(f"/api/ops/{c.id}/reanalizar").json()["estado"], "pendiente")
