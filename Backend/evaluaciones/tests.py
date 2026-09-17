"""Pruebas de procesos, asignaciones, revisiones y aislamiento (app y RLS)."""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

from asgiref.sync import async_to_sync

from django.core import mail
from django.db import ProgrammingError, transaction
from django.utils import timezone

from cuentas.aislamiento import NINGUNA, SISTEMA, fijar_entidad
from cuentas.models import Rol, TipoArea, Usuario
from cuentas.tests import CLAVE, BaseCuentas, Cliente, crear_entidad
from evaluaciones import servicios
from evaluaciones.models import EstadoEvaluacion, EstadoTrabajo, Evaluacion, Proceso, Trabajador, Trabajo
from evaluaciones.trabajador import trabajar
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
        """Encola todo y deja que el trabajador real atienda la fila con el motor simulado."""
        detalle = c.get(f"/api/evaluaciones/{evaluacion_id}").json()
        r = c.post(f"/api/evaluaciones/{evaluacion_id}/evaluar", {})
        self.assertEqual(r.status_code, 200, r.content)
        correr_fila()
        return detalle


def correr_fila(motor=motor_falso):
    with mock.patch("evaluaciones.trabajador.evaluar_todos_en_proceso", motor):
        async_to_sync(trabajar)(2, una_vez=True)


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

    def test_abogado_crea_su_propio_proceso_aunque_no_tenga_el_area(self):
        _, ev = self.crear("tecnico@iccu.gov.co")
        self.assertEqual(ev["estado"], EstadoEvaluacion.ASIGNADA)
        self.assertEqual(ev["responsable"]["email"], "tecnico@iccu.gov.co")
        c = Cliente()
        c.entrar("tecnico@iccu.gov.co")
        self.assertTrue(c.get(f"/api/evaluaciones/{ev['id']}").json()["evaluacion"]["puede_trabajar"])

    def test_abogado_no_asigna_a_otro_al_crear(self):
        c = Cliente()
        c.entrar("abogado@iccu.gov.co")
        r = c.post(
            "/api/evaluaciones/procesos",
            {"documento_base": DOCUMENTO_BASE, "proponentes": PROPONENTES, "responsable_id": str(self.abogado2.id)},
        )
        self.assertEqual(r.status_code, 403)

    def test_jefe_asigna_al_crear(self):
        c = Cliente()
        c.entrar("jefe@iccu.gov.co")
        with self.captureOnCommitCallbacks(execute=True):
            r = c.post(
                "/api/evaluaciones/procesos",
                {"documento_base": DOCUMENTO_BASE, "proponentes": PROPONENTES, "responsable_id": str(self.abogado2.id)},
            )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()[0]["responsable"]["email"], "abogado2@iccu.gov.co")
        self.assertEqual(mail.outbox[-1].to, ["abogado2@iccu.gov.co"])

    def test_superadmin_crea_asigna_y_ve_equipo_de_cualquier_entidad(self):
        import pyotp

        c = Cliente()
        c.entrar("santiagopebe01@lemartek.com")
        secreto = c.post("/api/auth/2fa/configurar").json()["secreto"]
        c.post("/api/auth/2fa/verificar", {"codigo": pyotp.TOTP(secreto).now()})
        # Debe elegir la entidad.
        r = c.post("/api/evaluaciones/procesos", {"documento_base": DOCUMENTO_BASE, "proponentes": PROPONENTES})
        self.assertEqual(r.status_code, 400)
        r = c.post(
            "/api/evaluaciones/procesos",
            {"documento_base": DOCUMENTO_BASE, "proponentes": PROPONENTES, "entidad_id": str(self.otra.id), "responsable_id": str(self.eval_otra.id)},
        )
        self.assertEqual(r.status_code, 201, r.content)
        ev = r.json()[0]
        self.assertEqual(ev["entidad_nombre"], "Gobernación de Prueba")
        self.assertEqual(ev["estado"], EstadoEvaluacion.ASIGNADA)
        # No puede asignar a alguien de otra entidad.
        self.assertEqual(c.post(f"/api/evaluaciones/{ev['id']}/asignar", {"responsable_id": str(self.evaluador.id)}).status_code, 400)
        # Reasigna, ve el equipo de esa entidad, evalúa y aprueba.
        self.assertEqual(c.post(f"/api/evaluaciones/{ev['id']}/asignar", {"responsable_id": None}).status_code, 200)
        equipo = {m["email"] for m in c.get(f"/api/evaluaciones/equipo?entidad_id={self.otra.id}").json()}
        self.assertIn("abogado@otra.gov.co", equipo)
        self.assertNotIn("abogado@iccu.gov.co", equipo)
        detalle = self.evaluar_todo(c, ev["id"])
        for p in detalle["proponentes"]:
            c.http.put(
                f"/api/evaluaciones/{ev['id']}/revisiones",
                {"proponente_id": p["id"], "requisito": 2, "cumple": True},
                content_type="application/json",
                headers={"X-CSRFToken": c.csrf},
            )
        self.assertEqual(c.post(f"/api/evaluaciones/{ev['id']}/aprobar").json()["estado"], EstadoEvaluacion.APROBADA)

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

    def test_tecnica_y_financiera_se_crean_y_asignan_pero_no_evaluan(self):
        c = Cliente()
        c.entrar("admin@iccu.gov.co")
        with self.captureOnCommitCallbacks(execute=True):
            r = c.post(
                "/api/evaluaciones/procesos",
                {
                    "documento_base": DOCUMENTO_BASE,
                    "proponentes": PROPONENTES,
                    "tipos": ["juridica", "tecnica", "financiera"],
                    "responsables": {"juridica": str(self.evaluador.id), "tecnica": str(self.tecnico.id), "financiera": None},
                },
            )
        self.assertEqual(r.status_code, 201, r.content)
        por_tipo = {e["tipo"]: e for e in r.json()}
        self.assertEqual(por_tipo["juridica"]["responsable"]["email"], "abogado@iccu.gov.co")
        self.assertEqual(por_tipo["tecnica"]["responsable"]["email"], "tecnico@iccu.gov.co")
        self.assertIsNone(por_tipo["financiera"]["responsable"])
        self.assertTrue(por_tipo["juridica"]["tipo_disponible"])
        self.assertFalse(por_tipo["tecnica"]["tipo_disponible"])
        self.assertEqual({m.to[0] for m in mail.outbox}, {"abogado@iccu.gov.co", "tecnico@iccu.gov.co"})
        # El técnico no puede ser responsable jurídico (no tiene el área), y la técnica aún no evalúa.
        r = c.post(f"/api/evaluaciones/{por_tipo['tecnica']['id']}/evaluar", {})
        self.assertEqual(r.status_code, 409)
        self.assertIn("en preparación", r.json()["detail"])
        self.assertEqual(c.get(f"/api/evaluaciones/{por_tipo['tecnica']['id']}/informe").status_code, 400)
        tipos = {t["clave"]: t["disponible"] for t in c.get("/api/evaluaciones/tipos").json()}
        self.assertEqual(tipos, {"juridica": True, "tecnica": False, "financiera": False})

    def test_tipo_invalido(self):
        c = Cliente()
        c.entrar("jefe@iccu.gov.co")
        r = c.post("/api/evaluaciones/procesos", {"documento_base": DOCUMENTO_BASE, "proponentes": PROPONENTES, "tipos": ["ambiental"]})
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
            self.assertEqual(c.post(f"/api/evaluaciones/{eid}/evaluar", {"proponente_ids": [prop]}).status_code, 403, email)

    def test_proponente_de_otro_proceso_rechazado(self):
        _, otro = self.crear(codigo="OTRO-001")
        prop_otro = self.jefe.get(f"/api/evaluaciones/{otro['id']}").json()["proponentes"][0]["id"]
        r = self.abogado.post(f"/api/evaluaciones/{self.ev['id']}/evaluar", {"proponente_ids": [prop_otro]})
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


