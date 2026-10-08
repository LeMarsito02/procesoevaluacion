"""Pruebas del motor de prestación de servicios (motor/ops) con datos
inventados: ninguna persona, entidad ni contrato es real."""
from __future__ import annotations

from datetime import date
from unittest import mock

from django.test import SimpleTestCase

from motor.ops import documentos
from motor.ops.certificaciones import leer_periodos
from motor.ops.estudio_previo import leer_estudio_previo, problema_con_el_cdp, valor_del_cdp
from motor.ops.hoja_de_vida import estudios_declarados
from motor.ops.matricula import leer_matricula
from motor.ops.experiencia import Periodo, ajustar_a_franja, poner_en_linea
from motor.ops.honorarios import ESPECIALIZACION, MAESTRIA, SIN_POSGRADO, FranjaProfesional, FranjaReconocimiento, TablaHonorarios
from motor.ops.identidad import libreta_exigible
from motor.ops.idoneidad import Perfil, Reglas, evaluar_idoneidad
from motor.ops.relacion import obligaciones_especificas, obligaciones_iguales
from motor.ops.tiempo import dias_comerciales, fechas_en, texto_duracion
from motor.ops.titulos import BACHILLER, PROFESIONAL, Titulo, fecha_de_grado, leer_titulos

CONTRACTUAL = """EL SUBDIRECTOR DE CONTRATACIÓN DEL
INSTITUTO DE OBRAS DE VILLA FICTICIA
CERTIFICA
Que ANA INVENTADA PÉREZ suscribió el contrato con las siguientes características:
No. CONTRATO: IOVF-045-2024
OBJETO: "PRESTACIÓN DE SERVICIOS PROFESIONALES A LA OFICINA DE PLANEACIÓN".
FECHA DE INICIO: 01 DE FEBRERO DE 2024
PLAZO DE EJECUCION INICIAL: OCHO (08) MESES
FECHA DE TERMINACIÓN INICIAL: 30 DE SEPTIEMBRE DE 2024
SUSPENSION NO 1: 21 DE JUNIO AL 05 DE JULIO DE 2024
FECHA DE TERMINACION FINAL: 30 DE NOVIEMBRE DE 2024
OBLIGACIONES ESPECIFICAS
1. Apoyar a la Oficina de Planeación en el seguimiento a los indicadores de gestión y la
elaboración de los informes requeridos por la Dirección.
2. Asistir a las reuniones del comité de archivo de la entidad cuando sea citada.
Se expide a solicitud de la contratista, a los diez (10) días del mes de diciembre de 2024.
"""

LABORAL = """LA DIRECTORA DE TALENTO HUMANO
DEPARTAMENTO DE VALLE INVENTADO
C E R T I F I C A:
Que revisada la historia laboral de ANA INVENTADA PÉREZ, se estableció que estuvo vinculada
desde el 14 de febrero de 2012 hasta
el 31 de diciembre de 2019, del el 03 de febrero de 2020 hasta el 30 de junio de 2021.
Nombrada mediante Resolución número 0307 del 02 de febrero de 2012.
La presente certificación se expide el 16 de abril de 2022.
"""

EN_EJECUCION = """CORPORACIÓN REGIONAL DE RÍO INVENTADO
CERTIFICA
CONTRATO DE PRESTACIÓN DE SERVICIOS 26 DE 2009.
PLAZO:
Doce (12) meses.
FECHA DE INICIO:
12 de Febrero de 2009.
Este contrato se encuentra en ejecución al expedir esta certificación.
Elaboró B. Ortiz
Fecha: Septiembre 10 de 2009.
"""

TERMINADO = """CORPORACIÓN REGIONAL DE RÍO INVENTADO
CERTIFICA
CONTRATO DE PRESTACIÓN DE SERVICIOS 026 DE 2009.
FECHA DE INICIO:
12 de Febrero de 2009
PRORROGA:
Seis (6) meses a partir del 12 de Febrero de 2010
FECHA DE TERMINACIÓN:
11 de Agosto de 2010
"""

ACTA_PREGRADO = """UNIVERSIDAD DE VILLA FICTICIA
COPIA ACTA DE GRADO No. 100
En la ciudad de Villa Ficticia, el día 11 de JUNIO de 2004, se llevó a cabo el acto de
graduación, autorizado según Acuerdo 006 del día 12 del mes de agosto de 1999, y se
confirió el título de
ECONOMISTA
A ANA INVENTADA PÉREZ
"""

ACTA_POSGRADO = """LA SECRETARIA GENERAL CERTIFICA:
ACTA N° 051. A los veinticinco (25) días del mes de Mayo del año dos mil once (2011) se
celebró la ceremonia de graduación de ANA INVENTADA PÉREZ, a quien se entregó el diploma
que la acredita como ESPECIALISTA EN GESTIÓN DE PROYECTOS
PARA EL DESARROLLO
"""

ESTUDIO_PREVIO = """OBLIGACIONES GENERALES:
1. Cumplir a cabalidad con el objeto del contrato de conformidad con la propuesta presentada.
OBLIGACIONES ESPECÍFICAS:
1. Apoyar a la Oficina de Planeación en el seguimiento a los indicadores de gestión y la
FORMATO CÓDIGO MS-00
ESTUDIOS PREVIOS FECHA 03/03/2025
Página 7 de 13
elaboración de los informes requeridos por la Dirección General.
2. Asesorar en la elaboración de los informes estadísticos del anuario departamental y de
los datos abiertos de la entidad.
OBLIGACIONES DEL INSTITUTO:
a. Pagar los montos establecidos dentro de los plazos señalados en el contrato.
"""

TABLA = TablaHonorarios(
    vigencia=2026,
    norma="Resolución inventada 1 de 2025",
    profesional=[
        FranjaProfesional(0, 5, 5_000_000, 6_000_000, 7_000_000),
        FranjaProfesional(5, 10, 7_000_000, 8_000_000, 9_000_000),
        FranjaProfesional(10, 15, 9_000_000, 10_000_000, 11_000_000),
        FranjaProfesional(15, None, 11_000_000, 12_000_000, 13_000_000),
    ],
    reconocimiento=[FranjaReconocimiento(1, 5, 1_500_000), FranjaReconocimiento(5, None, 3_000_000)],
)


