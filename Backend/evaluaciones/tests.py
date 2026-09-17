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
                {"proponente_id": p["id"], "requisito": 2, "cumple": True, "nota": "Revisado por superadmin"},
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


PLANTILLA_ICCU = "motor/plantillas/plantilla_evaluacion_juridica.xlsx"


def subir(c: "Cliente", tipo="juridica", ruta=PLANTILLA_ICCU, nombre="plantilla.xlsx", entidad_id=None):
    from django.core.files.uploadedfile import SimpleUploadedFile

    with open(ruta, "rb") as f:
        archivo = SimpleUploadedFile(nombre, f.read())
    url = "/api/configuracion/plantillas" + (f"?entidad_id={entidad_id}" if entidad_id else "")
    return c.http.post(url, {"tipo": tipo, "archivo": archivo}, headers={"X-CSRFToken": c.csrf})


class PlantillasTests(BaseEvaluaciones):
    def setUp(self):
        import tempfile

        from django.test import override_settings

        self._tmp = tempfile.TemporaryDirectory()
        self._override = override_settings(MEDIA_ROOT=self._tmp.name)
        self._override.enable()
        self.admin = Cliente()
        self.admin.entrar("admin@iccu.gov.co")

    def tearDown(self):
        self._override.disable()
        self._tmp.cleanup()

    def test_subir_ajustar_mapeo_y_usar_en_el_informe(self):
        r = subir(self.admin, nombre="Plantilla ICCU 2026.xlsx")
        self.assertEqual(r.status_code, 201, r.content)
        plantilla = r.json()
        self.assertTrue(plantilla["inspeccion"]["valida"])
        self.assertGreater(plantilla["inspeccion"]["hojas_proponente"], 0)
        self.assertIn("1", plantilla["inspeccion"]["filas"])

        mapeo = {**plantilla["mapeo"], "prefijo_codigo": "IDU"}
        r = self.admin.http.put(
            f"/api/configuracion/plantillas/{plantilla['id']}/mapeo",
            {"mapeo": mapeo},
            content_type="application/json",
            headers={"X-CSRFToken": self.admin.csrf},
        )
        self.assertEqual(r.status_code, 200, r.content)

        listado = {t["tipo"]: t for t in self.admin.get("/api/configuracion/plantillas").json()}
        self.assertEqual(listado["juridica"]["activa"]["id"], plantilla["id"])
        self.assertFalse(listado["juridica"]["usa_plantilla_del_sistema"])
        self.assertTrue(listado["tecnica"]["activa"] is None and not listado["tecnica"]["motor_disponible"])

        # El informe usa la plantilla y el mapeo de la entidad.
        import io

        import openpyxl

        jefe, ev = self.crear()
        self.evaluar_todo(jefe, ev["id"])
        r = jefe.get(f"/api/evaluaciones/{ev['id']}/informe")
        self.assertEqual(r.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        self.assertIn("IDU-ICCU-CM-037", wb["P-01"]["F3"].value)

    def test_nueva_plantilla_reemplaza_la_activa_y_se_puede_volver(self):
        primera = subir(self.admin).json()
        segunda = subir(self.admin).json()
        self.assertEqual(len(self.admin.get("/api/configuracion/plantillas").json()[0]["historial"]), 2)
        r = self.admin.post(f"/api/configuracion/plantillas/{primera['id']}/activar")
        self.assertTrue(r.json()["activa"])
        activas = [p for p in self.admin.get("/api/configuracion/plantillas").json()[0]["historial"] if p["activa"]]
        self.assertEqual([p["id"] for p in activas], [primera["id"]])
        self.assertNotEqual(primera["id"], segunda["id"])

    def test_tecnica_y_financiera_aceptan_plantilla(self):
        self.assertEqual(subir(self.admin, tipo="tecnica").status_code, 201)
        self.assertEqual(subir(self.admin, tipo="financiera").status_code, 201)

    def test_rechaza_lo_que_no_es_xlsx(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".xlsx") as f:
            f.write(b"esto no es un excel")
            f.flush()
            self.assertEqual(subir(self.admin, ruta=f.name).status_code, 400)
        self.assertEqual(subir(self.admin, nombre="macros.xlsm").status_code, 400)

    def test_permisos_y_aislamiento(self):
        plantilla = subir(self.admin).json()
        otra = Cliente()
        otra.entrar("admin@otra.gov.co")
        self.assertEqual(otra.get(f"/api/configuracion/plantillas/{plantilla['id']}/archivo").status_code, 404)
        self.assertEqual(otra.delete(f"/api/configuracion/plantillas/{plantilla['id']}").status_code, 404)
        self.assertEqual(otra.get("/api/configuracion/plantillas").json()[0]["activa"], None)
        jefe = Cliente()
        jefe.entrar("jefe@iccu.gov.co")
        self.assertEqual(jefe.get("/api/configuracion/plantillas").status_code, 403)
        self.assertEqual(subir(jefe).status_code, 403)
        self.assertEqual(self.admin.get(f"/api/configuracion/plantillas/{plantilla['id']}/archivo").status_code, 200)

    def test_superadmin_sube_para_una_entidad(self):
        import pyotp

        c = Cliente()
        c.entrar("santiagopebe01@lemartek.com")
        secreto = c.post("/api/auth/2fa/configurar").json()["secreto"]
        c.post("/api/auth/2fa/verificar", {"codigo": pyotp.TOTP(secreto).now()})
        self.assertEqual(subir(c).status_code, 400)  # debe indicar la entidad
        self.assertEqual(subir(c, entidad_id=self.otra.id).status_code, 201)
        otra = Cliente()
        otra.entrar("admin@otra.gov.co")
        self.assertIsNotNone(otra.get("/api/configuracion/plantillas").json()[0]["activa"])


def definicion_propia():
    """ICCU sin sanciones del RUP, con numeración propia y un requisito nuevo por bloques."""
    from motor.criterios import definicion_sistema

    base = definicion_sistema("juridica").model_dump(mode="json")
    requisitos = [r for r in base["requisitos"] if r["verificacion"] != "juridica.sanciones_rup"]
    for i, r in enumerate(requisitos, start=1):
        r["numero"] = i
    requisitos.append(
        {
            "numero": 30,
            "titulo": "Certificado de la Junta Central de Contadores",
            "corto": "JCC",
            "grupo": "antecedentes",
            "verificacion": "personalizado",
            "config": {"frases_documento": ["JUNTA CENTRAL DE CONTADORES"], "bloques": [{"tipo": "vigencia_maxima", "meses": 3}]},
        }
    )
    return {"parametros": {"copnia_meses": 6}, "requisitos": requisitos}


class PlantillaEvaluacionTests(BaseEvaluaciones):
    def setUp(self):
        self.admin = Cliente()
        self.admin.entrar("admin@iccu.gov.co")

    def publicar(self, c=None, definicion=None, nombre="Jurídica ICCU 2026", entidad_id=None):
        c = c or self.admin
        url = "/api/configuracion/evaluaciones" + (f"?entidad_id={entidad_id}" if entidad_id else "")
        return c.post(url, {"tipo": "juridica", "nombre": nombre, "definicion": definicion or definicion_propia()})

    def test_catalogo_del_motor(self):
        cat = self.admin.get("/api/configuracion/catalogo?tipo=juridica").json()
        self.assertEqual(len(cat["verificaciones"]), 17)
        self.assertIn("copnia_meses", {p["clave"] for p in cat["parametros"]})

    def test_sin_version_propia_usa_la_base_del_sistema(self):
        juridica = self.admin.get("/api/configuracion/evaluaciones").json()[0]
        self.assertIsNone(juridica["activa"])
        self.assertEqual(len(juridica["definicion"]["requisitos"]), 17)

    def test_publicar_y_evaluar_con_la_definicion_de_la_entidad(self):
        r = self.publicar()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["version"], 1)

        jefe, ev = self.crear()
        self.assertEqual(ev["plantilla_version"], 1)
        detalle = jefe.get(f"/api/evaluaciones/{ev['id']}").json()
        self.assertEqual(len(detalle["catalogo"]), 17)
        self.assertEqual(detalle["catalogo"][-1]["titulo"], "Certificado de la Junta Central de Contadores")
        self.assertTrue(detalle["catalogo"][-1]["personalizado"])

        recibido = {}

        async def motor_que_mira(proponente, proceso):
            recibido["criterios"] = proceso.criterios
            return resultados_falsos(proponente, proceso)

        jefe.post(f"/api/evaluaciones/{ev['id']}/evaluar", {})
        correr_fila(motor_que_mira)
        self.assertEqual(recibido["criterios"]["parametros"], {"copnia_meses": 6})
        self.assertEqual(len(recibido["criterios"]["requisitos"]), 17)

    def test_nueva_version_y_actualizar_evaluacion(self):
        self.publicar()
        jefe, ev = self.crear()
        self.evaluar_todo(jefe, ev["id"])
        from motor.criterios import definicion_sistema

        v2 = definicion_sistema("juridica").model_dump(mode="json")
        v2["requisitos"] = [r for r in v2["requisitos"] if r["numero"] in (1, 2)]
        self.assertEqual(self.publicar(definicion=v2, nombre="Solo carta y aval").json()["version"], 2)

        resumen = jefe.get(f"/api/evaluaciones/{ev['id']}").json()["evaluacion"]
        self.assertTrue(resumen["plantilla_desactualizada"])
        r = jefe.post(f"/api/evaluaciones/{ev['id']}/actualizar-plantilla")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["plantilla_version"], 2)
        self.assertFalse(r.json()["plantilla_desactualizada"])
        # Se descartan resultados de requisitos que ya no existen (13) y se vuelve a evaluar a todos.
        self.assertEqual(Trabajo.objects.filter(evaluacion_id=ev["id"], estado=EstadoTrabajo.EN_FILA).count(), 2)
        self.assertEqual(jefe.post(f"/api/evaluaciones/{ev['id']}/actualizar-plantilla").status_code, 409)
        versiones = self.admin.get("/api/configuracion/evaluaciones").json()[0]["versiones"]
        self.assertEqual([(v["version"], v["activa"], v["evaluaciones"]) for v in versiones], [(2, True, 1), (1, False, 0)])

    def test_validacion_de_la_definicion(self):
        d = definicion_propia()
        d["requisitos"][1]["numero"] = d["requisitos"][0]["numero"]
        r = self.publicar(definicion=d)
        self.assertEqual(r.status_code, 400)
        self.assertIn("repetidos", r.json()["detail"])
        d = definicion_propia()
        d["parametros"]["copnia_meses"] = 100
        self.assertEqual(self.publicar(definicion=d).status_code, 400)
        d = definicion_propia()
        d["requisitos"][0]["verificacion"] = "juridica.inventada"
        self.assertEqual(self.publicar(definicion=d).status_code, 400)
        self.assertEqual(self.publicar(definicion={"requisitos": []}).status_code, 400)

    def test_permisos_y_aislamiento(self):
        v = self.publicar().json()
        otra = Cliente()
        otra.entrar("admin@otra.gov.co")
        self.assertIsNone(otra.get("/api/configuracion/evaluaciones").json()[0]["activa"])
        self.assertEqual(otra.post(f"/api/configuracion/evaluaciones/{v['id']}/activar").status_code, 404)
        jefe = Cliente()
        jefe.entrar("jefe@iccu.gov.co")
        self.assertEqual(self.publicar(c=jefe).status_code, 403)

    def test_superadmin_crea_entidad_con_base_o_copia(self):
        import pyotp

        self.publicar()
        c = Cliente()
        c.entrar("santiagopebe01@lemartek.com")
        secreto = c.post("/api/auth/2fa/configurar").json()["secreto"]
        c.post("/api/auth/2fa/verificar", {"codigo": pyotp.TOTP(secreto).now()})
        r = c.post("/api/plataforma/entidades", {"nombre": "Instituto de Desarrollo Urbano", "nit": "899999081", "email_admin": "a@idu.gov.co", "sigla": "idu"})
        self.assertEqual(r.status_code, 201, r.content)
        idu = r.json()["id"]
        juridica = c.get(f"/api/configuracion/evaluaciones?entidad_id={idu}").json()[0]
        self.assertEqual(juridica["activa"]["version"], 1)
        self.assertEqual(juridica["definicion"]["parametros"]["prefijo_codigo"], "IDU")
        self.assertIn("IDU", juridica["definicion"]["parametros"]["beneficiario_claves"])

        r = c.post(
            "/api/plataforma/entidades",
            {"nombre": "Copia ICCU", "nit": "123", "email_admin": "a@copia.gov.co", "base": "copiar", "copiar_de": str(self.iccu.id)},
        )
        self.assertEqual(r.status_code, 201, r.content)
        copia = c.get(f"/api/configuracion/evaluaciones?entidad_id={r.json()['id']}").json()[0]
        self.assertEqual(copia["activa"]["nombre"], "Jurídica ICCU 2026")
        self.assertEqual(len(copia["definicion"]["requisitos"]), 17)

    def test_probar_requisito_contra_ofertas(self):
        from concurrent.futures import ThreadPoolExecutor

        _, ev = self.crear()
        props = self.admin.get(f"/api/evaluaciones/{ev['id']}").json()["proponentes"]
        requisito = definicion_propia()["requisitos"][-1]

        def falso(proponente, proceso, req, parametros):
            from motor.esquemas.proceso import ResultadoRequisito

            return ResultadoRequisito(hoja=proponente.hoja, numero_orden=proponente.numero_orden, nombre_proponente=proponente.nombre_proponente, requisito=req["numero"], cumple=proponente.hoja == "P-01", motivo=None if proponente.hoja == "P-01" else "No se encontró el documento")

        with ThreadPoolExecutor(2) as pool, mock.patch("api.configuracion.obtener_pool", return_value=pool), mock.patch("api.configuracion.probar_requisito", falso):
            r = self.admin.post("/api/configuracion/requisitos/probar", {"evaluacion_id": ev["id"], "requisito": requisito, "proponente_ids": [p["id"] for p in props]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(sorted((x["hoja"], x["cumple"]) for x in r.json()), [("P-01", True), ("P-02", False)])
        otra = Cliente()
        otra.entrar("admin@otra.gov.co")
        r = otra.post("/api/configuracion/requisitos/probar", {"evaluacion_id": ev["id"], "requisito": requisito, "proponente_ids": [props[0]["id"]]})
        self.assertEqual(r.status_code, 404)

    def test_proponer_con_ia(self):
        propuesta = {
            "titulo": "Certificado de la Junta Central de Contadores del contador",
            "corto": "JCC",
            "grupo": "antecedentes",
            "verifica": "Sin antecedentes y máximo 3 meses",
            "config": {"frases_documento": ["JUNTA CENTRAL DE CONTADORES"], "bloques": [{"tipo": "vigencia_maxima", "meses": 3}, {"tipo": "contiene", "frases": ["NO REGISTRA ANTECEDENTES"]}]},
        }
        with mock.patch("api.configuracion.consultar_json", return_value=propuesta):
            r = self.admin.post("/api/configuracion/requisitos/proponer", {"descripcion": "Certificado de la Junta Central de Contadores del contador con vigencia de 3 meses que diga no registra antecedentes"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["verificacion"], "personalizado")
        with mock.patch("api.configuracion.consultar_json", return_value=None):
            r = self.admin.post("/api/configuracion/requisitos/proponer", {"descripcion": "Certificado de la Junta Central de Contadores del contador"})
        self.assertEqual(r.status_code, 503)


class RetencionTests(BaseEvaluaciones):
    def test_borra_ofertas_de_procesos_aprobados_hace_mas_de_30_dias(self):
        import os
        import tempfile
        import time as tiempo
        from pathlib import Path

        from evaluaciones import retencion

        jefe, ev = self.crear()
        _, otro = self.crear(codigo="VIGENTE-001")
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            ofertas = cache / "drive_files"
            ocr = cache / "ocr"
            ofertas.mkdir()
            ocr.mkdir()
            for fid in ("a1", "a2"):
                (ofertas / f"{fid}.zip").write_bytes(b"zip")
                (ofertas / f"{fid}.meta.json").write_text("{}")
            viejo = ocr / "viejo.txt"
            viejo.write_text("texto")
            hace_40_dias = tiempo.time() - 40 * 86400
            os.utime(viejo, (hace_40_dias, hace_40_dias))
            (ocr / "reciente.txt").write_text("texto")

            with mock.patch.object(retencion, "CACHE", cache), mock.patch.object(retencion, "DIRECTORIO_OFERTAS", ofertas):
                # Sin aprobar: no se borra nada de ofertas.
                self.assertEqual(retencion.aplicar(30).procesos, [])
                Evaluacion.objects.filter(pk=ev["id"]).update(
                    estado=EstadoEvaluacion.APROBADA, aprobada_en=timezone.now() - timedelta(days=31)
                )
                # El otro proceso vigente usa las mismas ofertas (a1, a2): se conservan.
                self.assertEqual(retencion.aplicar(30).archivos_ofertas, 0)
                Evaluacion.objects.filter(pk=otro["id"]).update(
                    estado=EstadoEvaluacion.APROBADA, aprobada_en=timezone.now() - timedelta(days=35)
                )
                # Sin expediente permanente generado no se borra nada.
                self.assertEqual(retencion.aplicar(30).procesos, [])
                from evaluaciones.models import EstadoExpediente, Expediente

                for eid in (ev["id"], otro["id"]):
                    e = Evaluacion.objects.get(pk=eid)
                    Expediente.objects.create(entidad_id=e.entidad_id, evaluacion=e, version=1, estado=EstadoExpediente.LISTO)
                simulacro = retencion.aplicar(30, simulacro=True)
                self.assertTrue((ofertas / "a1.zip").exists())
                self.assertEqual(sorted(simulacro.procesos), ["ICCU-CM-037-2026", "VIGENTE-001"])
                informe = retencion.aplicar(30)

            self.assertEqual(sorted(informe.procesos), ["ICCU-CM-037-2026", "VIGENTE-001"])
            self.assertFalse((ofertas / "a1.zip").exists())
            self.assertFalse(viejo.exists())
            self.assertTrue((ocr / "reciente.txt").exists())

        # Ya no se pueden abrir los documentos, pero sí el informe y los resultados.
        prop = jefe.get(f"/api/evaluaciones/{otro['id']}").json()["proponentes"][0]["id"]
        r = jefe.get(f"/api/evaluaciones/{otro['id']}/proponentes/{prop}/documento?archivo=x.pdf")
        self.assertEqual(r.status_code, 410)
        self.assertEqual(jefe.get(f"/api/evaluaciones/{otro['id']}").status_code, 200)



def pdf_minimo(texto: str = "certificado") -> bytes:
    return b"%PDF-1.4\n1 0 obj<<>>endobj\n% " + texto.encode() + b"\n%%EOF"


class HistoricoTests(BaseEvaluaciones):
    def setUp(self):
        import tempfile

        from django.test import override_settings

        self._tmp = tempfile.TemporaryDirectory()
        self._override = override_settings(MEDIA_ROOT=self._tmp.name)
        self._override.enable()
        self.jefe, self.ev = self.crear()
        self.jefe.post(f"/api/evaluaciones/{self.ev['id']}/asignar", {"responsable_id": str(self.evaluador.id)})
        self.abogado = Cliente()
        self.abogado.entrar("abogado@iccu.gov.co")
        self.detalle = self.evaluar_todo(self.abogado, self.ev["id"])
        self.p1 = self.detalle["proponentes"][0]["id"]

    def tearDown(self):
        self._override.disable()
        self._tmp.cleanup()

    def revisar(self, c, prop, req, cumple, nota):
        return c.http.put(
            f"/api/evaluaciones/{self.ev['id']}/revisiones",
            {"proponente_id": prop, "requisito": req, "cumple": cumple, "nota": nota},
            content_type="application/json",
            headers={"X-CSRFToken": c.csrf},
        )

    def aportar(self, c, prop, requisito, persona_id=None, contenido=None, nombre="redam.pdf"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        datos = {"requisito": requisito, "fecha_expedicion": "2026-08-10", "observacion": "Consultado en la página oficial", "archivo": SimpleUploadedFile(nombre, contenido or pdf_minimo())}
        if persona_id:
            datos["persona_id"] = persona_id
        return c.http.post(f"/api/evaluaciones/{self.ev['id']}/proponentes/{prop}/aportados", datos, headers={"X-CSRFToken": c.csrf})

    def test_justificacion_obligatoria(self):
        self.assertEqual(self.revisar(self.abogado, self.p1, 2, True, "").status_code, 400)
        self.assertEqual(self.revisar(self.abogado, self.p1, 2, True, "Se verificó el COPNIA en físico").status_code, 200)

    def test_personas_y_certificados_aportados(self):
        url = f"/api/evaluaciones/{self.ev['id']}/proponentes/{self.p1}/personas"
        empresa = self.abogado.post(url, {"rol": "integrante", "tipo": "juridica", "nombre": "Vías del Norte SAS", "documento": "900.123.456-7"}).json()
        self.assertEqual(empresa["documento"], "900123456-7")
        rep = self.abogado.post(url, {"rol": "representante_legal", "tipo": "natural", "nombre": "Pedro Pérez", "documento": "1.020.304", "fecha_expedicion_documento": "2005-03-01", "de_id": empresa["id"]})
        self.assertEqual(rep.status_code, 201, rep.content)
        # El representante debe ser persona natural y solo una jurídica tiene representantes.
        self.assertEqual(self.abogado.post(url, {"rol": "suplente", "tipo": "juridica", "nombre": "Otra SAS", "documento": "8001"}).status_code, 400)
        self.assertEqual(self.abogado.post(url, {"rol": "suplente", "tipo": "natural", "nombre": "Ana Ruiz", "documento": "5566", "de_id": rep.json()["id"]}).status_code, 400)

        r = self.aportar(self.abogado, self.p1, 2, rep.json()["id"])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.aportar(self.abogado, self.p1, 2, contenido=b"no es pdf").status_code, 400)
        self.assertEqual(self.aportar(self.abogado, self.p1, 99).status_code, 400)
        datos = self.abogado.get(f"/api/evaluaciones/{self.ev['id']}/proponentes/{self.p1}/antecedentes").json()
        self.assertEqual(len(datos["personas"]), 2)
        self.assertEqual(len(datos["aportados"]), 1)
        archivo = self.abogado.get(f"/api/evaluaciones/{self.ev['id']}/aportados/{r.json()['id']}/archivo")
        self.assertEqual(b"".join(archivo.streaming_content)[:5], b"%PDF-")
        # No se quita una persona con certificados; consulta y otra entidad no modifican ni ven.
        self.assertEqual(self.abogado.delete(f"/api/evaluaciones/{self.ev['id']}/personas/{empresa['id']}").status_code, 409)
        consulta = Cliente()
        consulta.entrar("control@iccu.gov.co")
        self.assertEqual(self.aportar(consulta, self.p1, 2).status_code, 403)
        otra = Cliente()
        otra.entrar("admin@otra.gov.co")
        self.assertEqual(otra.get(f"/api/evaluaciones/{self.ev['id']}/aportados/{r.json()['id']}/archivo").status_code, 404)

    def test_reporte_word_y_expediente(self):
        import io
        import zipfile

        from docx import Document

        from evaluaciones.expediente import atender_pendientes

        for p in self.detalle["proponentes"]:
            self.assertEqual(self.revisar(self.abogado, p["id"], 2, True, "COPNIA verificado en la página del Consejo").status_code, 200)
        persona = self.abogado.post(
            f"/api/evaluaciones/{self.ev['id']}/proponentes/{self.p1}/personas",
            {"rol": "representante_legal", "tipo": "natural", "nombre": "Juan Pérez", "documento": "1020304"},
        ).json()
        self.aportar(self.abogado, self.p1, 1, persona["id"])

        r = self.abogado.get(f"/api/evaluaciones/{self.ev['id']}/reporte")
        self.assertEqual(r.status_code, 200)
        self.assertIn("BORRADOR", r["Content-Disposition"])
        texto = "\n".join(c.text for t in Document(io.BytesIO(r.content)).tables for fila in t.rows for c in fila.cells)
        self.assertIn("Aprobado automáticamente por MiEvaluador", texto)
        self.assertIn("Validado manualmente por Abogado Uno", texto)
        self.assertIn("COPNIA verificado en la página del Consejo", texto)
        self.assertIn("Certificado consultado y aportado por Abogado Uno", texto)

        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.jefe.post(f"/api/evaluaciones/{self.ev['id']}/aprobar").status_code, 200)
        exp = self.jefe.get(f"/api/evaluaciones/{self.ev['id']}/expedientes").json()
        self.assertEqual([(e["version"], e["estado"]) for e in exp], [(1, "pendiente")])

        oferta = io.BytesIO()
        with zipfile.ZipFile(oferta, "w") as z:
            z.writestr("CARTA/carta.pdf", pdf_minimo("carta"))
        from motor.esquemas.proceso import ResultadoRequisito

        Resultado = __import__("evaluaciones.models", fromlist=["Resultado"]).Resultado
        for res in Resultado.objects.filter(evaluacion_id=self.ev["id"], requisito=1):
            datos = ResultadoRequisito.model_validate(res.datos).model_copy(update={"archivo_evaluado": "CARTA/carta.pdf"})
            res.datos = datos.model_dump(mode="json")
            res.save()
        with mock.patch("evaluaciones.expediente.download_file_bytes", return_value=oferta.getvalue()):
            self.assertEqual(atender_pendientes(), 1)
        exp = self.jefe.get(f"/api/evaluaciones/{self.ev['id']}/expedientes").json()[0]
        self.assertEqual(exp["estado"], "listo", exp["avisos"])
        r = self.jefe.get(f"/api/evaluaciones/{self.ev['id']}/expedientes/{exp['id']}/archivo")
        zbytes = b"".join(r.streaming_content)
        with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
            nombres = z.namelist()
            self.assertIn("registro.json", nombres)
            self.assertIn("MANIFIESTO.txt", nombres)
            self.assertTrue(any(n.startswith("informe/") and n.endswith(".docx") for n in nombres))
            self.assertTrue(any(n.startswith("informe/") and n.endswith(".xlsx") for n in nombres))
            self.assertTrue(any("documentos evaluados" in n for n in nombres))
            self.assertTrue(any("antecedentes aportados" in n for n in nombres))
            self.assertNotIn("BORRADOR", " ".join(nombres))
        # Si el expediente se anula mientras se arma, no revive al terminar.
        from evaluaciones.expediente import construir, solicitar
        from evaluaciones.models import EstadoExpediente, Expediente

        anulado = solicitar(Evaluacion.objects.get(pk=self.ev["id"]), None)
        Expediente.objects.filter(pk=anulado.pk).update(estado=EstadoExpediente.GENERANDO)
        anulado.estado = EstadoExpediente.GENERANDO
        Expediente.objects.filter(pk=anulado.pk).delete()
        with mock.patch("evaluaciones.expediente.download_file_bytes", return_value=oferta.getvalue()):
            construir(anulado)
        self.assertFalse(Expediente.objects.filter(pk=anulado.pk).exists())

        # Otra entidad no descarga el expediente; regenerar crea la versión 2.
        otra = Cliente()
        otra.entrar("admin@otra.gov.co")
        self.assertEqual(otra.get(f"/api/evaluaciones/{self.ev['id']}/expedientes/{exp['id']}/archivo").status_code, 404)
        self.assertEqual(self.jefe.post(f"/api/evaluaciones/{self.ev['id']}/expedientes").json()["version"], 2)
