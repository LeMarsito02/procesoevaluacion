"""Coincidencias entre ofertas de un mismo proceso (RF-14). Datos inventados."""
from __future__ import annotations

import io
import zipfile
from unittest import mock

from django.test import SimpleTestCase

from cuentas.models import EventoAuditoria
from cuentas.tests import Cliente
from evaluaciones.models import PersonaVerificada, Proponente
from evaluaciones.tests import BaseEvaluaciones
from motor.coincidencias import DatosOferta, buscar, contactos

FORMATO = b"%PDF formato en blanco del pliego " + b"x" * 4000
PROPIO_A = b"%PDF certificado propio de A " + b"a" * 4000
COPIADO = b"%PDF presupuesto copiado " + b"c" * 4000


class MotorTests(SimpleTestCase):
    def test_detecta_cada_senal_y_separa_los_formatos_del_pliego(self):
        ofertas = [
            DatosOferta("1", "Uno S.A.S", {"f.pdf": FORMATO, "a.pdf": PROPIO_A, "x.pdf": COPIADO},
                        personas=[("Ana Inventada Pérez", "1.000.000.001", "representante_legal")], empresas=[("Socia Común S.A.S", "900.111.222-3")],
                        matriculas=[("Ingeniería civil", "25202-000111")],
                        texto_contacto="Correo: ofertas@uno.com Tel 310 555 1234 Dirección: Calle 26 # 51-53"),
            DatosOferta("2", "Dos Ltda", {"f.pdf": FORMATO, "y.pdf": COPIADO},
                        personas=[("Pedro Otro Ruiz", "2000000002", "representante_legal"), ("Ana Inventada Perez", "1000000001", "suplente")],
                        empresas=[("SOCIA COMUN SAS", "9001112223")], matriculas=[("Ingeniería civil", "25202-000111")],
                        texto_contacto="ofertas@uno.com · Cl. 26 No. 51 - 53 · celular 3105551234"),
            DatosOferta("3", "Tres S.A.S", {"f.pdf": FORMATO}, personas=[("Luis Tercero Gómez", "3000000003", "representante_legal")],
                        texto_contacto="tres@tres.com"),
        ]
        r = buscar(ofertas)
        tipos = {(c.tipo, tuple(c.ofertas)) for c in r.coincidencias}
        self.assertEqual(tipos, {("documento", ("1", "2")), ("persona", ("1", "2")), ("empresa", ("1", "2")), ("profesional", ("1", "2")),
                                 ("correo", ("1", "2")), ("telefono", ("1", "2")), ("direccion", ("1", "2"))})
        self.assertEqual([(c.tipo, c.ofertas) for c in r.comunes], [("documento", ["1", "2", "3"])])

    def test_sin_coincidencias_y_con_una_sola_oferta(self):
        a = DatosOferta("1", "Uno", {"a.pdf": PROPIO_A}, personas=[("Ana Inventada Pérez", "1000000001", "rl")])
        b = DatosOferta("2", "Dos", {"b.pdf": COPIADO}, personas=[("Pedro Otro Ruiz", "2000000002", "rl")])
        self.assertEqual(buscar([a, b]).coincidencias, [])
        self.assertEqual(buscar([a]).coincidencias, [])

    def test_contactos(self):
        c = contactos("Notificaciones: Carrera 7 No 26-20, Bogotá. Tel: (601) 745 6788 · Cel 300-123-4567 · licitaciones@empresa.co · soporte@secop.gov.co")
        self.assertEqual(c, {"correo": {"licitaciones@empresa.co"}, "telefono": {"3001234567"}, "direccion": {"CARRERA 7 # 26-20"}})


def _zip(**archivos):
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as z:
        for nombre, contenido in archivos.items():
            z.writestr(nombre, contenido)
    return salida.getvalue()


class PlataformaTests(BaseEvaluaciones):
    def test_calcula_guarda_y_el_comite_deja_su_nota(self):
        jefe, ev = self.crear()
        proceso = ev["proceso_id"]
        p1, p2 = Proponente.objects.filter(proceso_id=proceso).order_by("numero_orden")[:2]
        for p in (p1, p2):
            PersonaVerificada.objects.create(entidad=self.entidad1, evaluacion_id=ev["id"], proponente=p, rol="representante_legal",
                                             tipo="natural", nombre="Ana Inventada Pérez", documento="1000000001")
        zips = {p1.drive_file_id: _zip(**{"a/copia.pdf": COPIADO}), p2.drive_file_id: _zip(**{"b/copia.pdf": COPIADO})}
        url = f"/api/coincidencias/procesos/{proceso}"
        self.assertEqual(jefe.get(url).json()["calculado"], False)
        with mock.patch("evaluaciones.coincidencias.download_file_bytes", side_effect=lambda i: zips.get(i, _zip())):
            d = jefe.post(url).json()
        self.assertEqual({c["tipo"] for c in d["coincidencias"]}, {"documento", "persona"})
        persona = next(c for c in d["coincidencias"] if c["tipo"] == "persona")
        self.assertEqual(persona["detalle"], "Ana Inventada Pérez (representante_legal)")
        self.assertEqual(jefe.put(f"{url}/{persona['clave']}", {"nota": " "}).status_code, 400)
        d = jefe.put(f"{url}/{persona['clave']}", {"nota": "Es la misma persona: se remite a la SIC."}).json()
        self.assertEqual(d["revisiones"][persona["clave"]]["por"], "Jefe Jurídico")
        self.assertTrue(EventoAuditoria.objects.filter(accion="coincidencias.revisada").exists())
        otra = Cliente()
        otra.entrar("admin@otraentidad.gov.co")
        self.assertEqual(otra.get(url).status_code, 404)