class TiempoComercialTests(SimpleTestCase):
    def test_meses_de_treinta_dias_y_anio_de_trescientos_sesenta(self):
        self.assertEqual(dias_comerciales(date(2024, 1, 1), date(2024, 1, 31)), 30)
        self.assertEqual(dias_comerciales(date(2023, 2, 1), date(2023, 2, 28)), 30)
        self.assertEqual(dias_comerciales(date(2023, 1, 1), date(2023, 12, 31)), 360)
        self.assertEqual(dias_comerciales(date(2024, 7, 23), date(2024, 12, 22)), 150)
        self.assertEqual(dias_comerciales(date(2024, 3, 10), date(2024, 3, 10)), 1)

    def test_sin_contar_el_ultimo_dia_y_fechas_al_reves(self):
        self.assertEqual(dias_comerciales(date(2024, 1, 1), date(2024, 1, 30), ambos_extremos=False), 29)
        self.assertEqual(dias_comerciales(date(2024, 5, 1), date(2024, 4, 1)), 0)

    def test_la_duracion_se_escribe_sin_lo_que_vale_cero(self):
        self.assertEqual(texto_duracion(5764), "16 años y 4 días")
        self.assertEqual(texto_duracion(360 + 30 + 1), "1 año, 1 mes y 1 día")
        self.assertEqual(texto_duracion(180), "6 meses")
        self.assertEqual(texto_duracion(0), "0 días")

    def test_lee_las_formas_en_que_se_escriben_las_fechas(self):
        texto = "DEL 14/02/2012 · 20 DE FEBRERO DE 2025 · FEBRERO 2 DE 2009 · A LOS DIECISEIS (16) DIAS DEL MES DE DICIEMBRE DE 2025 · 31/02/2020 · 18/JUL/2024"
        self.assertEqual(
            [f for _, f in fechas_en(texto)],
            [date(2012, 2, 14), date(2025, 2, 20), date(2009, 2, 2), date(2025, 12, 16), date(2024, 7, 18)],
        )


class ExperienciaEnLineaTests(SimpleTestCase):
    def test_dos_contratos_en_el_mismo_anio_valen_un_anio(self):
        a = Periodo(date(2020, 1, 1), date(2020, 12, 31), referencia="A")
        b = Periodo(date(2020, 1, 1), date(2020, 12, 31), referencia="B")
        lineal = poner_en_linea([a, b])
        self.assertEqual(lineal.dias, 360)
        self.assertEqual([d.motivo for d in lineal.descartados], ["Se traslapa por completo con A."])

    def test_el_que_se_cruza_solo_aporta_lo_que_no_estaba_cubierto(self):
        a = Periodo(date(2020, 1, 1), date(2020, 6, 30), referencia="A")
        b = Periodo(date(2020, 4, 1), date(2020, 9, 30), referencia="B")
        lineal = poner_en_linea([b, a])
        self.assertEqual([(t.periodo.referencia, t.inicio, t.dias, t.recortado) for t in lineal.tramos],
                         [("A", date(2020, 1, 1), 180, False), ("B", date(2020, 7, 1), 90, True)])

    def test_un_encargo_dentro_de_otro_periodo_no_suma(self):
        largo = Periodo(date(2020, 1, 1), date(2022, 12, 31), referencia="CARGO")
        encargo = Periodo(date(2021, 6, 8), date(2021, 6, 30), referencia="ENCARGO")
        despues = Periodo(date(2023, 1, 1), date(2023, 3, 30), referencia="DESPUES")
        lineal = poner_en_linea([largo, encargo, despues])
        self.assertEqual(lineal.dias, 3 * 360 + 90)
        self.assertEqual([d.periodo.referencia for d in lineal.descartados], ["ENCARGO"])

    def test_lo_anterior_al_grado_no_cuenta(self):
        antes = Periodo(date(2003, 1, 1), date(2003, 12, 31), referencia="ANTES")
        cruza = Periodo(date(2004, 1, 1), date(2004, 12, 31), referencia="CRUZA")
        lineal = poner_en_linea([antes, cruza], desde=date(2004, 7, 1))
        self.assertEqual(lineal.dias, 180)
        self.assertEqual(lineal.descartados[0].motivo, "Es anterior al grado (01/07/2004).")

    def test_las_suspensiones_se_descuentan(self):
        p = Periodo(date(2024, 2, 1), date(2024, 11, 30), suspensiones=[(date(2024, 6, 21), date(2024, 7, 5))])
        self.assertEqual(poner_en_linea([p]).dias, 300 - 15)

    def test_sobra_experiencia_se_retira_la_mas_antigua_y_no_la_relacionada(self):
        vieja_relacionada = Periodo(date(2005, 1, 1), date(2006, 12, 31), referencia="RELACIONADA", relacionada=True)
        vieja = Periodo(date(2007, 1, 1), date(2008, 12, 31), referencia="VIEJA")
        reciente = Periodo(date(2010, 1, 1), date(2022, 12, 31), referencia="RECIENTE")
        lineal = poner_en_linea([vieja_relacionada, vieja, reciente])
        self.assertEqual(lineal.dias, 17 * 360)
        self.assertEqual([t.periodo.referencia for t in ajustar_a_franja(lineal, 10, 15)], ["VIEJA"])
        self.assertEqual(ajustar_a_franja(lineal, 10, None), [])

    def test_no_se_retira_un_periodo_si_deja_la_experiencia_por_debajo_del_minimo(self):
        unico = Periodo(date(2005, 1, 1), date(2022, 12, 31))
        self.assertEqual(ajustar_a_franja(poner_en_linea([unico]), 10, 15), [])


