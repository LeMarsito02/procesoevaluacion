"""Pruebas del motor de evaluación técnica (motor/tecnica) con datos
inventados: ningún nombre, NIT ni contrato es real."""
from __future__ import annotations

import io
from datetime import date

import openpyxl
from django.test import SimpleTestCase

from motor import criterios
from motor.esquemas.proceso import ResultadoRequisito
from motor.tecnica.experiencia import IntegranteTecnico, evaluar_experiencia, objeto_valido
from motor.tecnica.formato3 import ContratoFormato3, Formato3, consecutivos_de, leer_filas
from motor.tecnica.informe import PENDIENTE, ResultadoInforme, generar_informe
from motor.tecnica.longitud import longitudes_en, numeros_del_contrato
from motor.tecnica.parametros import LoteTecnico, ParametrosTecnicos, _clases_unspsc, lotes_del_pliego
from motor.tecnica.rup import ExperienciaRup, Rup, leer_rup, leer_rups

RUP_CONFECAMARAS = """CÁMARA DE COMERCIO DE VILLA FICTICIA
CERTIFICADO DE INSCRIPCIÓN Y CLASIFICACIÓN EN EL REGISTRO DE PROPONENTES
Fecha expedición: 20/07/2026 - 10:00:00
CERTIFICA:
IDENTIFICACIÓN
NOMBRE:VIAS INVENTADAS S.A.S.
NIT:900111222-3
FECHA DE CONSTITUCIÓN:10/02/2015
TAMAÑO DE EMPRESA:PEQUEÑA EMPRESA
*** EXPERIENCIA No.1 :
NÚMERO CONSECUTIVO DEL CONTRATO:12
CONTRATO CELEBRADO POR         :1 - EL PROPONENTE
NOMBRE DEL CONTRATISTA         :VIAS INVENTADAS S.A.S.
NOMBRE DEL CONTRATANTE         :MUNICIPIO DE PUEBLO NUEVO
VALOR CONTRATADO EN SMMLV      :2500,50
SG FM CL PR - DESCRIPCIÓN
72 14 10 00 : SERVICIOS DE CONSTRUCCIÓN DE AUTOPISTAS Y CARRETERAS
*** EXPERIENCIA No.2 :
NÚMERO CONSECUTIVO DEL CONTRATO:13
                                                            Página 5 de 9
                                             CÁMARA DE COMERCIO DE VILLA FICTICIA
                         CERTIFICADO DE INSCRIPCIÓN Y CLASIFICACIÓN EN EL REGISTRO DE PROPONENTES
                                                     Fecha expedición: 20/07/2026 - 10:00:00
CONTRATO CELEBRADO POR         :3 - CONSORCIO O UNIÓN TEMPORAL
NOMBRE DEL CONTRATISTA         :CONSORCIO CAMINOS DE PRUEBA
NOMBRE DEL CONTRATANTE         :DEPARTAMENTO DE ENSAYO
VALOR CONTRATADO EN SMMLV      :4000
PORCENTAJE DE PARTICIPACIÓN EN EL VALOR EJECUTADO EN CASO DE CONSORCIOS Y UNIONES TEMPORALES: 40%
SG FM CL PR - DESCRIPCIÓN
72 14 11 00 : SERVICIOS DE CONSTRUCCIÓN, REVESTIMIENTO Y PAVIMENTACIÓN
"""

RUP_BOGOTA = """CAMARA DE COMERCIO DE BOGOTA
SEDE VIRTUAL
CÓDIGO VERIFICACIÓN: X1
16 DE JULIO DE 2026 HORA 08:34:29
AB1 PÁGINA: 1 DE 3
CERTIFICA:
IDENTIFICACION
QUE: PAVIMENTOS DE MENTIRA S.A.S
NIT: 900333444 5
INFORMACION CONSTITUCION.
POR DOCUMENTO PRIVADO DEL 7 DE MAYO DE 2025 DE ASAMBLEA DE ACCIONISTAS, INSCRITO
CLASIFICACION POR TAMAÑO DE LA EMPRESA
QUE EL INSCRITO SE CLASIFICO COMO:
GRAN EMPRESA
NUMERO CONSECUTIVO DEL REPORTE DEL CONTRATO EJECUTADO: 7
CONTRATO CELEBRADO POR:
ACCIONISTA, SOCIO O CONSTITUYENTE DEL PROPONENTE
NOMBRE DEL CONTRATISTA: SOCIO INVENTADO S.A.
NOMBRE DEL CONTRATANTE: INSTITUTO DE VIAS
DE PRUEBA
VALOR DEL CONTRATO EJECUTADO EXPRESADO EN SMMLV: 3.100,00
CONTRATO EJECUTADO IDENTIFICADO CON EL CLASIFICADOR DE BIENES Y
| 72 | 14 | 10 | 00 | | 81 | 10 | 15 | 00 |
"""


