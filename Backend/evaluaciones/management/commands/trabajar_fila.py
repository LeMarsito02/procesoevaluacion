import asyncio
import logging
import os

from django.core.management.base import BaseCommand

from evaluaciones.trabajador import trabajar


class Command(BaseCommand):
    help = "Atiende la fila central de evaluaciones (correr uno o varios en paralelo)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--capacidad",
            type=int,
            default=int(os.environ.get("MAX_WORKERS", "2")),
            help="Proponentes evaluados a la vez (por defecto MAX_WORKERS o 2).",
        )
        parser.add_argument("--una-vez", action="store_true", help="Sale cuando la fila queda vacía.")

    def handle(self, *args, **opciones):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        asyncio.run(trabajar(opciones["capacidad"], una_vez=opciones["una_vez"]))
