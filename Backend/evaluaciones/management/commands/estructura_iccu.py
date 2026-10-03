"""Crea en una entidad la estructura de evaluación del ICCU (ver
docs/normas y el organigrama de roles):

- Jurídica: Dirección Jurídica y Subdirección de Gestión Contractual.
- Financiera: Dirección Financiera.
- Técnica, según el contrato: Área de Construcciones, Caminos e
  Infraestructura Vial y Área de Concesiones.

    manage.py estructura_iccu --nit 999000001

No toca las dependencias que ya existan con el mismo nombre. Los jefes e
integrantes se asignan después en Configuración → Estructura de evaluación.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from cuentas.models import Entidad
from evaluaciones.models import Dependencia

ESTRUCTURA = [
    ("juridica", "Dirección Jurídica y Subdirección de Gestión Contractual", ""),
    ("financiera", "Dirección Financiera", ""),
    ("tecnica", "Área de Construcciones", "construcción\nedificación\nedificio\ncolegio\nsede\nescenario deportivo\nestructura"),
    ("tecnica", "Caminos e Infraestructura Vial", "vía\nvial\ncarretera\npavimento\nmalla vial\nmejoramiento\nrehabilitación\nmantenimiento\npuente"),
    ("tecnica", "Área de Concesiones", "concesión\nconcesionario\nAPP\nasociación público privada\npeaje"),
]


class Command(BaseCommand):
    help = "Crea la estructura de evaluación del ICCU en una entidad."

    def add_arguments(self, parser):
        parser.add_argument("--nit", required=True)

    def handle(self, *args, **opciones):
        entidad = Entidad.objects.filter(nit=opciones["nit"]).first()
        if entidad is None:
            raise CommandError(f"No existe una entidad con NIT {opciones['nit']}.")
        for orden, (tipo, nombre, palabras) in enumerate(ESTRUCTURA):
            _, creada = Dependencia.objects.get_or_create(
                entidad=entidad, tipo=tipo, nombre=nombre, defaults={"palabras_clave": palabras, "orden": orden}
            )
            self.stdout.write(f"{'Creada' if creada else 'Ya existía'}: {nombre}")
