"""Registra en una entidad la tabla de honorarios máximos del ICCU para 2026
(Resolución 1750 de 2025, experiencia profesional y reconocimiento por
experiencia calificada) y activa el módulo de prestación de servicios:

    manage.py honorarios_iccu --nit 999000001

Si la entidad ya tiene tabla de 2026, no la toca. La entidad la puede cambiar
después en Prestación de servicios → Tabla de honorarios.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from cuentas.models import Entidad
from evaluaciones.models import TablaHonorariosOps

VIGENCIA = 2026
NORMA = "Resolución 1750 de 2025"
# (desde, hasta, sin especialización, con especialización, con maestría o más)
PROFESIONAL = [
    (0, 1, 5_174_097, 6_594_086, 7_331_582),
    (1, 2, 5_817_919, 6_594_086, 7_331_582),
    (2, 5, 6_594_086, 6_594_086, 7_331_582),
    (5, 10, 7_331_582, 8_045_300, 8_730_681),
    (10, 15, 8_730_681, 9_588_365, 10_234_769),
    (15, 20, 10_234_769, 10_882_711, 11_818_094),
    (20, 30, 12_047_571, 12_678_053, 13_279_321),
    (30, None, 12_678_053, 13_279_321, 13_879_205),
]
RECONOCIMIENTO = [(1, 2, 1_525_479), (2, 5, 3_050_824), (5, 10, 4_451_495), (10, None, 5_817_658)]


class Command(BaseCommand):
    help = "Registra la tabla de honorarios 2026 del ICCU y activa el módulo de prestación de servicios."

    def add_arguments(self, parser):
        parser.add_argument("--nit", required=True)

    def handle(self, *args, **opciones):
        entidad = Entidad.objects.filter(nit=opciones["nit"]).first()
        if entidad is None:
            raise CommandError(f"No existe una entidad con NIT {opciones['nit']}.")
        _, creada = TablaHonorariosOps.objects.get_or_create(
            entidad=entidad, vigencia=VIGENCIA,
            defaults={
                "norma": NORMA,
                "profesional": [
                    {"desde": d, "hasta": h, "sin_especializacion": a, "con_especializacion": b, "con_maestria": c}
                    for d, h, a, b, c in PROFESIONAL
                ],
                "reconocimiento": [{"desde": d, "hasta": h, "valor": v} for d, h, v in RECONOCIMIENTO],
            },
        )
        self.stdout.write(f"Tabla de honorarios {VIGENCIA}: {'registrada' if creada else 'ya existía'}.")
        if not entidad.modulo_ops:
            entidad.modulo_ops = True
            entidad.save(update_fields=["modulo_ops"])
            self.stdout.write("Módulo de prestación de servicios activado.")
