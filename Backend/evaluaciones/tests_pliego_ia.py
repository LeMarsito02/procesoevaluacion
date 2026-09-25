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


class RequisitosQueElMotorNoVerificaTests(SimpleTestCase):
    """La garantía que hace al programa compatible con cualquier pliego: no
    necesita saber verificarlo todo, necesita no dar por cumplido lo que no
    miró. Un requisito que el pliego exige y el motor no conoce se nombra y
    manda el lote a revisión."""

    def test_el_catalogo_reconoce_lo_que_el_motor_sabe_hacer(self):
        from motor.pliego.catalogo_tecnico import verificacion_de

        self.assertEqual(verificacion_de("Un contrato debe contemplar un área intervenida superior al 50% de los metros cuadrados"),
                         "tecnica.area")
        self.assertEqual(verificacion_de("El índice de liquidez debe ser mayor o igual a 1,2"), "financiera.indicadores")
        self.assertEqual(verificacion_de("La capacidad residual debe ser superior a la del proceso"),
                         "financiera.capacidad_residual")
        self.assertEqual(verificacion_de("Los contratos deben estar clasificados en los códigos UNSPSC"), "tecnica.unspsc")

    def test_lo_que_el_motor_no_sabe_verificar_queda_señalado(self):
        from motor.pliego.catalogo_tecnico import verificacion_de

        self.assertIsNone(verificacion_de("El proponente debe acreditar una póliza de responsabilidad civil extracontractual"))
        self.assertIsNone(verificacion_de("El proponente debe presentar un plan de manejo de tránsito aprobado"))

    def test_los_tramites_de_la_entidad_no_son_requisitos_del_proponente(self):
        from motor.pliego.catalogo_tecnico import verificacion_de

        # Cadena vacía: ni se verifica ni cuenta como requisito sin verificar.
        self.assertEqual(verificacion_de("La Entidad verificará la información en el SECOP"), "")
        self.assertEqual(verificacion_de("Serán causales de rechazo de la oferta las siguientes"), "")

    def test_la_cobertura_separa_lo_uno_de_lo_otro(self):
        from motor.pliego.catalogo_tecnico import cobertura

        cubiertos, faltantes = cobertura([
            ("Acreditar un índice de liquidez mayor o igual a 1,2", "liquidez mayor o igual a 1,2"),
            ("Aportar una póliza de responsabilidad civil extracontractual", "póliza de responsabilidad civil"),
            ("La Entidad consultará el RUP en línea", "La Entidad consultará"),
        ])
        self.assertEqual(list(cubiertos), ["financiera.indicadores"])
        self.assertEqual([r for r, _ in faltantes], ["Aportar una póliza de responsabilidad civil extracontractual"])

    def test_un_requisito_sin_verificar_manda_el_lote_a_revision(self):
        from datetime import date

        from evaluaciones.tests_tecnica import _fila, _parametros, _rup, _exp, Formato3
        from motor.tecnica.experiencia import IntegranteTecnico, evaluar_experiencia

        parametros = _parametros()
        integrante = IntegranteTecnico("VIAS ALFA S.A.S.", None, 1.0,
                                       _rup("VIAS ALFA S.A.S.", _exp("12", 3000), _exp("7", 3000)))
        formato3 = Formato3("f3", [_fila(1, "12", "ALFA"), _fila(2, "7", "GAMMA")])
        antes, _ = evaluar_experiencia(formato3, [integrante], parametros, date(2026, 8, 3), False)
        self.assertTrue(antes.cumple)

        parametros.requisitos_sin_verificar = ["Aportar una póliza de responsabilidad civil — pliego: «…»"]
        despues, _ = evaluar_experiencia(formato3, [integrante], parametros, date(2026, 8, 3), False)
        self.assertFalse(despues.cumple)
        self.assertTrue(any("no verifica" in m for m in despues.motivos))

    def test_el_area_exigida_por_el_pliego_no_se_da_por_cumplida(self):
        """Caso real de ICCU-LP-027: el pliego pide un contrato con área
        intervenida ≥ 50 % de 1.144 m². Si no se encuentra en los soportes,
        el lote no se aprueba."""
        from datetime import date

        from evaluaciones.tests_tecnica import _fila, _parametros, _rup, _exp, Formato3
        from motor.tecnica.experiencia import IntegranteTecnico, evaluar_experiencia

        parametros = _parametros()
        parametros.lotes[0].area_minima_m2 = 572.0
        parametros.lotes[0].area_total_m2 = 1144.0
        parametros.lotes[0].fraccion_area = 0.5
        integrante = IntegranteTecnico("VIAS ALFA S.A.S.", None, 1.0,
                                       _rup("VIAS ALFA S.A.S.", _exp("12", 3000), _exp("7", 3000)))
        resultado, _ = evaluar_experiencia(Formato3("f3", [_fila(1, "12", "ALFA"), _fila(2, "7", "GAMMA")]),
                                           [integrante], parametros, date(2026, 8, 3), False)
        self.assertFalse(resultado.cumple)
        self.assertIsNone(resultado.area)
        self.assertTrue(any("572" in m and "m²" in m for m in resultado.motivos))