def _certificado(nombre: str, nit: str, consecutivo: str) -> str:
    return (
        f"CAMARA DE COMERCIO DE CIUDAD\nLUGAR Y FECHA DE EXPEDICION: CIUDAD, 2026/07/06 HORA: 10:36:0\n"
        + "RELLENO DEL ENCABEZADO\n" * 3
        + f" IDENTIFICACION\nQUE: {nombre}\nNIT: {nit}\nINFORMACION CONSTITUCION\n"
        "FECHA DE ADQUISICION DE LA PERSONERIA JURIDICA: 2020/11/18\n"
        " CLASIFICACION POR TAMANO DE LA EMPRESA\nQUE EL INSCRITO SE CLASIFICO COMO:\n MICROEMPRESA\n"
        f"NUMERO CONSECUTIVO DEL REPORTE DEL CONTRATO EJECUTADO: {consecutivo}\n"
        "CONTRATO CELEBRADO POR: EL PROPONENTE\nNOMBRE DEL CONTRATISTA: X\nNOMBRE DEL CONTRATANTE: MUNICIPIO DE ALFA\n"
        "VALOR DEL CONTRATO EJECUTADO EXPRESADO EN SMMLV: 1.766,48\n"
        "CONTRATO EJECUTADO IDENTIFICADO CON EL CLASIFICADOR DE BIENES Y SERVICIOS EN EL\nTERCER NIVEL:\n"
        "SEGMENTO FAMILIA CLASE PRODUCTO SEGMENTO FAMILIA CLASE PRODUCTO\n 30 10 15 00 72 14 10 00\n"
        + "FIRMA DEL SECRETARIO\n" * 150
    )


class RupTests(SimpleTestCase):
    def test_formato_confecamaras_con_bloque_partido_entre_paginas(self):
        rup = leer_rup(RUP_CONFECAMARAS)
        self.assertEqual(rup.nombre, "VIAS INVENTADAS S.A.S.")
        self.assertEqual(rup.fecha_expedicion, date(2026, 7, 20))
        self.assertEqual(rup.fecha_constitucion, date(2015, 2, 10))
        self.assertTrue(rup.es_mipyme)
        solo = rup.experiencias["12"]
        self.assertEqual((solo.valor_smmlv, solo.participacion, solo.valor_aportado), (2500.50, None, 2500.50))
        self.assertIn("721410", solo.clases)
        consorcio = rup.experiencias["13"]
        self.assertTrue(consorcio.en_consorcio)
        self.assertEqual(consorcio.contratante, "DEPARTAMENTO DE ENSAYO")
        self.assertAlmostEqual(consorcio.valor_aportado, 1600.0)
        self.assertEqual(consorcio.clases, {"721411"})

    def test_formato_bogota_campos_partidos_y_tabla_de_codigos(self):
        rup = leer_rup(RUP_BOGOTA)
        self.assertEqual(rup.nombre, "PAVIMENTOS DE MENTIRA S.A.S")
        self.assertEqual(rup.fecha_constitucion, date(2025, 5, 7))
        self.assertFalse(rup.es_mipyme)
        exp = rup.experiencias["7"]
        self.assertTrue(exp.de_un_socio)
        self.assertEqual(exp.contratante, "INSTITUTO DE VIAS DE PRUEBA")
        self.assertEqual(exp.valor_smmlv, 3100.0)
        self.assertEqual(exp.clases, {"721410", "811015"})

    def test_pdf_con_los_rup_de_dos_integrantes(self):
        texto = _certificado("UNO DE PRUEBA S.A.S.", "901000001-1", "1") + _certificado("DOS DE PRUEBA S.A.S.", "901000002-2", "5")
        rups = leer_rups(texto)
        self.assertEqual([r.nombre for r in rups], ["UNO DE PRUEBA S.A.S.", "DOS DE PRUEBA S.A.S."])
        self.assertEqual(list(rups[1].experiencias), ["5"])
        self.assertEqual(rups[0].fecha_constitucion, date(2020, 11, 18))
        self.assertIn("721410", rups[0].experiencias["1"].clases)
        self.assertTrue(rups[0].es_mipyme)


