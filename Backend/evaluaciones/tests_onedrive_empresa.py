"""Carpetas de ofertas en el OneDrive/SharePoint de la entidad (Microsoft 365)."""
import os
from unittest import mock

import jwt
import pyotp
from django.test import SimpleTestCase

from cuentas.models import Entidad, EventoAuditoria
from cuentas.tests import Cliente
from evaluaciones.tests import DOCUMENTO_BASE, BaseEvaluaciones
from motor.integrations import onedrive_empresa as od

DIRECTORIO = "11111111-2222-3333-4444-555555555555"
OTRO = "99999999-8888-7777-6666-555555555555"
ENLACE = "https://contoso-my.sharepoint.com/:f:/g/personal/compras_contoso_gov_co/EabcDEF?e=x1"
CREDENCIALES = {"MICROSOFT_CLIENT_ID": "app-id", "MICROSOFT_CLIENT_SECRET": "secreto"}


class Respuesta:
    def __init__(self, datos=None, status=200, contenido=b""):
        self._datos, self.status_code, self.content = datos or {}, status, contenido
        self.ok = status < 400

    def json(self):
        return self._datos

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)


def microsoft_falso(roles=("Files.Read.All",), token_ok=True):
    """Simula a Microsoft: directorio por nombre, token y Graph."""
    def post(url, data=None, timeout=None):
        if not token_ok:
            return Respuesta({"error": "invalid_client", "error_description": "AADSTS7000229"}, 401)
        return Respuesta({"access_token": jwt.encode({"roles": list(roles)}, "x"), "expires_in": 3600})

    def get(url, headers=None, timeout=None, **kw):
        if ".well-known/openid-configuration" in url:
            return Respuesta({"issuer": f"https://login.microsoftonline.com/{DIRECTORIO}/v2.0"})
        if "/shares/" in url:
            return Respuesta({"id": "RAIZ", "folder": {}, "parentReference": {"driveId": "b!drv-1"}})
        if url.endswith("/items/RAIZ/children?$top=200"):
            return Respuesta({"value": [
                {"id": "F1", "name": "1. Consorcio Uno.zip", "size": 10, "file": {"hashes": {"quickXorHash": "h1"}}},
                {"id": "C1", "name": "Proponente 2", "folder": {}},
            ]})
        if url.endswith("/items/C1/children?$top=200"):
            return Respuesta({"value": [{"id": "F2", "name": "2. Vías SAS.zip", "size": 20, "file": {"hashes": {"quickXorHash": "h2"}}}]})
        if url.endswith("/items/F1/content"):
            return Respuesta(contenido=b"PK zip uno")
        return Respuesta(status=404)

    return mock.patch.multiple(od.requests, post=mock.Mock(side_effect=post), get=mock.Mock(side_effect=get))


@mock.patch.dict(os.environ, CREDENCIALES)
class OneDriveEmpresaTests(SimpleTestCase):
    def setUp(self):
        od._TOKENS.clear()
        od._DIRECTORIOS.clear()

    def test_reconoce_el_enlace_y_el_inquilino(self):
        self.assertTrue(od.es_enlace(ENLACE))
        self.assertTrue(od.es_enlace("https://contoso.sharepoint.com/:f:/s/Compras/Eabc"))
        self.assertFalse(od.es_enlace("https://1drv.ms/f/s!abc"))
        self.assertFalse(od.es_enlace("https://drive.google.com/drive/folders/abc"))
        self.assertEqual(od.inquilino_de(ENLACE), "contoso")

    def test_lista_y_descarga_solo_del_directorio_de_la_entidad(self):
        with microsoft_falso():
            archivos = od.listar(ENLACE, DIRECTORIO, 3)
            self.assertEqual([(a["name"], a["carpeta"], a["md5Checksum"]) for a in archivos],
                             [("1. Consorcio Uno.zip", "", "h1"), ("2. Vías SAS.zip", "Proponente 2", "h2")])
            self.assertEqual(od.partes(archivos[0]["id"]), (DIRECTORIO, "b!drv-1", "F1"))
            self.assertEqual(od.descargar(archivos[0]["id"]), b"PK zip uno")
            with self.assertRaisesRegex(od.OneDriveEmpresaError, "otra organización"):
                od.listar(ENLACE, OTRO, 3)
            with self.assertRaisesRegex(od.OneDriveEmpresaError, "directorio de Microsoft"):
                od.listar(ENLACE, None, 3)

    def test_sin_aprobacion_un_mensaje_claro(self):
        with microsoft_falso(token_ok=False), self.assertRaisesRegex(od.OneDriveEmpresaError, "aún no autoriza"):
            od.listar(ENLACE, DIRECTORIO, 3)

    def test_el_listado_general_lo_usa(self):
        from motor.integrations import drive
        with microsoft_falso():
            r = drive.list_proponentes(ENLACE, DIRECTORIO)
        # Las ofertas son las del nivel más alto; la de la subcarpeta no se mezcla.
        self.assertEqual([p.hoja for p in r.proponentes], ["P-01"])
        self.assertTrue(r.proponentes[0].drive_file_id.startswith(od.PREFIJO_ID))
        self.assertIn("subcarpeta", r.no_reconocidos[0])
        with microsoft_falso(), self.assertRaises(drive.DriveAccessError):
            drive.list_proponentes(ENLACE, OTRO)


