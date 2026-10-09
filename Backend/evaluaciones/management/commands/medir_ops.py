"""Lee un expediente de prestación de servicios tal como lo haría la
plataforma y muestra el resultado, para medir el módulo con casos reales:

    manage.py medir_ops <carpeta de la entidad> <carpeta del contratista> [--fecha 2026-01-22] [--nit 999000001]

Las carpetas traen los PDF ya descomprimidos. Si entre los documentos de la
entidad está su certificado de idoneidad, se comparan los periodos que
certificó con los que leyó el motor. No guarda nada.
"""
from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from cuentas.models import Entidad
from evaluaciones import ops
from motor.ops.certificaciones import leer_periodos
from motor.ops.expediente import leer_expediente
from motor.ops.identidad import identificar
from motor.ops.idoneidad import Perfil, evaluar_idoneidad
from motor.ops.tiempo import texto_duracion
from motor.procesamiento.pdf_utils import paginas_de_texto
from motor.tecnica.rup import normalizar


def _pdfs(carpeta: str) -> dict[str, bytes]:
    ruta = Path(carpeta)
    if not ruta.is_dir():
        raise CommandError(f"No existe la carpeta {carpeta}.")
    return {f.name: f.read_bytes() for f in sorted(ruta.iterdir()) if f.suffix.lower().rstrip("_") == ".pdf"}


class Command(BaseCommand):
    help = "Lee un expediente de prestación de servicios y lo compara con el certificado de idoneidad de la entidad."

    def add_arguments(self, parser):
        parser.add_argument("entidad")
        parser.add_argument("contratista")
        parser.add_argument("--fecha", default=None, help="Fecha del estudio previo (por defecto, hoy).")
        parser.add_argument("--nit", default=None, help="Entidad cuya tabla de honorarios se usa.")

    def handle(self, *args, **o):
        fecha = date.fromisoformat(o["fecha"]) if o["fecha"] else date.today()
        de_la_entidad, del_contratista = _pdfs(o["entidad"]), _pdfs(o["contratista"])
        tabla = None
        if o["nit"]:
            entidad = Entidad.objects.filter(nit=o["nit"]).first()
            if entidad is None:
                raise CommandError(f"No existe una entidad con NIT {o['nit']}.")
            tabla = ops.tabla_de(entidad.id, fecha.year)
        inicio = time.monotonic()
        nombre, cedula = identificar(del_contratista)
        exp = leer_expediente(de_la_entidad, del_contratista, nombre or "", cedula, fecha)
        perfil = exp.estudio.perfil if exp.estudio and exp.estudio.perfil else Perfil(0, None)
        r = evaluar_idoneidad(exp.periodos, exp.titulos, perfil, tabla)
        w = self.stdout.write
        w(f"Leído en {time.monotonic() - inicio:.1f} s · {nombre or 'nombre sin leer'} · C.C. {cedula or 'sin leer'}")
        w(f"Perfil: {perfil.descripcion or 'sin leer'}")
        w(f"  {perfil.anios_minimos:g} a {perfil.anios_maximos} años · posgrado {perfil.posgrado} · honorarios ${perfil.honorarios_mensuales:,}".replace(",", "."))
        w(f"Grado: {r.grado} · posgrado acreditado: {r.posgrado}")
        w(f"Experiencia: {texto_duracion(r.dias)} (leída {texto_duracion(r.lineal.dias)}; relacionada {texto_duracion(r.dias_relacionada)})")
        if r.franja:
            w(f"Franja {r.franja.nombre} · tope ${r.tope:,}".replace(",", "."))
        leidos = {(p.inicio, p.fin) for p in exp.periodos}
        certificados: set[tuple[date, date]] = set()
        if cert := next((n for n in de_la_entidad if "IDONEIDAD" in normalizar(n)), None):
            certificados = {(p.inicio, p.fin) for p in leer_periodos(paginas_de_texto(de_la_entidad[cert]), cert).periodos}
        for periodo in sorted(leidos | certificados):
            marca = "ambos" if periodo in leidos and periodo in certificados else "solo el motor" if periodo in leidos else "solo la entidad"
            w(f"  {periodo[0]:%d/%m/%Y} a {periodo[1]:%d/%m/%Y}  {marca if certificados else ''}")
        pendientes = [d for d in exp.documentos if d.estado not in ("cumple", "no_aplica")]
        w(f"Documentos: {len(exp.documentos) - len(pendientes)} de {len(exp.documentos)} al día")
        for d in pendientes:
            w(f"  {d.estado}: {d.nombre} — {d.motivo}")
        if exp.sin_reconocer:
            w("Sin reconocer: " + ", ".join(exp.sin_reconocer))
        for aviso in [*exp.avisos, *r.revisiones]:
            w(f"  · {re.sub(chr(10), ' ', aviso)}")
