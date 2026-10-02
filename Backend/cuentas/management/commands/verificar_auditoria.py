"""Comprueba que la auditoría no fue alterada: recalcula la cadena de huellas
de todos los eventos, en orden, y dice dónde se rompe si alguien modificó,
insertó o borró eventos directamente en la base de datos.

    python manage.py verificar_auditoria
"""
from __future__ import annotations

import hashlib

from django.core.management.base import BaseCommand, CommandError

from cuentas.models import EventoAuditoria


ACCION_BRECHA = "auditoria.brecha_documentada"


def huella_contenido(evento: EventoAuditoria) -> str:
    return hashlib.sha256(evento.contenido_para_huella().encode()).hexdigest()


def brechas_documentadas() -> dict[int, dict]:
    """Huecos de la cadena que alguien dejó documentados (evento → detalles)."""
    return {
        int(e.detalles["evento"]): {**e.detalles, "documentado_en": e.pk}
        for e in EventoAuditoria.objects.filter(accion=ACCION_BRECHA)
        if str(e.detalles.get("evento", "")).isdigit()
    }


def verificar() -> tuple[int, EventoAuditoria | None, list[dict]]:
    """Eventos verificados, el primero cuya huella no coincide (None si todo
    cuadra) y los huecos documentados que se encontraron en el camino.

    Un hueco documentado (eventos borrados, p. ej. al eliminar por la fuerza
    una cuenta) se acepta solo si los eventos que faltan son EXACTAMENTE los
    documentados: así no sirve para tapar un evento modificado, donde no falta
    ninguno. La cadena sigue verificándose desde el evento que sigue al hueco,
    y la constancia del hueco queda dentro de la misma cadena protegida."""
    documentadas = brechas_documentadas()
    anterior, anterior_id = "", 0
    n = 0
    encontradas: list[dict] = []
    for evento in EventoAuditoria.objects.order_by("id").iterator():
        esperada = EventoAuditoria.calcular_huella(anterior, evento.contenido_para_huella())
        if evento.huella != esperada:
            brecha = documentadas.get(evento.pk)
            faltantes = list(range(anterior_id + 1, evento.pk))
            if brecha is None or not faltantes or sorted(brecha.get("faltantes", [])) != faltantes:
                return n, evento, encontradas
            # La huella del último evento borrado se perdió con él: el ancla es el
            # evento que sigue al hueco, tal como estaba al documentarlo.
            if brecha.get("huella_evento") != evento.huella or brecha.get("contenido_evento") != huella_contenido(evento):
                return n, evento, encontradas
            encontradas.append(brecha)
        anterior, anterior_id = evento.huella, evento.pk
        n += 1
    return n, None, encontradas


class Command(BaseCommand):
    help = "Verifica la cadena de huellas de la auditoría."

    def handle(self, *args, **opciones):
        n, roto, brechas = verificar()
        for b in brechas:
            self.stdout.write(self.style.WARNING(
                f"Hueco documentado: faltan los eventos {', '.join(map(str, b['faltantes']))} — {b.get('motivo')} "
                f"(constancia en el evento {b['documentado_en']}, por {b.get('por')})."
            ))
        if roto is not None:
            raise CommandError(
                f"La cadena de la auditoría se rompe en el evento {roto.pk} ({roto.fecha:%Y-%m-%d %H:%M}, "
                f"«{roto.accion}»), después de {n} eventos correctos: fue modificado, o se borró o insertó "
                "un evento antes de él."
            )
        self.stdout.write(self.style.SUCCESS(
            f"Auditoría íntegra: {n} eventos verificados" + (f", con {len(brechas)} hueco(s) documentado(s)." if brechas else ".")
        ))