class CertificacionesTests(SimpleTestCase):
    def test_contractual_toma_la_terminacion_final_y_la_suspension(self):
        lectura = leer_periodos([CONTRACTUAL], "certificaciones.pdf")
        self.assertEqual(lectura.avisos, [])
        (p,) = lectura.periodos
        self.assertEqual((p.inicio, p.fin, p.referencia), (date(2024, 2, 1), date(2024, 11, 30), "IOVF-045-2024"))
        self.assertEqual(p.suspensiones, [(date(2024, 6, 21), date(2024, 7, 5))])
        self.assertEqual((p.entidad, p.archivo, p.pagina, p.abierto), ("INSTITUTO DE OBRAS DE VILLA FICTICIA", "certificaciones.pdf", 1, False))

    def test_laboral_en_prosa_con_dos_periodos(self):
        lectura = leer_periodos([LABORAL])
        self.assertEqual([(p.inicio, p.fin, p.referencia) for p in lectura.periodos], [
            (date(2012, 2, 14), date(2019, 12, 31), ""),
            (date(2020, 2, 3), date(2021, 6, 30), ""),
        ])

    def test_en_ejecucion_se_cuenta_hasta_la_expedicion(self):
        (p,) = leer_periodos([EN_EJECUCION]).periodos
        self.assertEqual((p.inicio, p.fin, p.abierto), (date(2009, 2, 12), date(2009, 9, 10), True))

    def test_la_certificacion_abierta_cede_ante_la_del_contrato_terminado(self):
        lectura = leer_periodos([EN_EJECUCION, TERMINADO, TERMINADO])
        (p,) = lectura.periodos
        self.assertEqual((p.inicio, p.fin, p.abierto, p.pagina), (date(2009, 2, 12), date(2010, 8, 11), False, 2))

    def test_sin_fecha_de_terminacion_avisa_y_no_inventa(self):
        lectura = leer_periodos(["MUNICIPIO DE PUEBLO NUEVO\nCONTRATO DE PRESTACIÓN DE SERVICIOS 7 DE 2015\nFECHA DE INICIO: 01/03/2015\nPLAZO: seis meses"])
        self.assertEqual(lectura.periodos, [])
        self.assertIn("empieza el 01/03/2015 y no se leyó la fecha de terminación", lectura.avisos[0])

    def test_el_contrato_de_otra_pagina_lejana_no_se_le_atribuye(self):
        paginas = ["ORDEN DE SERVICIOS 210 DE 2007\nOBJETO: apoyar", "obligaciones", "FECHA DE INICIO: 16 de Enero de 2008.\nFECHA DE TERMINACIÓN: 15 de Enero de 2009."]
        (p,) = leer_periodos(paginas).periodos
        self.assertEqual((p.referencia, p.pagina), ("", 3))

    def test_documento_sin_periodos(self):
        self.assertEqual(leer_periodos(["Hoja de vida"], "hv.pdf").avisos, ["No se encontró ningún periodo de experiencia en hv.pdf."])


class TitulosTests(SimpleTestCase):
    def test_pregrado_y_posgrado(self):
        titulos = leer_titulos([ACTA_PREGRADO, "página escaneada ilegible", ACTA_POSGRADO], "titulos.pdf")
        self.assertEqual([(t.nivel, t.nombre, t.fecha, t.pagina) for t in titulos], [
            (PROFESIONAL, "ECONOMISTA", date(2004, 6, 11), 1),
            (ESPECIALIZACION, "ESPECIALISTA EN GESTIÓN DE PROYECTOS PARA EL DESARROLLO", date(2011, 5, 25), 3),
        ])
        self.assertEqual(fecha_de_grado(titulos), date(2004, 6, 11))

    def test_sin_pregrado_legible_no_hay_fecha_de_grado(self):
        self.assertIsNone(fecha_de_grado([Titulo(ESPECIALIZACION, "", date(2011, 5, 25)), Titulo(PROFESIONAL, "", None)]))


class HonorariosTests(SimpleTestCase):
    def test_la_franja_incluye_el_minimo_y_no_el_maximo(self):
        self.assertEqual(TABLA.franja(10 * 360).nombre, "entre 10 y 15 años")
        self.assertEqual(TABLA.franja(15 * 360 - 1).nombre, "entre 10 y 15 años")
        self.assertEqual(TABLA.franja(15 * 360).nombre, "mayor a 15 años")

    def test_tope_por_posgrado_y_reconocimiento(self):
        franja = TABLA.franja(12 * 360)
        self.assertEqual((franja.tope(SIN_POSGRADO), franja.tope(ESPECIALIZACION), franja.tope(MAESTRIA)), (9_000_000, 10_000_000, 11_000_000))
        self.assertEqual((TABLA.valor_reconocimiento(200), TABLA.valor_reconocimiento(2 * 360)), (0, 1_500_000))

    def test_franja_minima_para_unos_honorarios(self):
        self.assertEqual(TABLA.franja_minima_para(8_500_000, SIN_POSGRADO).nombre, "entre 10 y 15 años")
        self.assertEqual(TABLA.franja_minima_para(8_500_000, MAESTRIA).nombre, "entre 5 y 10 años")
        self.assertIsNone(TABLA.franja_minima_para(20_000_000, MAESTRIA))


class RelacionadaTests(SimpleTestCase):
    def test_lee_las_obligaciones_especificas_saltando_el_encabezado_de_pagina(self):
        obligaciones = obligaciones_especificas(ESTUDIO_PREVIO)
        self.assertEqual(len(obligaciones), 2)
        self.assertTrue(obligaciones[0].endswith("elaboración de los informes requeridos por la Dirección General."))
        self.assertNotIn("Pagar los montos", obligaciones[1])
        self.assertTrue(obligaciones[1].startswith("Asesorar en la elaboración"))

    def test_iguales_es_casi_palabra_por_palabra(self):
        obligaciones = obligaciones_especificas(ESTUDIO_PREVIO)
        self.assertEqual(obligaciones_iguales(obligaciones, CONTRACTUAL), [1])
        self.assertEqual(obligaciones_iguales(obligaciones, LABORAL), [])