class Formato3Tests(SimpleTestCase):
    def test_consecutivos_de_celdas_libres(self):
        self.assertEqual(consecutivos_de("*** EXPERIENCIA No.88 :\nNÚMERO CONSECUTIVO DEL CONTRATO:490"), ["490"])
        self.assertEqual(consecutivos_de("ANA PEREZ\nCONSECUTIVO - 204\n\nB&C\nCONSECUTIVO - 065"), ["204", "65"])
        self.assertEqual(consecutivos_de("60"), ["60"])

    def test_columnas_por_encabezado(self):
        filas = [
            ["", "No. de Orden", "Número consecutivo del reporte del contrato ejecutado en el RUP", "EXPERIENCIA REQUERIDA",
             "Entidad Contratante", "Contrato o Resolución", None, "CLASIFICADOR", "FORMAS DE EJECUCIÓN", None,
             "Integrante que aporta experiencia", "Fecha de Terminación", "VALOR TOTAL DEL CONTRATO EN SMMLV", None, "Lotes"],
            [None, None, None, None, None, "No.", "Objeto", None, "I,C,UT, OTRA", "%", None, None,
             "VALOR TOTAL REPORTADO EN EL RUP", "VALOR TOTAL DEL CONTRATO EN SMMLV de conformidad", None],
            [None, 1, "12", "GENERAL", "MUNICIPIO DE PUEBLO NUEVO", "045 DE 2020", "MEJORAMIENTO DE VIAS URBANAS",
             "721410", "I", 1, "VIAS INVENTADAS", "10/03/2021", 2500.5, 2500.5, "LOTE 2"],
            [None, "NOTA No. 1: ...", None],
        ]
        formato = leer_filas(filas, "f3.xlsx")
        self.assertEqual(len(formato.contratos), 1)
        c = formato.contratos[0]
        self.assertEqual((c.orden, c.consecutivos, c.numero_contrato, c.lotes), (1, ["12"], "045 DE 2020", "LOTE 2"))
        self.assertEqual(c.objeto, "MEJORAMIENTO DE VIAS URBANAS")
        self.assertEqual(c.terminacion, date(2021, 3, 10))
        self.assertEqual(c.valor_rup, 2500.5)


def _parametros(longitud: float | None = None) -> ParametrosTecnicos:
    return ParametrosTecnicos(
        smmlv=1_000_000,
        lotes=[
            LoteTecnico("LOTE 1", 2_000_000_000, "CONSTRUCCIÓN O MEJORAMIENTO O MANTENIMIENTO EN PAVIMENTO ASFALTICO DE VIAS", "",
                        fraccion_un_contrato=0.7),
            LoteTecnico("LOTE 2", 2_000_000_000, "CONSTRUCCIÓN O MEJORAMIENTO EN PAVIMENTO ASFALTICO DE VIAS", "",
                        fraccion_un_contrato=0.7, longitud_minima_km=longitud, longitud_total_km=longitud and longitud / 0.7,
                        fraccion_longitud=longitud and 0.7),
        ],
        clases_unspsc={"721410", "721411"},
    )


def _rup(nombre: str, *experiencias: ExperienciaRup, constitucion: date = date(2010, 1, 1)) -> Rup:
    return Rup(nombre=nombre, nit="", fecha_constitucion=constitucion, tamano_empresa="PEQUENA EMPRESA",
               experiencias={e.consecutivo: e for e in experiencias})


def _exp(consecutivo: str, valor: float, contratante: str = "MUNICIPIO DE ALFA", participacion: float | None = None,
         celebrado: str = "EL PROPONENTE") -> ExperienciaRup:
    return ExperienciaRup(consecutivo, 1, celebrado_por=celebrado, contratante=contratante, valor_smmlv=valor,
                          participacion=participacion, clases={"721410"})


