from django.core.management.base import BaseCommand

from evaluaciones.retencion import aplicar


class Command(BaseCommand):
    help = "Borra documentos de proponentes de procesos aprobados hace más de RETENCION_DIAS (correr a diario)."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=None)
        parser.add_argument("--simulacro", action="store_true", help="Solo informa qué se borraría.")

    def handle(self, *args, **opciones):
        informe = aplicar(opciones["dias"], simulacro=opciones["simulacro"])
        prefijo = "Se borrarían" if opciones["simulacro"] else "Borrados"
        self.stdout.write(
            f"{prefijo}: {len(informe.procesos)} procesos ({', '.join(informe.procesos) or '—'}), "
            f"{informe.archivos_ofertas} archivos de ofertas, {informe.archivos_cache} de caché, "
            f"{informe.bytes_liberados / 1e6:.1f} MB."
        )
