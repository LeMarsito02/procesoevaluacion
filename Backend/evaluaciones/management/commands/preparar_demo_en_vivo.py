"""Deja lista la demostración en vivo en una entidad aparte.

    manage.py preparar_demo_en_vivo

Crea (o reutiliza):
- la entidad «Entidad de demostración», para que en la presentación la lista de
  procesos muestre solo la demo y no los procesos de prueba del equipo;
- un evaluador de esa entidad («Equipo evaluador (demostración)»), que es con
  quien se presenta: un usuario normal, no el superadministrador, que solo ve
  datos de otras entidades con un permiso de desarrollo;
- el análisis del pliego del kit, copiado del que ya se leyó con IA, para que
  al subirlo en vivo no se vuelva a leer;
- el proceso de respaldo DEMO-CM-043-2026, ya evaluado con la precarga.

El usuario queda sin contraseña: se la pones tú con
`manage.py changepassword <correo>` (no se imprime ninguna aquí). En el primer
ingreso la plataforma le pide activar el segundo factor, como a todos.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from cuentas.models import Area, Entidad, Rol, TipoArea, Usuario
from evaluaciones import servicios
from evaluaciones.models import AnalisisPliego, Proceso

NOMBRE_ENTIDAD = "Entidad de demostración"
NIT_ENTIDAD = "999000001"
CORREO = "demo@lemartek.com"
NOMBRE_USUARIO = "Equipo evaluador (demostración)"
RESPALDO = "DEMO-CM-043-2026"


class Command(BaseCommand):
    help = "Prepara la entidad, el usuario y el respaldo de la demostración en vivo."

    def handle(self, *args, **opciones):
        kit = Path(settings.DEMO_KIT_DIR)
        pliego_kit = kit / "pliego.pdf"
        if not pliego_kit.is_file() or not (kit / "ofertas").is_dir():
            raise CommandError(f"No está el kit de la demo en {kit}.")

        entidad, nueva = Entidad.objects.get_or_create(nit=NIT_ENTIDAD, defaults={"nombre": NOMBRE_ENTIDAD})
        if nueva:
            Area.objects.bulk_create([Area(entidad=entidad, tipo=t) for t in TipoArea.values])
        self.stdout.write(f"Entidad: {entidad.nombre}{' (nueva)' if nueva else ''}")

        usuario = Usuario.objects.filter(email=CORREO).first()
        if usuario is None:
            usuario = Usuario.objects.create_user(CORREO, None, nombre_completo=NOMBRE_USUARIO, entidad=entidad, rol=Rol.EVALUADOR)
            usuario.set_unusable_password()
            usuario.save()
            self.stdout.write(f"Usuario creado: {CORREO} — ponle contraseña con: manage.py changepassword {CORREO}")
        elif usuario.entidad_id != entidad.id:
            raise CommandError(f"{CORREO} ya existe en otra entidad; no se toca.")
        usuario.areas.set(entidad.areas.all())

        # El pliego del kit, ya leído (reglas + IA) en otra entidad: se copia
        # para que al subirlo en vivo se reutilice en vez de volver a leerse.
        contenido = pliego_kit.read_bytes()
        huella = hashlib.sha256(contenido).hexdigest()
        if not AnalisisPliego.objects.filter(entidad=entidad, sha256=huella).exists():
            origen = AnalisisPliego.objects.filter(sha256=huella, estado_ia="listo").first()
            if origen is None:
                raise CommandError("El pliego del kit no se ha leído completo en ninguna entidad: créalo primero con crear_proceso_local.")
            copia = AnalisisPliego(
                entidad=entidad,
                sha256=huella,
                **{campo: getattr(origen, campo) for campo in (
                    "nombre_archivo", "paginas", "documento_tipo", "extraccion", "version", "estado_ia", "progreso_ia",
                    "requisitos_ia", "modelo_ia", "version_ia", "error_ia", "ia_iniciada", "ia_terminada", "parametros_ia",
                    "version_parametros_ia", "parametros_confirmados", "confirmados_en", "requisitos_asumidos",
                )},
                confirmados_por=usuario if origen.confirmados_por_id else None,
                creado_por=usuario,
            )
            copia.archivo.save(f"pliego-demo-{huella[:12]}.pdf", ContentFile(contenido), save=False)
            copia.save()
            self.stdout.write("Pliego de la demo copiado (ya leído, no se vuelve a leer en vivo).")

        # El respaldo, ya evaluado: si algo falla en vivo, se abre este.
        anterior = Proceso.objects.filter(entidad=entidad, codigo=RESPALDO).first()
        if anterior is not None:
            servicios.eliminar_proceso(anterior)
        call_command(
            "crear_proceso_local", str(kit), codigo=RESPALDO, cierre=_fecha_cierre(kit),
            tipos="juridica,tecnica,financiera", correo=CORREO, stdout=self.stdout,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Listo. Entra con {CORREO}. El respaldo {RESPALDO} se está evaluando con la precarga (segundos)."
        ))


def _fecha_cierre(kit: Path) -> str:
    import json

    try:
        return json.loads((kit / "demo.json").read_text(encoding="utf-8"))["fecha_cierre"]
    except (OSError, ValueError, KeyError) as exc:
        raise CommandError(f"Falta la fecha de cierre en {kit / 'demo.json'}.") from exc