def _fila(orden: int, consecutivo: str, integrante: str, objeto: str = "MEJORAMIENTO DE LA VIA A BETA",
          contratante: str = "MUNICIPIO DE ALFA", valor: float | None = None) -> ContratoFormato3:
    return ContratoFormato3(orden=orden, consecutivos=consecutivos_de(consecutivo), texto_consecutivo=consecutivo,
                            contratante=contratante, numero_contrato=f"{orden}0 DE 2020", objeto=objeto,
                            integrante=integrante, terminacion=date(2021, 1, 1), valor_rup=valor)


class ExperienciaTests(SimpleTestCase):
    cierre = date(2026, 8, 3)

    def test_individual_cumple_valor_y_setenta_por_ciento(self):
        # Presupuesto 2.000 SMMLV: con 1 contrato se certifican 1.500 (75 %) y uno debe valer 1.400 (70 %).
        integrante = IntegranteTecnico("VIAS ALFA S.A.S.", None, 1.0, _rup("VIAS ALFA S.A.S.", _exp("12", 1600)))
        lote1, _ = evaluar_experiencia(Formato3("f3", [_fila(1, "12", "VIAS ALFA")]), [integrante], _parametros(), self.cierre, False)
        self.assertTrue(lote1.cumple, lote1.motivos)
        self.assertEqual(lote1.valor_a_certificar, 1500)
        integrante.rup = _rup("VIAS ALFA S.A.S.", _exp("12", 1450))
        lote1, _ = evaluar_experiencia(Formato3("f3", [_fila(1, "12", "VIAS ALFA")]), [integrante], _parametros(), self.cierre, False)
        self.assertFalse(lote1.cumple)
        self.assertIn("se requieren 1,500.00", " ".join(lote1.motivos))

    def test_contrato_de_dos_integrantes_cuenta_uno_con_la_suma_de_participaciones(self):
        a = IntegranteTecnico("ANA PRUEBA GOMEZ", None, 0.5, _rup("ANA PRUEBA GOMEZ", _exp("204", 4000, participacion=0.2, celebrado="CONSORCIO")))
        b = IntegranteTecnico("B&C INVENTOS SAS", None, 0.5, _rup("B&C INVENTOS SAS", _exp("65", 4000, participacion=0.15, celebrado="CONSORCIO")))
        fila = _fila(1, "ANA PRUEBA GOMEZ CONSECUTIVO - 204 B&C CONSECUTIVO - 065", "ANA PRUEBA GOMEZ")
        lote1, _ = evaluar_experiencia(Formato3("f3", [fila]), [a, b], _parametros(), self.cierre, True)
        contrato = lote1.contratos[0]
        self.assertAlmostEqual(contrato.participacion, 0.35)
        self.assertAlmostEqual(contrato.valor_aportado, 1400)

    def test_consecutivo_repetido_en_otro_integrante_no_se_suma(self):
        a = IntegranteTecnico("ALFA OBRAS SAS", None, 0.8, _rup("ALFA OBRAS SAS", _exp("15", 1600)))
        b = IntegranteTecnico("BETA VIAS SAS", None, 0.2, _rup("BETA VIAS SAS", _exp("15", 900, contratante="OTRA ENTIDAD")))
        lote1, _ = evaluar_experiencia(Formato3("f3", [_fila(1, "15", "ALFA OBRAS SAS")]), [a, b], _parametros(), self.cierre, True)
        self.assertEqual(lote1.contratos[0].aportes, {"ALFA OBRAS SAS": 1600})

    def test_plural_integrante_sin_experiencia_con_mas_del_diez_por_ciento(self):
        a = IntegranteTecnico("ALFA OBRAS SAS", None, 0.7, _rup("ALFA OBRAS SAS", _exp("1", 3000)))
        b = IntegranteTecnico("BETA VIAS SAS", None, 0.3, _rup("BETA VIAS SAS"))
        lote1, _ = evaluar_experiencia(Formato3("f3", [_fila(1, "1", "ALFA OBRAS")]), [a, b], _parametros(), self.cierre, True)
        self.assertFalse(lote1.cumple)
        self.assertFalse(lote1.condiciones_plural)
        b.participacion, a.participacion = 0.1, 0.9
        lote1, _ = evaluar_experiencia(Formato3("f3", [_fila(1, "1", "ALFA OBRAS")]), [a, b], _parametros(), self.cierre, True)
        self.assertTrue(lote1.cumple, lote1.motivos)

    def test_experiencia_de_socios_segun_la_edad_de_la_sociedad(self):
        exp = _exp("7", 3000, celebrado="ACCIONISTA, SOCIO O CONSTITUYENTE DEL PROPONENTE")
        integrante = IntegranteTecnico("GAMMA SAS", None, 1.0, _rup("GAMMA SAS", exp))
        lote1, _ = evaluar_experiencia(
            Formato3("f3", [_fila(1, "7", "GAMMA")]), [integrante], _parametros(), self.cierre, False,
            verificar_socio=lambda nombre: (True, "tiene más de tres años"),
        )
        self.assertTrue(lote1.cumple, lote1.motivos)
        lote1, _ = evaluar_experiencia(
            Formato3("f3", [_fila(1, "7", "GAMMA")]), [integrante], _parametros(), self.cierre, False,
            verificar_socio=lambda nombre: (None, "menos de tres años, sin documento"),
        )
        self.assertFalse(lote1.cumple)

    def test_objeto_segun_las_actividades_del_lote(self):
        _, lote2 = _parametros().lotes
        self.assertTrue(objeto_valido("MEJORAMIENTO DE LA VIA A BETA", lote2))
        # El lote 2 no admite mantenimiento: lo decide quien revisa.
        self.assertIsNone(objeto_valido("MANTENIMIENTO RUTINARIO DE LA MALLA VIAL", lote2))
        self.assertFalse(objeto_valido("CONSTRUCCION DE UN COLEGIO", lote2))

    def test_longitud_afectada_por_la_participacion(self):
        integrante = IntegranteTecnico("VIAS ALFA S.A.S.", None, 1.0, _rup("VIAS ALFA S.A.S.", _exp("12", 3000, participacion=0.5, celebrado="CONSORCIO")))
        parametros = _parametros(longitud=1.512)
        _, lote2 = evaluar_experiencia(
            Formato3("f3", [_fila(1, "12", "VIAS ALFA")]), [integrante], parametros, self.cierre, False,
            buscar_longitud=lambda c: (2.35, "acta.pdf", None),
        )
        self.assertIsNone(lote2.longitud)  # 2,35 km × 50 % = 1,175 km < 1,512 km
        self.assertFalse(lote2.cumple)
        _, lote2 = evaluar_experiencia(
            Formato3("f3", [_fila(1, "12", "VIAS ALFA")]), [integrante], parametros, self.cierre, False,
            buscar_longitud=lambda c: (3.2, "acta.pdf", None),
        )
        self.assertTrue(lote2.longitud)

    def test_longitudes_explicitas(self):
        self.assertEqual([round(x, 5) for x in longitudes_en("SE CONSTRUYO UNA LONGITUD TOTAL DE 5,041,56 METROS LINEALES DE VIA")],
                         [5.04156])
        self.assertEqual(longitudes_en("Longitud Intervenida: 2346,73 ML"), [2.34673])
        self.assertEqual(longitudes_en("se pavimentaron 2,3 km de via"), [2.3])
        # Cantidades de la tabla de ítems o medidas de materiales no son la longitud de la vía.
        self.assertEqual(longitudes_en("PREPARACION DE LA SUPERFICIE ML 4623,87"), [])
        self.assertEqual(longitudes_en("VARILLAS LONGITUD 0,35 M"), [])
        self.assertEqual(numeros_del_contrato("ICCU-CTO-688 DE 2023"), ["688"])

    def test_area_intervenida_no_es_longitud(self):
        from motor.tecnica.longitud import areas_en

        self.assertEqual(areas_en("AREA INTERVENIDA: 15.230,5 M2"), [15230.5])
        self.assertEqual(areas_en("SE PAVIMENTARON 8.400 M2 DE VIA"), [8400])
        # Cantidades de la tabla de ítems de obra no son el área intervenida.
        self.assertEqual(areas_en("RIEGO DE LIGA CON EMULSION M2 127.265,45"), [])
        self.assertEqual(longitudes_en("AREA INTERVENIDA: 15.230,5 M2"), [])

    def test_soporte_con_area_y_sin_longitud_pide_aclaracion(self):
        integrante = IntegranteTecnico("VIAS ALFA S.A.S.", None, 1.0, _rup("VIAS ALFA S.A.S.", _exp("12", 3000)))
        _, lote2 = evaluar_experiencia(
            Formato3("f3", [_fila(1, "12", "VIAS ALFA")]), [integrante], _parametros(longitud=1.512), self.cierre, False,
            buscar_longitud=lambda c: (None, None, None), buscar_area=lambda c: (15230.5, "acta.pdf", None),
        )
        self.assertFalse(lote2.cumple)
        self.assertIsNone(lote2.longitud)
        self.assertTrue(any("área intervenida (15,230.50 m²)" in m and "aclaración" in m for m in lote2.motivos), lote2.motivos)


