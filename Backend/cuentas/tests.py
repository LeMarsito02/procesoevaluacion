"""Pruebas de identidad, roles y aislamiento entre entidades."""
from __future__ import annotations

import re

import pyotp
from django.core import mail
from django.test import Client, TestCase

from cuentas.models import Area, Entidad, EventoAuditoria, Invitacion, Rol, TipoArea, Usuario

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
        cls.iccu = crear_entidad("ICCU", "900258772")
        cls.otra = crear_entidad("Gobernación de Prueba", "800000001")
        cls.admin_iccu = Usuario.objects.create_user("admin@iccu.gov.co", CLAVE, nombre_completo="Admin ICCU", entidad=cls.iccu, rol=Rol.ADMIN_ENTIDAD)
        cls.jefe = Usuario.objects.create_user("jefe@iccu.gov.co", CLAVE, nombre_completo="Jefe Jurídico", entidad=cls.iccu, rol=Rol.JEFE_AREA)
        cls.jefe.areas.set(cls.iccu.areas.filter(tipo=TipoArea.JURIDICA))
        cls.evaluador = Usuario.objects.create_user("abogado@iccu.gov.co", CLAVE, nombre_completo="Abogado Uno", entidad=cls.iccu, rol=Rol.EVALUADOR)
        cls.evaluador.areas.set(cls.iccu.areas.filter(tipo=TipoArea.JURIDICA))
        cls.tecnico = Usuario.objects.create_user("tecnico@iccu.gov.co", CLAVE, nombre_completo="Ingeniero Uno", entidad=cls.iccu, rol=Rol.EVALUADOR)
        cls.tecnico.areas.set(cls.iccu.areas.filter(tipo=TipoArea.TECNICA))
        cls.admin_otra = Usuario.objects.create_user("admin@otra.gov.co", CLAVE, nombre_completo="Admin Otra", entidad=cls.otra, rol=Rol.ADMIN_ENTIDAD)
        cls.superadmin = Usuario.objects.create_superuser("santiagopebe01@lemartek.com", CLAVE, nombre_completo="Santiago")


