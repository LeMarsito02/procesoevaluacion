"""Aplica a las evaluaciones en curso las reglas vigentes del pliego: quita
los resultados de requisitos que ya no se exigen (formatos de puntaje,
duplicados de lo que el motor ya verifica). Las aprobadas no se tocan."""
from django.core.management.base import BaseCommand
from django.db import connection

from evaluaciones import servicios
from evaluaciones.models import Evaluacion


class Command(BaseCommand):
    help = "Quita los resultados de requisitos que las reglas vigentes ya no exigen."

    def handle(self, *args, **opciones):
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.entidad_id', '*', false)")
        total = 0
        for evaluacion in Evaluacion.objects.select_related("proceso"):
            borrados = servicios.depurar_requisitos_retirados(evaluacion)
            if borrados:
                self.stdout.write(f"{evaluacion.proceso.codigo} ({evaluacion.get_tipo_display()}): {borrados} resultados retirados")
            total += borrados
        self.stdout.write(self.style.SUCCESS(f"Listo: {total} resultados de requisitos que ya no se exigen."))