class ParametrosTests(SimpleTestCase):
    def test_codigos_unspsc_con_la_tabla_partida(self):
        texto = (
            "3.5.4 CLASIFICACION DE LA EXPERIENCIA EN EL CLASIFICADOR DE BIENES\nSEGMENTOS FAMILIA CLASE NOMBRE\n"
            "72 14 10 SERVICIOS DE CONSTRUCCION DE AUTOPISTAS\n72 SERVICIOS DE CONSTRUCCION, REVESTIMIENTO\n14 11\n"
            "INFRAESTRUCTURA.\n3.5.5 ACREDITACION DE LA EXPERIENCIA REQUERIDA\n70 12 15"
        )
        self.assertEqual(_clases_unspsc(texto), {"721410", "721411"})

    def test_presupuesto_de_cada_lote_escrito_en_letras(self):
        texto = (
            "1.1. OBJETO, PRESUPUESTO OFICIAL, PLAZO Y UBICACION\nTRES MIL MILLONES ($3.000.000.000,00)\n"
            "CINCO MIL MILLONES ($5.000.000.000,00)\n1.2. DOCUMENTOS DEL PROCESO\n"
        )
        self.assertEqual(lotes_del_pliego(texto, ["1", "2"]), [("LOTE 1", 3e9), ("LOTE 2", 5e9)])

    def test_tabla_de_valor_minimo(self):
        p = ParametrosTecnicos(smmlv=1)
        self.assertEqual([p.factor(n) for n in (1, 2, 3, 5, 7)], [0.75, 0.75, 1.2, 1.5, 1.5])


