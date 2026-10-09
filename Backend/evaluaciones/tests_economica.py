"""Factor económico (RF-11), ofertas artificialmente bajas (RF-13) y corrección aritmética."""
from __future__ import annotations

import io
from decimal import Decimal

import openpyxl
from django.test import SimpleTestCase

from motor.economica import ponderacion as p
from motor.economica.correccion import al_peso, revisar_excel


class MetodoTests(SimpleTestCase):
    def test_los_centavos_de_la_trm_escogen_el_metodo(self):
        self.assertEqual(p.centavos("4123.57"), 57)
        self.assertEqual(p.metodo_por_trm("4123.00"), p.MEDIANA_VALOR_ABSOLUTO)
        self.assertEqual(p.metodo_por_trm("4123.24"), p.MEDIANA_VALOR_ABSOLUTO)
        self.assertEqual(p.metodo_por_trm("4123.25"), p.MEDIA_GEOMETRICA)
        self.assertEqual(p.metodo_por_trm("4123.74"), p.MEDIA_ARITMETICA_BAJA)
        self.assertEqual(p.metodo_por_trm("4123.99"), p.MENOR_VALOR)
        self.assertEqual(p.metodo_por_trm("4123.57", p.RANGOS_ANTERIORES), p.MEDIA_GEOMETRICA_PRESUPUESTO)

    def test_en_lotes_cada_lote_toma_el_metodo_siguiente(self):
        self.assertEqual([p.metodo_por_trm("4000.80", lote=n) for n in (1, 2, 3)], [p.MENOR_VALOR, p.MEDIANA_VALOR_ABSOLUTO, p.MEDIA_GEOMETRICA])


class CalificacionTests(SimpleTestCase):
    V = {"A": 100.0, "B": 90.0, "C": 80.0}

    def test_menor_valor(self):
        c = p.calificar(self.V, p.MENOR_VALOR, 48.5)
        self.assertEqual(c.puntajes, {"A": 38.8, "B": 43.1111111, "C": 48.5})

    def test_mediana_impar_y_par(self):
        c = p.calificar(self.V, p.MEDIANA_VALOR_ABSOLUTO, 100)
        self.assertEqual((c.referencia, c.puntajes), (90.0, {"A": 88.8888888, "B": 100, "C": 88.8888888}))
        par = p.calificar({**self.V, "D": 70.0}, p.MEDIANA_VALOR_ABSOLUTO, 100)
        # Mediana 85: el máximo es para la inmediatamente por debajo (80).
        self.assertEqual((par.referencia, par.puntajes["C"], par.puntajes["A"]), (80.0, 100, 75.0))

    def test_media_geometrica(self):
        c = p.calificar(self.V, p.MEDIA_GEOMETRICA, 100)
        self.assertAlmostEqual(c.referencia, (100 * 90 * 80) ** (1 / 3))
        self.assertEqual(c.puntajes["B"], 100)
        self.assertLess(c.puntajes["A"], 100)

    def test_media_aritmetica_baja(self):
        c = p.calificar(self.V, p.MEDIA_ARITMETICA_BAJA, 100)
        self.assertEqual(c.referencia, 85.0)  # (80 + 90) / 2
        self.assertEqual(c.puntajes, {"A": 82.3529411, "B": 94.1176470, "C": 94.1176470})

    def test_metodos_anteriores_castigan_el_doble_por_encima(self):
        c = p.calificar(self.V, p.MEDIA_ARITMETICA, 100)
        self.assertEqual(c.puntajes, {"A": 77.7777777, "B": 100, "C": 88.8888888})
        alta = p.calificar(self.V, p.MEDIA_ARITMETICA_ALTA, 100)
        self.assertEqual(alta.referencia, 95.0)
        g = p.calificar(self.V, p.MEDIA_GEOMETRICA_PRESUPUESTO, 100, presupuesto=110)
        self.assertAlmostEqual(g.referencia, (110 * 100 * 90 * 80) ** 0.25)
        self.assertEqual(p.veces_presupuesto(7), 3)

    def test_puntajes_negativos_son_cero_y_errores(self):
        c = p.calificar({"A": 10.0, "B": 100.0}, p.MEDIA_ARITMETICA, 100)
        self.assertEqual(c.puntajes["B"], 0)
        with self.assertRaises(p.ErrorPonderacion):
            p.calificar({}, p.MENOR_VALOR, 100)
        with self.assertRaises(p.ErrorPonderacion):
            p.calificar(self.V, p.MEDIA_GEOMETRICA_PRESUPUESTO, 100)


