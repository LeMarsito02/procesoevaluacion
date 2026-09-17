"""Pruebas de procesos, asignaciones, revisiones y aislamiento (app y RLS)."""
from __future__ import annotations

from unittest import mock

from django.core import mail
from django.db import ProgrammingError, transaction

from cuentas.aislamiento import NINGUNA, SISTEMA, fijar_entidad
from cuentas.models import Rol, TipoArea, Usuario
from cuentas.tests import CLAVE, BaseCuentas, Cliente, crear_entidad
from evaluaciones.models import EstadoEvaluacion, Evaluacion, Proceso
from motor.esquemas.proceso import ResultadoRequisito

DOCUMENTO_BASE = {
    "codigo_proceso": "ICCU-CM-037-2026",
    "fecha_cierre": "2026-08-20",
    "objeto_general": "Mantenimiento de vías",
    "lotes": [{"numero": "LOTE 1", "objeto": "Vías", "plazo_meses": 4, "valor_presupuesto": 1000000, "lugar_ejecucion": None}],
    "lote_mayor_valor": "LOTE 1",
    "presupuesto_total": 1000000,
    "garantia_seriedad": {
        "vigencia_meses": 3,
        "porcentaje": 0.1,
        "base_calculo": "lote_mayor_valor",
        "lote_base": "LOTE 1",
        "valor_base": 1000000,
        "valor_asegurado": 100000,
        "fecha_cierre": "2026-08-20",
        "fecha_vencimiento": "2026-11-20",
    },
    "advertencias": [],
}

PROPONENTES = [
    {"numero_orden": 1, "hoja": "P-01", "nombre_proponente": "Consorcio Uno", "nombre_archivo": "P1 Consorcio Uno.zip", "drive_file_id": "a1"},
    {"numero_orden": 2, "hoja": "P-02", "nombre_proponente": "Vías SAS", "nombre_archivo": "P2 Vías SAS.zip", "drive_file_id": "a2"},
]


def resultados_falsos(proponente, proceso):
    """Motor simulado: el requisito 2 queda por revisar, el resto cumple."""
    return [
        ResultadoRequisito(
            hoja=proponente.hoja,
            numero_orden=proponente.numero_orden,
            nombre_proponente=proponente.nombre_proponente,
            requisito=n,
            cumple=n != 2,
            motivo="No se encontró el COPNIA" if n == 2 else None,
        )
        for n in (1, 2, 13)
    ]


async def motor_falso(proponente, proceso):
    return resultados_falsos(proponente, proceso)


class BaseEvaluaciones(BaseCuentas):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.consulta = Usuario.objects.create_user("control@iccu.gov.co", CLAVE, nombre_completo="Control Interno", entidad=cls.iccu, rol=Rol.CONSULTA)
        cls.abogado2 = Usuario.objects.create_user("abogado2@iccu.gov.co", CLAVE, nombre_completo="Abogado Dos", entidad=cls.iccu, rol=Rol.EVALUADOR)
        cls.abogado2.areas.set(cls.iccu.areas.filter(tipo=TipoArea.JURIDICA))
        cls.eval_otra = Usuario.objects.create_user("abogado@otra.gov.co", CLAVE, nombre_completo="Abogado Otra", entidad=cls.otra, rol=Rol.EVALUADOR)
        cls.eval_otra.areas.set(cls.otra.areas.filter(tipo=TipoArea.JURIDICA))

    def crear(self, email="jefe@iccu.gov.co", codigo="ICCU-CM-037-2026"):
        c = Cliente()
        c.entrar(email)
        doc = {**DOCUMENTO_BASE, "codigo_proceso": codigo}
        r = c.post("/api/evaluaciones/procesos", {"documento_base": doc, "carpeta_drive": "x", "proponentes": PROPONENTES})
        self.assertEqual(r.status_code, 201, r.content)
        return c, r.json()[0]

    def evaluar_todo(self, c, evaluacion_id):
        detalle = c.get(f"/api/evaluaciones/{evaluacion_id}").json()
        with mock.patch("api.evaluaciones.evaluar_todos_en_proceso", motor_falso):
            for p in detalle["proponentes"]:
                r = c.post(f"/api/evaluaciones/{evaluacion_id}/proponentes/{p['id']}/evaluar")
                self.assertEqual(r.status_code, 200, r.content)
        return detalle


