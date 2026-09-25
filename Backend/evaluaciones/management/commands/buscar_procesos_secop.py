"""Buscar procesos en el SECOP II para conseguir material de prueba.

El SECOP publica sus datos en el portal de datos abiertos del Estado
(datos.gov.co), que se consulta sin iniciar sesión y desde la línea de comandos.
De ahí salen el código del proceso, su modalidad, su estado, el presupuesto, el
plazo y el enlace a su página.

Lo que NO sale de aquí son los documentos: el pliego y los informes están en el
portal del SECOP, que responde con un reCAPTCHA a cualquier petición que no venga
de un navegador. Esa puerta está cerrada a propósito y no se fuerza; los PDF se
bajan desde el navegador, y este comando dice a qué procesos ir para no buscar a
ciegas entre siete mil.

    manage.py buscar_procesos_secop --desde 2025-01-01
    manage.py buscar_procesos_secop --nit 899999061 --limite 40
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

# "SECOP II - Procesos de Contratación" en el portal de datos abiertos.
RECURSO = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
NIT_ICCU = "900258711"
# Las modalidades que evalúa el programa (las demás no tienen requisitos
# habilitantes que verificar).
MODALIDADES = ("icitaci", "oncurso", "enor cuant", "inima cuant")
DATASET = Path(__file__).resolve().parent.parent.parent.parent.parent / "datasetdepruebas"


class Command(BaseCommand):
    help = "Lista procesos del SECOP II que sirven como material de prueba (no descarga documentos)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--nit", default=NIT_ICCU, help=f"NIT de la entidad (por defecto el ICCU, {NIT_ICCU})")
        parser.add_argument("--desde", default="2025-01-01", help="publicados desde esta fecha (AAAA-MM-DD)")
        parser.add_argument("--limite", type=int, default=30)
        parser.add_argument("--todas-las-modalidades", action="store_true",
                            help="sin filtrar por licitación, concurso de méritos o menor cuantía")
        parser.add_argument("--json", dest="como_json", action="store_true", help="salida en JSON")

    def handle(self, *args, **opciones) -> None:
        condiciones = [f"nit_entidad='{opciones['nit']}'", f"fecha_de_publicacion_del>'{opciones['desde']}'"]
        if not opciones["todas_las_modalidades"]:
            condiciones.append("(" + " OR ".join(
                f"modalidad_de_contratacion like '%{m}%'" for m in MODALIDADES) + ")")
        consulta = urllib.parse.urlencode({
            "$where": " AND ".join(condiciones),
            "$order": "fecha_de_publicacion_del DESC",
            "$limit": max(1, min(opciones["limite"], 500)),
        })
        try:
            with urllib.request.urlopen(f"{RECURSO}?{consulta}", timeout=60) as respuesta:
                filas = json.loads(respuesta.read())
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"No se pudo consultar el portal de datos abiertos: {exc}") from exc

        ya = {c.name for c in DATASET.glob("*/*") if c.is_dir()} if DATASET.exists() else set()
        vistos: set[str] = set()
        salida = []
        for f in filas:
            codigo = (f.get("referencia_del_proceso") or "").split(" (")[0].strip()
            if not codigo or codigo in vistos:
                continue
            vistos.add(codigo)
            salida.append({
                "codigo": codigo,
                "modalidad": f.get("modalidad_de_contratacion", ""),
                "estado": f.get("estado_del_procedimiento", ""),
                "adjudicado": f.get("adjudicado", ""),
                "presupuesto": float(f.get("precio_base") or 0),
                "plazo": f"{f.get('duracion', '')} {f.get('unidad_de_duracion', '')}".strip(),
                "cierre": (f.get("fecha_de_recepcion_de") or "")[:10],
                "objeto": (f.get("descripci_n_del_procedimiento") or "")[:90],
                "url": (f.get("urlproceso") or {}).get("url", ""),
                "ya_lo_tenemos": codigo in ya,
            })
        if opciones["como_json"]:
            self.stdout.write(json.dumps(salida, ensure_ascii=False, indent=1))
            return
        nuevos = [s for s in salida if not s["ya_lo_tenemos"]]
        self.stdout.write(f"{len(salida)} procesos · {len(nuevos)} que no están en el dataset\n")
        self.stdout.write(f"{'CÓDIGO':22s} {'MODALIDAD':22s} {'ESTADO':14s} {'PRESUPUESTO':>16s} {'PLAZO':10s} CIERRE")
        for s in salida:
            marca = "" if s["ya_lo_tenemos"] else "  ←"
            self.stdout.write(
                f"{s['codigo']:22s} {s['modalidad'][:22]:22s} {s['estado'][:14]:14s} "
                f"${s['presupuesto']:>15,.0f} {s['plazo'][:10]:10s} {s['cierre']}{marca}"
            )
        if nuevos:
            self.stdout.write("\nLos que no tenemos, con su página en el SECOP (los documentos se bajan desde el navegador):")
            for s in nuevos[:15]:
                self.stdout.write(f"  {s['codigo']}\n    {s['objeto']}\n    {s['url']}")
