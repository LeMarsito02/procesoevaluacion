"""Pruebas de procesos, asignaciones, revisiones y aislamiento (app y RLS)."""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

from asgiref.sync import async_to_sync

from django.core import mail
from django.db import ProgrammingError, transaction
from django.test import TestCase
from django.utils import timezone

from cuentas.aislamiento import NINGUNA, SISTEMA, fijar_entidad
from cuentas.models import Rol, TipoArea, Usuario
from cuentas.tests import CLAVE, BaseCuentas, Cliente, crear_entidad
from evaluaciones import servicios
from evaluaciones.models import EstadoEvaluacion, EstadoTrabajo, Evaluacion, Proceso, Trabajador, Trabajo
from evaluaciones.trabajador import trabajar
from motor.esquemas.proceso import ResultadoRequisito

DOCUMENTO_BASE = {
    "codigo_proceso": "ENT-CM-037-2026",
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
        cls.consulta = Usuario.objects.create_user("control@entidad.gov.co", CLAVE, nombre_completo="Control Interno", entidad=cls.entidad1, rol=Rol.CONSULTA)
        cls.abogado2 = Usuario.objects.create_user("abogado2@entidad.gov.co", CLAVE, nombre_completo="Abogado Dos", entidad=cls.entidad1, rol=Rol.EVALUADOR)
        cls.abogado2.areas.set(cls.entidad1.areas.filter(tipo=TipoArea.JURIDICA))
        cls.eval_otra = Usuario.objects.create_user("abogado@otraentidad.gov.co", CLAVE, nombre_completo="Abogado Otra", entidad=cls.otra, rol=Rol.EVALUADOR)
        cls.eval_otra.areas.set(cls.otra.areas.filter(tipo=TipoArea.JURIDICA))

    def crear(self, email="jefe@entidad.gov.co", codigo="ENT-CM-037-2026"):
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
        self.assertEqual(mail.outbox[-1].to, ["abogado@entidad.gov.co"])
        # Aparece en "mis evaluaciones" del abogado y no en la del otro abogado.
        a1 = Cliente()
        a1.entrar("abogado@entidad.gov.co")
        self.assertEqual([e["id"] for e in a1.get("/api/evaluaciones/mias").json()], [ev["id"]])
        a2 = Cliente()
        a2.entrar("abogado2@entidad.gov.co")
        self.assertEqual(a2.get("/api/evaluaciones/mias").json(), [])

    def test_evaluador_que_crea_queda_responsable(self):
        _, ev = self.crear("abogado@entidad.gov.co")
        self.assertEqual(ev["estado"], EstadoEvaluacion.ASIGNADA)
        self.assertEqual(ev["responsable"]["email"], "abogado@entidad.gov.co")

    def test_abogado_crea_su_propio_proceso_aunque_no_tenga_el_area(self):
        _, ev = self.crear("tecnico@entidad.gov.co")
        self.assertEqual(ev["estado"], EstadoEvaluacion.ASIGNADA)
        self.assertEqual(ev["responsable"]["email"], "tecnico@entidad.gov.co")
        c = Cliente()
        c.entrar("tecnico@entidad.gov.co")
        self.assertTrue(c.get(f"/api/evaluaciones/{ev['id']}").json()["evaluacion"]["puede_trabajar"])

    def test_abogado_no_asigna_a_otro_al_crear(self):
        c = Cliente()
        c.entrar("abogado@entidad.gov.co")
        r = c.post(
            "/api/evaluaciones/procesos",
            {"documento_base": DOCUMENTO_BASE, "proponentes": PROPONENTES, "responsable_id": str(self.abogado2.id)},
        )
        self.assertEqual(r.status_code, 403)

    def test_jefe_asigna_al_crear(self):
        c = Cliente()
        c.entrar("jefe@entidad.gov.co")
        with self.captureOnCommitCallbacks(execute=True):
            r = c.post(
                "/api/evaluaciones/procesos",
                {"documento_base": DOCUMENTO_BASE, "proponentes": PROPONENTES, "responsable_id": str(self.abogado2.id)},
            )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()[0]["responsable"]["email"], "abogado2@entidad.gov.co")
        self.assertEqual(mail.outbox[-1].to, ["abogado2@entidad.gov.co"])

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
        self.assertEqual(ev["entidad_nombre"], "Otra Entidad")
        self.assertEqual(ev["estado"], EstadoEvaluacion.ASIGNADA)
        # No puede asignar a alguien de otra entidad.
        self.assertEqual(c.post(f"/api/evaluaciones/{ev['id']}/asignar", {"responsable_id": str(self.evaluador.id)}).status_code, 400)
        # Reasigna, ve el equipo de esa entidad, evalúa y aprueba.
        self.assertEqual(c.post(f"/api/evaluaciones/{ev['id']}/asignar", {"responsable_id": None}).status_code, 200)
        equipo = {m["email"] for m in c.get(f"/api/evaluaciones/equipo?entidad_id={self.otra.id}").json()}
        self.assertIn("abogado@otraentidad.gov.co", equipo)
        self.assertNotIn("abogado@entidad.gov.co", equipo)
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
        for email in ("abogado@entidad.gov.co", "control@entidad.gov.co"):
            c = Cliente()
            c.entrar(email)
            r = c.post(f"/api/evaluaciones/{ev['id']}/asignar", {"responsable_id": str(self.evaluador.id)})
            self.assertEqual(r.status_code, 403, email)

    def test_consulta_no_crea_procesos(self):
        c = Cliente()
        c.entrar("control@entidad.gov.co")
        r = c.post("/api/evaluaciones/procesos", {"documento_base": DOCUMENTO_BASE, "proponentes": PROPONENTES})
        self.assertEqual(r.status_code, 403)

    def test_codigo_repetido_en_la_misma_entidad(self):
        self.crear()
        c = Cliente()
        c.entrar("jefe@entidad.gov.co")
        r = c.post("/api/evaluaciones/procesos", {"documento_base": DOCUMENTO_BASE, "proponentes": PROPONENTES})
        self.assertEqual(r.status_code, 409)

    def test_mismo_codigo_en_otra_entidad_si_se_permite(self):
        self.crear()
        self.crear("abogado@otraentidad.gov.co")

    def test_tecnica_y_financiera_se_crean_y_asignan_pero_no_evaluan(self):
        c = Cliente()
        c.entrar("admin@entidad.gov.co")
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
        self.assertEqual(por_tipo["juridica"]["responsable"]["email"], "abogado@entidad.gov.co")
        self.assertEqual(por_tipo["tecnica"]["responsable"]["email"], "tecnico@entidad.gov.co")
        self.assertIsNone(por_tipo["financiera"]["responsable"])
        self.assertTrue(por_tipo["juridica"]["tipo_disponible"])
        self.assertFalse(por_tipo["tecnica"]["tipo_disponible"])
        self.assertEqual({m.to[0] for m in mail.outbox}, {"abogado@entidad.gov.co", "tecnico@entidad.gov.co"})
        # El técnico no puede ser responsable jurídico (no tiene el área), y la técnica aún no evalúa.
        r = c.post(f"/api/evaluaciones/{por_tipo['tecnica']['id']}/evaluar", {})
        self.assertEqual(r.status_code, 409)
        self.assertIn("en preparación", r.json()["detail"])
        self.assertEqual(c.get(f"/api/evaluaciones/{por_tipo['tecnica']['id']}/informe").status_code, 400)
        tipos = {t["clave"]: t["disponible"] for t in c.get("/api/evaluaciones/tipos").json()}
        self.assertEqual(tipos, {"juridica": True, "tecnica": False, "financiera": False})

    def test_tipo_invalido(self):
        c = Cliente()
        c.entrar("jefe@entidad.gov.co")
        r = c.post("/api/evaluaciones/procesos", {"documento_base": DOCUMENTO_BASE, "proponentes": PROPONENTES, "tipos": ["ambiental"]})
        self.assertEqual(r.status_code, 400)


