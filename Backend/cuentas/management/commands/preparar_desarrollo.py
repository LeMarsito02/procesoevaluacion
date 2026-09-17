"""Crea las cuentas del entorno de desarrollo (nunca en producción).

- Superadministrador de la plataforma (2FA obligatorio al primer ingreso).
- Entidad de pruebas "LeMarTek · Pruebas" con sus tres áreas.
- Cuenta de medición (evaluador jurídico) que usa `scratch_medicion.py`.

Las contraseñas nuevas se guardan en `.env` (fuera de git) y se muestran una vez.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from cuentas.models import Area, Entidad, Rol, TipoArea, Usuario

SUPERADMIN = "santiagopebe01@lemartek.com"
MEDICION = "medicion@lemartek.com"


def _clave() -> str:
    return secrets.token_urlsafe(12)


def _guardar_en_env(variables: dict[str, str]) -> None:
    ruta = Path(settings.BASE_DIR) / ".env"
    lineas = ruta.read_text().splitlines() if ruta.exists() else []
    lineas = [l for l in lineas if l.split("=", 1)[0] not in variables]
    lineas += [f"{k}={v}" for k, v in variables.items()]
    ruta.write_text("\n".join(lineas) + "\n")


class Command(BaseCommand):
    help = "Crea superadmin, entidad de pruebas y cuenta de medición para desarrollo."

    def handle(self, *args, **opciones):
        if not settings.DEBUG:
            raise CommandError("Solo se puede usar con DJANGO_DEBUG=1.")

        nuevas: dict[str, str] = {}
        if not Usuario.objects.filter(email=SUPERADMIN).exists():
            clave = _clave()
            Usuario.objects.create_superuser(SUPERADMIN, clave, nombre_completo="Santiago Peña")
            nuevas["DEV_SUPERADMIN_CLAVE"] = clave
            self.stdout.write(f"Superadmin {SUPERADMIN} creado. Contraseña: {clave}")

        entidad, _ = Entidad.objects.get_or_create(nit="000000000-LMT", defaults={"nombre": "LeMarTek · Pruebas"})
        for tipo in TipoArea.values:
            Area.objects.get_or_create(entidad=entidad, tipo=tipo)

        if not Usuario.objects.filter(email=MEDICION).exists():
            clave = _clave()
            usuario = Usuario.objects.create_user(
                MEDICION, clave, nombre_completo="Cuenta de medición", entidad=entidad, rol=Rol.EVALUADOR
            )
            usuario.areas.set(entidad.areas.filter(tipo=TipoArea.JURIDICA))
            nuevas.update(MEDICION_EMAIL=MEDICION, MEDICION_CLAVE=clave)
            self.stdout.write(f"Cuenta de medición {MEDICION} creada.")

        if nuevas:
            _guardar_en_env(nuevas)
            self.stdout.write("Contraseñas guardadas en .env.")
        else:
            self.stdout.write("Las cuentas ya existían; no se cambió nada.")
