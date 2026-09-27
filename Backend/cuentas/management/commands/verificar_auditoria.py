"""Comprueba que la auditoría no fue alterada: recalcula la cadena de huellas
de todos los eventos, en orden, y dice dónde se rompe si alguien modificó,
insertó o borró eventos directamente en la base de datos.

    python manage.py verificar_auditoria
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from cuentas.models import EventoAuditoria


def verificar() -> tuple[int, EventoAuditoria | None]:
    """Eventos verificados y el primero cuya huella no coincide (None si todo cuadra)."""
    anterior = ""
    n = 0
    for evento in EventoAuditoria.objects.order_by("id").iterator():
        esperada = EventoAuditoria.calcular_huella(anterior, evento.contenido_para_huella())
        if evento.huella != esperada:
            return n, evento
        anterior = evento.huella
        n += 1
    return n, None


class Command(BaseCommand):
    help = "Verifica la cadena de huellas de la auditoría."

    def handle(self, *args, **opciones):
        n, roto = verificar()
        if roto is not None:
            raise CommandError(
                f"La cadena de la auditoría se rompe en el evento {roto.pk} ({roto.fecha:%Y-%m-%d %H:%M}, "
                f"«{roto.accion}»), después de {n} eventos correctos: fue modificado, o se borró o insertó "
                "un evento antes de él."
            )
        self.stdout.write(self.style.SUCCESS(f"Auditoría íntegra: {n} eventos verificados."))
