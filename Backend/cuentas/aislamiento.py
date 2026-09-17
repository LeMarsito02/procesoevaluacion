"""Contexto de entidad para la Row-Level Security de PostgreSQL.

- Conexiones fuera de una petición (comandos, workers, migraciones): '*'.
- Cada petición HTTP empieza sin entidad ('' = no ve ninguna fila) y la
  autenticación fija la entidad del usuario ('*' para el superadmin).
"""
from __future__ import annotations

from django.db import connection
from django.db.backends.signals import connection_created
from django.dispatch import receiver

SISTEMA = "*"
NINGUNA = ""


def fijar_entidad(valor: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.entidad_id', %s, false)", [valor])


@receiver(connection_created)
def _contexto_sistema(sender, connection, **kwargs) -> None:  # noqa: ARG001
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.entidad_id', %s, false)", [SISTEMA])


class AislamientoMiddleware:
    """Cada petición parte sin acceso a datos de entidades."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        fijar_entidad(NINGUNA)
        return self.get_response(request)
