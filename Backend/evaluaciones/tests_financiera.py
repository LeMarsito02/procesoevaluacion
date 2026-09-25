"""Pruebas del motor de evaluación financiera (motor/financiera) con datos
inventados: ningún nombre, NIT ni cifra es real."""
from __future__ import annotations

from datetime import date
from unittest import mock

from django.test import SimpleTestCase, TestCase

from motor import criterios
from motor.esquemas.proceso import ProcesoDocumentoBase, Proponente
from motor.financiera import evaluador
from motor.financiera.capacidad import (
    Indicadores, Revision, capacidad_financiera, capacidad_organizacional, capital_de_trabajo,
)
from motor.financiera.contadores import leer_certificado_jcc
from motor.financiera.parametros import LoteFinanciero, ParametrosFinancieros, Umbrales, _plazos, umbrales_del_texto
from motor.financiera.proponente import ResultadoFinanciero
from motor.financiera.residual import _cifra, _del_integrante, _ingreso_operacional, _sce
from motor.tecnica.experiencia import IntegranteTecnico
from motor.tecnica.informe import PENDIENTE
from motor.tecnica.rup import leer_financiera, normalizar

UMBRALES = Umbrales(1.2, 0.70, 1.0, 0.01, 0.02, fuente="prueba")


def _ind(**cambios) -> Indicadores:
    base = dict(activo_corriente=2_000.0, activo_total=4_000.0, pasivo_corriente=1_000.0, pasivo_total=1_600.0,
                patrimonio=2_400.0, utilidad_operacional=400.0, gastos_intereses=100.0)
    return Indicadores(**{**base, **cambios})


class ParametrosFinancierosTests(SimpleTestCase):
    def test_capital_de_trabajo_y_capacidad_residual_del_lote(self):
        # Plazo menor a 12 meses: (POE − anticipo) × 33 %; K del proceso = POE − anticipo.
        lote = LoteFinanciero("LOTE 1", 1_000_000_000, plazo_meses=4, anticipo=0.20)
        self.assertAlmostEqual(lote.capital_de_trabajo_demandado, 264_000_000)
        self.assertAlmostEqual(lote.capacidad_residual_del_proceso, 800_000_000)
        # Plazo de 18 meses: (POE − anticipo) / plazo × 4 meses de apalancamiento; K = … / plazo × 12.
        largo = LoteFinanciero("LOTE 2", 1_800_000_000, plazo_meses=18, anticipo=0.0)
        self.assertAlmostEqual(largo.capital_de_trabajo_demandado, 400_000_000)
        self.assertAlmostEqual(largo.capacidad_residual_del_proceso, 1_200_000_000)

    def test_plazo_de_cada_lote_aunque_la_tabla_parta_el_texto(self):
        texto = normalizar(
            "1.1 OBJETO, PRESUPUESTO OFICIAL, PLAZO Y UBICACION\nLOTE 1 ... CUATRO (4) MILLONES\nDE PESOS MESES\n"
            "LOTE 2 ... SEIS (6) MESES\n1.2 SIGUIENTE"
        )
        self.assertEqual(_plazos(texto, 2), [4.0, 6.0])

    def test_umbrales_escritos_en_el_texto(self):
        u = umbrales_del_texto(normalizar(
            "INDICE DE LIQUIDEZ MAYOR O IGUAL A 1,2\nNIVEL DE ENDEUDAMIENTO MENOR O IGUAL A 0,70\n"
            "RAZON DE COBERTURA DE INTERESES >= 1\nRENTABILIDAD DEL ACTIVO >= 0,01\nRENTABILIDAD DEL PATRIMONIO >= 0,02"
        ), "pliego")
        self.assertTrue(u.completos)
        self.assertEqual((u.liquidez_min, u.endeudamiento_max, u.roe_min), (1.2, 0.70, 0.02))


class CapacidadTests(SimpleTestCase):
    def test_sin_pasivo_corriente_la_liquidez_se_cumple(self):
        r = capacidad_financiera(_ind(pasivo_corriente=0.0), UMBRALES, [])
        self.assertTrue(r.cumple)
        self.assertIn("indeterminado", r.motivos[0])

    def test_sin_gastos_de_intereses_depende_de_la_utilidad(self):
        self.assertTrue(capacidad_financiera(_ind(gastos_intereses=0.0), UMBRALES, []).cumple)
        self.assertFalse(capacidad_financiera(_ind(gastos_intereses=0.0, utilidad_operacional=-5.0), UMBRALES, []).cumple)

    def test_sin_umbrales_de_la_matriz_va_a_revision(self):
        r = capacidad_financiera(_ind(), Umbrales(), [])
        self.assertFalse(r.cumple)
        self.assertIn("Matriz 2", r.motivos[0])
        self.assertAlmostEqual(r.detalle["liquidez"], 2.0)

    def test_rentabilidades_y_capital_de_trabajo(self):
        self.assertTrue(capacidad_organizacional(_ind(), UMBRALES, []).cumple)
        self.assertFalse(capacidad_organizacional(_ind(utilidad_operacional=10.0), UMBRALES, []).cumple)
        lote = LoteFinanciero("LOTE 1", 3_000.0, plazo_meses=4, anticipo=0.2)  # exige 792
        self.assertTrue(capital_de_trabajo(_ind(), lote, []).cumple)
        self.assertFalse(capital_de_trabajo(_ind(activo_corriente=1_500.0), lote, []).cumple)

    def test_informacion_financiera_del_rup(self):
        info = leer_financiera(normalizar(
            "INFORMACIÓN FINANCIERA\nFECHA DE CORTE DE LA INFORMACIÓN FINANCIERA: 2025/12/31\n"
            "ACTIVO CORRIENTE : $ 1.500.000,00\nACTIVO TOTAL : $ 3.000.000,00\nPASIVO CORRIENTE : $ 500.000,00\n"
            "PASIVO TOTAL : $ 900.000,00\nPATRIMONIO : $ 2.100.000,00\nUTILIDAD OPERACIONAL : $ (20.000,00)\n"
            "GASTOS DE INTERESES : $ 0,00\n"
        ))
        self.assertEqual(info.fecha_corte, date(2025, 12, 31))
        self.assertEqual((info.activo_corriente, info.utilidad_operacional, info.gastos_intereses), (1_500_000, -20_000, 0))