class IdoneidadTests(SimpleTestCase):
    def _periodos(self):
        return leer_periodos([CONTRACTUAL, LABORAL, EN_EJECUCION, TERMINADO]).periodos

    def test_experiencia_franja_tope_y_relacionada(self):
        titulos = leer_titulos([ACTA_PREGRADO, ACTA_POSGRADO])
        perfil = Perfil(10, 15, ESPECIALIZACION, 9_500_000, obligaciones_especificas(ESTUDIO_PREVIO))
        r = evaluar_idoneidad(self._periodos(), titulos, perfil, TABLA)
        # 2009-2010: 540 · 2012-2019: 2837 · 2020-2021: 508 · 2024: 300 - 15 de suspensión
        self.assertEqual((r.lineal.dias, r.retirar, r.dias_relacionada), (540 + 2837 + 508 + 285, [], 285))
        self.assertEqual((r.grado, r.posgrado, r.franja.nombre, r.tope), (date(2004, 6, 11), ESPECIALIZACION, "entre 10 y 15 años", 10_000_000))
        self.assertEqual(r.revisiones, [])

    def test_honorarios_por_encima_del_tope_y_grado_sin_leer(self):
        r = evaluar_idoneidad(self._periodos(), [], Perfil(10, 15, honorarios_mensuales=9_500_000), TABLA)
        self.assertEqual(r.posgrado, SIN_POSGRADO)
        self.assertIn("No se leyó la fecha de grado", r.revisiones[0])
        self.assertIn("Los honorarios ($9.500.000) superan el tope de la franja entre 10 y 15 años ($9.000.000).", r.revisiones)

    def test_no_llega_al_minimo_y_cuenta_toda_si_la_regla_lo_dice(self):
        titulos = [Titulo(PROFESIONAL, "ECONOMISTA", date(2020, 1, 1))]
        corto = evaluar_idoneidad(self._periodos(), titulos, Perfil(10, 15))
        self.assertIn("no llega a los 10 años del perfil", corto.revisiones[-1])
        completo = evaluar_idoneidad(self._periodos(), titulos, Perfil(10, 15), reglas=Reglas(desde_el_grado=False))
        self.assertEqual(completo.revisiones, [])

    def test_avisa_cuando_cuenta_una_certificacion_abierta(self):
        r = evaluar_idoneidad(leer_periodos([EN_EJECUCION]).periodos, [], Perfil(0, None), reglas=Reglas(desde_el_grado=False))
        self.assertEqual(r.revisiones, ["CONTRATO DE PRESTACIÓN DE SERVICIOS 26 DE 2009 no trae fecha de terminación: se contó hasta el 10/09/2009, cuando se expidió."])


PAQUETE = {
    "5. delitos.pdf": "CONSULTA EN LÍNEA DE INHABILIDADES DE QUIENES HAYAN SIDO CONDENADOS POR DELITOS SEXUALES\n"
                      "cédula de ciudadanía No. 1000000001 ANA INVENTADA PEREZ NO REGISTRA INHABILIDAD",
    "8. situacion.pdf": "EJÉRCITO NACIONAL COMANDO DE RECLUTAMIENTO certifica la definición de su situación militar de ANA INVENTADA PEREZ",
    "12 formato.pdf": "FORMATO ÚNICO\nHOJA DE VIDA\nPersona Natural\nLIBRETA MILITAR: primera clase",
    "13. HV.pdf": "ANA INVENTADA\nPERFIL PROFESIONAL\nEconomista",
    "15. TARJETA PROFESIONAL.pdf": "",
    "16. consejo.pdf": "ANA INVENTADA PEREZ, documento 1000000001, se encuentra inscrita como economista, y no ha sido sancionada.",
    "25. examen.pdf": "Certificado de Aptitud Laboral Fecha: 18/Jul/2024 Nro Identidad: 1000000001",
    "99. recibo.pdf": "Factura de servicios públicos",
}


class DocumentosTests(SimpleTestCase):
    def _verificar(self, **opciones):
        cumple = mock.Mock(cumple=True, archivo="antecedente.pdf")
        with (
            mock.patch.object(documentos, "paginas_de_texto", side_effect=lambda contenido, _: [contenido.decode()]),
            mock.patch.object(documentos.antecedentes, "evaluar_antecedente", return_value=cumple),
        ):
            pdfs = {nombre: texto.encode() for nombre, texto in PAQUETE.items()}
            lista, _ = documentos.verificar_documentos(pdfs, "Ana Inventada Pérez", "1.000.000.001", date(2026, 1, 22), **opciones)
            return {r.clave: r for r in lista}

    def test_reconoce_cada_documento_por_lo_que_dice_o_por_el_nombre_del_archivo(self):
        r = self._verificar(exige_libreta=True)
        self.assertEqual(
            {c: r[c].archivo for c in ("delitos_sexuales", "libreta_militar", "hoja_de_vida_sigep", "hoja_de_vida", "tarjeta_profesional", "vigencia_matricula", "examen_ocupacional")},
            {"delitos_sexuales": "5. delitos.pdf", "libreta_militar": "8. situacion.pdf", "hoja_de_vida_sigep": "12 formato.pdf",
             "hoja_de_vida": "13. HV.pdf", "tarjeta_profesional": "15. TARJETA PROFESIONAL.pdf", "vigencia_matricula": "16. consejo.pdf",
             "examen_ocupacional": "25. examen.pdf"},
        )
        self.assertTrue(all(r[c].estado == documentos.CUMPLE for c in ("delitos_sexuales", "libreta_militar", "vigencia_matricula", "disciplinarios")))
        self.assertEqual((r["rut"].estado, r["rut"].motivo), (documentos.FALTA, "No se encontró entre los documentos."))

    def test_documento_de_otra_persona_va_a_revision(self):
        with mock.patch.dict(PAQUETE, {"16. consejo.pdf": "PEDRO OTRO RUIZ, documento 2000000002, se encuentra inscrito como economista"}):
            r = self._verificar()
        self.assertEqual(r["vigencia_matricula"].estado, documentos.REVISION)

    def test_vigencia_por_documento(self):
        r = self._verificar(vigencia_meses={"examen_ocupacional": 12})
        self.assertEqual((r["examen_ocupacional"].estado, r["examen_ocupacional"].fecha), (documentos.NO_CUMPLE, date(2024, 7, 18)))
        self.assertEqual(self._verificar(vigencia_meses={"examen_ocupacional": 36})["examen_ocupacional"].estado, documentos.CUMPLE)

    def test_la_libreta_solo_se_exige_a_hombres_menores_de_cincuenta(self):
        with mock.patch.dict(PAQUETE):
            del PAQUETE["8. situacion.pdf"]
            self.assertEqual(self._verificar(exige_libreta=False)["libreta_militar"].estado, documentos.NO_APLICA)
            self.assertEqual(self._verificar(exige_libreta=True)["libreta_militar"].estado, documentos.FALTA)
            self.assertEqual(self._verificar()["libreta_militar"].estado, documentos.REVISION)

    def test_antecedente_que_falta_o_trae_novedad(self):
        falta = mock.Mock(cumple=False, motivo="No se encontró el certificado.", archivo=None, personas=[mock.Mock(estado="falta")])
        novedad = mock.Mock(cumple=False, motivo="Reporta novedades.", archivo="a.pdf", personas=[mock.Mock(estado="con_novedad")])
        doc = documentos.DOCUMENTOS_ICCU[0]
        with mock.patch.object(documentos.antecedentes, "evaluar_antecedente", side_effect=[falta, novedad]):
            self.assertEqual(documentos._antecedente(doc, {}, "Ana", "1", None).estado, documentos.FALTA)
            self.assertEqual(documentos._antecedente(doc, {}, "Ana", "1", None).estado, documentos.REVISION)