class TrabajoTests(BaseEvaluaciones):
    def setUp(self):
        self.jefe, self.ev = self.crear()
        self.jefe.post(f"/api/evaluaciones/{self.ev['id']}/asignar", {"responsable_id": str(self.evaluador.id)})
        self.abogado = Cliente()
        self.abogado.entrar("abogado@entidad.gov.co")

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
        for email in ("abogado2@entidad.gov.co", "control@entidad.gov.co"):
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
        c.entrar("admin@otraentidad.gov.co")
        self.assertEqual(c.get("/api/evaluaciones/procesos").json(), [])
        self.assertEqual(c.get("/api/evaluaciones/mias").json(), [])
        self.assertEqual(c.get(f"/api/evaluaciones/{eid}").status_code, 404)
        self.assertEqual(c.get(f"/api/evaluaciones/{eid}/informe").status_code, 404)
        self.assertEqual(c.get(f"/api/evaluaciones/{eid}/proponentes/{prop}/documento?archivo=x.pdf").status_code, 404)
        self.assertEqual(c.post(f"/api/evaluaciones/{eid}/asignar", {"responsable_id": None}).status_code, 404)
        self.assertEqual(c.post(f"/api/evaluaciones/{eid}/aprobar").status_code, 404)

    def test_rls_filtra_aunque_la_consulta_no_filtre(self):
        self.crear()
        self.crear("abogado@otraentidad.gov.co", codigo="OTRA-001")
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
                    entidad=self.entidad1, codigo="X", fecha_cierre="2026-01-01", documento_base={}, creado_por=self.admin_otra
                )
        finally:
            fijar_entidad(SISTEMA)
        self.assertEqual(Proceso.objects.count(), 2)

    def test_superadmin_ve_todas(self):
        import pyotp

        self.crear()
        self.crear("abogado@otraentidad.gov.co", codigo="OTRA-001")
        c = Cliente()
        c.entrar("santiagopebe01@lemartek.com")
        secreto = c.post("/api/auth/2fa/configurar").json()["secreto"]
        c.post("/api/auth/2fa/verificar", {"codigo": pyotp.TOTP(secreto).now()})
        self.assertEqual(len(c.get("/api/evaluaciones/procesos").json()), 2)


class EntidadNueva(BaseEvaluaciones):
    def test_entidad_sin_procesos(self):
        crear_entidad("Vacía", "123")
        c = Cliente()
        c.entrar("admin@entidad.gov.co")
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
        self.assertEqual(mail.outbox[-1].to, ["abogado@entidad.gov.co"])
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
        c.entrar("control@entidad.gov.co")
        self.assertEqual(c.post(f"/api/evaluaciones/{self.eid}/evaluar", {}).status_code, 403)
        self.assertEqual(c.post(f"/api/evaluaciones/{self.eid}/pausar").status_code, 403)

    def test_otra_entidad_no_ve_novedades(self):
        c = Cliente()
        c.entrar("admin@otraentidad.gov.co")
        self.assertEqual(c.get(f"/api/evaluaciones/{self.eid}/novedades").status_code, 404)

    def test_estado_de_la_fila_por_rol(self):
        self.jefe.post(f"/api/evaluaciones/{self.eid}/evaluar", {})
        c = Cliente()
        c.entrar("admin@entidad.gov.co")
        r = c.get("/api/evaluaciones/fila/estado").json()
        self.assertEqual(r["total_en_fila"], 2)
        self.assertEqual([e["id"] for e in r["evaluaciones"]], [self.eid])
        self.assertEqual(r["trabajadores"], [])
        otra = Cliente()
        otra.entrar("admin@otraentidad.gov.co")
        self.assertEqual(otra.get("/api/evaluaciones/fila/estado").json()["evaluaciones"], [])
        self.assertEqual(self.jefe.get("/api/evaluaciones/fila/estado").status_code, 403)


PLANTILLA_EJEMPLO = "motor/plantillas/plantilla_evaluacion_juridica.xlsx"


def subir(c: "Cliente", tipo="juridica", ruta=PLANTILLA_EJEMPLO, nombre="plantilla.xlsx", entidad_id=None):
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
        self.admin.entrar("admin@entidad.gov.co")

    def tearDown(self):
        self._override.disable()
        self._tmp.cleanup()

    def test_subir_ajustar_mapeo_y_usar_en_el_informe(self):
        r = subir(self.admin, nombre="Plantilla de la entidad 2026.xlsx")
        self.assertEqual(r.status_code, 201, r.content)
        plantilla = r.json()
        self.assertTrue(plantilla["inspeccion"]["valida"])
        self.assertGreater(plantilla["inspeccion"]["hojas_proponente"], 0)
        self.assertIn("1", plantilla["inspeccion"]["filas"])

        mapeo = {**plantilla["mapeo"], "prefijo_codigo": "ENT3"}
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
        self.assertIn("ENT3-ENT-CM-037", wb["P-01"]["F3"].value)

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
        otra.entrar("admin@otraentidad.gov.co")
        self.assertEqual(otra.get(f"/api/configuracion/plantillas/{plantilla['id']}/archivo").status_code, 404)
        self.assertEqual(otra.delete(f"/api/configuracion/plantillas/{plantilla['id']}").status_code, 404)
        self.assertEqual(otra.get("/api/configuracion/plantillas").json()[0]["activa"], None)
        jefe = Cliente()
        jefe.entrar("jefe@entidad.gov.co")
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
        otra.entrar("admin@otraentidad.gov.co")
        self.assertIsNotNone(otra.get("/api/configuracion/plantillas").json()[0]["activa"])