class PuntajeTests(SimpleTestCase):
    def test_porcentaje_de_personal_colombiano(self):
        from motor.tecnica.puntaje import _porcentaje_nacional, minimo_con_discapacidad

        self.assertEqual(_porcentaje_nacional("DE AL MENOS EL [100%] DEL TOTAL"), 100)
        self.assertEqual(_porcentaje_nacional("AL MENOS EL NOVENTA POR CIENTO (90 %) DEL PERSONAL"), 90)
        self.assertIsNone(_porcentaje_nacional("SIN PORCENTAJE"))
        self.assertEqual([minimo_con_discapacidad(n) for n in (13, 31, 150, 201)], [1, 2, 3, 5])


class DiscapacidadMujeresTests(SimpleTestCase):
    def test_constancia_del_ministerio_con_su_vigencia(self):
        from motor.tecnica.puntaje import _mas_meses, leer_certificado_discapacidad
        from motor.tecnica.rup import normalizar

        texto = normalizar(
            "NOMBRE – RAZON SOCIAL: OBRAS INVENTADAS S.A.S. IDENTIFICACIÓN: NIT. 900111222-3 A. NUMERO TOTAL DE "
            "TRABAJADORES: 12 B. NUMERO DE TRABAJADORES CON DISCAPACIDAD: 1 Numeral 2 ... La vigencia de la presente "
            "constancia es de Seis (6) Meses contados a partir de la fecha de expedición ... Dado en, Neiva Huila a los "
            "seis (06) días del mes de febrero de 2026 FUNCIONARIO DE PRUEBA"
        )
        c = leer_certificado_discapacidad("c.pdf", texto)
        self.assertEqual((c.identificacion, c.total, c.con_discapacidad, c.vigencia_meses), ("9001112223", 12, 1, 6))
        self.assertEqual(c.expedicion, date(2026, 2, 6))
        self.assertEqual(_mas_meses(c.expedicion, 6), date(2026, 8, 6))
        otra = leer_certificado_discapacidad("d.pdf", normalizar("Dado en, Bogotá D.C. el miércoles, 15 de julio de 2026 X"))
        self.assertEqual(otra.expedicion, date(2026, 7, 15))

    def test_cuadro_de_accionistas_sin_la_segunda_declaracion(self):
        from motor.tecnica.puntaje import _CUADRO_RE, _mantenida_desde
        from motor.tecnica.rup import normalizar

        texto = normalizar(
            "EN EL SIGUIENTE CUADRO SEÑALAMOS ... ANA INVENTADA C.C. 60% NUMERO DE ACCIONES DE IGUAL MANERA, MANIFESTAMOS "
            "QUE MAS DEL CINCUENTA POR CIENTO (50 %) ... SE HA MANTENIDO A PARTIR DE: 02 DE ENERO DE 2025."
        )
        self.assertNotIn("50 %", _CUADRO_RE.search(texto).group(1))
        self.assertEqual(_mantenida_desde(texto), date(2025, 1, 2))
        self.assertEqual(_mantenida_desde("SE HA MANTENIDO A PARTIR DE: 08-10-2002"), date(2002, 10, 8))