class CrearYAsignarTests(BaseEvaluaciones):
    def test_jefe_crea_sin_asignar_y_asigna(self):
        jefe, ev = self.crear()
        self.assertEqual(ev["estado"], EstadoEvaluacion.SIN_ASIGNAR)
        self.assertEqual(ev["avance"]["proponentes"], 2)
        with self.captureOnCommitCallbacks(execute=True):
            r = jefe.post(f"/api/evaluaciones/{ev['id']}/asignar", {"responsable_id": str(self.evaluador.id)})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["estado"], EstadoEvaluacion.ASIGNADA)
        self.assertEqual(mail.outbox[-1].to, ["abogado@iccu.gov.co"])
        # Aparece en "mis evaluaciones" del abogado y no en la del otro abogado.
        a1 = Cliente()
        a1.entrar("abogado@iccu.gov.co")
        self.assertEqual([e["id"] for e in a1.get("/api/evaluaciones/mias").json()], [ev["id"]])
        a2 = Cliente()
        a2.entrar("abogado2@iccu.gov.co")
        self.assertEqual(a2.get("/api/evaluaciones/mias").json(), [])

    def test_evaluador_que_crea_queda_responsable(self):
        _, ev = self.crear("abogado@iccu.gov.co")
        self.assertEqual(ev["estado"], EstadoEvaluacion.ASIGNADA)
        self.assertEqual(ev["responsable"]["email"], "abogado@iccu.gov.co")

    def test_no_asigna_a_otra_area_ni_otra_entidad(self):
        jefe, ev = self.crear()
        self.assertEqual(jefe.post(f"/api/evaluaciones/{ev['id']}/asignar", {"responsable_id": str(self.tecnico.id)}).status_code, 400)
        self.assertEqual(jefe.post(f"/api/evaluaciones/{ev['id']}/asignar", {"responsable_id": str(self.eval_otra.id)}).status_code, 400)
        self.assertEqual(jefe.post(f"/api/evaluaciones/{ev['id']}/asignar", {"responsable_id": str(self.consulta.id)}).status_code, 400)

    def test_evaluador_y_consulta_no_asignan(self):
        _, ev = self.crear()
        for email in ("abogado@iccu.gov.co", "control@iccu.gov.co"):
            c = Cliente()
            c.entrar(email)
            r = c.post(f"/api/evaluaciones/{ev['id']}/asignar", {"responsable_id": str(self.evaluador.id)})
            self.assertEqual(r.status_code, 403, email)

    def test_consulta_no_crea_procesos(self):
        c = Cliente()
        c.entrar("control@iccu.gov.co")
        r = c.post("/api/evaluaciones/procesos", {"documento_base": DOCUMENTO_BASE, "proponentes": PROPONENTES})
        self.assertEqual(r.status_code, 403)

    def test_codigo_repetido_en_la_misma_entidad(self):
        self.crear()
        c = Cliente()
        c.entrar("jefe@iccu.gov.co")
        r = c.post("/api/evaluaciones/procesos", {"documento_base": DOCUMENTO_BASE, "proponentes": PROPONENTES})
        self.assertEqual(r.status_code, 409)

    def test_mismo_codigo_en_otra_entidad_si_se_permite(self):
        self.crear()
        self.crear("abogado@otra.gov.co")

    def test_solo_juridica_disponible(self):
        c = Cliente()
        c.entrar("jefe@iccu.gov.co")
        r = c.post("/api/evaluaciones/procesos", {"documento_base": DOCUMENTO_BASE, "proponentes": PROPONENTES, "tipos": ["tecnica"]})
        self.assertEqual(r.status_code, 400)


class TrabajoTests(BaseEvaluaciones):
    def setUp(self):
        self.jefe, self.ev = self.crear()
        self.jefe.post(f"/api/evaluaciones/{self.ev['id']}/asignar", {"responsable_id": str(self.evaluador.id)})
        self.abogado = Cliente()
        self.abogado.entrar("abogado@iccu.gov.co")

    def test_flujo_completo(self):
        eid = self.ev["id"]
        detalle = self.evaluar_todo(self.abogado, eid)
        resumen = self.abogado.get(f"/api/evaluaciones/{eid}").json()["evaluacion"]
        self.assertEqual(resumen["estado"], EstadoEvaluacion.EN_REVISION)
        # Requisito 2 por revisar en ambos; el 13 (RUT) no cuenta; ninguno con error.
        self.assertEqual(resumen["avance"]["pendientes"], 2)
        self.assertEqual(resumen["avance"]["con_error"], 0)

        # Con pendientes no se aprueba.
        self.assertEqual(self.jefe.post(f"/api/evaluaciones/{eid}/aprobar").status_code, 409)

        for p in detalle["proponentes"]:
            r = self.abogado.http.put(
                f"/api/evaluaciones/{eid}/revisiones",
                {"proponente_id": p["id"], "requisito": 2, "cumple": p["hoja"] == "P-01", "nota": "Revisado en físico"},
                content_type="application/json",
                headers={"X-CSRFToken": self.abogado.csrf},
            )
            self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.abogado.get(f"/api/evaluaciones/{eid}").json()["evaluacion"]["avance"]["pendientes"], 0)

        # El evaluador no aprueba; el jefe sí.
        self.assertEqual(self.abogado.post(f"/api/evaluaciones/{eid}/aprobar").status_code, 403)
        self.assertEqual(self.jefe.post(f"/api/evaluaciones/{eid}/aprobar").json()["estado"], EstadoEvaluacion.APROBADA)

        # Aprobada: no se modifica hasta reabrir.
        r = self.abogado.http.put(
            f"/api/evaluaciones/{eid}/revisiones",
            {"proponente_id": detalle["proponentes"][0]["id"], "requisito": 2, "cumple": False},
            content_type="application/json",
            headers={"X-CSRFToken": self.abogado.csrf},
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.jefe.post(f"/api/evaluaciones/{eid}/reabrir").json()["estado"], EstadoEvaluacion.EN_REVISION)

        # Informe con las decisiones aplicadas.
        r = self.abogado.get(f"/api/evaluaciones/{eid}/informe")
        self.assertEqual(r.status_code, 200)
        self.assertIn("BORRADOR", r["Content-Disposition"])
        self.assertTrue(r.content.startswith(b"PK"))

    def test_otro_evaluador_y_consulta_no_trabajan(self):
        eid = self.ev["id"]
        prop = self.abogado.get(f"/api/evaluaciones/{eid}").json()["proponentes"][0]["id"]
        for email in ("abogado2@iccu.gov.co", "control@iccu.gov.co"):
            c = Cliente()
            c.entrar(email)
            # Pueden consultar…
            self.assertEqual(c.get(f"/api/evaluaciones/{eid}").status_code, 200)
            # …pero no evaluar.
            with mock.patch("api.evaluaciones.evaluar_todos_en_proceso", motor_falso):
                self.assertEqual(c.post(f"/api/evaluaciones/{eid}/proponentes/{prop}/evaluar").status_code, 403, email)

    def test_proponente_de_otro_proceso_rechazado(self):
        _, otro = self.crear(codigo="OTRO-001")
        prop_otro = self.jefe.get(f"/api/evaluaciones/{otro['id']}").json()["proponentes"][0]["id"]
        with mock.patch("api.evaluaciones.evaluar_todos_en_proceso", motor_falso):
            r = self.abogado.post(f"/api/evaluaciones/{self.ev['id']}/proponentes/{prop_otro}/evaluar")
        self.assertEqual(r.status_code, 404)

    def test_endpoints_de_medicion_cerrados_fuera_de_debug(self):
        r = self.abogado.post("/api/procesos/evaluar-todos/proponente", {"documento_base": DOCUMENTO_BASE, "proponente": PROPONENTES[0]})
        self.assertEqual(r.status_code, 404)