def definicion_propia():
    """Base del sistema sin sanciones del RUP, con numeración propia y un requisito nuevo por bloques."""
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
        self.admin.entrar("admin@entidad.gov.co")

    def publicar(self, c=None, definicion=None, nombre="Jurídica Entidad 2026", entidad_id=None):
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
        # Además del parámetro de la entidad, el salario mínimo del año del cierre.
        self.assertEqual(recibido["criterios"]["parametros"], {"copnia_meses": 6, "smmlv": 1_750_905})
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
        otra.entrar("admin@otraentidad.gov.co")
        self.assertIsNone(otra.get("/api/configuracion/evaluaciones").json()[0]["activa"])
        self.assertEqual(otra.post(f"/api/configuracion/evaluaciones/{v['id']}/activar").status_code, 404)
        jefe = Cliente()
        jefe.entrar("jefe@entidad.gov.co")
        self.assertEqual(self.publicar(c=jefe).status_code, 403)

    def test_superadmin_crea_entidad_con_base_o_copia(self):
        import pyotp

        self.publicar()
        c = Cliente()
        c.entrar("santiagopebe01@lemartek.com")
        secreto = c.post("/api/auth/2fa/configurar").json()["secreto"]
        c.post("/api/auth/2fa/verificar", {"codigo": pyotp.TOTP(secreto).now()})
        r = c.post(
            "/api/plataforma/entidades",
            {"nombre": "Tercera Entidad", "nit": "899000003", "email_admin": "admin@tercera.gov.co", "nombre_admin": "Admin Tercera", "sigla": "ent3"},
        )
        self.assertEqual(r.status_code, 201, r.content)
        tercera = r.json()["entidad"]["id"]
        juridica = c.get(f"/api/configuracion/evaluaciones?entidad_id={tercera}").json()[0]
        self.assertEqual(juridica["activa"]["version"], 1)
        self.assertEqual(juridica["definicion"]["parametros"]["prefijo_codigo"], "ENT3")
        self.assertIn("ENT3", juridica["definicion"]["parametros"]["beneficiario_claves"])

        r = c.post(
            "/api/plataforma/entidades",
            {
                "nombre": "Entidad Copiada", "nit": "123", "email_admin": "a@copia.gov.co", "nombre_admin": "Admin Copia",
                "base": "copiar", "copiar_de": str(self.entidad1.id),
            },
        )
        self.assertEqual(r.status_code, 201, r.content)
        copia = c.get(f"/api/configuracion/evaluaciones?entidad_id={r.json()['entidad']['id']}").json()[0]
        self.assertEqual(copia["activa"]["nombre"], "Jurídica Entidad 2026")
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
        otra.entrar("admin@otraentidad.gov.co")
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
                self.assertEqual(sorted(simulacro.procesos), ["ENT-CM-037-2026", "VIGENTE-001"])
                informe = retencion.aplicar(30)

            self.assertEqual(sorted(informe.procesos), ["ENT-CM-037-2026", "VIGENTE-001"])
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


class BaseHistorico(BaseEvaluaciones):
    def setUp(self):
        import tempfile

        from django.test import override_settings

        self._tmp = tempfile.TemporaryDirectory()
        self._override = override_settings(MEDIA_ROOT=self._tmp.name)
        self._override.enable()
        self.jefe, self.ev = self.crear()
        self.jefe.post(f"/api/evaluaciones/{self.ev['id']}/asignar", {"responsable_id": str(self.evaluador.id)})
        self.abogado = Cliente()
        self.abogado.entrar("abogado@entidad.gov.co")
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


class HistoricoTests(BaseHistorico):
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
        consulta.entrar("control@entidad.gov.co")
        self.assertEqual(self.aportar(consulta, self.p1, 2).status_code, 403)
        otra = Cliente()
        otra.entrar("admin@otraentidad.gov.co")
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
        otra.entrar("admin@otraentidad.gov.co")
        self.assertEqual(otra.get(f"/api/evaluaciones/{self.ev['id']}/expedientes/{exp['id']}/archivo").status_code, 404)
        self.assertEqual(self.jefe.post(f"/api/evaluaciones/{self.ev['id']}/expedientes").json()["version"], 2)


class SancionesRupTests(TestCase):
    """Reglas del abogado sobre multas y sanciones del RUP (art. 58 Ley 2195/2022
    y art. 90 Ley 1474/2011)."""

    cierre = __import__("datetime").date(2026, 8, 20)

    def sancion(self, tipo, anio, contrato="C1", penal=False, incumpl=False, descripcion=""):
        from datetime import date as _date

        from motor.evaluacion.sanciones_rup import Sancion

        return Sancion(
            tipo=tipo, entidad="ENTIDAD", contrato=contrato, descripcion=descripcion, fecha=_date(anio, 3, 1),
            valor="", es_incumplimiento=incumpl, clausula_penal=penal,
        )

    def evaluar(self, sanciones):
        from motor.evaluacion.sanciones_rup import evaluar_sanciones

        return evaluar_sanciones(sanciones, self.cierre)

    def test_multa_del_ultimo_ano_rechaza_y_las_viejas_no(self):
        self.assertFalse(self.evaluar([self.sancion("multa", 2026)])[0])
        self.assertFalse(self.evaluar([self.sancion("sancion", 2026, penal=True)])[0])
        cumple, motivo = self.evaluar([self.sancion("multa", 2023)])
        self.assertTrue(cumple)
        self.assertIn("anteriores al periodo evaluado", motivo)

    def test_inhabilidad_por_incumplimiento_reiterado(self):
        cinco = [self.sancion("multa", 2023, f"C{i}") for i in range(5)]
        self.assertFalse(self.evaluar(cinco)[0])
        self.assertTrue(self.evaluar(cinco[:4])[0])
        dos_contratos = [self.sancion("declaratoria", 2023, "C1"), self.sancion("declaratoria", 2023, "C2")]
        self.assertFalse(self.evaluar(dos_contratos)[0])
        # Mismo contrato en años distintos: no es reiterado en una vigencia fiscal.
        self.assertTrue(self.evaluar([self.sancion("declaratoria", 2023, "C1"), self.sancion("declaratoria", 2022, "C1")])[0])
        mixto = [self.sancion("multa", 2023, "C1"), self.sancion("multa", 2023, "C2"), self.sancion("declaratoria", 2023, "C3")]
        self.assertFalse(self.evaluar(mixto)[0])

    def test_un_mismo_hecho_reportado_dos_veces_no_cuenta_doble(self):
        # El RUP repite el hecho en «SANCIONES» y en «DECLARATORIAS DE INCUMPLIMIENTO».
        repetido = [
            self.sancion("sancion", 2022, "1242-2018", penal=True, incumpl=True),
            self.sancion("declaratoria", 2022, "1242-2018", penal=True),
        ]
        self.assertTrue(self.evaluar(repetido)[0])

    def test_datos_dudosos_van_a_revision(self):
        contradictoria = self.sancion("sancion", 2023, descripcion="INCUMPLIMIENTO DEFINITIVO")
        cumple, motivo = self.evaluar([contradictoria])
        self.assertFalse(cumple)
        self.assertIn("se contradice", motivo)
        sin_fecha = self.sancion("multa", 2023)
        sin_fecha.fecha = None
        self.assertFalse(self.evaluar([sin_fecha])[0])

    def test_lectura_del_rup_real(self):
        """Formatos reales de tres cámaras de comercio distintas."""
        import glob

        from motor.evaluacion.camara_comercio import _norm, _texto_paginas_finales
        from motor.evaluacion.sanciones_rup import extraer_sanciones

        archivos = sorted(glob.glob(".scratch/sanciones_rup/*.pdf"))
        if not archivos:
            self.skipTest("Sin RUP de ejemplo en .scratch (solo se ejecuta en el equipo de desarrollo).")
        for ruta in archivos:
            with open(ruta, "rb") as f:
                sanciones = extraer_sanciones(_norm(_texto_paginas_finales(f.read())))
            self.assertTrue(sanciones, ruta)
            self.assertTrue(all(s.fecha and s.entidad for s in sanciones), ruta)