class ResidualTests(SimpleTestCase):
    def test_ingreso_operacional_con_nota_y_formatos_de_miles(self):
        self.assertEqual(_ingreso_operacional("INGRESO DE ACTIVIDADES ORDINARIAS 13 16.017.439.164 9.856.675.085 6.160.764.079 62,50"),
                         16_017_439_164)
        # El pliego pide el año de mayor ingreso: el segundo año comparado puede ser mayor.
        self.assertEqual(_ingreso_operacional("INGRESOS OPERACIONALES 21 $ 9.845.278.808 $ 10.841.154.141"), 10_841_154_141)
        self.assertEqual(_ingreso_operacional("INGRESOS OPERACIONALES NOTA 13 $ 1 54,066,247,835 $ 140,026,856,388"),
                         154_066_247_835)
        self.assertEqual(_cifra("40,850,976,491.79"), 40_850_976_491.79)

    def test_ingreso_operacional_toma_la_fila_de_total(self):
        texto = ("INGRESOS DE ACTIVIDADES ORDINARIAS OBRAS CIVILES $ 4.325.793.361 $ 5.817.126.639 TRANSPORTE $ 383.190.277 "
                 "INGRESOS DE ACTIVIDADES ORDINARIAS NETOS 1 1 $ 3 2 . 7 6 0 . 9 7 9 . 3 4 8 $ 3 2 . 9 0 0.045.880 COSTO")
        self.assertEqual(_ingreso_operacional(texto), 32_900_045_880)
        self.assertEqual(_ingreso_operacional("INGRESOS POR OBRA 1 .239.212.894 VENTAS NETAS 1 .918.119.166 2 .511.355.015"),
                         2_511_355_015)

    def test_saldo_con_fila_de_total(self):
        texto = normalizar(
            "FORMATO NO. 5.3 - LISTADO DE LOS CONTRATOS EN EJECUCION VALOR TOTAL DEL CONTRATO "
            "001 DE 2025 $ 900.000.000,00 6,00 2/02/2026 50,00% $ 5.000.000,00 $ 150.000.000,00 NO "
            "TOTAL $ 150.000.000,00 EN CONSTANCIA DE LO ANTERIOR"
        )
        self.assertEqual(_sce(texto), (150_000_000, False))

    def test_saldo_sumando_las_filas_si_no_hay_total(self):
        texto = normalizar(
            "FORMATO NO. 5.3 - LISTADO DE LOS CONTRATOS EN EJECUCION "
            "A-1 $ 1.000.000.000,00 10,00 25/06/2025 10% $ 3 .333.333,33 $ 80.000.000,00 NO "
            "B-2 $ 2.000.000.000,00 12,00 21/07/2025 20% $ 5.555.555,56 $ 1 20.000.000,00 NO "
            "EN CONSTANCIA DE LO ANTERIOR FIRMO"
        )
        self.assertEqual(_sce(texto), (200_000_000, False))
        # Otra lectura del PDF saca primero el saldo.
        otro = normalizar(
            "FORMATO NO. 5.3 - LISTADO DE LOS CONTRATOS EN EJECUCION "
            "C-3 $ 70.000.000,00 NO $ 1.000.000.000,00 18 11/11/2025 10% $ 1.851.851,85 2025 "
        )
        self.assertEqual(_sce(otro), (70_000_000, False))
        # Sin "$", un número sin separadores de miles no es el saldo ("2025" es otra columna).
        con_ano = normalizar(
            "FORMATO NO. 5.3 - LISTADO DE LOS CONTRATOS EN EJECUCION "
            "D-4 $ 1.000.000.000,00 18 11/11/2025 10% 1.851.851,85 2025 NO EN CONSTANCIA"
        )
        with mock.patch("motor.financiera.residual.consultar_json", return_value=None):
            self.assertEqual(_sce(con_ano), (None, False))

    def test_listado_repetido_no_se_suma_dos_veces(self):
        texto = normalizar(
            "FORMATO NO. 5.3 - LISTADO DE LOS CONTRATOS EN EJECUCION OFERENTE: X "
            "A-1 $ 1.000.000.000,00 10,00 25/06/2025 10% $ 3.333.333,33 $ 80.000.000,00 NO EN CONSTANCIA"
        )
        self.assertEqual(_sce(texto + " " + texto), (80_000_000, False))

    def test_saldo_que_no_cuadra_con_el_contrato_no_se_acepta(self):
        # 900 millones de saldo en un contrato de 1.000 millones al 10 %: la fila está mal leída.
        texto = normalizar(
            "FORMATO NO. 5.3 - LISTADO DE LOS CONTRATOS EN EJECUCION "
            "A-1 $ 1.000.000.000,00 10,00 25/06/2025 10% $ 3.333.333,33 $ 900.000.000,00 NO EN CONSTANCIA"
        )
        with mock.patch("motor.financiera.residual.consultar_json", return_value=None):
            self.assertEqual(_sce(texto), (None, False))

    def test_sin_contratos_en_ejecucion(self):
        texto = normalizar("FORMATO 5C SALDO DE CONTRATOS EN EJECUCION: NO CUENTA CON CONTRATOS EN EJECUCION")
        self.assertEqual(_sce(texto), (0.0, False))

    def test_documento_de_cada_integrante(self):
        a = IntegranteTecnico("OBRAS FICTICIAS S.A.S.", "900111222-3", 0.5, None)
        b = IntegranteTecnico("PEDRO INVENTADO PEREZ", "7.123.456-1", 0.5, None)
        integrantes = [a, b]
        self.assertTrue(_del_integrante(b, "ESTADOS FINANCIEROS PEDRO INVENTADO NIT 7.123.456 - 1", integrantes))
        self.assertFalse(_del_integrante(a, "ESTADOS FINANCIEROS PEDRO INVENTADO NIT 7.123.456 - 1", integrantes))
        # Sin NIT: por el nombre, siempre que no nombre también al otro.
        self.assertTrue(_del_integrante(a, "INTEGRANTE: OBRAS  FICTICIAS SAS", integrantes))
        self.assertFalse(_del_integrante(a, "OBRAS FICTICIAS SAS Y PEDRO INVENTADO PEREZ", integrantes))
        # Palabras sueltas del nombre no bastan: tiene que estar seguido.
        self.assertFalse(_del_integrante(a, "OBRAS DE LA VIA; PERSONAS FICTICIAS", integrantes))

    def test_pagina_suelta_es_del_dueno_del_pdf(self):
        from motor.financiera.integrantes import estados_del_integrante

        a = IntegranteTecnico("OBRAS FICTICIAS S.A.S.", "900111222-3", 0.5, None)
        b = IntegranteTecnico("VIAS DE ENSAYO S.A.S.", "900333444-5", 0.5, None)
        estados = {"eeff b.pdf (pág. 1)": "ESTADO DE RESULTADOS INGRESOS ... OBRAS FICTICIAS (CLIENTE)"}
        completos = {"eeff b.pdf": "VIAS DE ENSAYO S.A.S. NIT 900.333.444-5 ESTADO DE RESULTADOS ..."}
        self.assertEqual(estados_del_integrante(a, estados, [a, b], completos), {})
        self.assertEqual(list(estados_del_integrante(b, estados, [a, b], completos)), ["eeff b.pdf (pág. 1)"])