ESTUDIO_COMPLETO = """OBJETO PARA CONTRATAR: PRESTACIÓN DE SERVICIOS PROFESIONALES A LA OFICINA DE
PLANEACIÓN DEL INSTITUTO DE OBRAS DE VILLA FICTICIA.

1. DESCRIPCIÓN DE LA NECESIDAD
Se requiere contratar los servicios de un profesional en Economía o afines, con Especialización y
experiencia profesional entre DIEZ (10) a QUINCE (15) años.
""" + ESTUDIO_PREVIO + """2.2.2. Plazo de Ejecución: Diez (10) meses
2.2.4. Valor estimado del contrato: NOVENTA MILLONES DE PESOS M/CTE
(90.000.000). Suma que incluye los impuestos a que haya lugar.
VR MENSUAL TIEMPO VR TOTAL
$9.000.000 10 MESES $90.000.000
"""


class EstudioPrevioTests(SimpleTestCase):
    def test_lee_objeto_plazo_valor_y_perfil(self):
        e = leer_estudio_previo(ESTUDIO_COMPLETO)
        self.assertEqual(e.avisos, [])
        self.assertTrue(e.objeto.startswith("PRESTACIÓN DE SERVICIOS PROFESIONALES") and e.objeto.endswith("VILLA FICTICIA."))
        self.assertEqual((e.plazo_meses, e.valor), (10, 90_000_000))
        p = e.perfil
        self.assertEqual((p.anios_minimos, p.anios_maximos, p.posgrado, p.honorarios_mensuales, len(p.obligaciones)), (10, 15, ESPECIALIZACION, 9_000_000, 2))

    def test_experiencia_minima_sin_posgrado_y_honorarios_por_division(self):
        e = leer_estudio_previo(
            "OBJETO: APOYO A LA GESTIÓN DOCUMENTAL.\n\nSe requiere un profesional con experiencia mínima de DOS (2) años.\n"
            "Plazo de Ejecución: Seis (6) meses\nValor estimado del contrato: TREINTA MILLONES ($30.000.000)\n"
        )
        self.assertEqual((e.perfil.anios_minimos, e.perfil.anios_maximos, e.perfil.posgrado, e.perfil.honorarios_mensuales), (2, None, SIN_POSGRADO, 5_000_000))
        self.assertEqual(e.avisos, ["No se leyeron las obligaciones específicas."])

    def test_avisa_lo_que_no_lee_y_la_tabla_que_no_cuadra(self):
        e = leer_estudio_previo("Documento sin nada útil.\nVR MENSUAL TIEMPO VR TOTAL\n$9.000.000 10 MESES $80.000.000\nTOTAL $80.000.000")
        self.assertIsNone(e.perfil)
        self.assertEqual(e.avisos, [
            "El análisis del valor no cuadra: $9.000.000 por 10 meses no da $80.000.000.",
            "No se leyó la experiencia que exige el perfil.", "No se leyó el objeto.",
        ])

    def test_valor_del_cdp(self):
        self.assertEqual(valor_del_cdp("RUBRO 2.1.2 VALOR 90,000,000.00\nTOTAL CDP 90,000,000.00\nSON: NOVENTA MILLONES"), 90_000_000)
        self.assertIsNone(valor_del_cdp("certificado ilegible"))
        e = leer_estudio_previo(ESTUDIO_COMPLETO)
        self.assertIsNone(problema_con_el_cdp(e, 90_000_000))
        self.assertEqual(problema_con_el_cdp(e, 80_000_000), "El valor del contrato ($90.000.000) supera el del CDP ($80.000.000).")
        self.assertEqual(problema_con_el_cdp(e, None), "No se leyó el valor del CDP.")


