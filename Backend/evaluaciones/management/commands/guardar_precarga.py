"""Guarda los resultados de un proceso ya evaluado como precarga de demostración.

Los resultados quedan en disco, indexados por el CONTENIDO de cada oferta
(sha256 del zip), no por el proceso. Así, en la demostración, el usuario sube en
vivo las mismas ofertas bajo un código que empiece por «DEMO-» y el trabajador
las restaura en segundos (evaluaciones/precarga.py), en vez de evaluar de nuevo.

    manage.py guardar_precarga ICCU-LP-027-2026

Se corre sobre un proceso REAL ya evaluado (y con los requisitos del pliego ya
confirmados, para que los números sean los definitivos).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from evaluaciones import precarga, servicios
from evaluaciones.models import Evaluacion, Proceso, Proponente, Resultado


class Command(BaseCommand):
    help = "Guarda los resultados de un proceso evaluado como precarga de demostración."

    def add_arguments(self, parser):
        parser.add_argument("codigo", help="Código del proceso ya evaluado")

    def handle(self, *args, **opciones):
        proceso = Proceso.objects.filter(codigo=opciones["codigo"]).order_by("-creado_en").first()
        if proceso is None:
            raise CommandError(f"No existe el proceso {opciones['codigo']}.")

        evaluaciones = list(Evaluacion.objects.filter(proceso=proceso))
        if not evaluaciones:
            raise CommandError("El proceso no tiene evaluaciones.")

        guardados = 0
        for proponente in Proponente.objects.filter(proceso=proceso).order_by("numero_orden"):
            huella = precarga.huella_de(servicios.proponente_motor(proponente))
            if not huella:
                self.stderr.write(f"  {proponente.hoja}: no se pudo leer la oferta, se omite.")
                continue
            for evaluacion in evaluaciones:
                datos = list(
                    Resultado.objects.filter(evaluacion=evaluacion, proponente=proponente)
                    .order_by("requisito")
                    .values_list("datos", flat=True)
                )
                if not datos:
                    continue
                precarga.guardar(huella, evaluacion.tipo, datos)
                guardados += 1
            self.stdout.write(f"  {proponente.hoja} · {proponente.nombre[:40]} · {huella[:12]}…")

        self.stdout.write(
            self.style.SUCCESS(
                f"Precarga guardada: {guardados} archivos en {precarga.DIR_PRECARGA} "
                f"({len(evaluaciones)} áreas × proponentes de {proceso.codigo})."
            )
        )