class ContadoresTests(SimpleTestCase):
    def test_certificado_de_la_junta_central_de_contadores(self):
        c = leer_certificado_jcc("jcc.pdf", (
            "JUNTA CENTRAL DE CONTADORES\nCERTIFICA\nQue el CONTADOR PUBLICO MARIA FICTICIA RUIZ identificado con "
            "CÉDULA DE CIUDADANÍA No. 52111222 y TARJETA PROFESIONAL No. 123456-T no tiene antecedentes. "
            "Con vigencia de (3) meses. Dado en BOGOTA a los 10 días del mes de ABRIL de 2026"
        ))
        self.assertEqual((c.tarjeta, c.cedula, c.vigencia_meses), ("123456", "52111222", 3))
        self.assertEqual(c.expedicion, date(2026, 4, 10))
        self.assertTrue(c.vigente(date(2026, 7, 9)))
        self.assertFalse(c.vigente(date(2026, 8, 3)))


class EvaluadorFinancieroTests(SimpleTestCase):
    def _proceso(self) -> ProcesoDocumentoBase:
        parametros = ParametrosFinancieros(
            smmlv=1_000_000,
            lotes=[LoteFinanciero("LOTE 1", 1_000.0, 4, 0.2), LoteFinanciero("LOTE 2", 2_000.0, 4, 0.2)],
            umbrales=UMBRALES,
        )
        proceso = ProcesoDocumentoBase.model_construct(codigo_proceso="PRUEBA-1", fecha_cierre=date(2026, 8, 3))
        proceso.parametros_financieros = evaluador.parametros_a_dict(parametros)
        return proceso

    def _con(self, resultado: ResultadoFinanciero):
        return mock.patch("motor.financiera.evaluador.resultado_financiero", return_value=resultado)

    def test_parametros_ida_y_vuelta(self):
        proceso = self._proceso()
        p = evaluador.parametros_de_dict(proceso.parametros_financieros)
        self.assertEqual([l.nombre for l in p.lotes], ["LOTE 1", "LOTE 2"])
        self.assertTrue(p.umbrales.completos)

    def test_lote_al_que_no_se_presenta_y_lote_de_mayor_valor(self):
        proponente = Proponente.model_construct(hoja="P-01", numero_orden=1, nombre_proponente="CONSORCIO DE PRUEBA")
        residual = Revision(False, ["no alcanza"], {"lotes_cubiertos": ["LOTE 2"]})
        resultado = ResultadoFinanciero(lotes_presentados=["LOTE 1", "LOTE 2"], residual=residual)
        with self._con(resultado):
            k1 = evaluador.evaluar(proponente, self._proceso(), "residual", 221, 0)
            k2 = evaluador.evaluar(proponente, self._proceso(), "residual", 222, 1)
        self.assertFalse(k1.cumple)
        self.assertTrue(k2.cumple)
        self.assertIn("mayor valor", k2.motivo)
        solo_uno = ResultadoFinanciero(lotes_presentados=["LOTE 2"], residual=Revision(True, ["alcanza"]))
        with self._con(solo_uno):
            na = evaluador.evaluar(proponente, self._proceso(), "capital_trabajo", 211, 0)
        self.assertTrue(na.cumple)
        self.assertTrue(na.motivo.startswith("N.A."))

    def test_un_aviso_del_proponente_impide_aprobar(self):
        proponente = Proponente.model_construct(hoja="P-02", numero_orden=2, nombre_proponente="OBRAS FICTICIAS S.A.S.")
        resultado = ResultadoFinanciero(lotes_presentados=["LOTE 1"], financiera=Revision(True, ["liquidez 2,000"]),
                                        avisos=["no se identificaron los integrantes del Formato 2"])
        with self._con(resultado):
            r = evaluador.evaluar(proponente, self._proceso(), "indicadores", 201)
        self.assertFalse(r.cumple)
        self.assertTrue(r.motivo.startswith("no se identificaron"))

    def test_definicion_con_requisitos_por_lote(self):
        definicion = criterios.expandir_lotes(criterios.definicion_sistema("financiera"), ["LOTE 1", "LOTE 2"])
        numeros = [r.numero for r in definicion.requisitos]
        self.assertEqual(numeros, [201, 202, 203, 204, 211, 212, 221, 222])