class InicioSesionTests(BaseCuentas):
    def test_login_correcto_y_yo(self):
        c = Cliente()
        datos = c.entrar("ADMIN@iccu.gov.co ")
        self.assertEqual(datos["estado"], "ok")
        yo = c.get("/api/auth/yo").json()
        self.assertEqual(yo["entidad"]["nombre"], "ICCU")
        self.assertEqual(yo["rol"], Rol.ADMIN_ENTIDAD)

    def test_sin_sesion_no_hay_acceso(self):
        c = Cliente()
        self.assertEqual(c.get("/api/auth/yo").status_code, 401)
        self.assertEqual(c.get("/api/equipo/usuarios").status_code, 401)

    def test_evaluacion_exige_sesion(self):
        c = Cliente()
        self.assertEqual(c.get("/api/health").status_code, 200)
        self.assertEqual(c.post("/api/procesos/evaluar-todos/proponente", {}).status_code, 401)
        self.assertEqual(c.post("/api/procesos/generar-excel", {}).status_code, 401)

    def test_evaluacion_con_sesion_exige_csrf(self):
        c = Cliente()
        c.entrar("abogado@iccu.gov.co")
        r = c.http.post("/api/procesos/generar-excel", {}, content_type="application/json")
        self.assertEqual(r.status_code, 403)
        # Con CSRF pasa la autenticación y llega a la validación del cuerpo.
        self.assertEqual(c.post("/api/procesos/generar-excel", {}).status_code, 422)

    def test_login_sin_csrf_rechazado(self):
        http = Client(enforce_csrf_checks=True)
        r = http.post("/api/auth/login", {"email": "admin@iccu.gov.co", "password": CLAVE}, content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_clave_incorrecta_y_bloqueo(self):
        c = Cliente()
        for _ in range(5):
            r = c.post("/api/auth/login", {"email": "admin@iccu.gov.co", "password": "mala"})
            self.assertEqual(r.status_code, 401)
        # Bloqueado incluso con la clave correcta.
        r = c.post("/api/auth/login", {"email": "admin@iccu.gov.co", "password": CLAVE})
        self.assertEqual(r.status_code, 429)

    def test_mensaje_igual_para_correo_inexistente(self):
        c = Cliente()
        r1 = c.post("/api/auth/login", {"email": "noexiste@iccu.gov.co", "password": "x"}).json()
        r2 = c.post("/api/auth/login", {"email": "admin@iccu.gov.co", "password": "x"}).json()
        self.assertEqual(r1["detail"], r2["detail"])

    def test_usuario_desactivado_pierde_sesion(self):
        c = Cliente()
        c.entrar("abogado@iccu.gov.co")
        Usuario.objects.filter(pk=self.evaluador.pk).update(is_active=False)
        self.assertEqual(c.get("/api/auth/yo").status_code, 401)

    def test_entidad_suspendida_no_entra(self):
        Entidad.objects.filter(pk=self.otra.pk).update(activa=False)
        c = Cliente()
        r = c.post("/api/auth/login", {"email": "admin@otra.gov.co", "password": CLAVE})
        self.assertEqual(r.status_code, 401)

    def test_logout(self):
        c = Cliente()
        c.entrar("abogado@iccu.gov.co")
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
        c.entrar("admin@iccu.gov.co")
        emails = {u["email"] for u in c.get("/api/equipo/usuarios").json()}
        self.assertIn("abogado@iccu.gov.co", emails)
        self.assertNotIn("admin@otra.gov.co", emails)
        # Pedir otra entidad explícitamente no sirve.
        self.assertEqual(c.get(f"/api/equipo/usuarios?entidad_id={self.otra.id}").status_code, 404)

    def test_admin_no_modifica_usuarios_de_otra_entidad(self):
        c = Cliente()
        c.entrar("admin@iccu.gov.co")
        r = c.patch(f"/api/equipo/usuarios/{self.admin_otra.id}", {"activo": False})
        self.assertEqual(r.status_code, 404)
        self.admin_otra.refresh_from_db()
        self.assertTrue(self.admin_otra.is_active)

    def test_admin_no_revoca_invitacion_de_otra_entidad(self):
        inv = Invitacion.objects.create(entidad=self.otra, email="x@otra.gov.co", rol=Rol.EVALUADOR, token_hash="h" * 64, expira_en="2099-01-01T00:00:00Z")
        c = Cliente()
        c.entrar("admin@iccu.gov.co")
        self.assertEqual(c.delete(f"/api/equipo/invitaciones/{inv.id}").status_code, 404)
        self.assertTrue(Invitacion.objects.filter(pk=inv.pk).exists())

    def test_admin_no_ve_auditoria_de_otra_entidad(self):
        EventoAuditoria.objects.create(entidad=self.otra, accion="secreto.otra")
        c = Cliente()
        c.entrar("admin@iccu.gov.co")
        acciones = {e["accion"] for e in c.get("/api/equipo/auditoria").json()}
        self.assertNotIn("secreto.otra", acciones)

    def test_jefe_ve_solo_su_area(self):
        c = Cliente()
        c.entrar("jefe@iccu.gov.co")
        emails = {u["email"] for u in c.get("/api/equipo/usuarios").json()}
        self.assertIn("abogado@iccu.gov.co", emails)
        self.assertNotIn("tecnico@iccu.gov.co", emails)

    def test_evaluador_no_gestiona_equipo(self):
        c = Cliente()
        c.entrar("abogado@iccu.gov.co")
        self.assertEqual(c.get("/api/equipo/usuarios").status_code, 403)
        self.assertEqual(c.post("/api/equipo/invitaciones", {"email": "n@iccu.gov.co", "rol": "evaluador"}).status_code, 403)

    def test_solo_superadmin_gestiona_entidades(self):
        c = Cliente()
        c.entrar("admin@iccu.gov.co")
        self.assertEqual(c.get("/api/plataforma/entidades").status_code, 403)

    def test_no_se_puede_escalar_a_superadmin(self):
        c = Cliente()
        c.entrar("admin@iccu.gov.co")
        r = c.patch(f"/api/equipo/usuarios/{self.evaluador.id}", {"rol": "superadmin"})
        self.assertEqual(r.status_code, 400)
        r = c.post("/api/equipo/invitaciones", {"email": "n@iccu.gov.co", "rol": "superadmin"})
        self.assertEqual(r.status_code, 400)

    def test_admin_no_se_desactiva_a_si_mismo(self):
        c = Cliente()
        c.entrar("admin@iccu.gov.co")
        r = c.patch(f"/api/equipo/usuarios/{self.admin_iccu.id}", {"activo": False})
        self.assertEqual(r.status_code, 400)


class InvitacionYRecuperacionTests(BaseCuentas):
    def _token_de_correo(self, patron: str) -> str:
        cuerpo = mail.outbox[-1].body
        return re.search(patron, cuerpo).group(1)

    def test_flujo_invitacion(self):
        c = Cliente()
        c.entrar("admin@iccu.gov.co")
        with self.captureOnCommitCallbacks(execute=True):
            r = c.post("/api/equipo/invitaciones", {"email": "Nuevo@iccu.gov.co", "rol": "evaluador", "areas": ["juridica"]})
        self.assertEqual(r.status_code, 201, r.content)
        token = self._token_de_correo(r"/invitacion/(\S+)")
        # En la base de datos no queda el token, solo su hash.
        self.assertFalse(Invitacion.objects.filter(token_hash=token).exists())

        nuevo = Cliente()
        info = nuevo.get(f"/api/auth/invitaciones/{token}").json()
        self.assertEqual(info["entidad"], "ICCU")
        self.assertEqual(nuevo.post(f"/api/auth/invitaciones/{token}/aceptar", {"nombre_completo": "Nuevo Abogado", "password": "123"}).status_code, 400)
        r = nuevo.post(f"/api/auth/invitaciones/{token}/aceptar", {"nombre_completo": "Nuevo Abogado", "password": CLAVE})
        self.assertEqual(r.status_code, 200, r.content)
        yo = nuevo.get("/api/auth/yo").json()
        self.assertEqual(yo["email"], "nuevo@iccu.gov.co")
        self.assertEqual([a["tipo"] for a in yo["areas"]], ["juridica"])
        # No se reutiliza.
        self.assertEqual(Cliente().get(f"/api/auth/invitaciones/{token}").status_code, 404)

    def test_superadmin_crea_entidad_con_admin(self):
        c = Cliente()
        c.entrar("santiagopebe01@lemartek.com")
        secreto = c.post("/api/auth/2fa/configurar").json()["secreto"]
        c.post("/api/auth/2fa/verificar", {"codigo": pyotp.TOTP(secreto).now()})
        with self.captureOnCommitCallbacks(execute=True):
            r = c.post("/api/plataforma/entidades", {"nombre": "IDU", "nit": "899999081", "email_admin": "admin@idu.gov.co"})
        self.assertEqual(r.status_code, 201, r.content)
        entidad = Entidad.objects.get(nit="899999081")
        self.assertEqual(entidad.areas.count(), 3)
        self.assertEqual(mail.outbox[-1].to, ["admin@idu.gov.co"])
        self.assertEqual(c.post("/api/plataforma/entidades", {"nombre": "IDU 2", "nit": "899999081", "email_admin": "b@idu.gov.co"}).status_code, 409)

    def test_recuperar_clave(self):
        c = Cliente()
        self.assertEqual(c.post("/api/auth/recuperar", {"email": "noexiste@x.co"}).status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        c.post("/api/auth/recuperar", {"email": "abogado@iccu.gov.co"})
        uid, token = re.search(r"/restablecer/(\S+)/(\S+)", mail.outbox[-1].body).groups()
        nueva = "Otra-Clave-Segura-99"
        r = c.post("/api/auth/restablecer", {"uid": uid, "token": token, "password": nueva})
        self.assertEqual(r.status_code, 200, r.content)
        # El enlace ya no sirve una segunda vez.
        self.assertEqual(c.post("/api/auth/restablecer", {"uid": uid, "token": token, "password": nueva + "x"}).status_code, 400)
        Cliente().entrar("abogado@iccu.gov.co", nueva)

    def test_auditoria_inmutable(self):
        evento = EventoAuditoria.objects.create(accion="prueba")
        with self.assertRaises(ValueError):
            evento.save()
        with self.assertRaises(ValueError):
            evento.delete()