class HuellaCriteriosTests(TestCase):
    """La caché nunca debe servir un resultado calculado con los criterios de
    una entidad a otra que evalúa distinto."""

    def test_configuraciones_distintas_dan_huellas_distintas(self):
        from motor import criterios

        with criterios.usar({"beneficiario_claves": ["ENT"]}):
            con_entidad = criterios.huella_parametros()
        with criterios.usar({"beneficiario_claves": ["OTRA"]}):
            otra_entidad = criterios.huella_parametros()
        self.assertIsNotNone(con_entidad)
        self.assertNotEqual(con_entidad, otra_entidad)

    def test_sin_configurar_no_hay_huella(self):
        from motor import criterios

        vacios = {clave: p.defecto for clave, p in criterios.PARAMETROS.items()}
        with criterios.usar(vacios):
            self.assertIsNone(criterios.huella_parametros())

    def test_el_entorno_cuenta_como_configuracion(self):
        """Un valor puesto por variable de entorno no es "el valor por defecto":
        si no contara, un resultado calculado sin él se serviría como válido."""
        from unittest import mock

        from motor import criterios

        with mock.patch.dict(criterios._ENTORNO, {"beneficiario_claves": ["ENT"]}, clear=True):
            with criterios.usar(None):
                self.assertEqual(criterios.valor("beneficiario_claves"), ["ENT"])
                self.assertIsNotNone(criterios.huella_parametros())
        with mock.patch.dict(criterios._ENTORNO, {}, clear=True):
            with criterios.usar(None):
                self.assertIsNone(criterios.huella_parametros())

    def test_la_entidad_manda_sobre_el_entorno(self):
        from unittest import mock

        from motor import criterios

        with mock.patch.dict(criterios._ENTORNO, {"beneficiario_claves": ["ENT"]}, clear=True):
            with criterios.usar({"beneficiario_claves": ["SUYA"]}):
                self.assertEqual(criterios.valor("beneficiario_claves"), ["SUYA"])


class IdentidadAntecedentesTests(TestCase):
    """Cada entidad redacta su certificado a su manera: lo que importa es sacar
    de quién es, para no pedirle al evaluador que revise algo que ya está."""

    def identidad(self, requisito, texto):
        from motor.evaluacion import antecedentes as ant

        config = next(c for c in ant._configs() if c.requisito == requisito)
        return config.extraer_identidad(ant._norm(texto))

    def test_rnmc_con_nombre_y_cedula(self):
        texto = (
            "EL CIUDADANO CON CEDULA DE CIUDADANIA NO. 79123456 Y NOMBRE: JUAN CARLOS PEREZ GOMEZ. "
            "NO TIENE MEDIDAS CORRECTIVAS PENDIENTES POR CUMPLIR."
        )
        self.assertEqual(self.identidad(17, texto), ("JUAN CARLOS PEREZ GOMEZ", "79123456"))

    def test_rnmc_solo_con_cedula(self):
        """Variante sin nombre: la cédula sola alcanza para saber de quién es."""
        texto = (
            "QUE A LA FECHA, 01/07/2026 08:38:35 A. M. EL CIUDADANO CON CEDULA DE CIUDADANIA "
            "NO. 79123456 . NO TIENE MEDIDAS CORRECTIVAS PENDIENTES POR CUMPLIR."
        )
        self.assertEqual(self.identidad(17, texto), (None, "79123456"))

    def test_rnmc_de_persona_juridica_no_es_de_nadie(self):
        """El certificado a nombre de un NIT no se puede atribuir a una persona."""
        texto = (
            "QUE A LA FECHA, 26/05/2026 PARA - NIT, SIN DIGITO DE VERIFICACION: NO. 900123456 "
            "NO TIENE MEDIDAS CORRECTIVAS PENDIENTES POR CUMPLIR."
        )
        self.assertEqual(self.identidad(17, texto), (None, None))

    def test_la_cedula_empareja_aunque_el_certificado_no_traiga_nombre(self):
        from motor.evaluacion.antecedentes import CONFIG_RNMC, evaluar_antecedente
        from unittest import mock

        from motor.evaluacion.antecedentes import Certificado

        certificado = Certificado(
            archivo="antecedentes.pdf",
            texto=(
                "SISTEMA REGISTRO NACIONAL DE MEDIDAS CORRECTIVAS RNMC "
                "EL CIUDADANO CON CEDULA DE CIUDADANIA NO. 79123456 . "
                "NO TIENE MEDIDAS CORRECTIVAS PENDIENTES POR CUMPLIR."
            ),
            requisitos=frozenset({17}),
        )
        with mock.patch("motor.evaluacion.antecedentes.leer_certificados", return_value=[certificado]):
            resultado = evaluar_antecedente({}, CONFIG_RNMC, [("JUAN CARLOS PEREZ GOMEZ", "79.123.456")])
        self.assertTrue(resultado.cumple, resultado.motivo)


class FacultadesRepresentanteTests(TestCase):
    """Criterio del abogado: un límite de cuantía solo impide contratar si
    queda por debajo del valor del proceso."""

    CERTIFICADO = (
        "CERTIFICADO DE EXISTENCIA Y REPRESENTACION LEGAL "
        "FACULTADES Y LIMITACIONES DEL REPRESENTANTE LEGAL: EL GERENTE NO PODRA SUSCRIBIR CONTRATOS "
        "SIN PREVIA AUTORIZACION DE LA ASAMBLEA POR CUANTIA SUPERIOR A {limite}. "
    )

    def evaluar(self, limite, valor_proceso, smmlv=0):
        from motor import criterios
        from motor.evaluacion.camara_comercio import _evaluar_facultades_certificado

        with criterios.usar({"smmlv": smmlv}):
            return _evaluar_facultades_certificado(
                "certificado.pdf", self.CERTIFICADO.format(limite=limite), valor_proceso
            )

    def test_limite_por_encima_del_proceso_se_aprueba(self):
        cumple, motivo = self.evaluar("$5.000.000.000", 2_269_370_336)
        self.assertTrue(cumple, motivo)
        self.assertIn("puede suscribir", motivo)

    def test_limite_por_debajo_va_a_revision(self):
        cumple, motivo = self.evaluar("$100.000.000", 2_269_370_336)
        self.assertFalse(cumple)
        self.assertIn("autorización", motivo)

    def test_limite_en_salarios_minimos_con_el_valor_configurado(self):
        # 100 salarios de $1.500.000 = $150.000.000: no alcanza para el proceso.
        cumple, _ = self.evaluar("100 SALARIOS MINIMOS MENSUALES LEGALES VIGENTES", 2_269_370_336, smmlv=1_500_000)
        self.assertFalse(cumple)
        # 3.000 salarios sí lo cubren.
        cumple, motivo = self.evaluar("3.000 SALARIOS MINIMOS MENSUALES LEGALES VIGENTES", 2_269_370_336, smmlv=1_500_000)
        self.assertTrue(cumple, motivo)

    def test_sin_salario_minimo_configurado_queda_para_revision(self):
        """Nunca se aprueba a ciegas: sin el dato, decide una persona."""
        cumple, motivo = self.evaluar("100 SALARIOS MINIMOS MENSUALES LEGALES VIGENTES", 2_269_370_336)
        self.assertFalse(cumple)
        self.assertIn("salario mínimo", motivo)