class InformeFinancieroTests(SimpleTestCase):
    def test_resumen_por_lote(self):
        import io

        import openpyxl

        from motor.esquemas.proceso import ResultadoRequisito
        from motor.financiera.informe import generar_informe
        from motor.tecnica.informe import ResultadoInforme

        def r(hoja, numero, cumple, decidido=False, detalle=None):
            return ResultadoInforme(ResultadoRequisito(hoja=hoja, numero_orden=1, nombre_proponente="X", requisito=numero,
                                                       cumple=cumple, detalle=detalle), decidido)

        na = {"financiera": {"no_aplica": True}}
        resultados = {}
        for hoja in ("P-01", "P-02"):
            for n in (201, 202, 203, 204, 211, 221):
                resultados[(hoja, n)] = r(hoja, n, True)
        resultados[("P-01", 212)] = r("P-01", 212, True)
        resultados[("P-01", 222)] = r("P-01", 222, False)  # sin decidir: pendiente
        resultados[("P-02", 212)] = r("P-02", 212, True, detalle=na)
        resultados[("P-02", 222)] = r("P-02", 222, True, detalle=na)
        contenido = generar_informe("PRUEBA-1", "Objeto", [(0, "LOTE 1"), (1, "LOTE 2")],
                                    [("P-01", "UNO"), ("P-02", "DOS")], resultados, [201, 202, 203, 204],
                                    {0: [211, 221], 1: [212, 222]}, borrador=True)
        hoja = openpyxl.load_workbook(io.BytesIO(contenido))["Resumen"]
        self.assertEqual([c.value for c in hoja[5]], ["P-01", "UNO", "CUMPLE", PENDIENTE])
        self.assertEqual([c.value for c in hoja[6]], ["P-02", "DOS", "CUMPLE", "N/A"])


class SceNotasTests(SimpleTestCase):
    def test_una_mencion_en_las_notas_no_es_un_listado_vacio(self):
        texto = normalizar(
            "NOTA 6: CUANDO UN CONTRATO HA SIDO FIRMADO SIN ACTA DE INICIO, DEBE INCLUIRSE EN EL FORMATO 5C CON EL VALOR TOTAL "
            "DEL CONTRATO. NOTA 8: LA ENTIDAD SOLICITARA SUBSANAR EL FORMATO 5C CUANDO PRESENTE SALDO NEGATIVO."
        )
        with mock.patch("motor.financiera.residual.consultar_json", return_value=None):
            self.assertEqual(_sce(texto), (None, False))

    def test_total_del_listado_con_otras_etiquetas(self):
        texto = normalizar(
            "FORMATO 5C SALDO DE CONTRATOS EN EJECUCION PROPONENTE: X 1 $ 1.000.000.000,00 6,00 6,00 6/04/26 90% "
            "119,00 61,00 $ 5.000.000,00 $ 300.000.000,00 NO N/A VALOR TOTAL CONTRATOS EN EJECUCION (EN PESOS "
            "COLOMBIANOS) $ 300.000.000,00"
        )
        self.assertEqual(_sce(texto), (300_000_000, False))


class HolguraTests(SimpleTestCase):
    def test_la_capacidad_residual_necesita_holgura(self):
        from motor.financiera.residual import HOLGURA, decidir_residual

        l1 = LoteFinanciero("LOTE 1", 1_000.0, 4, 0.2)  # K exigida 800
        l2 = LoteFinanciero("LOTE 2", 2_000.0, 4, 0.2)  # K exigida 1.600
        exigida = 2_400.0
        holgado = decidir_residual(exigida * HOLGURA, exigida, [l1, l2], "", {})
        self.assertTrue(holgado.cumple)
        self.assertEqual(holgado.detalle["lotes_cubiertos"], ["LOTE 1", "LOTE 2"])
        # Alcanza, pero por poco: a revisión, y con la holgura solo cubre el lote 2.
        justo = decidir_residual(exigida * 1.05, exigida, [l1, l2], "", {})
        self.assertFalse(justo.cumple)
        self.assertEqual(justo.detalle["lotes_cubiertos"], ["LOTE 2"])
        self.assertIn("margen", justo.motivos[0])
        nada = decidir_residual(1_000.0, exigida, [l1, l2], "", {})
        self.assertEqual(nada.detalle["lotes_cubiertos"], [])