class MemoPorPdfsTests(SimpleTestCase):
    def test_acepta_argumentos_por_nombre(self):
        # Se llamó una función memorizada con principal=... y fallaba en la
        # evaluación real (las pruebas la reemplazaban por un simulacro).
        from motor.procesamiento.memoria_proponente import PdfsProponente, memo_por_pdfs

        llamadas = []

        @memo_por_pdfs
        def f(pdfs, nombre, principal=False):
            llamadas.append((nombre, principal))
            return principal

        pdfs = PdfsProponente({"a.pdf": b""})
        self.assertTrue(f(pdfs, "ANA", principal=True))
        self.assertTrue(f(pdfs, "ANA", principal=True))
        self.assertFalse(f(pdfs, "ANA"))
        self.assertEqual(llamadas, [("ANA", True), ("ANA", False)])


class PuntajesDelPliegoTests(SimpleTestCase):
    def test_valores_y_no_aplica_salen_del_pliego(self):
        from motor.tecnica.parametros import _puntajes

        texto = (
            "\n4.2.1 IMPLEMENTACION DEL PROGRAMA DE GERENCIA DE PROYECTOS\nLA ENTIDAD ASIGNARA DIEZ (10) PUNTOS AL PROPONENTE"
            "\n4.2.2 DISPONIBILIDAD Y CONDICIONES FUNCIONALES DE LA MAQUINARIA DE OBRA\nNO APLICA"
            "\n4.2.4 CRITERIOS AMBIENTALES Y SOCIALES\nLA ENTIDAD ASIGNARA QUINCE (15) PUNTOS AL PROPONENTE"
            "\n4.6 EMPRENDIMIENTOS Y EMPRESAS DE MUJERES\nLA ENTIDAD ASIGNARA UN PUNTAJE DE CERO PUNTO VEINTICINCO (0.25) PUNTOS"
        )
        self.assertEqual(_puntajes(texto), {"gerencia_proyectos": 10, "maquinaria": None, "criterios_ambientales": 15, "mujeres": 0.25})

    def test_se_aplican_al_puntaje(self):
        from motor.tecnica.proponente import aplicar_puntajes_del_pliego
        from motor.tecnica.puntaje import Factor

        gerencia = Factor("gerencia_proyectos", "g", 5, puntaje=5)
        maquinaria = Factor("maquinaria", "m", 0)
        plan = Factor("plan_calidad", "p", 5, puntaje=5)
        aplicar_puntajes_del_pliego([gerencia, maquinaria, plan], {"gerencia_proyectos": 10, "maquinaria": None})
        self.assertEqual((gerencia.puntaje_maximo, gerencia.puntaje), (10, 10))
        self.assertTrue(maquinaria.no_aplica)
        # Sin valor en el pliego: a revisión, nunca se otorga el del documento tipo.
        self.assertIsNone(plan.puntaje)