class FormasRealesTests(SimpleTestCase):
    """Formas de escribir que aparecieron en expedientes reales (aquí, con datos inventados)."""

    def test_fechas_como_las_escribe_cada_quien(self):
        texto = ("05 DE ENERO 1991 · 31/OCTUBRE/2025 · A LOS 11 DIAS DEL MES DE MAYO ANO DE 1990 · 9 DE ABRIL DE 1.984 · "
                 "EL DIECIOCHO (18) DE FEBRERO DE 2003 · DEL 1* DE FEBRERO DE 2004 · 25-FEBRERO-2025 · LEY 80 DE 1993 · 3 MESES 2020")
        self.assertEqual([f for _, f in fechas_en(texto)], [
            date(1991, 1, 5), date(2025, 10, 31), date(1990, 5, 11), date(1984, 4, 9), date(2003, 2, 18), date(2004, 2, 1), date(2025, 2, 25),
        ])

    def _periodos(self, *paginas, hasta=None):
        lectura = leer_periodos(list(paginas), hasta=hasta)
        return [(p.inicio, p.fin) for p in lectura.periodos], lectura

    def test_prosa_con_a_partir_de_y_dia_en_letras(self):
        periodos, _ = self._periodos("CERTIFICA que suscribió contrato de trabajo a partir del dieciocho\n(18) de febrero de 2003, del cual laboró hasta el veinte (20) de Enero de 2004.")
        self.assertEqual(periodos, [(date(2003, 2, 18), date(2004, 1, 20))])

    def test_del_al_y_rango_sin_anio_en_la_primera_fecha(self):
        periodos, _ = self._periodos(
            "Del 26 de Agosto de 2016 hasta el 25 de Diciembre de 2016 mediante Contrato No. 210 de 2016.\n\n"
            "2 de Enero al 30 de Enero de 2004, prestó sus servicios mediante orden."
        )
        self.assertEqual(periodos, [(date(2004, 1, 2), date(2004, 1, 30)), (date(2016, 8, 26), date(2016, 12, 25))])

    def test_un_hasta_sin_inicio_toma_la_fecha_anterior_y_lo_avisa(self):
        _, lectura = self._periodos(
            "fue nombrado mediante Decreto de fecha\n20 de Mayo de 1993, en este Municipio, labor que desempeñó hasta el 30 de diciembre de 1994."
        )
        (p,) = lectura.periodos
        self.assertEqual((p.inicio, p.fin, p.nota), (date(1993, 5, 20), date(1994, 12, 30), "El inicio (20/05/1993) se dedujo del texto: confírmelo."))

    def test_dos_certificaciones_seguidas_no_se_funden(self):
        periodos, _ = self._periodos(
            "laboró desde el día 05 de enero de 1991 hasta el día 18 de febrero de 1993.",
            "nombrado mediante Decreto del 20 de Mayo de 1993, labor que desempeñó hasta el 30 de diciembre de 1994.",
        )
        self.assertEqual(periodos, [(date(1991, 1, 5), date(1993, 2, 18)), (date(1993, 5, 20), date(1994, 12, 30))])

    def test_prorroga_y_renuncia_a_partir_de_no_abren_otro_periodo(self):
        periodos, _ = self._periodos(
            "FECHA DE INICIO:\n12 de Febrero de 2009\nPRORROGA:\nSeis (6) meses a partir del 12 de Febrero de 2010\nFECHA DE TERMINACIÓN:\n11 de Agosto de 2010",
            "vinculado desde el 3 de marzo de 2012 hasta el 31 de diciembre de 2019. Se aceptó su renuncia a partir del 01 de enero de 2020.",
        )
        self.assertEqual(periodos, [(date(2009, 2, 12), date(2010, 8, 11)), (date(2012, 3, 3), date(2019, 12, 31))])

    def test_terminacion_anticipada_fechas_con_guion_y_suscripcion(self):
        _, lectura = self._periodos(
            "Contrato: ABC-PS-113-2021\nFecha de Inicio: 26-01-2021\nFecha de terminación 25-12-2021\nTerminación anticipada: 11-10-2021",
            "Contrato: ABC-PS-486-2017\nFecha de Suscripción: 20-12-2017\nFecha de terminación 20-09-2018",
            "CONTRATO 2025001\nFECHA DE INICIO 25-Febrero-2025\nFECHA DE TERMINACIÓN 31-Enero-2026",
            hasta=date(2026, 1, 22),
        )
        self.assertEqual([(p.inicio, p.fin, p.referencia, p.abierto) for p in lectura.periodos], [
            (date(2017, 12, 20), date(2018, 9, 20), "ABC-PS-486-2017", False),
            (date(2021, 1, 26), date(2021, 10, 11), "ABC-PS-113-2021", False),
            (date(2025, 2, 25), date(2026, 1, 22), "2025001", True),
        ])
        self.assertEqual([p.nota for p in lectura.periodos], [
            "No trae fecha de inicio: se tomó la de suscripción del contrato.", "Terminó antes de lo pactado (terminación anticipada).",
            "Termina después del 22/01/2026: se contó hasta esa fecha.",
        ])

    def test_tabla_con_los_rotulos_debajo_y_suspension_que_no_es_periodo(self):
        periodos, lectura = self._periodos(
            "FEBRERO 12 DE 2013\nDICIEMBRE 30 DE 2013\n$20.000.000\nOFICINA ASESORA\nFECHA DE INICIO\nFECHA DE TERMINACION\nVALOR",
            "FECHA DE INICIO: 20 DE FEBRERO DE 2025\nSUSPENSION NO 1: 20 DE JUNIO AL 03 DE JULIO DE 2025\nFECHA DE TERMINACION FINAL: 24 DE DICIEMBRE DE 2025",
        )
        self.assertEqual(periodos, [(date(2013, 2, 12), date(2013, 12, 30)), (date(2025, 2, 20), date(2025, 12, 24))])
        self.assertEqual(lectura.periodos[1].suspensiones, [(date(2025, 6, 20), date(2025, 7, 3))])

    def test_fecha_mal_leida_se_avisa_y_no_se_cuenta(self):
        periodos, lectura = self._periodos("desempeñando las funciones desde el 01 de Julio de 2074 hasta el 11 de Enero de 2016")
        self.assertEqual(periodos, [])
        self.assertIn("tiene una fecha mal leída: empieza el 01/07/2074 y termina el 11/01/2016", lectura.avisos[0])

    def test_entidad_y_cargo_como_estan_escritos(self):
        (p,) = leer_periodos([
            "GRUPO MONTAÑA CONSTRUCTORES S.A.S\nCERTIFICA QUE:\nLa señora Ana Inventada prestó sus servicios para nuestra empresa "
            "desde el día 02 de Mayo del 2025 hasta el día 30 de junio de 2025, desempeñándose en el cargo de RESIDENTE OBRA."
        ]).periodos
        self.assertEqual((p.entidad, p.referencia), ("GRUPO MONTAÑA CONSTRUCTORES S.A.S", "Residente Obra"))

    def test_estudio_previo_con_perfil_en_minusculas_especifica_y_tabla_partida(self):
        e = leer_estudio_previo(
            "OBJETO PARA CONTRATAR: PRESTAR SERVICIOS PROFESIONALES DE APOYO TÉCNICO.\n\n"
            "2.2.2. Plazo de Ejecución: 5 (CINCO) MESES\n2.2.4. Valor estimado del contrato: SESENTA Y CINCO MILLONES DE\nPESOS M/CTE. ($ 65.000.000,00).\n"
            "4. ANÁLISIS QUE SOPORTA EL VALOR ESTIMADO DEL CONTRATO\nDe acuerdo con la tabla de honorarios, el Instituto\nrequiere un Arquitecto con experiencia\n"
            "profesional entre veinte (20) y treinta (30) años, con especialización en gestión\npública y una experiencia calificada entre uno (01) y dos (02) años en la elaboración\n"
            "de presupuestos.\nEXPERIENCIA PROFESIONAL\nSALARIOS CON ESPECIALIZACION\n$ 12.678.053,00\nVR MENSUAL TIEMPO VR TOTAL\nCINCO (5)\n$ 13.000.000,00 $ 65.000.000,00\nMESES\nTOTAL"
        )
        p = e.perfil
        self.assertEqual((e.plazo_meses, e.valor, e.avisos), (5, 65_000_000, ["No se leyeron las obligaciones específicas."]))
        self.assertEqual((p.anios_minimos, p.anios_maximos, p.posgrado, p.honorarios_mensuales, p.especifica_minima, p.especifica_maxima),
                         (20, 30, ESPECIALIZACION, 13_000_000, 1, 2))
        self.assertTrue(p.descripcion.startswith("un Arquitecto con experiencia profesional entre veinte (20)") and p.descripcion.endswith("de presupuestos"))
        cero = leer_estudio_previo("requiere un Ingeniero Civil con maestría en vías con una experiencia profesional entre cero (0) y un (01) año.").perfil
        self.assertEqual((cero.anios_minimos, cero.anios_maximos, cero.posgrado), (0, 1, MAESTRIA))

    def test_experiencia_especifica_exigida_reconoce_valor_y_se_exige(self):
        perfil = Perfil(10, 15, ESPECIALIZACION, 11_000_000, especifica_minima=1, especifica_maxima=5)
        base = [Periodo(date(2010, 1, 1), date(2021, 12, 31))]
        sin = evaluar_idoneidad(base, [Titulo(ESPECIALIZACION, "", None)], perfil, TABLA, Reglas(desde_el_grado=False))
        self.assertEqual(sin.tope, 10_000_000)
        self.assertIn("El perfil pide 1 años de experiencia específica y hay 0 días marcados como relacionados", sin.revisiones[0])
        base.append(Periodo(date(2022, 1, 1), date(2023, 12, 31), relacionada=True))
        con = evaluar_idoneidad(base, [Titulo(ESPECIALIZACION, "", None)], perfil, TABLA, Reglas(desde_el_grado=False))
        self.assertEqual((con.tope, con.revisiones), (11_500_000, []))
        # Sin que el perfil la pida, la experiencia relacionada no sube el tope.
        libre = evaluar_idoneidad(base, [Titulo(ESPECIALIZACION, "", None)], Perfil(10, 15, ESPECIALIZACION), TABLA, Reglas(desde_el_grado=False))
        self.assertEqual(libre.tope, 10_000_000)

    def test_el_bachiller_no_es_grado_profesional_y_la_fecha_de_una_norma_no_es_la_del_grado(self):
        titulos = leer_titulos([
            "COLEGIO INVENTADO\nSegún Resolución No 000100 del 23 de Julio de 1993\notorgar el Título de Bachiller Académico\nDado a los 29 días del mes de Noviembre de 1997",
            "UNIVERSIDAD INVENTADA\nACTA DE GRADO No. 100\nconforme a la Resolución ICFES No. 1000 del 23 diciembre de 1992, confiriéndole el título de ABOGADA.\n"
            "Bogotá D.C. 08 de abril de 2005\nAnotado al Folio 98 del 08 de abril de 2005",
        ])
        self.assertEqual([(t.nivel, t.nombre, t.fecha) for t in titulos], [(BACHILLER, "", date(1997, 11, 29)), (PROFESIONAL, "ABOGADA", date(2005, 4, 8))])
        self.assertEqual(fecha_de_grado(titulos), date(2005, 4, 8))

    def test_estudios_declarados_en_la_hoja_de_vida_solo_suplen_lo_que_no_se_leyo(self):
        hoja = ("EDUCACIÓN SUPERIOR (PREGRADO Y POSTGRADO)\nMODALIDAD No. SEMESTRES GRADUADO NOMBRE DE LOS ESTUDIOS O TÍTULO TERMINACIÓN\nSI NO MES AÑO\n"
                "MASTER EN PLANIFICACION Y\nPOSTGRADO 4 X 10 1999 1234\nGESTION AMBIENTAL\nPREGRADO 10 X INGENIERIA AGRONOMICA 12 1986 1234\n"
                "POSTGRADO 3 X MAESTRIA EN CURSO\n3 EDUCACIÓN PARA EL TRABAJO")
        declarados = estudios_declarados(hoja)
        self.assertEqual([(t.nivel, t.nombre, t.fecha, t.declarado) for t in declarados], [
            (MAESTRIA, "MASTER EN PLANIFICACION Y GESTION AMBIENTAL", date(1999, 10, 31), True),
            (PROFESIONAL, "INGENIERIA AGRONOMICA", date(1986, 12, 31), True),
        ])
        leido = Titulo(PROFESIONAL, "INGENIERA", date(1986, 12, 12))
        self.assertEqual(fecha_de_grado([*declarados, leido]), date(1986, 12, 12))
        self.assertEqual(fecha_de_grado(declarados), date(1986, 12, 31))

    def test_matricula_profesional(self):
        m = leer_matricula("CERTIFICA\nQue la Arquitecta ANA INVENTADA con cédula 1000000001, registra Matrícula Profesional de Arquitectura No. A0002023-1000000001, "
                           "expedida en cumplimiento de la Resolución No. 19 del 28 de Abril de 2023, la cual se encuentra VIGENTE.\nLa profesional no registra ANTECEDENTES ni SANCIONES")
        self.assertEqual((m.profesion, m.numero, m.fecha, m.sin_sanciones), ("Arquitecta", "A0002023-1000000001", date(2023, 4, 28), True))
        copnia = leer_matricula("Certificado de vigencia y antecedentes disciplinarios\nse encuentra inscrito(a) en el Registro, en la profesión de INGENIERIA CIVIL con "
                                "MATRICULA PROFESIONAL 25202-000001 desde el 30 de Julio de 2019")
        self.assertEqual((copnia.profesion, copnia.fecha, copnia.sin_sanciones), ("Ingenieria civil", date(2019, 7, 30), False))
        self.assertIsNone(leer_matricula("Certificado de afiliación a salud"))


