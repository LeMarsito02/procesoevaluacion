"""Cifrado en reposo de los archivos (RF-21)."""
import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from motor import cifrado

CLAVE = cifrado.nueva_clave()
OTRA = cifrado.nueva_clave()


@mock.patch.dict(os.environ, {"CLAVE_CIFRADO_ARCHIVOS": CLAVE})
class CifradoTests(SimpleTestCase):
    def test_ida_y_vuelta_y_nada_alterado_pasa(self):
        c = cifrado.cifrar(b"%PDF cedula 79.123.456")
        self.assertTrue(c.startswith(cifrado.MAGIA))
        self.assertNotIn(b"79.123.456", c)
        self.assertEqual(cifrado.descifrar(c), b"%PDF cedula 79.123.456")
        dañado = c[:-1] + bytes([c[-1] ^ 1])
        with self.assertRaises(cifrado.ErrorCifrado):
            cifrado.descifrar(dañado)
        # Lo de antes del cifrado se lee tal cual.
        self.assertEqual(cifrado.descifrar(b"%PDF viejo"), b"%PDF viejo")
        # Cifrar dos veces no anida.
        self.assertEqual(cifrado.cifrar(c), c)

    def test_rotacion_de_clave(self):
        vieja = cifrado.cifrar(b"dato")
        with mock.patch.dict(os.environ, {"CLAVE_CIFRADO_ARCHIVOS": f"{OTRA},{CLAVE}"}):
            self.assertEqual(cifrado.descifrar(vieja), b"dato")
            self.assertFalse(cifrado.cifrado_con_actual(vieja))
        with mock.patch.dict(os.environ, {"CLAVE_CIFRADO_ARCHIVOS": OTRA}), self.assertRaises(cifrado.ErrorCifrado):
            cifrado.descifrar(vieja)

    def test_obligatorio_sin_clave_falla(self):
        with mock.patch.dict(os.environ, {"CLAVE_CIFRADO_ARCHIVOS": "", "CIFRADO_OBLIGATORIO": "1"}), self.assertRaises(cifrado.ErrorCifrado):
            cifrado.cifrar(b"x")
        with mock.patch.dict(os.environ, {"CLAVE_CIFRADO_ARCHIVOS": "corta"}), self.assertRaises(cifrado.ErrorCifrado):
            cifrado.cifrar(b"x")

    def test_almacenamiento_cifra_en_disco_y_entrega_en_claro(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            nombre = default_storage.save("entidades/e1/ops/c1/contratista/a.pdf", ContentFile(b"%PDF cedula"))
            self.assertTrue((Path(tmp) / nombre).read_bytes().startswith(cifrado.MAGIA))
            with default_storage.open(nombre) as f:
                self.assertEqual(f.read(), b"%PDF cedula")
            self.assertEqual(default_storage.size(nombre), len(b"%PDF cedula"))
            plantilla = default_storage.save("entidades/e1/plantillas/juridica/p.xlsx", ContentFile(b"PK plantilla"))
            self.assertEqual((Path(tmp) / plantilla).read_bytes(), b"PK plantilla")

    def test_cache_de_ofertas_cifrada(self):
        from motor.integrations import ofertas_locales
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ofertas_locales, "CACHE_DIR", Path(tmp)):
            fid = ofertas_locales.guardar("oferta.zip", b"PK oferta con cedulas")
            self.assertEqual(ofertas_locales.leer(fid), b"PK oferta con cedulas")
            self.assertTrue(all(p.read_bytes().startswith(cifrado.MAGIA) for p in Path(tmp).glob("*.zip")))

    def test_comando_cifra_lo_viejo_y_verifica(self):
        from evaluaciones.management.commands import cifrar_archivos
        with tempfile.TemporaryDirectory() as media, tempfile.TemporaryDirectory() as cache, override_settings(MEDIA_ROOT=media), \
                mock.patch.object(cifrar_archivos, "CACHE_DIR", Path(cache)):
            viejo = Path(media) / "entidades/e1/aportados/a.pdf"
            viejo.parent.mkdir(parents=True)
            viejo.write_bytes(b"%PDF viejo")
            (Path(cache) / "x.zip").write_bytes(b"PK viejo")
            with self.assertRaises(CommandError):
                call_command("cifrar_archivos", "--verificar", stdout=StringIO())
            call_command("cifrar_archivos", stdout=StringIO())
            call_command("cifrar_archivos", "--verificar", stdout=StringIO())
            self.assertEqual(cifrado.leer(viejo), b"%PDF viejo")
            self.assertEqual(cifrado.leer(Path(cache) / "x.zip"), b"PK viejo")
            # Rotación: con una clave nueva al frente, --rotar lo pasa a la nueva.
            with mock.patch.dict(os.environ, {"CLAVE_CIFRADO_ARCHIVOS": f"{OTRA},{CLAVE}"}):
                call_command("cifrar_archivos", "--rotar", stdout=StringIO())
                self.assertTrue(cifrado.cifrado_con_actual(viejo.read_bytes()))