class AislamientoEvaluacionesTests(BaseEvaluaciones):
    def test_otra_entidad_no_ve_ni_modifica(self):
        jefe, ev = self.crear()
        eid = ev["id"]
        prop = jefe.get(f"/api/evaluaciones/{eid}").json()["proponentes"][0]["id"]
        c = Cliente()
        c.entrar("admin@otra.gov.co")
        self.assertEqual(c.get("/api/evaluaciones/procesos").json(), [])
        self.assertEqual(c.get("/api/evaluaciones/mias").json(), [])
        self.assertEqual(c.get(f"/api/evaluaciones/{eid}").status_code, 404)
        self.assertEqual(c.get(f"/api/evaluaciones/{eid}/informe").status_code, 404)
        self.assertEqual(c.get(f"/api/evaluaciones/{eid}/proponentes/{prop}/documento?archivo=x.pdf").status_code, 404)
        self.assertEqual(c.post(f"/api/evaluaciones/{eid}/asignar", {"responsable_id": None}).status_code, 404)
        self.assertEqual(c.post(f"/api/evaluaciones/{eid}/aprobar").status_code, 404)

    def test_rls_filtra_aunque_la_consulta_no_filtre(self):
        self.crear()
        self.crear("abogado@otra.gov.co", codigo="OTRA-001")
        try:
            fijar_entidad(str(self.otra.id))
            self.assertEqual(list(Proceso.objects.values_list("codigo", flat=True)), ["OTRA-001"])
            self.assertEqual(Evaluacion.objects.count(), 1)
            fijar_entidad(NINGUNA)
            self.assertEqual(Proceso.objects.count(), 0)
            # Tampoco se puede escribir una fila de otra entidad.
            fijar_entidad(str(self.otra.id))
            with self.assertRaises(ProgrammingError), transaction.atomic():
                Proceso.objects.create(
                    entidad=self.iccu, codigo="X", fecha_cierre="2026-01-01", documento_base={}, creado_por=self.admin_otra
                )
        finally:
            fijar_entidad(SISTEMA)
        self.assertEqual(Proceso.objects.count(), 2)

    def test_superadmin_ve_todas(self):
        import pyotp

        self.crear()
        self.crear("abogado@otra.gov.co", codigo="OTRA-001")
        c = Cliente()
        c.entrar("santiagopebe01@lemartek.com")
        secreto = c.post("/api/auth/2fa/configurar").json()["secreto"]
        c.post("/api/auth/2fa/verificar", {"codigo": pyotp.TOTP(secreto).now()})
        self.assertEqual(len(c.get("/api/evaluaciones/procesos").json()), 2)


class EntidadNueva(BaseEvaluaciones):
    def test_entidad_sin_procesos(self):
        crear_entidad("Vacía", "123")
        c = Cliente()
        c.entrar("admin@iccu.gov.co")
        self.assertEqual(c.get("/api/evaluaciones/procesos").json(), [])
