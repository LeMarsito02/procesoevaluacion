"""Asistente de consulta: solo lee, y solo lo que la persona puede ver."""
from __future__ import annotations

import json
from unittest import mock

from django.test import override_settings

from cuentas.aislamiento import SISTEMA, fijar_entidad
from cuentas.models import EventoAuditoria
from cuentas.tests import Cliente
from evaluaciones import asistente
from evaluaciones.models import ConversacionAsistente, MensajeAsistente
from evaluaciones.tests import BaseEvaluaciones


def _modelo(*rondas):
    """Simula a Ollama: cada ronda es una lista de fragmentos de la respuesta."""
    pendientes = list(rondas)
    vistos = []

    def conversar(mensajes, con_herramientas=False):
        vistos.append([dict(m) for m in mensajes])
        yield from pendientes.pop(0)

    return conversar, vistos


def _llamada(nombre, **argumentos):
    return {"message": {"content": "", "tool_calls": [{"function": {"name": nombre, "arguments": argumentos}}]}}


def _texto(*partes):
    return [{"message": {"content": p}} for p in partes]


class AsistenteTests(BaseEvaluaciones):
    def setUp(self):
        self.jefe, self.ev = self.crear()
        self.jefe.post(f"/api/evaluaciones/{self.ev['id']}/asignar", {"responsable_id": str(self.evaluador.id)})
        self.abogado = Cliente()
        self.abogado.entrar("abogado@entidad.gov.co")
        self.evaluar_todo(self.abogado, self.ev["id"])
        self.codigo = "ENT-CM-037-2026"

    def test_las_consultas_respetan_quien_puede_ver_la_evaluacion(self):
        # El integrante del comité ve su evaluación y el detalle de un proponente.
        mias = asistente.consultar(self.evaluador, "mis_evaluaciones", {}).datos
        self.assertEqual([m["proceso"] for m in mias], [self.codigo])
        resumen = asistente.consultar(self.evaluador, "resumen_evaluacion", {"proceso": self.codigo})
        self.assertEqual(len(resumen.datos["proponentes"]), 2)
        self.assertEqual(resumen.fuentes[0]["evaluacion_id"], self.ev["id"])
        detalle = asistente.consultar(self.evaluador, "detalle_proponente", {"proceso": self.codigo, "proponente": "1"}).datos
        estados = {r["requisito"]: r["estado"] for r in detalle["requisitos"]}
        self.assertEqual(estados[2], "pendiente de revisión")
        pendientes = asistente.consultar(self.evaluador, "pendientes", {"proceso": "cm-037"}).datos
        self.assertEqual(pendientes["total"], 2)
        # Otro abogado de la misma entidad, control interno y otra entidad: nada.
        for ajeno in (self.abogado2, self.consulta, self.eval_otra):
            self.assertEqual(asistente.consultar(ajeno, "mis_evaluaciones", {}).datos, [], ajeno.email)
            for herramienta in ("resumen_evaluacion", "pendientes", "requisitos"):
                datos = asistente.consultar(ajeno, herramienta, {"proceso": self.codigo}).datos
                self.assertEqual(list(datos), ["no_encontrado"], (ajeno.email, herramienta))

    def test_la_decision_de_una_persona_se_informa_con_su_nombre(self):
        pid = self.abogado.get(f"/api/evaluaciones/{self.ev['id']}").json()["proponentes"][0]["id"]
        r = self.abogado.put(f"/api/evaluaciones/{self.ev['id']}/revisiones", {"proponente_id": pid, "requisito": 2, "cumple": True, "nota": "Revisado contra el certificado aportado"})
        self.assertEqual(r.status_code, 200, r.content)
        detalle = asistente.consultar(self.evaluador, "detalle_proponente", {"proceso": self.codigo, "proponente": "1"}).datos
        fila = next(x for x in detalle["requisitos"] if x["requisito"] == 2)
        self.assertEqual((fila["estado"], fila["origen"]), ("cumple", "decidido por Abogado Uno"))

    def test_herramienta_desconocida_o_argumentos_raros_no_rompen_ni_escriben(self):
        self.assertIn("error", asistente.consultar(self.evaluador, "borrar_todo", {"proceso": self.codigo}).datos)
        raro = asistente.consultar(self.evaluador, "resumen_evaluacion", {"proceso": self.codigo, "sql": "DROP TABLE"})
        self.assertEqual(raro.datos["proceso"], self.codigo)
        # Sin indicar el proceso, y con una sola evaluación a su cargo, es esa.
        self.assertEqual(asistente.consultar(self.evaluador, "resumen_evaluacion", {}).datos["proceso"], self.codigo)

    @override_settings(ASISTENTE_HERRAMIENTAS=True)
    def test_pregunta_consulta_responde_guarda_y_audita(self):
        conversar, vistos = _modelo([_llamada("pendientes", proceso=self.codigo)], _texto("Faltan ", "2 revisiones."))
        cid = self.abogado.post("/api/asistente/conversaciones").json()["id"]
        with mock.patch("evaluaciones.asistente._conversar", conversar):
            r = self.abogado.post(f"/api/asistente/conversaciones/{cid}/mensajes", {"texto": "¿Qué me falta en el CM-037?"})
            self.assertEqual(r.status_code, 200)
            eventos = [json.loads(linea) for linea in b"".join(r.streaming_content).splitlines()]
        self.assertEqual([e["tipo"] for e in eventos], ["consulta", "texto", "texto", "fuentes", "fin"])
        # Al modelo le llegó el resultado de la herramienta, no la base de datos.
        herramienta = next(m for m in vistos[1] if m["role"] == "tool")
        self.assertEqual(json.loads(herramienta["content"])["total"], 2)
        guardados = list(MensajeAsistente.objects.filter(conversacion_id=cid).values_list("rol", "contenido"))
        self.assertEqual(guardados, [("usuario", "¿Qué me falta en el CM-037?"), ("asistente", "Faltan 2 revisiones.")])
        respuesta = MensajeAsistente.objects.get(conversacion_id=cid, rol="asistente")
        self.assertEqual(respuesta.consultas, ["pendientes"])
        self.assertEqual(respuesta.fuentes[0]["evaluacion_id"], self.ev["id"])
        evento = EventoAuditoria.objects.filter(accion="asistente.respuesta").latest("id")
        self.assertEqual(evento.detalles["evaluaciones"], [self.ev["id"]])
        detalle = self.abogado.get(f"/api/asistente/conversaciones/{cid}").json()
        self.assertEqual(detalle["titulo"], "¿Qué me falta en el CM-037?")
        self.assertEqual(len(detalle["mensajes"]), 2)

    def test_las_conversaciones_son_personales(self):
        cid = self.abogado.post("/api/asistente/conversaciones").json()["id"]
        for email in ("abogado2@entidad.gov.co", "admin@entidad.gov.co", "admin@otraentidad.gov.co"):
            c = Cliente()
            c.entrar(email)
            self.assertEqual(c.get(f"/api/asistente/conversaciones/{cid}").status_code, 404, email)
            self.assertEqual(c.post(f"/api/asistente/conversaciones/{cid}/mensajes", {"texto": "hola"}).status_code, 404, email)
            self.assertEqual(c.get("/api/asistente").json()["conversaciones"], [], email)
        # La última petición dejó la conexión limitada a otra entidad: desde ahí la fila ni existe.
        self.assertFalse(ConversacionAsistente.objects.filter(pk=cid).exists())
        fijar_entidad(SISTEMA)
        self.assertEqual(ConversacionAsistente.objects.get(pk=cid).entidad_id, self.entidad1.id)

    def test_si_el_modelo_no_responde_se_avisa_y_no_se_guarda_respuesta(self):
        def caido(mensajes, con_herramientas=False):
            raise OSError("sin conexión")
            yield  # pragma: no cover

        cid = self.abogado.post("/api/asistente/conversaciones").json()["id"]
        with mock.patch("evaluaciones.asistente._conversar", caido):
            r = self.abogado.post(f"/api/asistente/conversaciones/{cid}/mensajes", {"texto": "¿Cómo va mi evaluación?"})
            eventos = [json.loads(linea) for linea in b"".join(r.streaming_content).splitlines()]
        self.assertEqual([e["tipo"] for e in eventos], ["error", "fin"])
        self.assertFalse(MensajeAsistente.objects.filter(conversacion_id=cid, rol="asistente").exists())

    @override_settings(ASISTENTE_HERRAMIENTAS=True)
    def test_el_modelo_no_puede_consultar_sin_fin(self):
        rondas = [[_llamada("mis_evaluaciones")] for _ in range(asistente.MAX_RONDAS)]
        conversar, vistos = _modelo(*rondas)
        with mock.patch("evaluaciones.asistente._conversar", conversar):
            eventos = list(asistente.responder(self.evaluador, [{"rol": "usuario", "contenido": "¿Cómo va mi evaluación?"}]))
        self.assertEqual(len(vistos), asistente.MAX_RONDAS)
        self.assertIn("No alcancé", eventos[-2]["texto"])

    def test_pregunta_vacia_o_enorme_se_rechaza(self):
        cid = self.abogado.post("/api/asistente/conversaciones").json()["id"]
        self.assertEqual(self.abogado.post(f"/api/asistente/conversaciones/{cid}/mensajes", {"texto": "   "}).status_code, 400)
        self.assertEqual(self.abogado.post(f"/api/asistente/conversaciones/{cid}/mensajes", {"texto": "x" * 2001}).status_code, 400)

    def test_saluda_sin_consultar_al_modelo(self):
        with mock.patch("evaluaciones.asistente._conversar", side_effect=AssertionError("no debe llamar al modelo")):
            for saludo in ("holaa", "Hola!", "buenos días", "¡Buenas tardes!", "gracias", "muchas gracias!!", "chao"):
                eventos = list(asistente.responder(self.evaluador, [{"rol": "usuario", "contenido": saludo}]))
                self.assertEqual([e["tipo"] for e in eventos], ["texto"], saludo)
            self.assertIn("Abogado", asistente.cortesia("hola", self.evaluador))
        # Una pregunta que empieza con un saludo sí va al modelo.
        for pregunta in ("hola, ¿qué me falta por revisar?", "buenas, cómo va el CM-037", "gracias, y el proponente 2?"):
            self.assertIsNone(asistente.cortesia(pregunta, self.evaluador), pregunta)

    def test_la_ia_recibe_los_datos_de_la_evaluacion_elegida_sin_pedirlos(self):
        conversar, vistos = _modelo(_texto("Listo."))
        r = self.abogado.post("/api/asistente/conversaciones", {"evaluacion_id": self.ev["id"]})
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()["id"]
        with mock.patch("evaluaciones.asistente._conversar", conversar):
            r = self.abogado.post(f"/api/asistente/conversaciones/{cid}/mensajes",
                                  {"texto": "¿Qué me falta por revisar?", "evaluacion_id": self.ev["id"], "cambiar_evaluacion": True})
            eventos = [json.loads(linea) for linea in b"".join(r.streaming_content).splitlines()]
        pregunta = vistos[0][-1]["content"]
        self.assertTrue(pregunta.startswith("¿Qué me falta por revisar?"))
        self.assertIn("DATOS DEL SISTEMA", pregunta)
        self.assertIn(f"proceso {self.codigo} · área Jurídica", pregunta)
        self.assertIn("PENDIENTES DE REVISIÓN EN TODA LA EVALUACIÓN: 2", pregunta)
        self.assertEqual(pregunta.count("pendientes 1"), 2)  # resumen por proponente
        # Lo que se guarda es la pregunta de la persona, sin los datos añadidos.
        self.assertEqual(MensajeAsistente.objects.get(conversacion_id=cid, rol="usuario").contenido, "¿Qué me falta por revisar?")
        # La evaluación de donde salieron los datos se cita aunque la IA no consulte nada más.
        self.assertEqual(next(e for e in eventos if e["tipo"] == "fuentes")["fuentes"][0]["evaluacion_id"], self.ev["id"])
        # El chat de dentro de la evaluación solo lista las conversaciones sobre ella.
        otra = self.abogado.post("/api/asistente/conversaciones").json()["id"]
        en_evaluacion = self.abogado.get(f"/api/asistente?evaluacion_id={self.ev['id']}").json()
        self.assertEqual([c["id"] for c in en_evaluacion["conversaciones"]], [cid])
        todas = self.abogado.get("/api/asistente").json()
        self.assertEqual({c["id"] for c in todas["conversaciones"]}, {cid, otra})
        self.assertEqual([o["id"] for o in todas["evaluaciones"]], [self.ev["id"]])

    def test_no_se_puede_elegir_una_evaluacion_ajena(self):
        ajeno = Cliente()
        ajeno.entrar("abogado2@entidad.gov.co")
        self.assertEqual(ajeno.get("/api/asistente").json()["evaluaciones"], [])
        self.assertEqual(ajeno.post("/api/asistente/conversaciones", {"evaluacion_id": self.ev["id"]}).status_code, 404)
        self.assertEqual(ajeno.get(f"/api/asistente?evaluacion_id={self.ev['id']}").status_code, 404)
        cid = ajeno.post("/api/asistente/conversaciones").json()["id"]
        r = ajeno.post(f"/api/asistente/conversaciones/{cid}/mensajes",
                       {"texto": "¿Cómo va?", "evaluacion_id": self.ev["id"], "cambiar_evaluacion": True})
        self.assertEqual(r.status_code, 404)

    def test_quien_sale_del_comite_deja_de_recibir_datos_en_su_conversacion(self):
        cid = self.abogado.post("/api/asistente/conversaciones", {"evaluacion_id": self.ev["id"]}).json()["id"]
        r = self.jefe.post(f"/api/evaluaciones/{self.ev['id']}/asignar", {"responsable_id": str(self.abogado2.id)})
        self.assertEqual(r.status_code, 200, r.content)
        conversar, vistos = _modelo(_texto("No tengo datos."))
        with mock.patch("evaluaciones.asistente._conversar", conversar):
            r = self.abogado.post(f"/api/asistente/conversaciones/{cid}/mensajes", {"texto": "¿Qué me falta por revisar?"})
            b"".join(r.streaming_content)
        enviado = "\n".join(m["content"] for m in vistos[0])
        self.assertNotIn(self.codigo, enviado)
        self.assertIn("no tiene evaluaciones a su cargo", enviado)

    def test_reconoce_al_proponente_aunque_lo_nombren_distinto(self):
        from types import SimpleNamespace as P

        lista = [
            P(hoja="P-100", numero_orden=100, nombre="SOCIEDAD TECNICA SOTA S.A.S"),
            P(hoja="P-104", numero_orden=104, nombre="SOLUCIONES PARA LA INGENIERIA S.A.S"),
            P(hoja="P-102", numero_orden=102, nombre="COMPANIA TECNICA DE INGENIERIA SAS"),
            P(hoja="P-10", numero_orden=10, nombre="CONSORCIO INTERVIAS COLOMBIA"),
            P(hoja="P-103", numero_orden=103, nombre="CONSORCIO INTERVIAL 2026"),
        ]
        casos = {
            "no entiendo, que debo revisar de soluciones para ingenieria sas": ["P-104"],
            "¿qué le falta a Soluciones para la Ingeniería?": ["P-104"],
            "y la compañía técnica de ingeniería?": ["P-102"],
            "qué pasa con sota": ["P-100"],
            "revisa el P-10": ["P-10"],
            "revisa el p 103 porfa": ["P-103"],
            "y el proponente 104": ["P-104"],
            "intervias colombia": ["P-10"],
            "¿qué me falta por revisar?": [],
            "¿qué es la ingeniería de detalle?": [],
        }
        for texto, esperado in casos.items():
            self.assertEqual([p.hoja for p in asistente.mencionados(lista, texto)], esperado, texto)

    def test_si_la_pregunta_nombra_a_un_proponente_lleva_su_detalle(self):
        datos, _, _ = asistente.contexto(self.evaluador, None, "¿qué debo revisar del proponente 1?")
        self.assertIn("DETALLE DE", datos)
        self.assertIn("Pendientes de revisión (1):", datos)
        self.assertNotIn("DETALLE DE", asistente.contexto(self.evaluador, None, "¿cómo va la evaluación?")[0])
        # Una herramienta que no identifica al proponente no debe leerse como «no tiene pendientes».
        fallo = asistente.consultar(self.evaluador, "detalle_proponente", {"proceso": self.codigo, "proponente": "zzz inexistente"}).datos
        self.assertIn("NO significa que no tenga pendientes", fallo["no_encontrado"])

    def test_con_la_ia_ocupada_la_pregunta_espera_turno_y_no_se_cuelga(self):
        from django.test import override_settings

        from api import asistente as api_asistente

        cid = self.abogado.post("/api/asistente/conversaciones").json()["id"]
        ocupados = [api_asistente._turnos.acquire(blocking=False) for _ in range(5)]
        try:
            with override_settings(ASISTENTE_ESPERA_MAX=0.05), mock.patch("evaluaciones.asistente._conversar", side_effect=AssertionError("sin turno no se llama al modelo")):
                r = self.abogado.post(f"/api/asistente/conversaciones/{cid}/mensajes", {"texto": "¿Cómo va mi evaluación?"})
                eventos = [json.loads(linea) for linea in b"".join(r.streaming_content).splitlines()]
        finally:
            for tomado in ocupados:
                if tomado:
                    api_asistente._turnos.release()
        self.assertEqual([e["tipo"] for e in eventos], ["espera", "error", "fin"])
        self.assertIn("muchas consultas", eventos[1]["texto"])
        # Liberado el turno, la misma persona puede volver a preguntar.
        conversar, _ = _modelo(_texto("Va bien."))
        with mock.patch("evaluaciones.asistente._conversar", conversar):
            r = self.abogado.post(f"/api/asistente/conversaciones/{cid}/mensajes", {"texto": "¿Cómo va mi evaluación?"})
            self.assertEqual(json.loads(b"".join(r.streaming_content).splitlines()[-1])["tipo"], "fin")

    def test_una_pregunta_a_la_vez_por_persona(self):
        from api import asistente as api_asistente

        cid = self.abogado.post("/api/asistente/conversaciones").json()["id"]
        self.assertTrue(api_asistente._ocupar(self.evaluador.id))
        try:
            r = self.abogado.post(f"/api/asistente/conversaciones/{cid}/mensajes", {"texto": "¿Cómo va mi evaluación?"})
            self.assertEqual(r.status_code, 429)
        finally:
            api_asistente._liberar(self.evaluador.id)

    def _segunda_evaluacion(self):
        _, otra = self.crear(codigo="ENT-LP-027-2026")
        self.jefe.post(f"/api/evaluaciones/{otra['id']}/asignar", {"responsable_id": str(self.evaluador.id)})
        return otra

    def test_sin_evaluacion_elegida_entrega_todas_y_nunca_un_no_encontre(self):
        otra = self._segunda_evaluacion()
        datos, fuentes, referencia = asistente.contexto(self.evaluador, None, "¿Qué me falta por revisar?")
        self.assertIn("La persona tiene 2 evaluaciones a su cargo", datos)
        self.assertIn(f"proceso {self.codigo} · área Jurídica", datos)
        self.assertIn("proceso ENT-LP-027-2026 · área Jurídica", datos)
        # La que tiene pendientes va con su detalle, lista para responder.
        self.assertIn("PENDIENTES DE REVISIÓN EN TODA LA EVALUACIÓN: 2", datos)
        self.assertIsNone(referencia)
        self.assertEqual({f["evaluacion_id"] for f in fuentes}, {self.ev["id"], otra["id"]})
        # Si la pregunta nombra el proceso, aunque sea a medias, se detalla ese y queda de referencia.
        for pregunta in ("¿cómo va el lp 027?", "qué falta en el 027", "ENT-LP-027-2026", "y la jurídica del LP-027?"):
            datos, _, referencia = asistente.contexto(self.evaluador, None, pregunta)
            self.assertIn("DETALLE (la pregunta nombra este proceso)", datos, pregunta)
            self.assertEqual(str(referencia.id), otra["id"], pregunta)
        # Y si nombra a un proponente, se busca en sus procesos.
        nombre = self.abogado.get(f"/api/evaluaciones/{self.ev['id']}").json()["proponentes"][0]["nombre_proponente"]
        datos, _, _ = asistente.contexto(self.evaluador, None, f"¿qué le falta a {nombre}?")
        self.assertIn("DETALLE DE", datos)

    def test_las_consultas_toleran_que_no_se_indique_bien_el_proceso(self):
        from evaluaciones.models import Evaluacion

        otra = self._segunda_evaluacion()
        elegida = Evaluacion.objects.get(pk=otra["id"])
        # Con una evaluación en la conversación, «todas», vacío o «actual» son esa.
        for proceso in ("", "todas", "la actual", "mi evaluación"):
            r = asistente.consultar(self.evaluador, "pendientes", {"proceso": proceso}, elegida)
            self.assertEqual(r.datos.get("proceso"), "ENT-LP-027-2026", proceso)
        # Un código a medias sirve; uno que no existe lista las disponibles en vez de decir «no hay».
        self.assertEqual(asistente.consultar(self.evaluador, "pendientes", {"proceso": "cm 037"}).datos["proceso"], self.codigo)
        fallo = asistente.consultar(self.evaluador, "pendientes", {"proceso": "XYZ-999"}).datos["no_encontrado"]
        self.assertIn(self.codigo, fallo)
        self.assertIn("ENT-LP-027-2026", fallo)
        sin_elegir = asistente.consultar(self.evaluador, "pendientes", {"proceso": ""}).datos["no_encontrado"]
        self.assertIn("Pregunte a la persona de cuál", sin_elegir)

    def test_el_numero_del_proceso_no_se_confunde_con_el_ano_ni_con_un_proponente(self):
        from types import SimpleNamespace as N

        def ev(codigo, tipo, pid):
            return N(proceso=N(codigo=codigo), proceso_id=pid, tipo=tipo)

        lista = [ev("ICCU-CM-043-2026", "juridica", 1), ev("ICCU-CM-043-2026", "tecnica", 1), ev("ICCU-LP-027-2026", "financiera", 2)]
        casos = {
            "qué me falta en el cm-043": [0, 1],
            "y la técnica del 043?": [1],
            "ICCU-LP-027-2026": [2],
            "lp027 financiera": [2],
            "¿qué pasó en 2026?": [],
            "¿qué me falta por revisar?": [],
        }
        for texto, esperado in casos.items():
            self.assertEqual([lista.index(e) for e in asistente.procesos_mencionados(lista, texto)], esperado, texto)
        self.assertEqual(asistente.mencionados([N(hoja="P-43", numero_orden=43, nombre="CONSORCIO ALFA")], "qué falta en el 043"), [])

    def test_por_defecto_el_modelo_solo_redacta_con_los_datos_del_servidor(self):
        enviados = []

        def conversar(mensajes, con_herramientas=False):
            enviados.append(con_herramientas)
            # Aunque el modelo intente pedir una herramienta, no se le hace caso.
            yield _llamada("pendientes", proceso="")
            yield from _texto("Le faltan 2.")

        with mock.patch("evaluaciones.asistente._conversar", conversar):
            eventos = list(asistente.responder(self.evaluador, [{"rol": "usuario", "contenido": "¿Qué me falta por revisar?"}]))
        self.assertEqual(enviados, [False])
        self.assertEqual([e["tipo"] for e in eventos], ["texto", "fuentes"])
        datos, _, _ = asistente.contexto(self.evaluador, None, "¿qué requisitos se verifican?")
        self.assertIn("REQUISITOS QUE SE VERIFICAN EN ESTA EVALUACIÓN (17):", datos)
        self.assertNotIn("PENDIENTES DE REVISIÓN EN TODA", datos)
        casos = {
            "¿Qué requisitos se verifican en la jurídica del demo cm 043?": True, "¿Qué se verifica?": True,
            "cuáles son los requisitos": True, "¿Qué me falta por revisar?": False,
            "que debo revisar de soluciones para ingenieria": False, "¿por qué el requisito 11 quedó pendiente?": False,
            "qué proponentes tienen requisitos que no cumplen": False,
        }
        for texto, esperado in casos.items():
            self.assertEqual(bool(asistente._PIDE_REQUISITOS.search(asistente._plano(texto))), esperado, texto)

    def test_entre_dos_procesos_con_el_mismo_numero_gana_el_que_se_nombra_completo(self):
        from types import SimpleNamespace as N

        def ev(codigo, tipo, pid):
            return N(proceso=N(codigo=codigo), proceso_id=pid, tipo=tipo)

        lista = [ev("DEMO-CM-043-2026", "tecnica", 1), ev("ICCU-CM-043-2026", "tecnica", 2), ev("DEMO-PRUEBA-2026", "tecnica", 3)]
        casos = {
            "que me falta en el iccu cm 043 tecnica": [1],
            "y el demo cm 043": [0],
            "el cm 043": [0, 1],
            "cómo va demo prueba": [2],
            "hagamos una prueba": [],
        }
        for texto, esperado in casos.items():
            self.assertEqual([lista.index(e) for e in asistente.procesos_mencionados(lista, texto)], esperado, texto)