NUMERADOS = {
    "7. Fotocopia de la cédula.pdf": "",
    "9. EPS.pdf": "CERTIFICADO DE AFILIACIÓN A LA EPS de ANA INVENTADA PEREZ 1000000001",
    "10. RUT.pdf": "Formulario del Registro Único Tributario",
    "18. Declaración de bienes y rentas y conflicto.pdf": "PUBLICACIÓN PROACTIVA DECLARACIÓN DE BIENES Y RENTAS Y REGISTRO DE CONFLICTOS DE INTERÉS",
    "18.2 formato bienes.pdf": "DECLARACIÓN JURAMENTADA DE BIENES Y RENTAS",
    "14. Certificaciones.pdf": "LA EMPRESA CERTIFICA que ANA INVENTADA PEREZ laboró desde el 1 de enero de 2020 hasta el 31 de diciembre de 2020",
    "certificacion suelta.pdf": "CONSORCIO INVENTADO CERTIFICA que ANA INVENTADA PEREZ prestó sus servicios mediante contrato",
    "24. Constancia.pdf": "",
    "foto.pdf": "",
}


class ClasificacionTests(SimpleTestCase):
    def test_el_numero_de_la_lista_ayuda_pero_manda_el_contenido(self):
        c = documentos.clasificar({a: documentos.normalizar(t) for a, t in NUMERADOS.items()})
        self.assertEqual({k: c.asignados.get(k) for k in ("cedula", "salud", "rut", "bienes_y_rentas", "certificaciones_laborales", "constancia_sigep")}, {
            "cedula": "7. Fotocopia de la cédula.pdf", "salud": "9. EPS.pdf", "rut": "10. RUT.pdf",
            "bienes_y_rentas": "18. Declaración de bienes y rentas y conflicto.pdf", "certificaciones_laborales": "14. Certificaciones.pdf",
            "constancia_sigep": "24. Constancia.pdf",
        })
        # La constancia vino sin texto ni nombre que la delate: solo el número, y eso lo confirma una persona.
        self.assertEqual(c.por_numero, {"constancia_sigep"})
        self.assertEqual(c.adicionales, {"bienes_y_rentas": ["18.2 formato bienes.pdf"], "certificaciones_laborales": ["certificacion suelta.pdf"]})
        self.assertEqual(c.sin_reconocer, ["foto.pdf"])

    def test_el_nombre_basta_con_la_mitad_de_sus_palabras(self):
        self.assertTrue(documentos._es_de_la_persona("CARTA DE ANA I. PEREZ", "Ana Inventada Pérez Ruiz", None))
        self.assertFalse(documentos._es_de_la_persona("CARTA DE ANA GOMEZ", "Ana Inventada Pérez Ruiz", None))
        self.assertTrue(documentos._es_de_la_persona("CC 1.000.000.001", "Otro Nombre", "1000000001"))