class ClaseDeRequisitoTests(SimpleTestCase):
    """Qué riesgo corre cada frase del pliego si el programa la ignora. La
    clasificación existe para revisar menos, así que cada caso de aquí es un
    caso donde equivocarse costaría una aprobación indebida."""

    def clase(self, texto, cita=""):
        from motor.pliego.catalogo_tecnico import clase_de

        return clase_de(texto, cita)

    def test_una_exclusion_del_pliego_es_lo_mas_peligroso(self):
        """Si el motor no aplica lo que el pliego excluye, cuenta un contrato
        que no debía contar: esas frases nunca dejan de frenar."""
        self.assertEqual(self.clase("Las auto certificaciones no servirán para acreditar la experiencia requerida"), "exclusion")
        self.assertEqual(self.clase("No se aceptará experiencia cuya ejecución sea exclusivamente en afirmado"), "exclusion")
        self.assertEqual(self.clase("No será válida la experiencia relacionada con estudios técnicos y diseños"), "exclusion")
        self.assertEqual(self.clase("De no lograrse la discriminación de los valores, la Entidad no lo tendrá en cuenta"), "exclusion")

    def test_una_restriccion_escrita_como_permiso_sigue_siendo_restriccion(self):
        self.assertEqual(
            self.clase("Solo uno (1) de los contratos podrá haber iniciado ejecución antes del 9 de enero de 1998"),
            "exclusion")

    def test_un_permiso_no_puede_aprobar_a_nadie_de_mas(self):
        """El pliego amplía lo aceptable. Ignorarlo puede hacer que se rechace a
        quien cumplía —y eso se muestra—, pero no aprueba a nadie de más."""
        self.assertEqual(
            self.clase("El Proponente podrá acreditar este requisito con un documento emitido por una firma de auditoría externa"),
            "permiso")
        self.assertEqual(
            self.clase("Los proponentes podrán acreditar experiencia proveniente de contratos celebrados con particulares"),
            "permiso")

    def test_un_deber_manda_sobre_la_regla_de_lectura_de_al_lado(self):
        """La IA devuelve el requisito junto con la frase vecina. Si la frase
        vecina decide la clase, una exigencia se cuela como regla de lectura y
        deja de frenar."""
        self.assertEqual(
            self.clase("Para Proponentes Plurales, uno de los integrantes debe aportar como mínimo el 50 % de la experiencia",
                       "en caso de discrepancias se tendrá en cuenta el de menor valor"),
            "exigencia")

    def test_una_exigencia_larga_sin_verbo_no_es_un_encabezado(self):
        """A la lectura se le va el verbo. Una lista de documentos por aportar
        no puede quedar como un título de tabla."""
        self.assertEqual(self.clase("Copias de las resoluciones de nombramiento y de posesión para cargos públicos"), "exigencia")
        self.assertEqual(self.clase("Actas de liquidación o actas de terminación de los contratos, en caso de aplicar"), "exigencia")
        self.assertEqual(self.clase("Objeto del contrato"), "encabezado")

    def test_lo_de_los_proponentes_extranjeros_nunca_se_da_por_verificado(self):
        """Sus requisitos hablan de los mismos temas que el motor sí verifica
        (estados financieros, códigos de clasificación), pero en su caso no se
        verificó nada: sin esto quedarían tapados."""
        from motor.pliego.catalogo_tecnico import verificacion_de

        self.assertIsNone(verificacion_de(
            "Los Proponentes extranjeros sin domicilio o Sucursal en Colombia deberán allegar el estado de situación "
            "financiera (balance general) y estado de resultado integral"))
        self.assertIsNone(verificacion_de(
            "Las personas jurídicas extranjeras sin domicilio en Colombia deberán indicar los códigos de clasificación"))

    def test_las_condiciones_del_proponente_plural_ya_no_piden_revision(self):
        """El motor verifica que uno de los integrantes aporte el 50 %, que los
        demás lleguen al 5 % y que no haya más de uno sin aportar. El catálogo
        no lo reconocía cuando el pliego lo escribía en plural, y eran 34
        requisitos pidiendo revisión de algo que sí se verifica."""
        from motor.pliego.catalogo_tecnico import verificacion_de

        for texto in (
            "En Proponentes Plurales, uno de los integrantes debe aportar como mínimo el cincuenta por ciento (50 %) de la experiencia",
            "Los demás integrantes deben acreditar al menos el cinco por ciento (5 %) de la experiencia solicitada",
            "Solo uno (1) de los integrantes, si así lo considera pertinente, podrá no acreditar experiencia",
        ):
            self.assertEqual(verificacion_de(texto), "tecnica.plural", texto)

    def test_un_requisito_del_plural_que_no_es_de_experiencia_no_queda_tapado(self):
        """El riesgo de ampliar la regla: que "los integrantes deben aportar el
        certificado de antecedentes" se dé por verificado con las condiciones de
        aporte de experiencia, que es otra cosa."""
        from motor.pliego.catalogo_tecnico import verificacion_de

        self.assertIsNone(verificacion_de(
            "Los integrantes del proponente plural deben aportar el certificado de antecedentes disciplinarios"))
        self.assertIsNone(verificacion_de(
            "Cada integrante del consorcio debe aportar su certificado de existencia y representación legal"))

    def test_lo_que_el_motor_si_verifica_deja_de_pedir_revision(self):
        """Falsos negativos que se encontraron en los 14 pliegos del ICCU: el
        motor sí lo verifica y el catálogo no lo reconocía."""
        from motor.pliego.catalogo_tecnico import verificacion_de

        self.assertEqual(verificacion_de("Patrimonio (Roe) Patrimonio"), "financiera.organizacional")
        self.assertEqual(verificacion_de("Que hayan contenido la ejecución de: PAVIMENTO ASFÁLTICO DE VÍAS"),
                         "tecnica.experiencia_general")
        self.assertEqual(verificacion_de("Acta de Inicio o la orden de inicio"), "tecnica.soporte")

    def test_los_permisos_no_entran_en_lo_que_frena_pero_se_listan(self):
        from motor.pliego.catalogo_tecnico import cobertura, permisos

        requisitos = [
            ("El Proponente podrá acreditarlo con un documento de una firma de auditoría externa", "podrá acreditarlo"),
            ("No se aceptará experiencia cuya ejecución sea exclusivamente en afirmado", "no se aceptará"),
        ]
        _, faltantes = cobertura(requisitos)
        self.assertEqual([r for r, _ in faltantes], [requisitos[1][0]])
        self.assertEqual([r for r, _ in permisos(requisitos)], [requisitos[0][0]])

    def test_lo_que_frena_sale_ordenado_por_riesgo(self):
        from motor.pliego.catalogo_tecnico import cobertura

        requisitos = [
            ("La contabilización de la experiencia se realizará en años", "se realizará en años"),
            ("El proponente debe presentar un plan de manejo de tránsito", "debe presentar un plan"),
            ("No se aceptará experiencia ejecutada exclusivamente en afirmado", "no se aceptará"),
        ]
        _, faltantes = cobertura(requisitos)
        self.assertEqual([r.split()[0] for r, _ in faltantes], ["No", "El", "La"])


