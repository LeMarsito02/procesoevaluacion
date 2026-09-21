"""Pruebas de identidad, roles y aislamiento entre entidades."""
from __future__ import annotations

import re

import pyotp
from django.core import mail
from django.test import Client, TestCase

from cuentas.models import Area, Entidad, EventoAuditoria, Rol, TipoArea, Usuario

CLAVE = "Clave-Segura-2026"


def crear_entidad(nombre: str, nit: str) -> Entidad:
    entidad = Entidad.objects.create(nombre=nombre, nit=nit)
    Area.objects.bulk_create([Area(entidad=entidad, tipo=t) for t in TipoArea.values])
    return entidad


class Cliente:
    """Cliente HTTP que se comporta como el frontend: pide el token CSRF y lo envía."""

    def __init__(self) -> None:
        self.http = Client(enforce_csrf_checks=True)
        self.csrf = self.http.get("/api/auth/csrf").json()["csrf"]

    def _h(self):
        return {"X-CSRFToken": self.csrf}

    def get(self, url):
        return self.http.get(url)

    def post(self, url, datos=None):
        r = self.http.post(url, datos or {}, content_type="application/json", headers=self._h())
        if r.headers.get("Content-Type", "").startswith("application/json") and isinstance(r.json(), dict):
            self.csrf = r.json().get("csrf", self.csrf)
        return r

    def patch(self, url, datos):
        return self.http.patch(url, datos, content_type="application/json", headers=self._h())

    def delete(self, url):
        return self.http.delete(url, headers=self._h())

    def entrar(self, email, clave=CLAVE):
        r = self.post("/api/auth/login", {"email": email, "password": clave})
        assert r.status_code == 200, r.content
        return r.json()


