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