class DefinicionTecnicaTests(SimpleTestCase):
    def test_un_requisito_de_experiencia_por_lote(self):
        definicion = criterios.expandir_lotes(criterios.definicion_sistema("tecnica"), ["LOTE 1", "LOTE 2"])
        experiencia = [(r.numero, r.lote, r.titulo) for r in definicion.requisitos if r.verificacion == "tecnica.experiencia"]
        self.assertEqual(experiencia, [(101, 0, "Experiencia habilitante — Lote 1"), (102, 1, "Experiencia habilitante — Lote 2")])
        self.assertIn(127, [r.numero for r in definicion.requisitos])
        self.assertTrue(all(r.verificacion.startswith("juridica.") for r in criterios.definicion_sistema("juridica").requisitos))


class InformeTecnicoTests(SimpleTestCase):
    def test_lo_no_decidido_sale_pendiente(self):
        def r(numero, cumple, maximo=None, decidido=False):
            detalle = {"puntaje_maximo": maximo} if maximo is not None else {"contratos": []}
            return ResultadoInforme(ResultadoRequisito(hoja="P-01", numero_orden=1, nombre_proponente="X", requisito=numero,
                                                       cumple=cumple, motivo="m", detalle=detalle), decidido)

        resultados = {("P-01", 101): r(101, True), ("P-01", 121): r(121, True, 5), ("P-01", 122): r(122, True, 5),
                      ("P-01", 123): r(123, True, 20), ("P-01", 124): r(124, False, 20, decidido=True),
                      ("P-01", 125): r(125, False, 1), ("P-01", 126): r(126, True, 0.25), ("P-01", 127): r(127, True, 0.25),
                      ("P-01", 130): r(130, True, 0)}
        contenido = generar_informe("PRUEBA-001", "Objeto", [(0, "LOTE 1")], [("P-01", "CONSORCIO INVENTADO")], resultados,
                                    {0: 101}, borrador=True)
        hoja = openpyxl.load_workbook(io.BytesIO(contenido))["Resumen"]
        fila = next(f for f in hoja.iter_rows(values_only=True) if f[0] == "P-01")
        self.assertEqual(fila[2:], ("CUMPLE", 30, 0, PENDIENTE, 0.25, 0.25, 0, f"30.5 + {PENDIENTE}"))


class AnaliticaTests(SimpleTestCase):
    def test_techo_del_error(self):
        from evaluaciones.analitica import techo_del_error

        # 0 errores en n decisiones: 1 - 0,05^(1/n) (regla de tres: ~3/n).
        self.assertAlmostEqual(techo_del_error(0, 1000), 0.002991, places=5)
        self.assertIsNone(techo_del_error(0, 0))
        # Con errores, la cota es mayor que la tasa observada.
        self.assertGreater(techo_del_error(1, 1000), 0.001)
        self.assertLess(techo_del_error(1, 1000), 0.006)

    def test_resumen_de_una_prueba(self):
        from evaluaciones.analitica import Fila, Prueba, resumir

        filas = [
            Fila("P-01", "1", "SI", "SI"), Fila("P-01", "2", "NO", "NO"),
            Fila("P-02", "1", "SI", "NO"), Fila("P-02", "2", "N.A.", "N.A."),
        ]
        r = resumir(Prueba("x", "juridica", "Prueba", filas=filas, tiempos={"P-01": 10, "P-02": 30}))
        self.assertEqual((r["decisiones"], r["automaticas"], r["indebidas"], r["revision_justificada"]), (4, 3, 1, 1))
        self.assertEqual(r["proponentes_resueltos_solos"], 1)
        self.assertEqual(r["proponentes_resueltos_solos_mal"], 1)
        self.assertEqual(r["segundos_por_proponente"], 20)


class SoporteDelContratoTests(SimpleTestCase):
    def test_contrato_sin_acta_ni_certificacion_va_a_revision(self):
        cierre = date(2026, 8, 3)
        integrante = IntegranteTecnico("VIAS ALFA S.A.S.", None, 1.0, _rup("VIAS ALFA S.A.S.", _exp("12", 1600)))
        formato3 = Formato3("f3", [_fila(1, "12", "VIAS ALFA")])
        con, _ = evaluar_experiencia(formato3, [integrante], _parametros(), cierre, False, buscar_soporte=lambda c: "acta.pdf")
        sin, _ = evaluar_experiencia(formato3, [integrante], _parametros(), cierre, False, buscar_soporte=lambda c: None)
        self.assertTrue(con.cumple, con.motivos)
        self.assertFalse(sin.cumple)
        self.assertTrue(any("acta o certificación" in m for m in sin.motivos))
