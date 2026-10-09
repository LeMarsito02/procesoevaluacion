from django.core.management.base import BaseCommand

from evaluaciones.retencion import aplicar


class Command(BaseCommand):
    help = "Borra documentos de procesos aprobados y de prestaciones de servicios confirmadas hace más de RETENCION_DIAS (correr a diario)."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=None)
        parser.add_argument("--simulacro", action="store_true", help="Solo informa qué se borraría.")

    def handle(self, *args, **opciones):
        informe = aplicar(opciones["dias"], simulacro=opciones["simulacro"])
        if not opciones["simulacro"]:
            # Procesos a medio crear que nadie retomó.
            from evaluaciones.preparacion import DIAS_DE_VIDA, borrar_vencidas

            self.stdout.write(f"Procesos a medio crear borrados (más de {DIAS_DE_VIDA} días): {borrar_vencidas()}.")
            from evaluaciones import subidas

            self.stdout.write(f"Subidas de ofertas abandonadas borradas: {subidas.borrar_vencidas()}.")
        prefijo = "Se borrarían" if opciones["simulacro"] else "Borrados"
        self.stdout.write(
            f"{prefijo}: {len(informe.procesos)} procesos ({', '.join(informe.procesos) or '—'}), "
            f"{informe.contrataciones} prestaciones de servicios ({informe.archivos_ops} documentos), "
            f"{informe.archivos_ofertas} archivos de ofertas, {informe.archivos_cache} de caché, "
            f"{informe.bytes_liberados / 1e6:.1f} MB."
        )