@mock.patch.dict(os.environ, CREDENCIALES)
class AutorizacionOneDriveTests(BaseEvaluaciones):
    def setUp(self):
        od._TOKENS.clear()
        Entidad.objects.filter(pk=self.entidad1.id).update(microsoft_directorio=DIRECTORIO)
        self.super = Cliente()
        self.super.entrar("santiagopebe01@lemartek.com")
        secreto = self.super.post("/api/auth/2fa/configurar").json()["secreto"]
        self.super.post("/api/auth/2fa/verificar", {"codigo": pyotp.TOTP(secreto).now()})
        self.url = f"/api/plataforma/entidades/{self.entidad1.id}/onedrive"

    def test_enlace_de_aprobacion_y_prueba(self):
        d = self.super.get(self.url).json()
        self.assertIn(f"login.microsoftonline.com/{DIRECTORIO}/v2.0/adminconsent", d["url"])
        self.assertIn("onedrive-retorno", d["redirect_uri"])
        with microsoft_falso(roles=("User.Read.All",)):
            self.assertEqual(self.super.post(f"{self.url}/probar").status_code, 409)
        with microsoft_falso():
            r = self.super.post(f"{self.url}/probar")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNotNone(r.json()["onedrive_autorizado_en"])
        self.assertTrue(EventoAuditoria.objects.filter(accion="entidad.onedrive_autorizado").exists())
        # Si después se revoca, «Probar» lo detecta y lo desmarca.
        with microsoft_falso(token_ok=False):
            self.assertEqual(self.super.post(f"{self.url}/probar").status_code, 409)
        self.assertIsNone(Entidad.objects.get(pk=self.entidad1.id).onedrive_autorizado_en)

    def test_solo_el_superadministrador(self):
        admin = Cliente()
        admin.entrar("admin@entidad.gov.co")
        self.assertEqual(admin.get(self.url).status_code, 403)

    def test_retorno_publico(self):
        r = Cliente().get("/api/auth/microsoft/onedrive-retorno?admin_consent=True&tenant=x")
        self.assertContains(r, "Permiso aprobado")
        self.assertContains(Cliente().get("/api/auth/microsoft/onedrive-retorno?error=access_denied"), "no se aprobó")

    def test_no_se_crea_un_proceso_con_archivos_de_otra_organizacion(self):
        jefe = Cliente()
        jefe.entrar("jefe@entidad.gov.co")
        ajeno = [{"numero_orden": 1, "hoja": "P-01", "nombre_proponente": "Uno", "nombre_archivo": "1.zip",
                  "drive_file_id": f"{od.PREFIJO_ID}{OTRO}!b!drv!F1"}]
        r = jefe.post("/api/evaluaciones/procesos", {"documento_base": {**DOCUMENTO_BASE, "codigo_proceso": "ENT-OD-1"},
                                                    "carpeta_drive": ENLACE, "proponentes": ajeno})
        self.assertEqual(r.status_code, 400)
        self.assertIn("otra organización", r.json()["detail"])
        propio = [{**ajeno[0], "drive_file_id": f"{od.PREFIJO_ID}{DIRECTORIO}!b!drv!F1"}]
        r = jefe.post("/api/evaluaciones/procesos", {"documento_base": {**DOCUMENTO_BASE, "codigo_proceso": "ENT-OD-2"},
                                                    "carpeta_drive": ENLACE, "proponentes": propio})
        self.assertEqual(r.status_code, 201, r.content)
