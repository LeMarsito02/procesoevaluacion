"""La lectura del pliego con IA y su fusión con las reglas.

Lo que se prueba aquí es sobre todo lo que NO se acepta: un modelo pequeño
rellena campos con lo primero que encuentra, y un umbral inventado aprobaría
a quien no debe. La regla es que ningún dato entra sin una cita que lo
respalde, y que lo que solo vio la IA no aprueba a nadie solo.
"""
from __future__ import annotations

from django.test import SimpleTestCase

from motor.pliego import fusion
from motor.pliego.parametros_ia import Leido, ParametrosIA, TrozoParametros, _aplicar


def _trozo(pregunta: str, texto: str) -> TrozoParametros:
    return TrozoParametros(pregunta=pregunta, seccion="3.5 EXPERIENCIA", texto=texto)


class ValidacionDeLaLecturaTests(SimpleTestCase):
    def test_un_numero_que_no_esta_en_la_cita_se_descarta(self):
        """El modelo puso "anticipo 30 %" citando una frase sin ese número."""
        p = ParametrosIA()
        texto = "8.3 ANTICIPO O PAGO ANTICIPADO\nLa Entidad entregará anticipo al contratista."
        _aplicar({"anticipo_porcentaje": 30, "cita": "La Entidad entregará anticipo al contratista"},
                 _trozo("anticipo", texto), p)
        self.assertIsNone(p.anticipo)

    def test_el_anticipo_se_lee_cuando_el_porcentaje_esta_en_la_cita(self):
        p = ParametrosIA()
        texto = "8.3 ANTICIPO O PAGO ANTICIPADO\nLa Entidad entregará a título de anticipo un valor equivalente al 30% del valor básico del contrato."
        _aplicar({"anticipo_porcentaje": 30, "cita": "anticipo un valor equivalente al 30% del valor básico del contrato"},
                 _trozo("anticipo", texto), p)
        self.assertEqual(p.anticipo.valor, 0.3)

    def test_anticipo_cero_solo_si_el_pliego_lo_niega(self):
        """Un cero inventado infla el capital de trabajo y la capacidad
        residual exigidos: solo se acepta con la frase que lo niega."""
        texto_sin_negacion = "8.3 ANTICIPO\nLa forma de pago se define en la minuta del contrato, anexo 5."
        p = ParametrosIA()
        _aplicar({"anticipo_porcentaje": 0, "cita": "La forma de pago se define en la minuta del contrato"},
                 _trozo("anticipo", texto_sin_negacion), p)
        self.assertIsNone(p.anticipo)

        texto_con_negacion = "8.3 ANTICIPO\nEn el presente proceso no se entregará anticipo ni pago anticipado."
        q = ParametrosIA()
        _aplicar({"anticipo_porcentaje": 0, "cita": "no se entregará anticipo ni pago anticipado"},
                 _trozo("anticipo", texto_con_negacion), q)
        self.assertEqual(q.anticipo.valor, 0.0)

    def test_un_umbral_sin_comparador_se_descarta(self):
        """Caso real: el OCR de la fórmula del indicador dejó un "45" suelto y
        el modelo lo dio como liquidez mínima (el valor real era 1,1)."""
        texto = "3.6 CAPACIDAD FINANCIERA\nLiquidez Activo Corriente Pasivo Corriente 45"
        p = ParametrosIA()
        _aplicar({"liquidez_minima": 45, "cita_liquidez": "Liquidez Activo Corriente Pasivo Corriente 45"},
                 _trozo("financiera", texto), p)
        self.assertIsNone(p.liquidez_min)

    def test_un_umbral_con_comparador_se_lee(self):
        texto = "3.6 CAPACIDAD FINANCIERA\nÍndice de liquidez mayor o igual a 1.2 y endeudamiento menor o igual a 70%."
        p = ParametrosIA()
        _aplicar({"liquidez_minima": 1.2, "cita_liquidez": "liquidez mayor o igual a 1.2",
                  "endeudamiento_maximo": 70, "cita_endeudamiento": "endeudamiento menor o igual a 70%"},
                 _trozo("financiera", texto), p)
        self.assertEqual(p.liquidez_min.valor, 1.2)
        # El endeudamiento se escribe en porcentaje y queda como razón.
        self.assertAlmostEqual(p.endeudamiento_max.valor, 0.70)

    def test_un_no_aplica_de_al_lado_no_apaga_un_factor(self):
        """Caso real: "No aplica la regla de origen", en la sección de
        industria nacional, apagaba siete factores de puntaje."""
        texto = "4.3.1 PROMOCIÓN DE SERVICIOS NACIONALES\nNo aplica la regla de origen para este proceso."
        p = ParametrosIA()
        _aplicar({"factores": [{"factor": "plan_calidad", "no_aplica": True, "cita": "No aplica la regla de origen"},
                               {"factor": "industria_nacional", "no_aplica": True, "cita": "No aplica la regla de origen"}]},
                 _trozo("puntaje", texto), p)
        self.assertEqual(p.puntajes, {})

    def test_el_no_aplica_se_acepta_cuando_nombra_el_factor(self):
        texto = "4.2.3. PRESENTACIÓN DE UN PLAN DE CALIDAD N/A."
        p = ParametrosIA()
        _aplicar({"factores": [{"factor": "plan_calidad", "no_aplica": True,
                                "cita": "PRESENTACIÓN DE UN PLAN DE CALIDAD N/A."}]},
                 _trozo("puntaje", texto), p)
        self.assertEqual(p.puntajes["plan_calidad"].valor, 0.0)

    def test_un_numero_que_no_es_puntaje_se_descarta(self):
        """El "90 %" del personal colombiano no son los puntos del factor."""
        texto = ("4.3 APOYO A LA INDUSTRIA NACIONAL\nSe otorgará el puntaje a los proponentes que vinculen al menos el "
                 "noventa por ciento (90 %) del personal requerido.")
        p = ParametrosIA()
        _aplicar({"factores": [{"factor": "industria_nacional", "puntos": 90,
                                "cita": "industria nacional a los proponentes que vinculen al menos el noventa por ciento (90 %) del personal requerido"}]},
                 _trozo("puntaje", texto), p)
        self.assertEqual(p.puntajes, {})

    def test_una_cita_que_no_esta_en_el_pliego_se_descarta(self):
        p = ParametrosIA()
        _aplicar({"maximo_contratos": 5, "cita_maximo": "máximo cinco (5) contratos"},
                 _trozo("experiencia", "3.5 EXPERIENCIA\nEl proponente acreditará su experiencia con el RUP."), p)
        self.assertIsNone(p.max_contratos)

    def test_la_experiencia_general_debe_traer_actividades_de_obra(self):
        """Sin esto el modelo llenaba el campo con frases de trámite."""
        texto = ("3.5 EXPERIENCIA\nLa experiencia se acredita con la información consignada en el RUP para quienes "
                 "estén obligados a tenerlo y la presentación del Formato 3.")
        p = ParametrosIA()
        _aplicar({"experiencia_general": "la información consignada en el RUP para quienes estén obligados a tenerlo",
                  "cita_general": "la información consignada en el RUP para quienes estén obligados a tenerlo",
                  "lote": "ÚNICO"}, _trozo("experiencia", texto), p)
        self.assertEqual(p.experiencia_general, {})