class BaseCuentas(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.entidad1 = crear_entidad("Entidad de Ejemplo", "900000001")
        cls.otra = crear_entidad("Otra Entidad", "800000002")
        cls.admin_entidad1 = Usuario.objects.create_user("admin@entidad.gov.co", CLAVE, nombre_completo="Admin Entidad", entidad=cls.entidad1, rol=Rol.ADMIN_ENTIDAD)
        cls.jefe = Usuario.objects.create_user("jefe@entidad.gov.co", CLAVE, nombre_completo="Jefe Jurídico", entidad=cls.entidad1, rol=Rol.JEFE_AREA)
        cls.jefe.areas.set(cls.entidad1.areas.filter(tipo=TipoArea.JURIDICA))
        cls.evaluador = Usuario.objects.create_user("abogado@entidad.gov.co", CLAVE, nombre_completo="Abogado Uno", entidad=cls.entidad1, rol=Rol.EVALUADOR)
        cls.evaluador.areas.set(cls.entidad1.areas.filter(tipo=TipoArea.JURIDICA))
        cls.tecnico = Usuario.objects.create_user("tecnico@entidad.gov.co", CLAVE, nombre_completo="Ingeniero Uno", entidad=cls.entidad1, rol=Rol.EVALUADOR)
        cls.tecnico.areas.set(cls.entidad1.areas.filter(tipo=TipoArea.TECNICA))
        cls.admin_otra = Usuario.objects.create_user("admin@otraentidad.gov.co", CLAVE, nombre_completo="Admin Otra", entidad=cls.otra, rol=Rol.ADMIN_ENTIDAD)
        cls.superadmin = Usuario.objects.create_superuser("santiagopebe01@lemartek.com", CLAVE, nombre_completo="Santiago")


class InicioSesionTests(BaseCuentas):
    def test_login_correcto_y_yo(self):
        c = Cliente()
        datos = c.entrar("ADMIN@entidad.gov.co ")
        self.assertEqual(datos["estado"], "ok")
        yo = c.get("/api/auth/yo").json()
        self.assertEqual(yo["entidad"]["nombre"], "Entidad de Ejemplo")
        self.assertEqual(yo["rol"], Rol.ADMIN_ENTIDAD)

    def test_sin_sesion_no_hay_acceso(self):
        c = Cliente()
        self.assertEqual(c.get("/api/auth/yo").status_code, 401)
        self.assertEqual(c.get("/api/equipo/usuarios").status_code, 401)

    def test_evaluacion_exige_sesion(self):
        c = Cliente()
        self.assertEqual(c.get("/api/health").status_code, 200)
        self.assertEqual(c.post("/api/procesos/evaluar-todos/proponente", {}).status_code, 401)
        self.assertEqual(c.post("/api/evaluaciones/procesos", {}).status_code, 401)

    def test_evaluacion_con_sesion_exige_csrf(self):
        c = Cliente()
        c.entrar("abogado@entidad.gov.co")
        r = c.http.post("/api/evaluaciones/procesos", {}, content_type="application/json")
        self.assertEqual(r.status_code, 403)
        # Con CSRF pasa la autenticación y llega a la validación del cuerpo.
        self.assertEqual(c.post("/api/evaluaciones/procesos", {}).status_code, 422)

    def test_login_sin_csrf_rechazado(self):
        http = Client(enforce_csrf_checks=True)
        r = http.post("/api/auth/login", {"email": "admin@entidad.gov.co", "password": CLAVE}, content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_clave_incorrecta_y_bloqueo(self):
        c = Cliente()
        for _ in range(5):
            r = c.post("/api/auth/login", {"email": "admin@entidad.gov.co", "password": "mala"})
            self.assertEqual(r.status_code, 401)
        # Bloqueado incluso con la clave correcta.
        r = c.post("/api/auth/login", {"email": "admin@entidad.gov.co", "password": CLAVE})
        self.assertEqual(r.status_code, 429)

    def test_mensaje_igual_para_correo_inexistente(self):
        c = Cliente()
        r1 = c.post("/api/auth/login", {"email": "noexiste@entidad.gov.co", "password": "x"}).json()
        r2 = c.post("/api/auth/login", {"email": "admin@entidad.gov.co", "password": "x"}).json()
        self.assertEqual(r1["detail"], r2["detail"])

    def test_usuario_desactivado_pierde_sesion(self):
        c = Cliente()
        c.entrar("abogado@entidad.gov.co")
        Usuario.objects.filter(pk=self.evaluador.pk).update(is_active=False)
        self.assertEqual(c.get("/api/auth/yo").status_code, 401)

    def test_entidad_suspendida_no_entra(self):
        Entidad.objects.filter(pk=self.otra.pk).update(activa=False)
        c = Cliente()
        r = c.post("/api/auth/login", {"email": "admin@otraentidad.gov.co", "password": CLAVE})
        self.assertEqual(r.status_code, 401)

    def test_logout(self):
        c = Cliente()
        c.entrar("abogado@entidad.gov.co")
        self.assertEqual(c.post("/api/auth/logout").status_code, 200)
        self.assertEqual(c.get("/api/auth/yo").status_code, 401)


class SegundoFactorTests(BaseCuentas):
    def test_superadmin_debe_configurar_y_usar_2fa(self):
        c = Cliente()
        datos = c.entrar("santiagopebe01@lemartek.com")
        self.assertEqual(datos["estado"], "configurar_2fa")
        # Sin el código no hay sesión.
        self.assertEqual(c.get("/api/auth/yo").status_code, 401)

        secreto = c.post("/api/auth/2fa/configurar").json()["secreto"]
        self.assertEqual(c.post("/api/auth/2fa/verificar", {"codigo": "000000"}).status_code, 401)
        r = c.post("/api/auth/2fa/verificar", {"codigo": pyotp.TOTP(secreto).now()})
        self.assertEqual(r.json()["estado"], "ok")
        self.assertEqual(c.get("/api/auth/yo").json()["rol"], Rol.SUPERADMIN)

        # Siguiente inicio: pide verificar, no configurar, y no deja reconfigurar.
        c2 = Cliente()
        self.assertEqual(c2.entrar("santiagopebe01@lemartek.com")["estado"], "verificar_2fa")
        self.assertEqual(c2.post("/api/auth/2fa/configurar").status_code, 400)

    def test_2fa_sin_contrasena_previa(self):
        c = Cliente()
        self.assertEqual(c.post("/api/auth/2fa/verificar", {"codigo": "123456"}).status_code, 401)

    def test_demasiados_codigos_incorrectos(self):
        c = Cliente()
        c.entrar("santiagopebe01@lemartek.com")
        c.post("/api/auth/2fa/configurar")
        for _ in range(5):
            c.post("/api/auth/2fa/verificar", {"codigo": "000000"})
        self.assertEqual(c.post("/api/auth/2fa/configurar").status_code, 401)


class AislamientoTests(BaseCuentas):
    def test_admin_solo_ve_su_entidad(self):
        c = Cliente()
        c.entrar("admin@entidad.gov.co")
        emails = {u["email"] for u in c.get("/api/equipo/usuarios").json()}
        self.assertIn("abogado@entidad.gov.co", emails)
        self.assertNotIn("admin@otraentidad.gov.co", emails)
        # Pedir otra entidad explícitamente no sirve.
        self.assertEqual(c.get(f"/api/equipo/usuarios?entidad_id={self.otra.id}").status_code, 404)

    def test_admin_no_modifica_usuarios_de_otra_entidad(self):
        c = Cliente()
        c.entrar("admin@entidad.gov.co")
        r = c.patch(f"/api/equipo/usuarios/{self.admin_otra.id}", {"activo": False})
        self.assertEqual(r.status_code, 404)
        self.admin_otra.refresh_from_db()
        self.assertTrue(self.admin_otra.is_active)

    def test_admin_no_reinicia_la_clave_de_otra_entidad(self):
        c = Cliente()
        c.entrar("admin@entidad.gov.co")
        self.assertEqual(c.post(f"/api/equipo/usuarios/{self.admin_otra.id}/clave").status_code, 404)
        self.admin_otra.refresh_from_db()
        self.assertFalse(self.admin_otra.debe_cambiar_clave)

    def test_admin_no_ve_auditoria_de_otra_entidad(self):
        EventoAuditoria.objects.create(entidad=self.otra, accion="secreto.otra")
        c = Cliente()
        c.entrar("admin@entidad.gov.co")
        acciones = {e["accion"] for e in c.get("/api/equipo/auditoria").json()}
        self.assertNotIn("secreto.otra", acciones)

    def test_jefe_ve_solo_su_area(self):
        c = Cliente()
        c.entrar("jefe@entidad.gov.co")
        emails = {u["email"] for u in c.get("/api/equipo/usuarios").json()}
        self.assertIn("abogado@entidad.gov.co", emails)
        self.assertNotIn("tecnico@entidad.gov.co", emails)

    def test_evaluador_no_gestiona_equipo(self):
        c = Cliente()
        c.entrar("abogado@entidad.gov.co")
        self.assertEqual(c.get("/api/equipo/usuarios").status_code, 403)
        self.assertEqual(
            c.post("/api/equipo/usuarios", {"nombre_completo": "Nueva Persona", "email": "n@entidad.gov.co", "rol": "evaluador"}).status_code, 403
        )

    def test_solo_superadmin_gestiona_entidades(self):
        c = Cliente()
        c.entrar("admin@entidad.gov.co")
        self.assertEqual(c.get("/api/plataforma/entidades").status_code, 403)

    def test_no_se_puede_escalar_a_superadmin(self):
        c = Cliente()
        c.entrar("admin@entidad.gov.co")
        r = c.patch(f"/api/equipo/usuarios/{self.evaluador.id}", {"rol": "superadmin"})
        self.assertEqual(r.status_code, 400)
        r = c.post("/api/equipo/usuarios", {"nombre_completo": "Nueva Persona", "email": "n@entidad.gov.co", "rol": "superadmin"})
        self.assertEqual(r.status_code, 400)

    def test_admin_no_se_desactiva_a_si_mismo(self):
        c = Cliente()
        c.entrar("admin@entidad.gov.co")
        r = c.patch(f"/api/equipo/usuarios/{self.admin_entidad1.id}", {"activo": False})
        self.assertEqual(r.status_code, 400)


class CredencialesYRecuperacionTests(BaseCuentas):
    def test_flujo_credenciales(self):
        """El administrador crea la cuenta, entrega la contraseña temporal y la
        persona debe cambiarla antes de poder usar el sistema."""
        c = Cliente()
        c.entrar("admin@entidad.gov.co")
        with self.captureOnCommitCallbacks(execute=True):
            r = c.post(
                "/api/equipo/usuarios",
                {"nombre_completo": "Nuevo Abogado", "email": "Nuevo@entidad.gov.co", "rol": "evaluador", "areas": ["juridica"]},
            )
        self.assertEqual(r.status_code, 201, r.content)
        temporal = r.json()["password_temporal"]
        self.assertTrue(r.json()["usuario"]["debe_cambiar_clave"])
        # El correo avisa de la cuenta, pero nunca lleva la contraseña.
        self.assertEqual(mail.outbox[-1].to, ["nuevo@entidad.gov.co"])
        self.assertNotIn(temporal, mail.outbox[-1].body)

        nuevo = Cliente()
        self.assertEqual(nuevo.post("/api/auth/login", {"email": "nuevo@entidad.gov.co", "password": "otra"}).status_code, 401)
        self.assertEqual(nuevo.entrar("nuevo@entidad.gov.co", temporal)["estado"], "cambiar_clave")
        # Con la contraseña temporal todavía no hay sesión.
        self.assertEqual(nuevo.get("/api/auth/yo").status_code, 401)
        # Ni sirve repetir la temporal ni una débil.
        self.assertEqual(nuevo.post("/api/auth/clave-inicial", {"nueva": temporal}).status_code, 400)
        self.assertEqual(nuevo.post("/api/auth/clave-inicial", {"nueva": "123"}).status_code, 400)
        r = nuevo.post("/api/auth/clave-inicial", {"nueva": CLAVE})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["estado"], "ok")
        yo = nuevo.get("/api/auth/yo").json()
        self.assertEqual(yo["email"], "nuevo@entidad.gov.co")
        self.assertEqual([a["tipo"] for a in yo["areas"]], ["juridica"])

        # La temporal ya no sirve; la definitiva sí, y sin volver a pedir cambio.
        otro = Cliente()
        self.assertEqual(otro.post("/api/auth/login", {"email": "nuevo@entidad.gov.co", "password": temporal}).status_code, 401)
        self.assertEqual(otro.entrar("nuevo@entidad.gov.co", CLAVE)["estado"], "ok")

    def test_no_se_repite_el_correo(self):
        c = Cliente()
        c.entrar("admin@entidad.gov.co")
        datos = {"nombre_completo": "Abogado Uno", "email": "abogado@entidad.gov.co", "rol": "evaluador"}
        self.assertEqual(c.post("/api/equipo/usuarios", datos).status_code, 409)

    def test_admin_reinicia_la_clave_de_su_equipo(self):
        c = Cliente()
        c.entrar("admin@entidad.gov.co")
        with self.captureOnCommitCallbacks(execute=True):
            r = c.post(f"/api/equipo/usuarios/{self.evaluador.id}/clave")
        self.assertEqual(r.status_code, 200, r.content)
        temporal = r.json()["password_temporal"]
        self.assertEqual(mail.outbox[-1].to, ["abogado@entidad.gov.co"])
        # La contraseña anterior deja de servir y la nueva obliga a cambiarla.
        otro = Cliente()
        self.assertEqual(otro.post("/api/auth/login", {"email": "abogado@entidad.gov.co", "password": CLAVE}).status_code, 401)
        self.assertEqual(otro.entrar("abogado@entidad.gov.co", temporal)["estado"], "cambiar_clave")
        # El administrador no reinicia la suya propia por esta vía.
        self.assertEqual(c.post(f"/api/equipo/usuarios/{self.admin_entidad1.id}/clave").status_code, 400)

    def test_superadmin_crea_entidad_con_admin(self):
        c = Cliente()
        c.entrar("santiagopebe01@lemartek.com")
        secreto = c.post("/api/auth/2fa/configurar").json()["secreto"]
        c.post("/api/auth/2fa/verificar", {"codigo": pyotp.TOTP(secreto).now()})
        datos = {"nombre": "ENT3", "nit": "899999081", "email_admin": "admin@ent3.gov.co", "nombre_admin": "Admin Tercera"}
        with self.captureOnCommitCallbacks(execute=True):
            r = c.post("/api/plataforma/entidades", datos)
        self.assertEqual(r.status_code, 201, r.content)
        entidad = Entidad.objects.get(nit="899999081")
        self.assertEqual(entidad.areas.count(), 3)
        self.assertEqual(mail.outbox[-1].to, ["admin@ent3.gov.co"])
        # Su administrador entra con la contraseña temporal que se devolvió.
        temporal = r.json()["credenciales"]["password_temporal"]
        self.assertEqual(Cliente().entrar("admin@ent3.gov.co", temporal)["estado"], "cambiar_clave")
        self.assertEqual(c.post("/api/plataforma/entidades", {**datos, "email_admin": "b@ent3.gov.co"}).status_code, 409)

    def test_recuperar_clave(self):
        c = Cliente()
        self.assertEqual(c.post("/api/auth/recuperar", {"email": "noexiste@x.co"}).status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        c.post("/api/auth/recuperar", {"email": "abogado@entidad.gov.co"})
        uid, token = re.search(r"/restablecer/(\S+)/(\S+)", mail.outbox[-1].body).groups()
        nueva = "Otra-Clave-Segura-99"
        r = c.post("/api/auth/restablecer", {"uid": uid, "token": token, "password": nueva})
        self.assertEqual(r.status_code, 200, r.content)
        # El enlace ya no sirve una segunda vez.
        self.assertEqual(c.post("/api/auth/restablecer", {"uid": uid, "token": token, "password": nueva + "x"}).status_code, 400)
        Cliente().entrar("abogado@entidad.gov.co", nueva)

    def test_auditoria_inmutable(self):
        evento = EventoAuditoria.objects.create(accion="prueba")
        with self.assertRaises(ValueError):
            evento.save()
        with self.assertRaises(ValueError):
            evento.delete()


class SoporteTests(BaseCuentas):
    """Personal de LeMarTek: nada sin permiso; solo lectura y solo mientras el permiso esté vigente."""

    def setUp(self):
        import pyotp

        self.soporte = Usuario.objects.create_user("ana@lemartek.com", CLAVE, nombre_completo="Ana Soporte", rol=Rol.SOPORTE)
        self.c = Cliente()
        datos = self.c.entrar("ana@lemartek.com")
        self.assertEqual(datos["estado"], "configurar_2fa")  # el soporte también usa 2FA
        secreto = self.c.post("/api/auth/2fa/configurar").json()["secreto"]
        self.c.post("/api/auth/2fa/verificar", {"codigo": pyotp.TOTP(secreto).now()})
        self.admin = Cliente()
        self.admin.entrar("admin@entidad.gov.co")

    def otorgar(self, horas=4):
        with self.captureOnCommitCallbacks(execute=True):
            return self.admin.post("/api/equipo/soporte", {"soporte_id": str(self.soporte.id), "horas": horas, "motivo": "Revisar error en informe"})

    def test_sin_permiso_no_ve_nada(self):
        self.assertEqual(self.c.get("/api/auth/soporte/accesos").json(), [])
        self.assertEqual(self.c.post("/api/auth/soporte/entrar", {"entidad_id": str(self.entidad1.id)}).status_code, 403)
        self.assertIsNone(self.c.get("/api/auth/yo").json()["entidad"])
        self.assertEqual(self.c.get("/api/evaluaciones/procesos").json(), [])

    def test_con_permiso_entra_solo_lectura_y_se_revoca(self):
        r = self.otorgar()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(mail.outbox[-1].to, ["ana@lemartek.com"])
        self.assertEqual(len(self.c.get("/api/auth/soporte/accesos").json()), 1)
        yo = self.c.post("/api/auth/soporte/entrar", {"entidad_id": str(self.entidad1.id)}).json()
        self.assertEqual(yo["entidad"]["nombre"], "Entidad de Ejemplo")
        self.assertIsNotNone(yo["acceso_soporte_hasta"])
        # Ve la entidad pero no puede gestionar ni crear.
        self.assertEqual(self.c.get("/api/equipo/usuarios").status_code, 403)
        self.assertEqual(
            self.c.post("/api/equipo/usuarios", {"nombre_completo": "Otra Persona", "email": "x@entidad.gov.co", "rol": "evaluador"}).status_code, 403
        )
        from evaluaciones.permisos import puede_crear_procesos

        self.assertFalse(puede_crear_procesos(self.soporte))
        # No puede entrar a otra entidad sin permiso.
        self.assertEqual(self.c.post("/api/auth/soporte/entrar", {"entidad_id": str(self.otra.id)}).status_code, 403)
        self.c.post("/api/auth/soporte/entrar", {"entidad_id": str(self.entidad1.id)})
        # El administrador revoca: pierde el acceso en la siguiente petición.
        acceso = self.admin.get("/api/equipo/soporte").json()["accesos"][0]
        self.assertEqual(self.admin.delete(f"/api/equipo/soporte/{acceso['id']}").status_code, 204)
        self.assertIsNone(self.c.get("/api/auth/yo").json()["entidad"])
        acciones = {e["accion"] for e in self.admin.get("/api/equipo/auditoria").json()}
        self.assertTrue({"soporte.acceso_otorgado", "soporte.ingreso", "soporte.acceso_revocado"} <= acciones)

    def test_permiso_vencido(self):
        from datetime import timedelta

        from django.utils import timezone

        from cuentas.models import AccesoSoporte

        self.otorgar()
        self.c.post("/api/auth/soporte/entrar", {"entidad_id": str(self.entidad1.id)})
        AccesoSoporte.objects.update(expira_en=timezone.now() - timedelta(minutes=1))
        self.assertIsNone(self.c.get("/api/auth/yo").json()["entidad"])

    def test_limites_y_permisos_para_otorgar(self):
        self.assertEqual(self.otorgar(horas=100).status_code, 400)
        jefe = Cliente()
        jefe.entrar("jefe@entidad.gov.co")
        r = jefe.post("/api/equipo/soporte", {"soporte_id": str(self.soporte.id), "horas": 2, "motivo": "Revisar algo"})
        self.assertEqual(r.status_code, 403)
        # Un usuario normal no se puede usar como soporte.
        r = self.admin.post("/api/equipo/soporte", {"soporte_id": str(self.evaluador.id), "horas": 2, "motivo": "Revisar algo"})
        self.assertEqual(r.status_code, 400)


class RecaptchaTests(BaseCuentas):
    """reCAPTCHA Enterprise en el inicio de sesión y la recuperación de clave."""

    def configurado(self, respuesta=None, error=None):
        from unittest import mock

        from cuentas import recaptcha

        simulado = mock.Mock()
        if error:
            simulado.side_effect = error
        else:
            simulado.return_value.json.return_value = respuesta
            simulado.return_value.raise_for_status.return_value = None
        return (
            mock.patch.multiple(recaptcha, PROJECT_ID="proyecto-mievaluador", API_KEY="AIzaClaveDePrueba"),
            mock.patch.object(recaptcha.requests, "post", simulado),
            simulado,
        )

    def login(self, token="tok"):
        return Cliente().post("/api/auth/login", {"email": "admin@entidad.gov.co", "password": CLAVE, "recaptcha": token})

    def test_sin_configurar_no_se_verifica(self):
        self.assertEqual(self.login(token=None).status_code, 200)

    def test_token_valido_de_la_accion(self):
        conf, post, simulado = self.configurado({"tokenProperties": {"valid": True, "action": "LOGIN"}, "riskAnalysis": {"score": 0.9}})
        with conf, post:
            self.assertEqual(self.login().status_code, 200)
        cuerpo = simulado.call_args.kwargs["json"]["event"]
        self.assertEqual((cuerpo["token"], cuerpo["expectedAction"]), ("tok", "LOGIN"))

    def test_sin_token_se_rechaza(self):
        conf, post, _ = self.configurado({})
        with conf, post:
            self.assertEqual(self.login(token=None).status_code, 400)

    def test_token_de_otra_accion_se_rechaza(self):
        conf, post, _ = self.configurado({"tokenProperties": {"valid": True, "action": "RECUPERAR_CLAVE"}, "riskAnalysis": {"score": 0.9}})
        with conf, post:
            self.assertEqual(self.login().status_code, 400)

    def test_puntaje_bajo_se_rechaza(self):
        conf, post, _ = self.configurado({"tokenProperties": {"valid": True, "action": "LOGIN"}, "riskAnalysis": {"score": 0.1}})
        with conf, post:
            self.assertEqual(self.login().status_code, 403)

    def test_token_invalido_se_rechaza(self):
        conf, post, _ = self.configurado({"tokenProperties": {"valid": False, "invalidReason": "EXPIRED"}})
        with conf, post:
            self.assertEqual(self.login().status_code, 400)

    def test_google_caido_deja_pasar_salvo_estricto(self):
        from unittest import mock

        import requests

        from cuentas import recaptcha

        conf, post, _ = self.configurado(error=requests.ConnectionError("sin red"))
        with conf, post:
            self.assertEqual(self.login().status_code, 200)
            with mock.patch.object(recaptcha, "ESTRICTO", True):
                self.assertEqual(self.login().status_code, 503)

    def test_recuperar_clave_usa_su_propia_accion(self):
        conf, post, simulado = self.configurado({"tokenProperties": {"valid": True, "action": "RECUPERAR_CLAVE"}, "riskAnalysis": {"score": 0.8}})
        with conf, post:
            r = Cliente().post("/api/auth/recuperar", {"email": "admin@entidad.gov.co", "recaptcha": "tok"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(simulado.call_args.kwargs["json"]["event"]["expectedAction"], "RECUPERAR_CLAVE")


class RecaptchaConfiguracionTests(BaseCuentas):
    def test_clave_del_sitio_en_lugar_del_proyecto_se_detecta(self):
        from unittest import mock

        from cuentas import recaptcha

        with mock.patch.multiple(recaptcha, PROJECT_ID=recaptcha.SITE_KEY, API_KEY=recaptcha.SITE_KEY):
            self.assertIn("RECAPTCHA_PROJECT_ID", recaptcha.problema_de_configuracion())
            self.assertFalse(recaptcha.configurado())
        with mock.patch.multiple(recaptcha, PROJECT_ID="mievaluador-472315", API_KEY=recaptcha.SITE_KEY):
            self.assertIn("RECAPTCHA_API_KEY", recaptcha.problema_de_configuracion())
        with mock.patch.multiple(recaptcha, PROJECT_ID="mievaluador-472315", API_KEY="AIzaSyEjemplo"):
            self.assertIsNone(recaptcha.problema_de_configuracion())