class AntecedentesEmpresaTests(TestCase):
    """Criterio del abogado: a cada persona jurídica (por NIT) se le exigen
    Contraloría y Procuraduría; Policía, RNMC y REDAM no."""

    PROCURADURIA_EMPRESA = (
        "PROCURADURIA GENERAL DE LA NACION CERTIFICA QUE UNA VEZ CONSULTADO EL SISTEMA DE INFORMACION DE "
        "REGISTRO DE SANCIONES E INHABILIDADES (SIRI), LA PERSONA CONSTRUCTORA EJEMPLO S.A.S. IDENTIFICADO(A) "
        "CON NIT NUMERO 9001234565: NO REGISTRA SANCIONES NI INHABILIDADES VIGENTES"
    )
    PROCURADURIA_PERSONA = (
        "PROCURADURIA GENERAL DE LA NACION CERTIFICA QUE EL(LA) SEÑOR(A) JUAN CARLOS PEREZ GOMEZ IDENTIFICADO(A) "
        "CON CEDULA DE CIUDADANIA NUMERO 79123456: NO REGISTRA SANCIONES NI INHABILIDADES VIGENTES"
    )

    def evaluar(self, config, textos, empresas):
        from unittest import mock

        from motor.evaluacion.antecedentes import Certificado, evaluar_antecedente

        certificados = [Certificado(f"c{i}.pdf", t, frozenset({config.requisito})) for i, t in enumerate(textos)]
        with mock.patch("motor.evaluacion.antecedentes.leer_certificados", return_value=certificados):
            return evaluar_antecedente({}, config, [("JUAN CARLOS PEREZ GOMEZ", "79123456")], empresas)

    def test_la_empresa_se_reconoce_por_su_nit(self):
        from motor.evaluacion.antecedentes import CONFIG_PROCURADURIA
        from motor.evaluacion.camara_comercio import Empresa

        r = self.evaluar(
            CONFIG_PROCURADURIA,
            [self.PROCURADURIA_PERSONA, self.PROCURADURIA_EMPRESA],
            [Empresa("CONSTRUCTORA EJEMPLO S.A.S", "900123456")],
        )
        self.assertTrue(r.cumple, r.motivo)

    def test_nit_pegado_al_texto(self):
        from motor.evaluacion.antecedentes import _nit_del_certificado

        texto = "LA PERSONA LOS EJEMPLOS SAS IDENTIFICADO(A)CON NIT NUMERO 8909340411: NO REGISTRA SANCIONES"
        self.assertEqual(_nit_del_certificado(15, texto), "890934041")

    def test_falta_el_de_la_empresa(self):
        from motor.evaluacion.antecedentes import CONFIG_PROCURADURIA
        from motor.evaluacion.camara_comercio import Empresa

        r = self.evaluar(
            CONFIG_PROCURADURIA, [self.PROCURADURIA_PERSONA], [Empresa("CONSTRUCTORA EJEMPLO S.A.S", "900123456")]
        )
        self.assertFalse(r.cumple)
        self.assertIn("NIT 900123456", r.motivo)

    def test_resultado_de_cada_persona(self):
        """La tabla de antecedentes necesita el estado de cada persona y empresa, no solo el global."""
        from unittest import mock

        from motor.evaluacion.antecedentes import CONFIG_PROCURADURIA, Certificado, evaluar_antecedente
        from motor.evaluacion.camara_comercio import Empresa

        certificados = [Certificado("c0.pdf", self.PROCURADURIA_PERSONA, frozenset({15}))]
        personas = [("JUAN CARLOS PEREZ GOMEZ", "79123456", "representante_legal"), ("ANA MARIA RUIZ LOPEZ", "52999888", "suplente")]
        with mock.patch("motor.evaluacion.antecedentes.leer_certificados", return_value=certificados):
            r = evaluar_antecedente({}, CONFIG_PROCURADURIA, personas, [Empresa("CONSTRUCTORA EJEMPLO S.A.S", "900123456")], plural=True)
        self.assertEqual(
            [(x.nombre, x.rol, x.tipo, x.estado) for x in r.personas],
            [
                ("JUAN CARLOS PEREZ GOMEZ", "representante_legal", "natural", "cumple"),
                ("ANA MARIA RUIZ LOPEZ", "suplente", "natural", "falta"),
                ("CONSTRUCTORA EJEMPLO S.A.S", "integrante", "juridica", "falta"),
            ],
        )
        self.assertEqual(r.personas[0].archivo, "c0.pdf")

    def test_a_la_empresa_no_se_le_exige_policia_ni_rnmc(self):
        from motor.evaluacion.antecedentes import CONFIG_RNMC
        from motor.evaluacion.camara_comercio import Empresa

        rnmc_persona = (
            "SISTEMA REGISTRO NACIONAL DE MEDIDAS CORRECTIVAS RNMC EL CIUDADANO CON CEDULA DE CIUDADANIA NO. "
            "79123456 . NO TIENE MEDIDAS CORRECTIVAS PENDIENTES POR CUMPLIR."
        )
        r = self.evaluar(CONFIG_RNMC, [rnmc_persona], [Empresa("CONSTRUCTORA EJEMPLO S.A.S", "900123456")])
        self.assertTrue(r.cumple, r.motivo)