class AsumirRequisitosTests(SimpleTestCase):
    """La otra mitad de la garantía: que no dar por cumplido lo que no se miró
    no obligue a mirarlo trece veces. Un requisito del pliego se asume una vez
    para el proceso, y desde ahí los proponentes vuelven a poder aprobarse
    solos."""

    def _ia(self):
        cita = "el proponente deberá aportar una póliza de responsabilidad civil extracontractual"
        ia = ParametrosIA()
        ia.requisitos = [Leido(valor="El proponente debe aportar una póliza de responsabilidad civil extracontractual",
                               cita=cita, seccion="5.2 REQUISITOS")]
        return ia

    def test_un_requisito_pendiente_se_lista_con_su_clave_y_su_cita(self):
        pendientes = fusion.sin_verificar(self._ia())
        self.assertEqual(len(pendientes), 1)
        clave, requisito, cita = pendientes[0]
        self.assertTrue(clave)
        self.assertIn("póliza", requisito)
        self.assertIn("póliza", cita)

    def test_lo_asumido_deja_de_frenar_la_aprobacion(self):
        ia = self._ia()
        clave = fusion.sin_verificar(ia)[0][0]
        self.assertEqual(fusion.sin_verificar(ia, [clave]), [])

    def test_la_clave_aguanta_que_la_lectura_cambie_de_palabras(self):
        """La IA no lee dos veces igual. Si la clave dependiera del texto
        literal, lo asumido se olvidaría a la siguiente lectura y habría que
        revisarlo todo otra vez."""
        a = fusion.clave_de_requisito("El proponente debe aportar una póliza de responsabilidad civil extracontractual")
        b = fusion.clave_de_requisito("El Proponente deberá aportar la póliza de responsabilidad civil extracontractual.")
        self.assertEqual(a, b)

    def test_dos_requisitos_que_difieren_en_una_cifra_no_son_el_mismo(self):
        """El lado peligroso de tolerar la redacción: si la clave ignorara las
        cifras, asumir «5 años de experiencia» daría por revisado «8 años» y
        eso es una aprobación indebida."""
        a = fusion.clave_de_requisito("El personal clave debe acreditar 5 años de experiencia específica")
        b = fusion.clave_de_requisito("El personal clave debe acreditar 8 años de experiencia específica")
        self.assertNotEqual(a, b)

    def test_asumir_un_requisito_no_asume_los_demas(self):
        ia = self._ia()
        ia.requisitos.append(Leido(valor="El proponente debe presentar un plan de manejo de tránsito aprobado",
                                   cita="deberá presentar un plan de manejo de tránsito aprobado", seccion="5.3"))
        pendientes = fusion.sin_verificar(ia)
        self.assertEqual(len(pendientes), 2)
        quedan = fusion.sin_verificar(ia, [pendientes[0][0]])
        self.assertEqual([r for _, r, _ in quedan], [pendientes[1][1]])


