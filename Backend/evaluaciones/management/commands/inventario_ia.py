"""Inventario de los modelos de IA y control de sus cambios (ISO/IEC 42001).

    manage.py inventario_ia
    manage.py inventario_ia --aprobar --por "Nombre" --evidencia "Medición del 27/09/2026"

Lista, por cada uso de la IA en la plataforma, qué modelo está configurado y
su huella exacta (el digest que da Ollama), y lo compara con los modelos
aprobados en `config/modelos_ia_aprobados.json`.

Por qué: un modelo de IA distinto —aunque se llame igual, si se descargó otra
versión— puede leer distinto los documentos. Antes de usarlo en evaluaciones
reales hay que volver a medir contra informes de referencia (aprobaciones
indebidas = 0) y aprobarlo aquí, con quién lo aprobó y con qué evidencia. El
comando sale con código 1 si algún modelo en uso no está aprobado: se corre en
cada despliegue.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from evaluaciones.cumplimiento import modelos_ia

APROBADOS = Path(settings.BASE_DIR) / "config" / "modelos_ia_aprobados.json"

USOS = {
    "extraccion_documentos": "Extraer datos puntuales de documentos de la oferta (nombres, cédulas, valores); se verifican contra el texto",
    "lectura_pliego": "Leer el pliego completo y proponer requisitos y parámetros que una persona confirma",
    "vision": "Leer documentos escaneados (fecha de expedición de la cédula)",
}


def _huellas(url: str) -> dict[str, dict]:
    try:
        modelos = requests.get(f"{url}/api/tags", timeout=10).json()["models"]
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise CommandError(f"No se pudo consultar Ollama en {url}: {exc}") from exc
    return {m["name"]: m for m in modelos}


class Command(BaseCommand):
    help = "Inventario de los modelos de IA en uso y comparación con los aprobados (ISO/IEC 42001)."

    def add_arguments(self, parser):
        parser.add_argument("--aprobar", action="store_true", help="Registrar los modelos actuales como aprobados")
        parser.add_argument("--por", help="Quién aprueba (obligatorio con --aprobar)")
        parser.add_argument("--evidencia", help="Medición que respalda la aprobación (obligatorio con --aprobar)")

    def handle(self, *args, **opciones):
        from motor.llm import cliente

        instalados = _huellas(cliente.LLM_URL)
        aprobados = json.loads(APROBADOS.read_text(encoding="utf-8")) if APROBADOS.exists() else {}
        actuales: dict[str, dict] = {}
        sin_aprobar = 0
        for uso, nombre in modelos_ia().items():
            info = instalados.get(nombre) or instalados.get(f"{nombre}:latest")
            huella = info["digest"] if info else None
            detalles = (info or {}).get("details", {})
            actuales[uso] = {
                "modelo": nombre,
                "huella": huella,
                "parametros": detalles.get("parameter_size"),
                "cuantizacion": detalles.get("quantization_level"),
                "proposito": USOS.get(uso, ""),
            }
            aprobado = aprobados.get(uso, {})
            if huella is None:
                estado = "NO INSTALADO"
                sin_aprobar += 1
            elif aprobado.get("modelo") == nombre and aprobado.get("huella") == huella:
                estado = f"aprobado el {aprobado.get('aprobado_en')} por {aprobado.get('aprobado_por')}"
            else:
                estado = "SIN APROBAR (cambió el modelo o su versión: hay que volver a medir)"
                sin_aprobar += 1
            self.stdout.write(
                f"{uso}: {nombre} [{(huella or '—')[:12]}] {detalles.get('parameter_size', '')} "
                f"{detalles.get('quantization_level', '')} → {estado}"
            )

        if opciones["aprobar"]:
            if not opciones.get("por") or not opciones.get("evidencia"):
                raise CommandError("Para aprobar se necesita --por y --evidencia (la medición que lo respalda).")
            if any(a["huella"] is None for a in actuales.values()):
                raise CommandError("Hay modelos configurados que no están instalados: no se pueden aprobar.")
            for a in actuales.values():
                a.update(aprobado_en=date.today().isoformat(), aprobado_por=opciones["por"], evidencia=opciones["evidencia"])
            APROBADOS.write_text(json.dumps(actuales, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Modelos aprobados y registrados en {APROBADOS.name}."))
            return
        if sin_aprobar:
            raise CommandError(f"{sin_aprobar} modelo(s) en uso sin aprobar: mídalos y apruébelos con --aprobar.")
        self.stdout.write(self.style.SUCCESS("Todos los modelos en uso están aprobados."))