class IntegrantesNaturalesTests(TestCase):
    """Criterio del abogado: al integrante persona natural de un consorcio se
    le piden todos los antecedentes menos el REDAM."""

    def test_se_agregan_sin_repetir_al_representante(self):
        from motor.evaluacion.antecedentes import _con_integrantes_naturales
        from motor.evaluacion.proponente_plural import Integrante

        personas = [("JUAN CARLOS PEREZ GOMEZ", "79123456")]
        integrantes = [
            Integrante("CONSTRUCTORA EJEMPLO S.A.S", "900123456-5", False),
            Integrante("MARIA LUISA TORRES DIAZ", "52111222", True),
            Integrante("JUAN CARLOS PEREZ GOMEZ", "79.123.456", True),  # también es el representante
        ]
        self.assertEqual(
            _con_integrantes_naturales(personas, integrantes),
            [("JUAN CARLOS PEREZ GOMEZ", "79123456"), ("MARIA LUISA TORRES DIAZ", "52111222", "integrante")],
        )

    def test_el_redam_no_se_le_pide_al_integrante(self):
        from motor.evaluacion.antecedentes import REQUISITOS_INTEGRANTE_NATURAL

        self.assertNotIn(5, REQUISITOS_INTEGRANTE_NATURAL)

    def test_forma_societaria(self):
        from motor.evaluacion.proponente_plural import MARCA_PERSONA_JURIDICA_RE

        for empresa in ("INJERR S.A.S", "PC PROYECCION E INGENIERIA SAS", "SESAC S.A", "CODIPRO LTDA.", "UG21 SL SUCURSAL EN COLOMBIA"):
            self.assertIsNotNone(MARCA_PERSONA_JURIDICA_RE.search(empresa), empresa)
        for persona in ("GERMAN ALONSO PUENTES GORDO", "MARTA EUGENIA GARCIA BETANCUR", "ARCELIA ARIAS DIAZ"):
            self.assertIsNone(MARCA_PERSONA_JURIDICA_RE.search(persona), persona)


# --- El pliego de cada proceso ---
def _pagina(numero: int, *lineas: str) -> "object":
    from motor.pliego.lectura import Pagina

    encabezado = ["DOCUMENTO BASE", f"Código CCE-EJEMPLO-01 Página {numero} de 4"]
    return Pagina(numero, "\n".join([*encabezado, *lineas, str(numero), "Código CCE-EJEMPLO-01 Versión 1"]))


PLIEGO_DE_PRUEBA = [
    _pagina(1, "CAPÍTULO I. INFORMACIÓN GENERAL ..................... 1", "2.3 LIMITACIÓN A MIPYME ................ 2",
            "3.3.2 PERSONAS JURÍDICAS ................ 3", "3.4 SEGURIDAD SOCIAL .................... 3",
            "8.1 GARANTÍA DE SERIEDAD ................ 4"),
    _pagina(2, "CAPÍTULO II. ELABORACIÓN Y PRESENTACIÓN DE LA OFERTA", "2.3 LIMITACIÓN A MIPYME",
            "El presente proceso se limita a Mipyme: únicamente podrán participar Mipyme domiciliadas en Colombia."),
    _pagina(3, "CAPÍTULO III. REQUISITOS HABILITANTES Y SU VERIFICACIÓN", "3.2 CAPACIDAD JURÍDICA",
            "E. Presentar el certificado del Registro de Deudores Alimentarios Morosos – REDAM en los términos de la Ley",
            "2097 de 2021",
            "La Entidad debe consultar los Antecedentes Judiciales en línea en los registros de las bases de datos.",
            "3.3.2 PERSONAS JURÍDICAS",
            "a. Fecha de expedición del certificado no mayor a treinta (30) días calendario anteriores a la fecha de cierre.",
            "c. Las personas jurídicas deberán acreditar que su duración no será inferior a la del plazo del contrato y un año más.",
            "III. Fotocopia del documento de identificación del representante legal."),
    _pagina(4, "3.4 CERTIFICACIÓN DE PAGOS AL SISTEMA DE SEGURIDAD SOCIAL",
            "El proponente acreditará el pago de aportes de seguridad social.",
            "CAPÍTULO XI. LISTA DE ANEXOS", "11.2 FORMATOS", "1. Formato 1 – Carta de presentación de la oferta",
            "2. Formato 3 – Experiencia", "3. Formato 14 – Acreditación de Mipyme"),
]


class LecturaPliegoTests(TestCase):
    def test_secciones_sin_indice_ni_encabezados(self):
        from motor.pliego.lectura import secciones

        s = {x.numero: x for x in secciones(PLIEGO_DE_PRUEBA)}
        self.assertIn("3.3.2", s)
        self.assertEqual(s["3.3.2"].pagina, 3)
        self.assertNotIn("Página", s["3.2"].texto)  # encabezado repetido fuera
        self.assertEqual(sum(1 for x in secciones(PLIEGO_DE_PRUEBA) if x.numero == "2.3"), 1)  # el índice no cuenta

    def test_no_borra_contenido_que_parece_numero_de_pagina(self):
        """"2097 de 2021" es parte de "Ley 2097 de 2021", no un "página 2 de 4"."""
        from motor.pliego.lectura import secciones

        s = {x.numero: x for x in secciones(PLIEGO_DE_PRUEBA)}
        self.assertIn("2097 de 2021", s["3.2"].texto)