class UmbralesPlataformaTests(TestCase):
    def test_registrar_umbrales_de_la_matriz(self):
        from cuentas.models import Usuario
        from evaluaciones import servicios

        usuario = Usuario(email="financiero@ficticia.gov.co", nombre_completo="Ana Ficticia")
        proceso = mock.Mock(pk=1, parametros_financieros={"smmlv": 1_000_000, "lotes": [], "umbrales": {}})
        with mock.patch.object(type(proceso), "objects", create=True):
            datos = servicios.registrar_umbrales_financieros(
                proceso, {"liquidez_min": 1.2, "endeudamiento_max": 0.7, "cobertura_min": 1, "roa_min": 0.01, "roe_min": 0.02},
                usuario,
            )
        self.assertEqual(datos["umbrales"]["liquidez_min"], 1.2)
        self.assertIn("Ana Ficticia", datos["umbrales"]["fuente"])
        with self.assertRaises(ValueError):
            servicios.registrar_umbrales_financieros(proceso, {"liquidez_min": 1.2}, usuario)


class SceNotasDelFormatoTests(SimpleTestCase):
    def test_las_notas_no_anulan_el_listado_bueno(self):
        texto = normalizar(
            "FORMATO 5C SALDO CONTRATOS EN EJECUCION (SCE) PROPONENTE O INTEGRANTE: OBRAS FICTICIAS SAS "
            "1 $ 1.000.000.000,00 6,00 6/04/2026 90% $ 5.000.000,00 $ 300.000.000,00 NO TOTAL $ 300.000.000,00 "
            "NOTA 8: EN TODO CASO LA ENTIDAD SOLICITARA SUBSANAR EL FORMATO FORMATO 5C, CUANDO ESTE EN ALGUNO DE SUS "
            "CONTRATOS PRESENTE SALDO NEGATIVO. NOTA 7: UNA VEZ LA ENTIDAD VERIFIQUE EL FORMATO SALDO CONTRATOS EN "
            "EJECUCION Y SE ENCUENTREN ERRORES ARITMETICOS"
        )
        self.assertEqual(_sce(texto), (300_000_000, False))


class TarjetaParecidaTests(SimpleTestCase):
    def test_tarjeta_mal_leida_solo_con_el_nombre_en_los_estados(self):
        from motor.financiera.contadores import CertificadoJCC, _parecidas, _por_tarjeta_parecida

        self.assertTrue(_parecidas("209794", "209791"))
        self.assertTrue(_parecidas("106849", "106489"))
        self.assertFalse(_parecidas("106849", "106999"))
        cert = CertificadoJCC("jcc.pdf", "209791", nombre="MARIA FICTICIA RUIZ")
        self.assertEqual(_por_tarjeta_parecida("209794", [cert], "FIRMA MARIA FICTICIA RUIZ CONTADORA T.P. 209794-T"), [cert])
        self.assertEqual(_por_tarjeta_parecida("209794", [cert], "FIRMA PEDRO INVENTADO T.P. 209794-T"), [])


class TitularDelListadoTests(SimpleTestCase):
    def test_el_formato_dice_de_quien_es(self):
        from motor.financiera.integrantes import integrante_del_titular, titulares_del_documento

        socafer = IntegranteTecnico("SOCAFER SAS", None, 0.3, None)
        emaus = IntegranteTecnico("M&D EMAUS CONSTRUCCIONES S.A.S", None, 0.7, None)
        texto = "FORMATO 5C SALDO CONTRATOS EN EJECUCION (SCE) PROPONENTE O INTEGRANTE: M&D EMAUS SAS FECHA: 3/08/2026"
        self.assertEqual(titulares_del_documento(texto), ["M&D EMAUS SAS"])
        self.assertIs(integrante_del_titular(titulares_del_documento(texto), [socafer, emaus]), emaus)
        # El texto de las notas no es un rótulo.
        nota = "NOTA 2: EL FORMULARIO DEBE SER DILIGENCIADO POR EL PROPONENTE O POR CADA UNO DE LOS INTEGRANTES"
        self.assertEqual(titulares_del_documento(nota), [])
        # Dos integrantes con el mismo parecido: nadie gana, se decide por otra vía.
        a = IntegranteTecnico("VIAS DEL SUR S.A.S", None, 0.5, None)
        b = IntegranteTecnico("VIAS DEL NORTE S.A.S", None, 0.5, None)
        self.assertIsNone(integrante_del_titular(["VIAS DEL"], [a, b]))