class FilaTests(BaseEvaluaciones):
    def setUp(self):
        self.jefe, self.ev = self.crear()
        _, self.ev2 = self.crear(codigo="SEGUNDO-001")
        self.eid, self.eid2 = self.ev["id"], self.ev2["id"]

    def test_encolar_no_duplica_y_muestra_fila(self):
        r = self.jefe.post(f"/api/evaluaciones/{self.eid}/evaluar", {})
        self.assertEqual(r.json()["estado"], EstadoEvaluacion.EVALUANDO)
        self.assertEqual(r.json()["fila"]["en_fila"], 2)
        # Sin trabajadores activos no hay tiempo estimado.
        self.assertIsNone(r.json()["fila"]["eta_segundos"])
        self.jefe.post(f"/api/evaluaciones/{self.eid}/evaluar", {})
        self.assertEqual(Trabajo.objects.filter(evaluacion_id=self.eid).count(), 2)
        # Con un trabajador latiendo sí hay estimación.
        Trabajador.objects.create(id="prueba", capacidad=2, latido=timezone.now())
        fila = self.jefe.get(f"/api/evaluaciones/{self.eid}/novedades").json()["evaluacion"]["fila"]
        self.assertEqual(fila["capacidad"], 2)
        self.assertGreater(fila["eta_segundos"], 0)

    def test_reparto_por_turnos_entre_evaluaciones(self):
        self.jefe.post(f"/api/evaluaciones/{self.eid}/evaluar", {})
        self.jefe.post(f"/api/evaluaciones/{self.eid2}/evaluar", {})
        orden = []
        while (t := servicios.reclamar("prueba")) is not None:
            orden.append(str(t.evaluacion_id))
        # Primero un proponente de cada evaluación, luego el segundo de cada una.
        self.assertEqual(orden[0], self.eid)
        self.assertEqual(orden[1], self.eid2)
        self.assertEqual(sorted(orden[:2]), sorted(orden[2:]))

    def test_trabajador_evalua_guarda_y_avisa(self):
        self.jefe.post(f"/api/evaluaciones/{self.eid}/asignar", {"responsable_id": str(self.evaluador.id)})
        self.jefe.post(f"/api/evaluaciones/{self.eid}/evaluar", {})
        with self.captureOnCommitCallbacks(execute=True):
            correr_fila()
        resumen = self.jefe.get(f"/api/evaluaciones/{self.eid}").json()["evaluacion"]
        self.assertEqual(resumen["estado"], EstadoEvaluacion.EN_REVISION)
        self.assertEqual(resumen["avance"]["evaluados"], 2)
        self.assertIsNone(resumen["fila"])
        self.assertEqual(mail.outbox[-1].to, ["abogado@iccu.gov.co"])
        self.assertIn("Evaluación terminada", mail.outbox[-1].subject)
        self.assertFalse(Trabajador.objects.exists())
        # Novedades desde antes de evaluar trae los resultados guardados.
        r = self.jefe.get(f"/api/evaluaciones/{self.eid}/novedades?desde=2000-01-01T00:00:00Z").json()
        self.assertEqual(len(r["resultados"]), 6)

    def test_error_del_motor_no_detiene_la_fila(self):
        async def motor_roto(proponente, proceso):
            if proponente.hoja == "P-01":
                raise RuntimeError("zip dañado")
            return resultados_falsos(proponente, proceso)

        self.jefe.post(f"/api/evaluaciones/{self.eid}/evaluar", {})
        correr_fila(motor_roto)
        estados = dict(Trabajo.objects.filter(evaluacion_id=self.eid).values_list("proponente__hoja", "estado"))
        self.assertEqual(estados, {"P-01": EstadoTrabajo.ERROR, "P-02": EstadoTrabajo.TERMINADO})

    def test_pausar_saca_lo_que_no_empezo(self):
        self.jefe.post(f"/api/evaluaciones/{self.eid}/evaluar", {})
        servicios.reclamar("prueba")  # uno queda procesando
        r = self.jefe.post(f"/api/evaluaciones/{self.eid}/pausar").json()
        self.assertEqual(r["fila"]["en_fila"], 0)
        self.assertEqual(r["fila"]["procesando"], 1)

    def test_huerfanos_vuelven_a_la_fila_y_luego_fallan(self):
        self.jefe.post(f"/api/evaluaciones/{self.eid}/evaluar", {})
        viejo = timezone.now() - timedelta(minutes=10)
        for intento in range(3):
            t = servicios.reclamar("caido")
            Trabajo.objects.filter(pk=t.pk).update(latido=viejo)
            servicios.recuperar_huerfanos()
        t.refresh_from_db()
        self.assertEqual(t.estado, EstadoTrabajo.ERROR)

    def test_consulta_no_encola_ni_pausa(self):
        c = Cliente()
        c.entrar("control@iccu.gov.co")
        self.assertEqual(c.post(f"/api/evaluaciones/{self.eid}/evaluar", {}).status_code, 403)
        self.assertEqual(c.post(f"/api/evaluaciones/{self.eid}/pausar").status_code, 403)

    def test_otra_entidad_no_ve_novedades(self):
        c = Cliente()
        c.entrar("admin@otra.gov.co")
        self.assertEqual(c.get(f"/api/evaluaciones/{self.eid}/novedades").status_code, 404)

    def test_estado_de_la_fila_por_rol(self):
        self.jefe.post(f"/api/evaluaciones/{self.eid}/evaluar", {})
        c = Cliente()
        c.entrar("admin@iccu.gov.co")
        r = c.get("/api/evaluaciones/fila/estado").json()
        self.assertEqual(r["total_en_fila"], 2)
        self.assertEqual([e["id"] for e in r["evaluaciones"]], [self.eid])
        self.assertEqual(r["trabajadores"], [])
        otra = Cliente()
        otra.entrar("admin@otra.gov.co")
        self.assertEqual(otra.get("/api/evaluaciones/fila/estado").json()["evaluaciones"], [])
        self.assertEqual(self.jefe.get("/api/evaluaciones/fila/estado").status_code, 403)
