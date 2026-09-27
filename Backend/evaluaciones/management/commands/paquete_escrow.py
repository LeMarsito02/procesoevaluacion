"""Paquete para el depósito del código fuente en custodia (escrow) y para la
auditoría del sistema (expediente LEG-004, numeral 4.6; Diagnóstico ANCP-CCE
2026 sobre soberanía tecnológica).

Contiene el código fuente versionado en git, las dependencias fijadas, la
configuración de despliegue, la documentación, el catálogo de reglas del motor
generado desde el código y un manifiesto con la huella SHA-256 de cada archivo.

    python manage.py paquete_escrow --salida /ruta/mievaluador-escrow.zip
"""
from __future__ import annotations

import hashlib
import io
import subprocess
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

# Nunca van al paquete: secretos, credenciales y datos de entidades.
EXCLUIR = (".env", "credentials/", "almacenamiento/", "cache/", ".scratch/", "node_modules/")


def catalogo_de_reglas() -> str:
    """Qué verifica cada requisito base, en lenguaje claro, desde el registro del motor."""
    from motor import criterios

    lineas = [
        "# Catálogo de reglas del motor de MiEvaluador",
        "",
        f"Versión {settings.MIEVALUADOR_VERSION}. Generado desde `motor/criterios.py` (VERIFICACIONES).",
        "",
        "El sistema da un requisito por **verificado** solo cuando encuentra en el documento todos los datos que la "
        "regla exige; en cualquier otro caso lo deja **pendiente de revisión humana**. Nunca emite «no cumple».",
        "",
    ]
    por_tipo: dict[str, list] = {}
    for v in criterios.VERIFICACIONES.values():
        por_tipo.setdefault(v.tipo, []).append(v)
    for tipo, lista in sorted(por_tipo.items()):
        lineas += [f"## {tipo.capitalize()}", "", "| No. | Clave | Requisito | Qué se verifica | En la evaluación base |", "|---|---|---|---|---|"]
        for v in sorted(lista, key=lambda x: x.numero_interno):
            lineas.append(f"| {v.numero_interno} | `{v.clave}` | {v.titulo} | {v.verifica} | {'Sí' if v.base else 'Si el pliego lo pide'} |")
        lineas.append("")
    return "\n".join(lineas)


class Command(BaseCommand):
    help = "Genera el paquete de código fuente para depósito en custodia (escrow) y auditoría."

    def add_arguments(self, parser):
        parser.add_argument("--salida", required=True, help="Ruta del .zip a generar")

    def handle(self, *args, salida: str, **opciones):
        raiz = Path(settings.BASE_DIR).parent
        try:
            archivos = subprocess.run(
                ["git", "ls-files"], cwd=raiz, check=True, capture_output=True, text=True
            ).stdout.splitlines()
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=raiz, check=True, capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise CommandError("Se necesita el repositorio git para saber qué archivos forman el código fuente.") from exc
        def excluido(a: str) -> bool:
            nombre = Path(a).name
            if nombre.startswith(".env") and not nombre.endswith(".ejemplo"):
                return True
            return any(x in a for x in EXCLUIR if x != ".env") or a.lower().endswith((".pdf", ".xlsx", ".zip", ".rar"))

        archivos = [a for a in archivos if not excluido(a)]
        huellas = []
        destino = Path(salida)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED) as z:
            def agregar(ruta: str, contenido: bytes) -> None:
                z.writestr(f"mievaluador/{ruta}", contenido)
                huellas.append((ruta, hashlib.sha256(contenido).hexdigest(), len(contenido)))

            for a in archivos:
                ruta = raiz / a
                if ruta.is_file():
                    agregar(a, ruta.read_bytes())
            agregar("docs/REGLAS_DEL_MOTOR.md", catalogo_de_reglas().encode("utf-8"))
            manifiesto = io.StringIO()
            manifiesto.write("Paquete de código fuente de MiEvaluador para depósito en custodia y auditoría\n")
            manifiesto.write(f"Versión: {settings.MIEVALUADOR_VERSION}\nCommit: {commit}\nGenerado: {timezone.now().isoformat()}\n\n")
            manifiesto.write("SHA-256  tamaño  archivo\n")
            for ruta, huella, tam in huellas:
                manifiesto.write(f"{huella}  {tam}  {ruta}\n")
            z.writestr("mievaluador/MANIFIESTO.txt", manifiesto.getvalue())
        total = hashlib.sha256(destino.read_bytes()).hexdigest()
        self.stdout.write(self.style.SUCCESS(f"Paquete listo: {destino} ({len(huellas)} archivos). SHA-256 del paquete: {total}"))