class ConfirmarLoLeidoTests(SimpleTestCase):
    """Confirmar lo que la IA leyó es lo que devuelve el automatismo: a
    partir de ahí el parámetro vale como si lo hubieran leído las reglas."""

    def _tecnicos(self):
        from motor.tecnica.parametros import LoteTecnico, ParametrosTecnicos

        return ParametrosTecnicos(smmlv=1_750_905, lotes=[LoteTecnico("ÚNICO", 1e9)])

    def test_confirmar_pone_el_parametro_en_firme(self):
        parametros = self._tecnicos()
        ia = ParametrosIA(condicion_objeto={"ÚNICO": Leido(valor="DECLARADAS BIEN DE INTERÉS CULTURAL", cita="c")})

        antes = fusion.aplicar_a_tecnicos(self._tecnicos(), ia)
        self.assertEqual(len(antes.sin_confirmar), 1)

        despues = fusion.aplicar_a_tecnicos(parametros, ia,
                                            {"condición de objeto ÚNICO": "DECLARADAS BIEN DE INTERÉS CULTURAL"})
        self.assertEqual(despues.sin_confirmar, [])
        self.assertEqual(despues.procedencias["condición de objeto ÚNICO"].origen, "persona")

    def test_corregir_manda_sobre_las_dos_lecturas(self):
        parametros = self._tecnicos()
        parametros.lotes[0].fraccion_un_contrato = 0.7
        ia = ParametrosIA(fraccion_un_contrato={"ÚNICO": Leido(valor=0.3, cita="c")})
        fusion.aplicar_a_tecnicos(parametros, ia, {"porcentaje de un contrato ÚNICO": 0.4})
        self.assertEqual(parametros.lotes[0].fraccion_un_contrato, 0.4)

    def test_la_ia_separa_los_lotes_que_las_reglas_no_pudieron(self):
        """ICCU-LP-035 tiene tres lotes y el documento base no los separa:
        evaluarlo como uno solo da resultados equivocados."""
        parametros = self._tecnicos()
        ia = ParametrosIA(presupuesto_lotes={
            "LOTE 1": Leido(valor=3_542_952_462, cita="c"),
            "LOTE 2": Leido(valor=1_200_000_000, cita="c"),
        })
        resultado = fusion.aplicar_a_tecnicos(parametros, ia)
        self.assertEqual([l.nombre for l in parametros.lotes], ["LOTE 1", "LOTE 2"])
        self.assertEqual(parametros.lotes[0].presupuesto, 3_542_952_462)
        # Separarlos con la IA es una decisión que alguien tiene que confirmar.
        self.assertEqual(resultado.procedencias["lotes del proceso"].origen, "ia")

    def test_un_solo_lote_leido_por_la_ia_no_parte_el_proceso(self):
        parametros = self._tecnicos()
        ia = ParametrosIA(presupuesto_lotes={"LOTE 1": Leido(valor=3_542_952_462, cita="c")})
        fusion.aplicar_a_tecnicos(parametros, ia)
        self.assertEqual([l.nombre for l in parametros.lotes], ["ÚNICO"])


