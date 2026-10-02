"""Deja constancia, dentro de la propia auditoría, de un hueco en la cadena.

    python manage.py documentar_brecha_auditoria --motivo "..." --por "Nombre y cargo"

Si se borraron eventos de la auditoría (p. ej., al eliminar a la fuerza una
cuenta, que exige desactivar la protección), la cadena de huellas se rompe y
`verificar_auditoria` lo señala. La cadena NO se recalcula —eso sería
falsificarla—: se registra un evento que dice qué eventos faltan, por qué y
quién lo autorizó, anclado a la huella y al contenido del evento que sigue al
hueco. Desde entonces el verificador informa el hueco y sigue verificando.

Solo documenta la primera rotura, y solo si antes de ella falta algún número
de evento (si no falta ninguno, el evento fue modificado: es un incidente).
Ojo: PostgreSQL también deja números sin usar cuando una transacción se
revierte, así que un número faltante no prueba por sí solo un borrado; por eso
la constancia exige motivo y responsable. Para borrar cuentas, lo indicado es
desactivarlas.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from cuentas.aislamiento import SISTEMA, fijar_entidad
from cuentas.management.commands.verificar_auditoria import ACCION_BRECHA, huella_contenido, verificar
from cuentas.models import EventoAuditoria
from cuentas.seguridad import auditar


class Command(BaseCommand):
    help = "Documenta en la auditoría un hueco de eventos borrados (sin recalcular la cadena)."

    def add_arguments(self, parser):
        parser.add_argument("--motivo", required=True, help="Por qué faltan los eventos")
        parser.add_argument("--por", required=True, help="Quién autorizó o responde por el borrado")

    def handle(self, *args, **opciones):
        fijar_entidad(SISTEMA)
        _, roto, _ = verificar()
        if roto is None:
            raise CommandError("La cadena de la auditoría está íntegra: no hay nada que documentar.")
        previo = EventoAuditoria.objects.filter(pk__lt=roto.pk).order_by("-pk").values_list("pk", flat=True).first() or 0
        faltantes = list(range(previo + 1, roto.pk))
        if not faltantes:
            raise CommandError(
                f"La cadena se rompe en el evento {roto.pk} sin que falte ningún evento antes: fue MODIFICADO. "
                "Eso no se documenta como hueco; es un incidente de seguridad."
            )
        auditar(
            None,
            ACCION_BRECHA,
            entidad_id=None,
            evento=roto.pk,
            faltantes=faltantes,
            huella_evento=roto.huella,
            contenido_evento=huella_contenido(roto),
            motivo=opciones["motivo"].strip(),
            por=opciones["por"].strip(),
        )
        self.stdout.write(self.style.SUCCESS(
            f"Documentado: faltan los eventos {', '.join(map(str, faltantes))} antes del {roto.pk}. "
            "Corra verificar_auditoria para comprobar el resto de la cadena."
        ))