class LibretaTests(SimpleTestCase):
    def test_se_deduce_de_la_cedula_cuando_se_puede(self):
        ref = date(2026, 1, 22)
        self.assertEqual(libreta_exigible("51.630.142", {}, ref)[0], False)
        cedula = {"7. cedula.pdf": "REPUBLICA DE COLOMBIA CEDULA DE CIUDADANIA FECHA DE NACIMIENTO. 20-SEP.1977"}
        self.assertEqual(libreta_exigible("80000001", cedula, ref), (True, ""))
        mayor = {"7. cedula.pdf": "FECHA DE NACIMIENTO 10-JUN-1967"}
        self.assertEqual(libreta_exigible("79000002", mayor, ref), (False, "Tiene 58 años según su cédula: solo se exige a menores de 50."))
        # Sin fecha de nacimiento legible, o con una cédula de diez dígitos, no se sabe.
        self.assertEqual(libreta_exigible("79000002", {}, ref), (None, ""))
        self.assertEqual(libreta_exigible("1007651426", cedula, ref), (None, ""))
        hoja = {"12. hv.pdf": "DOCUMENTO DE IDENTIFICACION GENERO NACIONALIDAD\nC.C. X C.E. PAS NO 1007651426 F X M NB COL. X"}
        self.assertEqual(libreta_exigible("1007651426", hoja, ref)[0], False)
        hombre = {"12. hv.pdf": "NO 1007651427 F M X NB COL. X", **cedula}
        self.assertEqual(libreta_exigible("1007651427", hombre, ref), (True, ""))
