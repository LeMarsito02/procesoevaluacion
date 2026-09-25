"""Qué automatizar primero, según los pliegos que ya se evaluaron.

El registro se llena solo: cada proceso deja anotado lo que su pliego exige y el
programa no sabe verificar, y aparte cuenta cuántas veces una persona tuvo que
encargarse. Eso último es lo que manda, porque es trabajo humano que se va a
volver a hacer en el siguiente proceso.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from evaluaciones.models import RequisitoNoAutomatizado


class Command(BaseCommand):
    help = "Lista los requisitos de los pliegos que el programa no verifica, por lo que más cuestan."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limite", type=int, default=30, help="cuántos mostrar (30 por defecto)")
        parser.add_argument("--clase", default="", help="exigencia | exclusion | regla_lectura")
        parser.add_argument("--area", default="", help="tecnica | financiera")
        parser.add_argument("--todos", action="store_true", help="incluir los que ya tienen verificación programada")

    def handle(self, *args, **opciones) -> None:
        filas = RequisitoNoAutomatizado.objects.all()
        if not opciones["todos"]:
            filas = filas.filter(verificacion="")
        if opciones["clase"]:
            filas = filas.filter(clase=opciones["clase"])
        if opciones["area"]:
            filas = filas.filter(area=opciones["area"])
        total = filas.count()
        if not total:
            self.stdout.write("El registro está vacío: todavía no se ha evaluado ningún proceso con pliego leído.")
            return
        self.stdout.write(f"{total} requisitos que los pliegos exigen y el programa no verifica.\n")
        self.stdout.write(f"{'ASUMIDO':>8} {'PROCS':>6} {'CLASE':<14} REQUISITO")
        for f in filas[: opciones["limite"]]:
            self.stdout.write(f"{f.veces_asumido:>8} {f.veces:>6} {f.clase:<14} {f.requisito[:96]}")
        # Las exclusiones son las que, si nadie las mira, cuentan un contrato que
        # no debía contar: conviene saber cuántas van quedando.
        exclusiones = filas.filter(clase="exclusion").count()
        if exclusiones:
            self.stdout.write(f"\nDe esos, {exclusiones} son exclusiones del pliego («no se aceptará…»): "
                              "son las que más riesgo traen si nadie las mira.")