class ArtificialmenteBajasTests(SimpleTestCase):
    def test_con_cinco_o_mas_ofertas_mediana_menos_desviacion(self):
        a = p.ofertas_bajas({"A": 100, "B": 98, "C": 97, "D": 95, "E": 60}, None)
        self.assertEqual((a.metodo, [x.clave for x in a.alertas]), ("relativa", ["E"]))
        self.assertAlmostEqual(a.valor_minimo_aceptable, 97 - __import__("statistics").pstdev([100, 98, 97, 95, 60]))

    def test_con_menos_de_cinco_contra_el_costo_estimado(self):
        a = p.ofertas_bajas({"A": 100, "B": 79, "C": 81}, 100)
        self.assertEqual((a.metodo, [x.clave for x in a.alertas]), ("absoluta", ["B"]))
        self.assertIsNone(p.ofertas_bajas({"A": 1}, None).valor_minimo_aceptable)


def _excel(filas):
    libro = openpyxl.Workbook()
    for f in filas:
        libro.active.append(f)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


class CorreccionTests(SimpleTestCase):
    FILAS = [
        ["FORMULARIO 1 - PRESUPUESTO"],
        ["ÍTEM", "DESCRIPCIÓN", "UNIDAD", "CANTIDAD", "VALOR UNITARIO", "VALOR TOTAL"],
        ["1.1", "Excavación", "m3", 10, 1000.4, 10000],
        ["1.2", "Concreto", "m3", 2.5, 300000, 750000],
        [None, "TOTAL COSTO DIRECTO", None, None, None, 760000],
        [None, "ADMINISTRACIÓN", None, None, 0.2, 152000],
        [None, "IMPREVISTOS", None, None, 0.05, 38000],
        [None, "UTILIDAD", None, None, 0.05, 38000],
        [None, "IVA SOBRE LA UTILIDAD", None, None, 0.19, 7220],
        [None, "VALOR TOTAL DE LA OFERTA", None, None, None, 995220],
    ]

    def test_ajuste_al_peso(self):
        self.assertEqual((al_peso(Decimal("10.5")), al_peso(Decimal("10.49"))), (11, 10))

    def test_oferta_sin_errores(self):
        r = revisar_excel(_excel(self.FILAS))
        self.assertEqual((r.items, r.diferencias, r.sin_verificar, r.total_corregido, r.completa), (2, [], [], 995220, True))

    def test_encuentra_un_error_de_multiplicacion_y_corrige_el_total(self):
        filas = [list(f) for f in self.FILAS]
        filas[3][5] = 700000  # 2,5 × 300.000 no es 700.000
        r = revisar_excel(_excel(filas))
        self.assertEqual([d.texto for d in r.diferencias], ["Fila 4 · ítem «1.2 CONCRETO M3»: dice 700.000 y da 750.000."])
        self.assertEqual((r.total_declarado, r.total_corregido), (995220, 995220))

    def test_lo_que_no_reconoce_no_lo_corrige(self):
        r = revisar_excel(_excel([["ITEM", "DESCRIPCION"], ["1", "algo"]]))
        self.assertFalse(r.completa)
        self.assertIn("No se encontró la fila de títulos", r.sin_verificar[0])
        sin_porcentaje = [list(f) for f in self.FILAS]
        sin_porcentaje[5][4] = None
        self.assertIn("No se leyó el porcentaje de administracion", revisar_excel(_excel(sin_porcentaje)).sin_verificar[0])
        self.assertFalse(revisar_excel(b"no es excel").completa)


