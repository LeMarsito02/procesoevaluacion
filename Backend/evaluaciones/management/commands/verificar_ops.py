"""Campaña de sabotaje del módulo de prestación de servicios con expedientes
reales: a cada uno se le daña una cosa a la vez (otra persona, sin
certificaciones, sin antecedentes, sin títulos, certificaciones ajenas, sin
estudio previo, un perfil más exigente) y se comprueba que el sistema, sin
que nadie confirme nada, nunca llega a decir «cumple».

    manage.py verificar_ops <carpeta> --nit 999000001 --usuario alguien@entidad.gov.co [--fecha 2026-01-22]

La carpeta trae una subcarpeta por expediente, cada una con `entidad/` y
`contratista/` (los PDF ya descomprimidos). Hacen falta al menos dos
expedientes. Lo que se crea para la prueba se borra al terminar. Sale con
error si algún caso dañado queda aprobado: sirve de compuerta antes de
desplegar una versión nueva.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from cuentas.models import Entidad, Usuario
from evaluaciones import ops
from evaluaciones.models import ContratacionOps, OrigenDocumentoOps

Archivos = list[tuple[str, bytes]]


def _pdfs(carpeta: Path) -> Archivos:
    if not carpeta.is_dir():
        raise CommandError(f"Falta la carpeta {carpeta}.")
    return [(f.name, f.read_bytes()) for f in sorted(carpeta.iterdir()) if f.suffix.lower().rstrip("_") == ".pdf"]


def _sin(archivos: Archivos, *numeros: str) -> Archivos:
    """Sin los documentos que empiezan por esos números de la lista («14», «19»…)."""
    return [(n, b) for n, b in archivos if not any(n.lstrip().startswith((f"{x}.", f"{x} ", f"{x},")) for x in numeros)]


class Command(BaseCommand):
    help = "Daña expedientes reales de prestación de servicios y comprueba que ninguno queda aprobado."

    def add_arguments(self, parser):
        parser.add_argument("carpeta")
        parser.add_argument("--nit", required=True)
        parser.add_argument("--usuario", required=True)
        parser.add_argument("--fecha", default=None)

    def handle(self, *args, **o):
        entidad = Entidad.objects.filter(nit=o["nit"]).first()
        usuario = Usuario.objects.filter(email=o["usuario"]).first()
        if entidad is None or usuario is None:
            raise CommandError("No existe esa entidad o ese usuario.")
        fecha = date.fromisoformat(o["fecha"]) if o["fecha"] else date.today()
        casos = {d.name: (_pdfs(d / "entidad"), _pdfs(d / "contratista")) for d in sorted(Path(o["carpeta"]).iterdir()) if d.is_dir()}
        if len(casos) < 2:
            raise CommandError("Hacen falta al menos dos expedientes para cruzar personas.")

        def correr(de_la_entidad: Archivos, del_contratista: Archivos, nombre: str = "", cedula: str = ""):
            c = ContratacionOps.objects.create(
                entidad=entidad, referencia="VERIFICACION", contratista_nombre=nombre, contratista_cedula=cedula,
                fecha_referencia=fecha, creada_por=usuario,
            )
            try:
                ops.guardar_archivos(c, OrigenDocumentoOps.ENTIDAD, de_la_entidad, usuario)
                ops.guardar_archivos(c, OrigenDocumentoOps.CONTRATISTA, del_contratista, usuario)
                try:
                    c.resultado = ops.analizar(c)
                except ops.ErrorOps:
                    return None, ("", "")
                c.save()
                d = ops.detalle(c)
                return d["cumple"], (d["contratista_nombre"], d["contratista_cedula"])
            finally:
                for doc in c.documentos.all():
                    doc.archivo.delete(save=False)
                c.delete()

        nombres = list(casos)
        identidad: dict[str, tuple[str, str]] = {}
        self.stdout.write("Sin tocar:")
        for caso, (e, k) in casos.items():
            cumple, identidad[caso] = correr(e, k)
            self.stdout.write(f"  {caso}: {'cumple' if cumple else 'no cumple' if cumple is False else 'sin conclusión'}")
        # El perfil más exigente: el del expediente que pide más años.
        indebidos, total = [], 0
        for i, (caso, (e, k)) in enumerate(casos.items()):
            otro = nombres[(i + 1) % len(nombres)]
            # Las certificaciones del siguiente expediente que sí las traiga (si no, el caso no estaría dañado).
            ajenas = next(
                ([("99 " + n, b) for n, b in casos[x][1] if n.lstrip().startswith("14")]
                 for x in nombres[i + 1:] + nombres[:i] if any(n.lstrip().startswith("14") for n, _ in casos[x][1])),
                [],
            )
            escenarios = {
                "nombre y cédula de otra persona": lambda: correr(e, k, *identidad[otro]),
                "estudio previo de otro contrato": lambda: correr(casos[otro][0], k),
                "sin certificaciones": lambda: correr(e, _sin(k, "14")),
                "sin antecedentes disciplinarios": lambda: correr(e, _sin(k, "1")),
                "sin títulos": lambda: correr(e, _sin(k, "19")),
                **({"con certificaciones de otra persona": lambda: correr(e, k + ajenas)} if ajenas else {}),
                "sin estudio previo ni CDP": lambda: correr([], k),
            }
            for nombre, escenario in escenarios.items():
                cumple, _ = escenario()
                total += 1
                # Con el estudio previo de otro contrato puede cumplir de verdad: se informa, no cuenta como fallo.
                if cumple and nombre != "estudio previo de otro contrato":
                    indebidos.append(f"{caso}: {nombre}")
                elif cumple:
                    self.stdout.write(f"  (revise) {caso} cumple el perfil del contrato de {otro}")
        self.stdout.write(f"{total} casos dañados · aprobados indebidos: {len(indebidos)}")
        for linea in indebidos:
            self.stdout.write(self.style.ERROR(f"  APROBADO INDEBIDO → {linea}"))
        if indebidos:
            raise CommandError("El módulo aprobó casos dañados.")