class FusionTests(SimpleTestCase):
    def _tecnicos(self, **kwargs):
        from motor.tecnica.parametros import LoteTecnico, ParametrosTecnicos

        return ParametrosTecnicos(smmlv=1_750_905, lotes=[LoteTecnico("ÚNICO", 1e9, **kwargs)])

    def test_cuando_coinciden_queda_en_firme(self):
        parametros = self._tecnicos(experiencia_general="CONSTRUCCIÓN O MANTENIMIENTO DE EDIFICACIONES")
        ia = ParametrosIA(experiencia_general={"ÚNICO": Leido(valor="Construcción o mantenimiento de edificaciones", cita="c")})
        resultado = fusion.aplicar_a_tecnicos(parametros, ia)
        self.assertEqual(resultado.procedencias["experiencia general ÚNICO"].origen, "regla+ia")
        self.assertEqual(resultado.sin_confirmar, [])

    def test_lo_que_solo_vio_la_ia_queda_por_confirmar(self):
        parametros = self._tecnicos()
        ia = ParametrosIA(condicion_objeto={"ÚNICO": Leido(valor="DECLARADAS COMO BIENES DE INTERÉS CULTURAL", cita="c")})
        resultado = fusion.aplicar_a_tecnicos(parametros, ia)
        self.assertEqual(resultado.procedencias["condición de objeto ÚNICO"].origen, "ia")
        self.assertEqual(len(resultado.sin_confirmar), 1)
        # Se usa igual, para poder evaluar; lo que no se puede es aprobar solo.
        self.assertEqual(parametros.lotes[0].condicion_objeto, "DECLARADAS COMO BIENES DE INTERÉS CULTURAL")

    def test_si_discrepan_manda_la_regla_y_se_avisa(self):
        parametros = self._tecnicos(fraccion_un_contrato=0.7)
        ia = ParametrosIA(fraccion_un_contrato={"ÚNICO": Leido(valor=0.3, cita="c")})
        resultado = fusion.aplicar_a_tecnicos(parametros, ia)
        self.assertEqual(resultado.procedencias["porcentaje de un contrato ÚNICO"].origen, "conflicto")
        self.assertEqual(parametros.lotes[0].fraccion_un_contrato, 0.7)
        self.assertEqual(len(resultado.sin_confirmar), 1)

    def test_lo_que_confirma_una_persona_manda(self):
        parametros = self._tecnicos(fraccion_un_contrato=0.7)
        ia = ParametrosIA(fraccion_un_contrato={"ÚNICO": Leido(valor=0.3, cita="c")})
        resultado = fusion.aplicar_a_tecnicos(parametros, ia, {"porcentaje de un contrato ÚNICO": 0.5})
        self.assertEqual(parametros.lotes[0].fraccion_un_contrato, 0.5)
        self.assertEqual(resultado.sin_confirmar, [])

    def test_con_varios_lotes_no_se_usa_un_valor_sin_lote(self):
        """La IA devolvió "ÚNICO" en un proceso de dos lotes: aplicar el
        parámetro de uno al otro evalúa mal."""
        from motor.tecnica.parametros import LoteTecnico, ParametrosTecnicos

        parametros = ParametrosTecnicos(smmlv=1_750_905,
                                        lotes=[LoteTecnico("LOTE 1", 1e9), LoteTecnico("LOTE 2", 5e8)])
        ia = ParametrosIA(fraccion_un_contrato={"ÚNICO": Leido(valor=0.7, cita="c")})
        fusion.aplicar_a_tecnicos(parametros, ia)
        self.assertIsNone(parametros.lotes[0].fraccion_un_contrato)
        self.assertIsNone(parametros.lotes[1].fraccion_un_contrato)


class SinConfirmarNoApruebaTests(SimpleTestCase):
    def test_un_lote_con_parametros_sin_confirmar_va_a_revision(self):
        from datetime import date

        from evaluaciones.tests_tecnica import _fila, _parametros, _rup, _exp, Formato3
        from motor.tecnica.experiencia import IntegranteTecnico, evaluar_experiencia

        parametros = _parametros()
        integrante = IntegranteTecnico("VIAS ALFA S.A.S.", None, 1.0,
                                       _rup("VIAS ALFA S.A.S.", _exp("12", 3000), _exp("7", 3000)))
        formato3 = Formato3("f3", [_fila(1, "12", "ALFA"), _fila(2, "7", "GAMMA")])
        antes, _ = evaluar_experiencia(formato3, [integrante], parametros, date(2026, 8, 3), False)

        parametros.sin_confirmar = ["«anticipo» lo leyó la IA del pliego y nadie lo ha confirmado"]
        despues, _ = evaluar_experiencia(formato3, [integrante], parametros, date(2026, 8, 3), False)
        self.assertNotEqual(antes.cumple, despues.cumple)
        self.assertFalse(despues.cumple)
        self.assertTrue(any("falta confirmar" in m for m in despues.motivos))
