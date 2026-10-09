"""Cifra en reposo los archivos que se guardaron en claro (RF-21).

    manage.py cifrar_archivos              # cifra lo que esté en claro
    manage.py cifrar_archivos --rotar      # además, vuelve a cifrar con la clave nueva
                                           # (la primera de CLAVE_CIFRADO_ARCHIVOS)
    manage.py cifrar_archivos --verificar  # solo revisa; falla si queda algo en claro
    manage.py cifrar_archivos --generar-clave

Recorre los archivos subidos (menos las plantillas de informe, que no llevan
datos personales) y la caché de ofertas descargadas. Cada archivo se reescribe
de una vez (temporal + renombrar) y se comprueba que se descifre igual.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config.almacenamiento import _en_claro
from motor import cifrado
from motor.integrations.drive import CACHE_DIR


def archivos() -> list[Path]:
    raiz = Path(settings.MEDIA_ROOT)
    salida = []
    if raiz.exists():
        salida += [p for p in raiz.rglob("*") if p.is_file() and not p.name.startswith(".") and not _en_claro(str(p.relative_to(raiz)))]
    if CACHE_DIR.exists():
        salida += [p for p in CACHE_DIR.glob("*.zip") if p.is_file()]
    return sorted(salida)


class Command(BaseCommand):
    help = "Cifra en reposo los archivos subidos y la caché de ofertas."

    def add_arguments(self, parser):
        parser.add_argument("--verificar", action="store_true", help="Solo revisa; termina con error si queda algo en claro.")
        parser.add_argument("--rotar", action="store_true", help="Vuelve a cifrar con la clave actual lo cifrado con una anterior.")
        parser.add_argument("--generar-clave", action="store_true", help="Imprime una clave nueva para CLAVE_CIFRADO_ARCHIVOS.")

    def handle(self, *args, verificar=False, rotar=False, generar_clave=False, **opciones):
        if generar_clave:
            self.stdout.write(cifrado.nueva_clave())
            return
        if not cifrado.activo():
            raise CommandError("Falta CLAVE_CIFRADO_ARCHIVOS: genere una con --generar-clave y póngala en el .env.")
        en_claro, con_anterior, cifrados, errores = [], [], 0, []
        for ruta in archivos():
            datos = ruta.read_bytes()
            if not cifrado.cifrado(datos):
                en_claro.append(ruta)
            elif not cifrado.cifrado_con_actual(datos):
                con_anterior.append(ruta)
            if verificar:
                continue
            if ruta in en_claro[-1:] or (rotar and ruta in con_anterior[-1:]):
                try:
                    plano = cifrado.descifrar(datos)
                    cifrado.escribir(ruta, plano)
                    if cifrado.leer(ruta) != plano:
                        raise cifrado.ErrorCifrado("la copia cifrada no se descifra igual")
                    cifrados += 1
                except (OSError, cifrado.ErrorCifrado) as exc:
                    errores.append(f"{ruta}: {exc}")
        total = len(archivos())
        if verificar:
            self.stdout.write(f"{total} archivos: {len(en_claro)} en claro, {len(con_anterior)} con una clave anterior.")
            if en_claro:
                raise CommandError(f"Quedan {len(en_claro)} archivos sin cifrar: corra «manage.py cifrar_archivos».")
            return
        self.stdout.write(self.style.SUCCESS(f"{cifrados} archivos cifrados de {total}."))
        if con_anterior and not rotar:
            self.stdout.write(f"{len(con_anterior)} siguen con una clave anterior: use --rotar para pasarlos a la actual.")
        if errores:
            raise CommandError("No se pudieron cifrar:\n" + "\n".join(errores))
