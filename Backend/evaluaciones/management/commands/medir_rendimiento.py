"""Calcula la analítica de rendimiento contra las evaluaciones reales de
referencia y la guarda como la foto que muestra el tablero.

Uso: manage.py medir_rendimiento [--minutos-juridica 6] [--minutos-tecnica 10] [--minutos-financiera 15]

Las fuentes son las mediciones que dejan scratch_medicion.py (jurídica),
.scratch/tecnica/medir.py (técnica) y .scratch/financiera/medir.py
(financiera). Los nombres son comerciales: no llevan el nombre de la
entidad ni de los proponentes.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from evaluaciones import analitica
from evaluaciones.models import MedicionRendimiento
from motor import criterios

BASE = Path(__file__).resolve().parents[3]
SCRATCH = BASE / ".scratch"
# Las cifras de cada medición se guardan aquí para poder comparar en el tiempo.
ESTADISTICAS = BASE.parent / "estadisticas"


class Command(BaseCommand):
    help = "Calcula la analítica de rendimiento contra evaluaciones reales y la guarda para el tablero."

    def add_arguments(self, parser):
        parser.add_argument("--minutos-juridica", type=float, default=6.0,
                            help="Minutos que tarda una persona en verificar un requisito jurídico.")
        parser.add_argument("--minutos-tecnica", type=float, default=10.0,
                            help="Minutos que tarda una persona en verificar un requisito técnico.")
        parser.add_argument("--minutos-financiera", type=float, default=15.0,
                            help="Minutos que tarda una persona en verificar un requisito financiero.")
        parser.add_argument("--nota", default="")
        parser.add_argument("--sin-guardar", action="store_true",
                            help="No escribe la medición en la carpeta estadisticas/.")

    def handle(self, *args, **opciones):
        titulos = {str(n): v.titulo for n, v in criterios.VERIFICACION_POR_NUMERO_INTERNO.items()}
        pruebas = [
            analitica.prueba_juridica("juridica_cm", "Concurso de méritos · interventoría vial", SCRATCH,
                                      nota="Proceso con el que se desarrolló el motor jurídico."),
            analitica.prueba_juridica("juridica_lp", "Licitación de obra vial por lotes", SCRATCH / "prueba3",
                                      nota="Medido a ciegas la primera vez; después se usó para mejoras."),
            analitica.prueba_juridica("juridica_mc", "Menor cuantía · obra vial", SCRATCH / "prueba4",
                                      nota="Medido a ciegas la primera vez; después se usó para mejoras."),
        ]
        tecnica = SCRATCH / "tecnica"
        # La evaluación hecha en la plataforma, si existe; si no, las mediciones sueltas.
        plataforma = tecnica / "medicion_plataforma.json"
        mediciones = [plataforma] if plataforma.exists() else [
            m for m in sorted(tecnica.glob("medicion_*.json")) if not m.stem.count(".")  # sin versiones viejas (.v1)
        ]
        referencia = tecnica / "referencia.json"
        pruebas += [
            # P-01 a P-30 sirvieron para desarrollar el motor técnico: se muestran
            # aparte de la medición a ciegas (P-31 en adelante).
            analitica.prueba_tecnica("tecnica_lp_ciegas", "Licitación de obra vial por lotes (a ciegas)", mediciones,
                                     referencia, desde=31, a_ciegas=True),
            analitica.prueba_tecnica("tecnica_lp_desarrollo", "Licitación de obra vial por lotes (desarrollo)",
                                     mediciones, referencia, hasta=30, a_ciegas=False,
                                     nota="Proponentes usados para desarrollar el motor técnico."),
        ]
        financiera = SCRATCH / "financiera"
        resultados = sorted((d for d in financiera.glob("res_v*") if d.is_dir()), key=lambda d: int(d.name[5:] or 0))
        if resultados:
            pruebas.append(analitica.prueba_financiera(
                "financiera_lp", "Licitación de obra vial por lotes (financiera)", resultados[-1],
                financiera / "referencia.json", nota="Proceso con el que se desarrolló el motor financiero.",
            ))
        resumenes = [analitica.resumir(p, titulos) for p in pruebas if p is not None]
        minutos = {"juridica": opciones["minutos_juridica"], "tecnica": opciones["minutos_tecnica"],
                   "financiera": opciones["minutos_financiera"]}
        datos = {
            "global": analitica.global_(resumenes, minutos),
            "global_a_ciegas": analitica.global_([r for r in resumenes if r["a_ciegas"]], minutos),
            "pruebas": resumenes,
            "confianza": analitica.CONFIANZA,
        }
        foto = MedicionRendimiento.objects.create(datos=datos, nota=opciones["nota"][:300])
        g = datos["global"]
        self.stdout.write(
            f"Foto {foto.id}: {g['pruebas']} pruebas, {g['proponentes']} proponentes, {g['automaticas']}/{g['decisiones']} "
            f"decisiones automáticas, {g['indebidas']} indebidas, techo del error {100 * (g['techo_error'] or 0):.2f} %"
        )
        for r in resumenes:
            self.stdout.write(
                f"  {r['clave']:22s} {r['proponentes']:3d} prop · automatización {100 * (r['automatizacion'] or 0):5.1f} % · "
                f"indebidas {r['indebidas']} · techo {100 * (r['techo_error'] or 0):.2f} % · "
                f"{(r['segundos_por_proponente'] or 0):.0f} s/prop"
            )
        if not opciones["sin_guardar"]:
            archivo = guardar_estadisticas(datos, opciones["nota"])
            self.stdout.write(f"Guardado en {archivo.relative_to(BASE.parent)}")


def guardar_estadisticas(datos: dict, nota: str) -> Path:
    """Deja la medición en estadisticas/ (un archivo por corrida y un resumen
    en Markdown que se sobrescribe con la última)."""
    from datetime import datetime

    carpeta = ESTADISTICAS / "mediciones"
    carpeta.mkdir(parents=True, exist_ok=True)
    momento = datetime.now()
    archivo = carpeta / f"{momento:%Y-%m-%d_%H%M}.json"
    archivo.write_text(json.dumps({"fecha": momento.isoformat(timespec="minutes"), "nota": nota, **datos},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    (ESTADISTICAS / "resumen.md").write_text(_resumen_markdown(datos, momento, nota), encoding="utf-8")
    return archivo


def _pct(valor) -> str:
    return "—" if valor is None else f"{100 * valor:.1f} %"


def _resumen_markdown(datos: dict, momento, nota: str) -> str:
    g = datos["global"]
    lineas = [
        "# Rendimiento de MiEvaluador",
        "",
        f"Última medición: {momento:%d/%m/%Y %H:%M}." + (f" {nota}" if nota else ""),
        "",
        f"- Proponentes medidos: **{g['proponentes']}** en {g['pruebas']} pruebas.",
        f"- Decisiones que el programa resolvió solo: **{g['automaticas']} de {g['decisiones']}** ({_pct(g['automatizacion'])}).",
        f"- Aprobaciones indebidas (el programa aprobó y el evaluador dijo que no): **{g['indebidas']}**.",
        f"- Error máximo con {100 * datos['confianza']:.0f} % de confianza: **{_pct(g['techo_error'])}**.",
        f"- Horas de trabajo ahorradas: **{g['horas_ahorradas']:.0f}**.",
        "",
        "| Prueba | Proponentes | Decide solo | Indebidas | Error máximo | Tiempo por oferta |",
        "|---|---|---|---|---|---|",
    ]
    for r in datos["pruebas"]:
        segundos = r["segundos_por_proponente"]
        lineas.append(
            f"| {r['nombre']} | {r['proponentes']} | {r['automaticas']}/{r['decisiones']} ({_pct(r['automatizacion'])}) | "
            f"{r['indebidas']} | {_pct(r['techo_error'])} | {'—' if not segundos else f'{segundos:.0f} s'} |"
        )
    lineas += ["", "Cada corrida queda en `mediciones/` con el detalle requisito por requisito."]
    return "\n".join(lineas) + "\n"