class UmbralesYAnticipoTests(SimpleTestCase):
    def test_umbral_en_porcentaje_y_con_simbolos(self):
        from motor.financiera.parametros import _texto_con_simbolos

        u = umbrales_del_texto(normalizar(_texto_con_simbolos(
            "INDICE DE LIQUIDEZ ≥ 1,2 NIVEL DE ENDEUDAMIENTO MENOR O IGUAL A 70 % "
            "RAZON DE COBERTURA DE INTERESES >= 1 RENTABILIDAD DEL ACTIVO MAYOR O IGUAL A 3% "
            "RENTABILIDAD DEL PATRIMONIO >= 0,02"
        )), "pliego")
        # Siempre en razón, nunca en porcentaje: si no, un endeudado pasaría.
        self.assertEqual((u.liquidez_min, u.endeudamiento_max, u.cobertura_min, u.roa_min, u.roe_min),
                         (1.2, 0.70, 1.0, 0.03, 0.02))

    def test_un_no_aplica_suelto_no_borra_el_anticipo(self):
        from motor.financiera.parametros import _anticipo

        con_anticipo = normalizar(
            "8.3 ANTICIPO Y/O PAGO ANTICIPADO LA ENTIDAD ENTREGARA A TITULO DE ANTICIPO EL VEINTE POR CIENTO (20 %) "
            "DEL VALOR DEL CONTRATO. PAGO ANTICIPADO: NO APLICA"
        )
        self.assertAlmostEqual(_anticipo(con_anticipo), 0.20)
        sin_anticipo = normalizar("8.3 ANTICIPO Y/O PAGO ANTICIPADO NO SE ENTREGARA ANTICIPO EN ESTE PROCESO (0 %)")
        self.assertEqual(_anticipo(sin_anticipo), 0.0)

    def test_lote_sin_numero_en_el_nombre_no_rompe_la_evaluacion(self):
        from motor.financiera.proponente import evaluar_proponente_financiero

        parametros = ParametrosFinancieros(
            smmlv=1_000_000,
            lotes=[LoteFinanciero("GRUPO NORTE", 1_000.0, 4, 0.2), LoteFinanciero("LOTE 2", 2_000.0, 4, 0.2)],
            umbrales=UMBRALES,
        )
        with mock.patch("motor.financiera.proponente.leer_rups", return_value=[]), \
                mock.patch("motor.financiera.proponente.integrantes_formato2", return_value=[]), \
                mock.patch("motor.financiera.proponente.integrantes_del_proponente", return_value=([], [])), \
                mock.patch("motor.financiera.proponente.lotes_de_la_oferta", return_value=({"2"}, [])), \
                mock.patch("motor.financiera.proponente.documentos_financieros") as docs, \
                mock.patch("motor.financiera.proponente.residual_del_proponente", return_value=Revision(False, [])):
            docs.return_value.estados = {}
            docs.return_value.completos = {}
            resultado = evaluar_proponente_financiero({}, {}, "CONSORCIO DE PRUEBA", parametros, date(2026, 8, 3), "PRUEBA-1")
        self.assertEqual(resultado.lotes_presentados, ["LOTE 2"])


class InformeNoAplicaTests(SimpleTestCase):
    def test_un_requisito_general_que_no_aplica_no_tapa_el_no_cumple(self):
        import io

        import openpyxl

        from motor.esquemas.proceso import ResultadoRequisito
        from motor.financiera.informe import generar_informe
        from motor.tecnica.informe import ResultadoInforme

        def r(numero, cumple, decidido=False, no_aplica=False):
            detalle = {"financiera": {"no_aplica": True}} if no_aplica else None
            return ResultadoInforme(
                ResultadoRequisito(hoja="P-01", numero_orden=1, nombre_proponente="X", requisito=numero,
                                   cumple=cumple, detalle=detalle),
                decidido,
            )

        resultados = {
            ("P-01", 201): r(201, True), ("P-01", 202): r(202, True), ("P-01", 203): r(203, True),
            ("P-01", 204): r(204, True, no_aplica=True),   # patrimonio: casi siempre no aplica
            ("P-01", 211): r(211, True), ("P-01", 221): r(221, False, decidido=True),  # K: no cumple
        }
        contenido = generar_informe("PRUEBA-1", "Objeto", [(0, "LOTE 1")], [("P-01", "UNO")], resultados,
                                    [201, 202, 203, 204], {0: [211, 221]}, borrador=True)
        hoja = openpyxl.load_workbook(io.BytesIO(contenido))["Resumen"]
        self.assertEqual([c.value for c in hoja[5]], ["P-01", "UNO", "NO CUMPLE"])


class SceSinListaDeFrasesTests(SimpleTestCase):
    """El saldo de contratos en ejecución no puede depender de una lista de
    redacciones: cada proponente lo escribe como quiere. Las reglas intentan
    primero y el modelo local cubre el resto, pero un cero solo se acepta si
    la frase que lo dice está en el formato."""

    def test_una_negacion_junto_a_contratos_vale_aunque_no_este_en_la_lista(self):
        from motor.financiera.residual import _niega_los_contratos

        tramo = ("FORMATO 5.3 LISTADO DE LOS CONTRATOS EN EJECUCION OFERENTE: X "
                 "A la fecha no se relacionan contratos de obra en ejecución.")
        self.assertTrue(_niega_los_contratos("no se relacionan contratos de obra en ejecución", tramo))
        self.assertTrue(_niega_los_contratos("NO SE RELACIONAN CONTRATOS DE OBRA EN EJECUCIÓN", tramo))

    def test_una_cita_que_no_esta_en_el_formato_no_vale(self):
        from motor.financiera.residual import _niega_los_contratos

        tramo = "FORMATO 5.3 LISTADO DE LOS CONTRATOS EN EJECUCION OFERENTE: X CONTRATO 1 $500.000.000"
        self.assertFalse(_niega_los_contratos("no tiene contratos en ejecución", tramo))

    def test_una_frase_sin_negacion_no_vale(self):
        from motor.financiera.residual import _niega_los_contratos

        tramo = "LISTADO DE LOS CONTRATOS EN EJECUCION del proponente para el presente proceso"
        self.assertFalse(_niega_los_contratos("LISTADO DE LOS CONTRATOS EN EJECUCION", tramo))

    def test_el_saldo_entre_parentesis_se_lee(self):
        """Un proponente lo escribió así: "$ (346.767.713)"."""
        from motor.financiera.residual import _sce

        texto = ("LISTADO DE LOS CONTRATOS EN EJECUCION OFERENTE: X VALOR DEL CONTRATO SALDO "
                 "SALDO DE CONTRATOS EN EJECUCION $ (346.767.713) EN CONSTANCIA")
        self.assertEqual(_sce(texto), (346_767_713.0, False))