class ValoresConfirmadosTests(SimpleTestCase):
    """Lo que una persona escribe en la pantalla llega como texto. Si el
    parámetro es un número hay que convertirlo: guardarlo como texto rompía
    la evaluación entera al comparar ("'>=' not supported between float and
    str")."""

    def _tecnicos(self):
        from motor.tecnica.parametros import LoteTecnico, ParametrosTecnicos

        return ParametrosTecnicos(smmlv=1_750_905, lotes=[LoteTecnico("ÚNICO", 1e9, fraccion_un_contrato=0.7)])

    def test_un_numero_escrito_como_texto_se_convierte(self):
        ia = ParametrosIA(fraccion_un_contrato={"ÚNICO": Leido(valor=0.3, cita="c")})
        for escrito in ("0,5", "0.5", 0.5):
            parametros = self._tecnicos()
            fusion.aplicar_a_tecnicos(parametros, ia, {"porcentaje de un contrato ÚNICO": escrito})
            self.assertEqual(parametros.lotes[0].fraccion_un_contrato, 0.5, f"escrito={escrito!r}")

    def test_un_texto_que_no_es_numero_no_se_guarda(self):
        ia = ParametrosIA(fraccion_un_contrato={"ÚNICO": Leido(valor=0.3, cita="c")})
        parametros = self._tecnicos()
        resultado = fusion.aplicar_a_tecnicos(parametros, ia, {"porcentaje de un contrato ÚNICO": "la mitad"})
        # Se queda el valor de las reglas y el parámetro sigue sin confirmar.
        self.assertEqual(parametros.lotes[0].fraccion_un_contrato, 0.7)
        self.assertEqual(len(resultado.sin_confirmar), 1)

    def test_una_lista_escrita_separada_por_comas(self):
        from motor.tecnica.parametros import ParametrosTecnicos

        parametros = ParametrosTecnicos(smmlv=1_750_905, clases_unspsc={"721410"})
        ia = ParametrosIA(clases_unspsc=Leido(valor=["721214"], cita="c"))
        fusion.aplicar_a_tecnicos(parametros, ia, {"códigos UNSPSC": "721410, 721411"})
        self.assertEqual(parametros.clases_unspsc, {"721410", "721411"})
