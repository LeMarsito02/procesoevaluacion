"""Al crear el proceso se puede designar el comité completo, no solo el responsable."""
from django.core import mail

from cuentas.tests import Cliente
from evaluaciones.models import Evaluacion
from evaluaciones.tests import DOCUMENTO_BASE, PROPONENTES, BaseEvaluaciones


class ComiteAlCrearTests(BaseEvaluaciones):
    def setUp(self):
        self.jefe = Cliente()
        self.jefe.entrar("jefe@entidad.gov.co")

    def _crear(self, codigo, **extra):
        return self.jefe.post("/api/evaluaciones/procesos", {
            "documento_base": {**DOCUMENTO_BASE, "codigo_proceso": codigo}, "carpeta_drive": "x", "proponentes": PROPONENTES, **extra})

    def test_responsable_y_mas_integrantes(self):
        with self.captureOnCommitCallbacks(execute=True):
            r = self._crear("ENT-COM-1", responsables={"juridica": str(self.evaluador.id)},
                            comites={"juridica": [str(self.abogado2.id), str(self.evaluador.id)]})
        self.assertEqual(r.status_code, 201, r.content[:300])
        ev = Evaluacion.objects.get(pk=r.json()[0]["id"])
        miembros = list(ev.comite.filter(retirado_en__isnull=True).order_by("designado_en").values_list("usuario__email", flat=True))
        self.assertEqual(ev.responsable_id, self.evaluador.id)
        self.assertEqual(sorted(miembros), ["abogado2@entidad.gov.co", "abogado@entidad.gov.co"])
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["abogado2@entidad.gov.co", "abogado@entidad.gov.co"])

    def test_sin_responsable_no_hay_comite_y_el_area_se_valida(self):
        r = self._crear("ENT-COM-2", comites={"juridica": [str(self.abogado2.id)]}, sin_responsable=True)
        self.assertEqual(r.status_code, 400)
        self.assertIn("responsable", r.json()["detail"])
        r = self._crear("ENT-COM-3", responsables={"juridica": str(self.evaluador.id)}, comites={"juridica": [str(self.tecnico.id)]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("no pertenece al área", r.json()["detail"])