class Matriz2Tests(SimpleTestCase):
    """Los umbrales de los indicadores no están en el pliego: están en la
    Matriz 2, un anexo que llega en Word, Excel o PDF. Sin ella la evaluación
    financiera entera queda en revisión."""

    def test_se_lee_el_texto_de_un_word(self):
        import io
        import zipfile

        from motor.procesamiento.documentos import texto_de_documento

        memoria = io.BytesIO()
        with zipfile.ZipFile(memoria, "w") as z:
            z.writestr("word/document.xml",
                       "<w:document><w:body><w:p><w:t>ÍNDICE DE LIQUIDEZ</w:t></w:p>"
                       "<w:p><w:t>&gt;= 1,2</w:t></w:p></w:body></w:document>")
        texto = texto_de_documento(memoria.getvalue())
        self.assertIn("LIQUIDEZ", texto)
        self.assertIn("1,2", texto)

    def test_varios_rangos_no_se_adivinan_sino_que_se_ofrecen(self):
        """La matriz trae una columna por rango de presupuesto y otra tabla
        para MIPYME: cuál aplica es decisión del proceso. Adivinar sería peor
        de las dos maneras (aprobar a quien no cumple o rechazar a quien sí),
        así que el umbral queda sin fijar y se ofrecen las opciones."""
        from motor.financiera.parametros import umbrales_de_la_matriz

        texto = ("INDICADOR VALOR CONCERTADO RANGO 1 VALOR CONCERTADO RANGO 2\n"
                 "INDICE DE LIQUIDEZ\n >=1,1\n >=1,2\n"
                 "INDICE DE ENDEUDAMIENTO\n <= 0,65\n <= 0,70\n")
        umbrales, opciones = umbrales_de_la_matriz(texto)
        self.assertIsNone(umbrales.liquidez_min)
        self.assertEqual(opciones["liquidez_min"], [1.1, 1.2])
        self.assertEqual(opciones["endeudamiento_max"], [0.65, 0.70])

    def test_si_todos_los_rangos_coinciden_el_umbral_queda_en_firme(self):
        from motor.financiera.parametros import umbrales_de_la_matriz

        texto = "RENTABILIDAD DEL ACTIVO\n >= 0,01\n >= 0,01\n"
        umbrales, opciones = umbrales_de_la_matriz(texto)
        self.assertEqual(umbrales.roa_min, 0.01)
        self.assertNotIn("roa_min", opciones)

    def test_el_valor_en_el_renglon_siguiente_se_lee(self):
        """En la matriz el valor no va al lado del indicador sino debajo."""
        from motor.financiera.parametros import umbrales_de_la_matriz

        umbrales, _ = umbrales_de_la_matriz("INDICE DE LIQUIDEZ\n\n >=1,3\n")
        self.assertEqual(umbrales.liquidez_min, 1.3)


class CifrasImposiblesTests(SimpleTestCase):
    """Cifras que no pueden ser: salen de una lectura mala y, si se usan, dan
    resultados excelentes con datos inventados."""

    def _umbrales(self):
        from motor.financiera.parametros import Umbrales

        return Umbrales(1.1, 0.7, 1.0, 0.01, 0.02, fuente="Matriz 2")

    def test_un_rup_con_activos_negativos_no_aprueba(self):
        """Con activo y pasivo negativos la liquidez sale 2,0 (dos negativos
        dan positivo) y el proponente quedaba aprobado."""
        from motor.financiera.capacidad import Indicadores, capacidad_financiera, capacidad_organizacional

        ind = Indicadores(-100, -200, -50, -60, -140, -30, -5)
        self.assertFalse(ind.creibles)
        self.assertEqual(ind.liquidez, 2.0)  # el número sale, pero no vale
        self.assertFalse(capacidad_financiera(ind, self._umbrales(), []).cumple)
        self.assertFalse(capacidad_organizacional(ind, self._umbrales(), []).cumple)

    def test_un_patrimonio_negativo_si_es_posible(self):
        """Una empresa puede tener patrimonio negativo y utilidad negativa:
        eso no es un error de lectura, es su situación."""
        from motor.financiera.capacidad import Indicadores

        self.assertTrue(Indicadores(5000, 8000, 1000, 9000, -1000, -500, 30).creibles)

    def test_un_plazo_o_un_anticipo_imposibles_no_calculan_capital(self):
        from motor.financiera.parametros import LoteFinanciero

        # El bueno: el mismo número que exigió el ICCU en LP-027.
        bueno = LoteFinanciero("ÚNICO", 5_458_954_545, plazo_meses=12, anticipo=0.25)
        self.assertAlmostEqual(bueno.capital_de_trabajo_demandado, 1_364_738_636.25, places=2)

        for plazo, anticipo in ((-5, 0.2), (0.0, 0.2), (500, 0.2), (8, 1.0), (8, -0.5)):
            lote = LoteFinanciero("ÚNICO", 1e9, plazo_meses=plazo or None, anticipo=anticipo)
            self.assertIsNone(lote.capital_de_trabajo_demandado, f"plazo={plazo} anticipo={anticipo}")

    def test_un_presupuesto_en_cero_no_calcula_capital(self):
        from motor.financiera.parametros import LoteFinanciero

        self.assertIsNone(LoteFinanciero("ÚNICO", 0, plazo_meses=8, anticipo=0.2).capital_de_trabajo_demandado)