from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402

from cuentas.models import EventoAuditoria  # noqa: E402
from cuentas.tests import Cliente  # noqa: E402
from evaluaciones.models import Evaluacion  # noqa: E402
from evaluaciones.tests import BaseEvaluaciones  # noqa: E402


class FactorEconomicoTests(BaseEvaluaciones):
    """Nunca se califica sobre algo sin confirmar."""

    def setUp(self):
        self.jefe, self.ev = self.crear()
        self.proceso = self.ev["proceso_id"]
        self.url = f"/api/economica/procesos/{self.proceso}"
        d = self.jefe.get(self.url).json()
        self.factor = d["factores"][0]["id"]
        self.proponentes = [x["id"] for x in d["proponentes"]]
        for pid in self.proponentes:
            self._resultado(pid, cumple=True)

    def _resultado(self, proponente_id, cumple, revision=False, requisito=1):
        from evaluaciones.models import Resultado
        ev = Evaluacion.objects.get(pk=self.ev["id"])
        Resultado.objects.update_or_create(
            evaluacion=ev, proponente_id=proponente_id, requisito=requisito,
            defaults={"entidad_id": ev.entidad_id, "datos": {"cumple": cumple}, "requiere_revision": revision},
        )

    def _oferta(self, i, valor, archivo=None):
        datos = {"proponente_id": self.proponentes[i], "valor_ofertado": str(valor)}
        if archivo:
            datos["archivo"] = archivo
        r = self.jefe.http.post(f"{self.url}/factores/{self.factor}/ofertas", datos, headers=self.jefe._h())
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_flujo_completo_y_nada_sin_confirmar(self):
        d = self.jefe.put(f"{self.url}/factores/{self.factor}", {"puntaje_maximo": "48.5"}).json()
        excel = SimpleUploadedFile("oferta.xlsx", _excel(CorreccionTests.FILAS))
        self._oferta(0, 995220, excel)
        d = self._oferta(1, 1000000)
        f = d["factores"][0]
        self.assertEqual(f["ofertas"][0]["revision"]["propuesto"], "995220")
        self.assertIn("Sin formulario en Excel", f["ofertas"][1]["revision"]["sin_verificar"][0])
        self.assertTrue(any("TRM" in x for x in f["por_confirmar"]))
        self.assertEqual(self.jefe.post(f"{self.url}/factores/{self.factor}/calificar").status_code, 409)
        self.jefe.put(f"{self.url}/factores/{self.factor}", {"trm": "4123.80", "fecha_trm": "2026-10-20"})
        r = self.jefe.post(f"{self.url}/factores/{self.factor}/calificar")
        self.assertIn("Confirmar el valor corregido de 2 ofertas", r.json()["detail"])
        for o in f["ofertas"]:
            self.jefe.put(f"{self.url}/ofertas/{o['id']}", {"confirmar_corregido": True, "valor_corregido": o["revision"].get("propuesto") or o["valor_ofertado"]})
        d = self.jefe.post(f"{self.url}/factores/{self.factor}/calificar").json()
        c = d["factores"][0]["calificacion"]
        self.assertEqual((c["metodo"], c["centavos_trm"], d["factores"][0]["confirmada_por"]), ("menor_valor", 80, "Jefe Jurídico"))
        self.assertEqual([x["puntaje"] for x in c["puntajes"]], [48.5, 48.2681700])
        # Cambiar algo deja sin efecto la calificación.
        d = self.jefe.put(f"{self.url}/factores/{self.factor}", {"puntaje_maximo": "50"}).json()
        self.assertIsNone(d["factores"][0]["calificacion"])
        self.assertTrue(EventoAuditoria.objects.filter(accion="economica.calificada").exists())

    def test_oferta_artificialmente_baja_bloquea_hasta_resolverla(self):
        self.jefe.put(f"{self.url}/factores/{self.factor}", {"puntaje_maximo": "48.5", "trm": "4123.10", "fecha_trm": "2026-10-20",
                                                            "costo_estimado": "1000000"})
        self._oferta(0, 1000000)
        d = self._oferta(1, 700000)
        for o in d["factores"][0]["ofertas"]:
            d = self.jefe.put(f"{self.url}/ofertas/{o['id']}", {"confirmar_corregido": True, "valor_corregido": o["valor_ofertado"]}).json()
        baja = next(o for o in d["factores"][0]["ofertas"] if o["alerta_baja"])
        self.assertIn("30,0 % por debajo del costo estimado", baja["alerta_baja"])
        self.assertTrue(any("artificialmente bajas" in x for x in d["factores"][0]["por_confirmar"]))
        d = self.jefe.put(f"{self.url}/ofertas/{baja['id']}", {"justificacion": "no_aceptada"}).json()
        rechazada = next(o for o in d["factores"][0]["ofertas"] if o["id"] == baja["id"])
        self.assertEqual(rechazada["estado"], "rechazada")
        d = self.jefe.post(f"{self.url}/factores/{self.factor}/calificar").json()
        self.assertEqual([x["puntaje"] for x in d["factores"][0]["calificacion"]["puntajes"]], [48.5])

    def test_solo_se_califica_a_los_habilitados(self):
        from evaluaciones.models import Revision
        self.jefe.put(f"{self.url}/factores/{self.factor}", {"puntaje_maximo": "40", "trm": "4123.80", "fecha_trm": "2026-10-20"})
        self._oferta(0, 1000000)
        d = self._oferta(1, 1100000)
        for o in d["factores"][0]["ofertas"]:
            d = self.jefe.put(f"{self.url}/ofertas/{o['id']}", {"confirmar_corregido": True, "valor_corregido": o["valor_ofertado"]}).json()
        # Un requisito en revisión deja pendiente al proponente: no se califica.
        self._resultado(self.proponentes[0], cumple=False, revision=True, requisito=2)
        r = self.jefe.post(f"{self.url}/factores/{self.factor}/calificar")
        self.assertEqual(r.status_code, 409)
        self.assertIn("requisitos habilitantes", r.json()["detail"])
        # La persona decide «no cumple»: ya no está habilitado y hay que rechazar su oferta.
        ev = Evaluacion.objects.get(pk=self.ev["id"])
        Revision.objects.create(entidad_id=ev.entidad_id, evaluacion=ev, proponente_id=self.proponentes[0], requisito=2, cumple=False,
                                usuario=self.jefe_usuario())
        d = self.jefe.get(self.url).json()
        self.assertTrue(any("no quedaron habilitados" in x for x in d["factores"][0]["por_confirmar"]))
        oferta = next(o for o in d["factores"][0]["ofertas"] if o["proponente_id"] == self.proponentes[0])
        self.assertEqual(oferta["habilitacion"], "no_habilitado")
        self.jefe.put(f"{self.url}/ofertas/{oferta['id']}", {"estado": "rechazada", "motivo_rechazo": "No quedó habilitado."})
        d = self.jefe.post(f"{self.url}/factores/{self.factor}/calificar").json()
        self.assertEqual([x["puntaje"] for x in d["factores"][0]["calificacion"]["puntajes"]], [40.0])
        # Un proponente sin evaluar también queda pendiente.
        from evaluaciones.models import Resultado
        Resultado.objects.filter(proponente_id=self.proponentes[1]).delete()
        d = self.jefe.get(self.url).json()
        self.assertTrue(any("requisitos habilitantes" in x for x in d["factores"][0]["por_confirmar"]))

    def jefe_usuario(self):
        from cuentas.models import Usuario
        return Usuario.objects.get(email="jefe@entidad.gov.co")

    def test_permisos(self):
        otra = Cliente()
        otra.entrar("admin@otraentidad.gov.co")
        self.assertEqual(otra.get(self.url).status_code, 404)
        abogado2 = Cliente()
        abogado2.entrar("abogado2@entidad.gov.co")
        self.assertEqual(abogado2.get(self.url).status_code, 404)