class AnalisisPliegoTests(TestCase):
    def hallazgos(self, definicion=None):
        from motor import criterios
        from motor.pliego.analisis import comparar, extraer

        return {h.id: h for h in comparar(extraer(PLIEGO_DE_PRUEBA), definicion or criterios.definicion_sistema("juridica"))}

    def test_detecta_lo_que_cambia_la_evaluacion(self):
        h = self.hallazgos()
        self.assertEqual(h["vigencia_existencia"].tipo, "ajuste_parametro")
        self.assertEqual((h["vigencia_existencia"].parametro, h["vigencia_existencia"].valor_pliego), ("camara_dias", 30))
        self.assertEqual(h["vigencia_existencia"].pagina, 3)
        self.assertIn("treinta (30) días", h["vigencia_existencia"].cita)
        for requisito in ("duracion_sociedad", "identidad_representante", "limitacion_mipyme"):
            self.assertEqual(h[requisito].tipo, "requisito_nuevo", requisito)
            self.assertTrue(h[requisito].requiere_decision)
        self.assertEqual(h["consulta_antecedentes_entidad"].tipo, "aclaracion")
        self.assertFalse(h["consulta_antecedentes_entidad"].requiere_decision)

    def test_formatos_y_alcance(self):
        h = self.hallazgos()
        tipos = {x.titulo: x.tipo for x in h.values() if x.id.startswith("formato_")}
        self.assertEqual(tipos.get("Formato 3 – Experiencia"), "fuera_de_alcance")
        self.assertNotIn("Formato 1 – Carta de presentación de la oferta", tipos)  # ya lo revisa la plantilla

    def test_sin_limitacion_mipyme_no_pide_nada(self):
        from motor.pliego.analisis import comparar, extraer
        from motor import criterios

        paginas = list(PLIEGO_DE_PRUEBA)
        paginas[1] = _pagina(2, "CAPÍTULO II. ELABORACIÓN", "2.3 LIMITACIÓN A MIPYME",
                             "El presente procedimiento de selección no es susceptible de limitarse a Mipyme.")
        h = {x.id: x for x in comparar(extraer(paginas), criterios.definicion_sistema("juridica"))}
        self.assertEqual(h["limitacion_mipyme"].tipo, "informativo")

    def test_si_la_plantilla_ya_usa_30_dias_no_hay_ajuste(self):
        from motor import criterios

        definicion = criterios.definicion_sistema("juridica")
        definicion.parametros = {"camara_dias": 30}
        self.assertNotIn("vigencia_existencia", self.hallazgos(definicion))

    def test_obligacion_desconocida_queda_a_la_vista(self):
        """Una exigencia que ningún detector conoce no se pierde: se muestra con su cita."""
        from motor import criterios
        from motor.pliego.analisis import comparar, extraer

        paginas = list(PLIEGO_DE_PRUEBA)
        paginas[3] = _pagina(4, "3.4 CERTIFICACIÓN DE PAGOS AL SISTEMA DE SEGURIDAD SOCIAL",
                             "El proponente deberá aportar el paz y salvo ambiental expedido por la corporación autónoma regional.")
        h = [x for x in comparar(extraer(paginas), criterios.definicion_sistema("juridica")) if x.tipo == "obligacion"]
        self.assertEqual(len(h), 1)
        self.assertIn("paz y salvo ambiental", h[0].cita)
        self.assertEqual(h[0].pagina, 4)

    def test_pliego_sin_estructura_avisa(self):
        from motor import criterios
        from motor.pliego.analisis import comparar, extraer
        from motor.pliego.lectura import Pagina

        paginas = [Pagina(i, "texto escaneado ilegible sin títulos") for i in range(1, 6)]
        h = comparar(extraer(paginas), criterios.definicion_sistema("juridica"))
        self.assertEqual(h[0].id, "estructura_no_reconocida")

    def test_aplicar_ajustes_aceptados(self):
        from evaluaciones.pliego import aplicar_ajustes
        from motor import criterios

        h = self.hallazgos()
        ajustes = [
            {"id": "vigencia_existencia", "decision": "aceptado", "hallazgo": h["vigencia_existencia"].model_dump()},
            {"id": "duracion_sociedad", "decision": "aceptado", "hallazgo": h["duracion_sociedad"].model_dump()},
            {"id": "identidad_representante", "decision": "rechazado", "nota": "No aplica", "hallazgo": h["identidad_representante"].model_dump()},
        ]
        base = criterios.definicion_sistema("juridica")
        ajustada = aplicar_ajustes(base, ajustes)
        self.assertEqual(ajustada.parametros["camara_dias"], 30)
        nuevos = ajustada.requisitos[len(base.requisitos):]
        self.assertEqual([(r.titulo, r.verificacion) for r in nuevos], [("Duración de la sociedad", criterios.MANUAL)])
        self.assertEqual(nuevos[0].numero, max(r.numero for r in base.requisitos) + 1)

    def test_la_verificacion_manual_queda_pendiente(self):
        from datetime import date

        from motor import criterios
        from motor.esquemas.proceso import Proponente
        from motor.evaluacion.todos import evaluar_requisito

        req = criterios.RequisitoDefinicion(numero=19, titulo="Duración de la sociedad", corto="Duración",
                                            verificacion=criterios.MANUAL, verifica="Plazo del contrato y un año más")
        proponente = Proponente(numero_orden=1, hoja="P-01", nombre_proponente="Ejemplo", nombre_archivo="p1.zip", drive_file_id="x")
        r = evaluar_requisito(proponente, None, req)
        self.assertFalse(r.cumple)
        self.assertIn("Verificación manual", r.motivo)
        self.assertEqual(r.requisito, 19)

    def test_vigencia_en_dias(self):
        from datetime import date

        from motor import criterios
        from motor.evaluacion.camara_comercio import limite_expedicion_camara

        with criterios.usar({"camara_dias": 30}):
            self.assertEqual(limite_expedicion_camara(date(2026, 8, 20))[0], date(2026, 7, 21))
        self.assertEqual(limite_expedicion_camara(date(2026, 8, 20))[0], date(2026, 7, 20))  # 1 mes


class PliegoProcesoTests(BaseEvaluaciones):
    """El proceso se crea con el pliego analizado y lo que la persona decidió."""

    def analisis(self, entidad=None):
        from motor.pliego.analisis import extraer

        with mock.patch("evaluaciones.pliego.leer", return_value=extraer(PLIEGO_DE_PRUEBA)):
            from evaluaciones import pliego

            a, _ = pliego.analizar((entidad or self.entidad1).id, b"%PDF-prueba", "pliego.pdf", self.jefe)
        return a

    def crear_con(self, analisis_id, decisiones, email="jefe@entidad.gov.co"):
        c = Cliente()
        c.entrar(email)
        datos = {"documento_base": DOCUMENTO_BASE, "carpeta_drive": "x", "proponentes": PROPONENTES,
                 "analisis_pliego_id": str(analisis_id), "decisiones_pliego": decisiones}
        return c, c.post("/api/evaluaciones/procesos", datos)

    def test_no_se_crea_sin_decidir_todo(self):
        _, r = self.crear_con(self.analisis().id, {"vigencia_existencia": {"decision": "aceptado"}})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Falta decidir", r.json()["detail"])

    def test_rechazar_exige_razon(self):
        a = self.analisis()
        decisiones = {h: {"decision": "aceptado"} for h in ("vigencia_existencia", "duracion_sociedad", "limitacion_mipyme")}
        decisiones["identidad_representante"] = {"decision": "rechazado", "nota": ""}
        _, r = self.crear_con(a.id, decisiones)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Explique", r.json()["detail"])

    def test_los_ajustes_llegan_a_la_evaluacion_y_al_reporte(self):
        from evaluaciones.models import Evaluacion
        from evaluaciones.reporte import generar_reporte

        a = self.analisis()
        decisiones = {h: {"decision": "aceptado"} for h in ("vigencia_existencia", "duracion_sociedad", "limitacion_mipyme")}
        decisiones["identidad_representante"] = {"decision": "rechazado", "nota": "La cédula se revisa con el RUP."}
        c, r = self.crear_con(a.id, decisiones)
        self.assertEqual(r.status_code, 201, r.content)
        evaluacion = Evaluacion.objects.get(pk=r.json()[0]["id"])
        definicion = servicios.definicion_de(evaluacion)
        self.assertEqual(definicion.parametros["camara_dias"], 30)
        self.assertIn("Duración de la sociedad", [x.titulo for x in definicion.requisitos])
        self.assertNotIn("Documento de identidad del representante legal", [x.titulo for x in definicion.requisitos])
        detalle = c.get(f"/api/evaluaciones/{evaluacion.id}").json()
        self.assertEqual(detalle["pliego"]["nombre_archivo"], "pliego.pdf")
        self.assertIn("Duración de la sociedad", [x["titulo"] for x in detalle["catalogo"]])
        contenido, _ = generar_reporte(evaluacion)
        self.assertGreater(len(contenido), 1000)

    def test_mismo_pdf_se_reutiliza_y_otra_entidad_no_lo_ve(self):
        from evaluaciones import pliego

        a = self.analisis()
        with mock.patch("evaluaciones.pliego.leer", side_effect=AssertionError("no debía releerse")):
            b, reutilizado = pliego.analizar(self.entidad1.id, b"%PDF-prueba", "otro-nombre.pdf", self.jefe)
        self.assertTrue(reutilizado)
        self.assertEqual(a.id, b.id)
        _, r = self.crear_con(a.id, {}, email="abogado@otraentidad.gov.co")
        self.assertEqual(r.status_code, 404)


    def test_el_pliego_queda_en_el_expediente(self):
        import io
        import json
        import zipfile

        from evaluaciones.expediente import construir
        from evaluaciones.models import EstadoExpediente, Evaluacion, Expediente

        a = self.analisis()
        decisiones = {h: {"decision": "aceptado"} for h in ("vigencia_existencia", "duracion_sociedad", "limitacion_mipyme", "identidad_representante")}
        _, r = self.crear_con(a.id, decisiones)
        self.assertEqual(r.status_code, 201, r.content)
        evaluacion = Evaluacion.objects.get(pk=r.json()[0]["id"])
        exp = Expediente.objects.create(entidad=evaluacion.entidad, evaluacion=evaluacion, version=1, estado=EstadoExpediente.GENERANDO)
        construir(exp)
        exp.refresh_from_db()
        with exp.archivo.open("rb") as f, zipfile.ZipFile(io.BytesIO(f.read())) as z:
            self.assertIn("pliego/pliego.pdf", z.namelist())
            registro = json.loads(z.read("registro.json"))
        self.assertEqual(registro["pliego"]["sha256"], a.sha256)
        self.assertEqual(len(registro["pliego"]["ajustes"]), 4)