class RevisionDirigidaFinancieraTests(SimpleTestCase):
    """Lo mismo que en técnica: lo que falta del pliego no desacredita lo que la
    oferta sí demostró, pero tampoco la aprueba."""

    def _resultado(self, avisos_de_la_oferta=(), avisos_del_pliego=()):
        from motor.financiera.proponente import ResultadoFinanciero, capacidad_acreditada
        from motor.tecnica.experiencia import PuntoDeRevision

        r = ResultadoFinanciero()
        r.lotes_presentados = ["LOTE 1"]
        r.financiera = Revision(True, [])
        r.organizacional = Revision(True, [])
        r.validez = Revision(True, [])
        r.capital_por_lote = {"LOTE 1": Revision(True, [])}
        r.residual = Revision(True, [])
        r.avisos = [*avisos_de_la_oferta, *avisos_del_pliego]
        r.revisiones = [
            *(PuntoDeRevision(f"o{i}", "oferta", a) for i, a in enumerate(avisos_de_la_oferta)),
            *(PuntoDeRevision(f"p{i}", "proceso", a) for i, a in enumerate(avisos_del_pliego)),
        ]
        return r, capacidad_acreditada

    def test_sin_pendientes_cumple_y_queda_acreditada(self):
        from motor.financiera.proponente import cumple_lote

        r, acreditada = self._resultado()
        self.assertTrue(cumple_lote(r, "LOTE 1"))
        self.assertTrue(acreditada(r, "LOTE 1"))

    def test_lo_que_falta_del_pliego_no_desacredita_la_capacidad(self):
        from motor.financiera.proponente import cumple_lote

        r, acreditada = self._resultado(avisos_del_pliego=["falta confirmar el anticipo leído con IA"])
        self.assertFalse(cumple_lote(r, "LOTE 1"))  # sigue sin aprobarse solo
        self.assertTrue(acreditada(r, "LOTE 1"))

    def test_un_aviso_de_la_oferta_si_deja_la_capacidad_sin_acreditar(self):
        from motor.financiera.proponente import cumple_lote

        r, acreditada = self._resultado(avisos_de_la_oferta=["no se encontró el RUP de BETA S.A.S."])
        self.assertFalse(cumple_lote(r, "LOTE 1"))
        self.assertFalse(acreditada(r, "LOTE 1"))

    def test_una_verificacion_que_no_pasa_no_se_acredita_por_mas_que_falte_el_pliego(self):
        r, acreditada = self._resultado(avisos_del_pliego=["falta confirmar el anticipo"])
        r.financiera = Revision(False, ["liquidez 0,8: el pliego exige 1,2"])
        self.assertFalse(acreditada(r, "LOTE 1"))


class LotesALosQueSePresentaTests(SimpleTestCase):
    """Un lote que no se identifica se marca «N.A. — no se presenta» y se da por
    cumplido sin mirar nada. Así que no puede depender de una sola lectura: se
    toma la unión de la carta de presentación y la garantía de seriedad, y si
    discrepan se dice."""

    def test_se_usa_la_union_de_la_carta_y_la_poliza(self):
        from unittest import mock

        from motor.financiera.capacidad import lotes_de_la_oferta

        with mock.patch("motor.financiera.capacidad._lotes_de_la_carta", return_value={"1"}), \
             mock.patch("motor.financiera.capacidad._lotes_de_la_poliza", return_value={"2"}):
            elegidos, avisos = lotes_de_la_oferta({}, ["1", "2", "3"])
        self.assertEqual(elegidos, {"1", "2"})
        self.assertTrue(avisos and "confirma a cuáles se presenta" in avisos[0])

    def test_sin_ninguna_fuente_se_evaluan_todos(self):
        from unittest import mock

        from motor.financiera.capacidad import lotes_de_la_oferta

        with mock.patch("motor.financiera.capacidad._lotes_de_la_carta", return_value=set()), \
             mock.patch("motor.financiera.capacidad._lotes_de_la_poliza", return_value=set()):
            elegidos, avisos = lotes_de_la_oferta({}, ["1", "2"])
        self.assertIsNone(elegidos)  # None = se evalúan todos
        self.assertEqual(avisos, [])

    def test_cuando_las_dos_fuentes_coinciden_no_hay_aviso(self):
        from unittest import mock

        from motor.financiera.capacidad import lotes_de_la_oferta

        with mock.patch("motor.financiera.capacidad._lotes_de_la_carta", return_value={"2"}), \
             mock.patch("motor.financiera.capacidad._lotes_de_la_poliza", return_value={"2"}):
            elegidos, avisos = lotes_de_la_oferta({}, ["1", "2"])
        self.assertEqual((elegidos, avisos), ({"2"}, []))
