"""Retención de documentos de proponentes.

- Procesos cuyas evaluaciones están todas aprobadas hace más de RETENCION_DIAS
  y ya tienen su expediente permanente: se borran las copias completas de las
  ofertas descargadas de Drive y se marca el proceso. El expediente (documentos
  evaluados, certificados aportados, Excel, Word y registro) nunca se borra.
- Cachés derivadas de los documentos (texto OCR, respuestas de la IA,
  resultados por requisito): se borran las que no se han usado en
  RETENCION_DIAS, sean del proceso que sean.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Max, Q
from django.utils import timezone

from evaluaciones.models import EstadoEvaluacion, EstadoExpediente, Proceso, Proponente

log = logging.getLogger("mievaluador.retencion")

CACHE = Path(settings.BASE_DIR) / "cache"
DIRECTORIO_OFERTAS = CACHE / "drive_files"
CACHES_DERIVADAS = ("ocr", "llm", "evaluaciones")


@dataclass
class Informe:
    procesos: list[str] = field(default_factory=list)
    archivos_ofertas: int = 0
    archivos_cache: int = 0
    bytes_liberados: int = 0


def _borrar(ruta: Path, informe: Informe, simulacro: bool) -> None:
    try:
        tam = ruta.stat().st_size
    except FileNotFoundError:
        return
    if not simulacro:
        ruta.unlink(missing_ok=True)
    informe.bytes_liberados += tam


def procesos_vencidos(dias: int):
    limite = timezone.now() - timedelta(days=dias)
    return (
        Proceso.objects.filter(documentos_eliminados_en__isnull=True)
        .annotate(
            total=Count("evaluaciones"),
            aprobadas=Count("evaluaciones", filter=Q(evaluaciones__estado=EstadoEvaluacion.APROBADA)),
            ultima=Max("evaluaciones__aprobada_en"),
        )
        .filter(total__gt=0, ultima__lte=limite)
    )


def aplicar(dias: int | None = None, simulacro: bool = False) -> Informe:
    dias = dias if dias is not None else settings.RETENCION_DIAS
    informe = Informe()

    # Solo si cada evaluación ya tiene su expediente permanente generado.
    vencidos = [
        p
        for p in procesos_vencidos(dias)
        if p.aprobadas == p.total
        and not p.evaluaciones.exclude(expedientes__estado=EstadoExpediente.LISTO).exists()
    ]
    en_uso = set(
        Proponente.objects.filter(proceso__documentos_eliminados_en__isnull=True)
        .exclude(proceso__in=vencidos)
        .values_list("drive_file_id", flat=True)
    )
    for proceso in vencidos:
        for file_id in proceso.proponentes.values_list("drive_file_id", flat=True):
            # Si otra evaluación vigente usa la misma oferta, se conserva.
            if file_id in en_uso:
                continue
            for ruta in (DIRECTORIO_OFERTAS / f"{file_id}.zip", DIRECTORIO_OFERTAS / f"{file_id}.meta.json"):
                if ruta.exists():
                    _borrar(ruta, informe, simulacro)
                    informe.archivos_ofertas += 1
        if not simulacro:
            proceso.documentos_eliminados_en = timezone.now()
            proceso.save(update_fields=["documentos_eliminados_en"])
        informe.procesos.append(proceso.codigo)

    limite = time.time() - dias * 86400
    for nombre in CACHES_DERIVADAS:
        carpeta = CACHE / nombre
        if not carpeta.is_dir():
            continue
        for ruta in carpeta.iterdir():
            # Fecha de último uso: la más reciente entre modificación y acceso.
            if ruta.is_file() and max(ruta.stat().st_mtime, ruta.stat().st_atime) < limite:
                _borrar(ruta, informe, simulacro)
                informe.archivos_cache += 1
    # Ofertas descargadas que no pertenecen a ningún proceso vigente y no se usan hace tiempo.
    if DIRECTORIO_OFERTAS.is_dir():
        for ruta in DIRECTORIO_OFERTAS.iterdir():
            file_id = ruta.name.split(".")[0]
            if file_id not in en_uso and ruta.is_file() and ruta.stat().st_mtime < limite:
                _borrar(ruta, informe, simulacro)
                informe.archivos_ofertas += 1

    log.info(
        "Retención%s: %d procesos, %d archivos de ofertas, %d de caché, %.1f MB",
        " (simulacro)" if simulacro else "",
        len(informe.procesos),
        informe.archivos_ofertas,
        informe.archivos_cache,
        informe.bytes_liberados / 1e6,
    )
    return informe