class TablaAntecedentesTests(BaseHistorico):
    """La tabla de antecedentes se arma sola con todas las personas que exige la
    regla (las que sean) y el estado del certificado de cada una."""

    def guardar(self, personas_por_requisito):
        from evaluaciones.models import Evaluacion, Proponente
        from motor.esquemas.proceso import PersonaAntecedente, ResultadoRequisito

        ev = Evaluacion.objects.get(pk=self.ev["id"])
        prop = Proponente.objects.get(pk=self.p1)
        resultados = [
            ResultadoRequisito(
                hoja=prop.hoja, numero_orden=prop.numero_orden, nombre_proponente=prop.nombre, requisito=req,
                cumple=all(p[3] == "cumple" for p in personas), motivo=None,
                personas_antecedente=[
                    PersonaAntecedente(nombre=n, documento=d, tipo=t, rol=r, estado=e) for n, d, r, e, t in
                    [(p[0], p[1], p[2], p[3], p[4] if len(p) > 4 else "natural") for p in personas]
                ],
            )
            for req, personas in personas_por_requisito.items()
        ]
        servicios.guardar_resultados(ev, prop, resultados)

    def tabla(self):
        return self.abogado.get(f"/api/evaluaciones/{self.ev['id']}/proponentes/{self.p1}/antecedentes").json()

    def test_varias_personas_con_su_estado(self):
        rep = ("ANA MARIA RUIZ LOPEZ", "52999888", "representante_legal")
        sup = ("CARLOS PEREZ GOMEZ", "79123456", "suplente")
        emp = ("CONSTRUCTORA EJEMPLO S.A.S", "900123456", "integrante")
        self.guardar({
            14: [(*rep, "cumple"), (*sup, "falta"), (*emp, "cumple", "juridica")],
            16: [(*rep, "cumple"), (*sup, "con_novedad")],
        })
        t = self.tabla()
        personas = {p["nombre"]: p for p in t["personas"]}
        self.assertEqual(set(personas), {"ANA MARIA RUIZ LOPEZ", "CARLOS PEREZ GOMEZ", "CONSTRUCTORA EJEMPLO S.A.S"})
        self.assertTrue(all(p["detectada"] for p in personas.values()))
        estados = t["estados"]
        self.assertEqual(estados[personas["CARLOS PEREZ GOMEZ"]["id"]]["14"]["estado"], "falta")
        self.assertEqual(estados[personas["CARLOS PEREZ GOMEZ"]["id"]]["16"]["estado"], "con_novedad")
        # A la empresa no se le exige Policía.
        self.assertEqual(estados[personas["CONSTRUCTORA EJEMPLO S.A.S"]["id"]]["16"]["estado"], "no_requerido")

    def test_reevaluar_no_toca_lo_manual_ni_lo_aportado(self):
        self.guardar({14: [("ANA MARIA RUIZ LOPEZ", "52999888", "representante_legal", "falta")]})
        manual = self.abogado.post(
            f"/api/evaluaciones/{self.ev['id']}/proponentes/{self.p1}/personas",
            {"rol": "integrante", "tipo": "natural", "nombre": "Pedro Pablo León", "documento": "1020304050"},
        ).json()
        ana = next(p for p in self.tabla()["personas"] if p["nombre"] == "ANA MARIA RUIZ LOPEZ")
        self.aportar(self.abogado, self.p1, 14, ana["id"])
        # Al reevaluar, el programa ya no la exige (otro representante): se conserva por tener un certificado aportado.
        self.guardar({14: [("JORGE LUIS DIAZ", "80111222", "representante_legal", "cumple")]})
        nombres = {p["nombre"] for p in self.tabla()["personas"]}
        self.assertEqual(nombres, {"ANA MARIA RUIZ LOPEZ", "PEDRO PABLO LEÓN", "JORGE LUIS DIAZ"})
        self.assertIn(manual["id"], {p["id"] for p in self.tabla()["personas"]})


class SalarioMinimoTests(BaseEvaluaciones):
    def test_la_evaluacion_usa_el_del_ano_del_cierre(self):
        from evaluaciones.models import Evaluacion, SalarioMinimo

        _, ev = self.crear()
        evaluacion = Evaluacion.objects.get(pk=ev["id"])
        ano = evaluacion.proceso.fecha_cierre.year
        SalarioMinimo.objects.update_or_create(ano=ano, defaults={"valor": 1_750_905})
        self.assertEqual(servicios.definicion_de(evaluacion).parametros["smmlv"], 1_750_905)
        SalarioMinimo.objects.filter(ano=ano).delete()
        self.assertNotIn("smmlv", servicios.definicion_de(evaluacion).parametros)

    def test_los_valores_oficiales_vienen_cargados(self):
        from evaluaciones.models import SalarioMinimo

        self.assertEqual(SalarioMinimo.objects.get(ano=2025).valor, 1_423_500)
        self.assertEqual(SalarioMinimo.objects.get(ano=2026).valor, 1_750_905)

    def test_solo_el_superadmin_lo_actualiza(self):
        import pyotp

        c = Cliente()
        c.entrar("admin@entidad.gov.co")
        self.assertEqual(c.http.put("/api/plataforma/salarios-minimos/2027", {"valor": 1900000}, content_type="application/json",
                                    headers={"X-CSRFToken": c.csrf}).status_code, 403)
        s = Cliente()
        s.entrar("santiagopebe01@lemartek.com")
        secreto = s.post("/api/auth/2fa/configurar").json()["secreto"]
        s.post("/api/auth/2fa/verificar", {"codigo": pyotp.TOTP(secreto).now()})
        r = s.http.put("/api/plataforma/salarios-minimos/2027", {"valor": 1900000, "norma": "Decreto de prueba"},
                       content_type="application/json", headers={"X-CSRFToken": s.csrf})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(s.get("/api/plataforma/salarios-minimos").json()[0]["ano"], 2027)
