"""Resultados precargados para la demostración en vivo.

El problema: evaluar de verdad un proceso grande tarda (la técnica y la
financiera no tienen caché y la jurídica solo acierta la caché del mismo
proceso), y en una demostración no se puede esperar hora y media. La idea es que
para un proceso de demostración —código que empieza por «DEMO-»— la evaluación
salga en segundos: en vez de correr el motor, el trabajador restaura resultados
ya calculados.

La clave es el CONTENIDO de la oferta (sha256 del zip), no el proceso ni el
nombre del archivo: así el usuario sube en vivo las mismas ofertas —con otro
código de proceso y otros identificadores— y los resultados calzan igual. Se
preparan una vez con `manage.py guardar_precarga <proceso ya evaluado>` y quedan
en disco. Si no hay precarga para una oferta, el trabajador evalúa normal, así
que esto nunca cambia un proceso de verdad (además del filtro por «DEMO-»).
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from django.conf import settings

from motor.esquemas.proceso import Proponente as ProponenteMotor
from motor.esquemas.proceso import ResultadoRequisito

log = logging.getLogger(__name__)

DIR_PRECARGA = Path(settings.BASE_DIR) / ".scratch" / "precarga"


def es_demo(codigo_proceso: str | None) -> bool:
    """Solo los procesos de demostración usan resultados precargados."""
    return bool(codigo_proceso) and codigo_proceso.upper().startswith("DEMO-")


def _hash_oferta(proponente: ProponenteMotor) -> str | None:
    """sha256 del zip de la oferta: la misma oferta calza aunque el proceso y el
    identificador del archivo sean otros."""
    from motor.integrations.drive import download_file_bytes

    try:
        return hashlib.sha256(download_file_bytes(proponente.drive_file_id)).hexdigest()
    except Exception:  # noqa: BLE001
        log.exception("No se pudo hashear la oferta para la precarga (%s)", proponente.drive_file_id)
        return None


def _ruta(huella: str, tipo: str) -> Path:
    return DIR_PRECARGA / f"{huella}.{tipo}.json"


def cargar(proponente: ProponenteMotor, tipo: str) -> list[ResultadoRequisito] | None:
    """Resultados precargados de esta oferta y área, o None si no hay."""
    huella = _hash_oferta(proponente)
    if not huella:
        return None
    ruta = _ruta(huella, tipo)
    if not ruta.exists():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        log.exception("Precarga ilegible en %s: se evalúa normal", ruta)
        return None
    # Los resultados se calcularon en otro proceso: traen la hoja, el número y
    # el nombre que el proponente tenía allá (P-10, P-100…). La pantalla agrupa
    # por la hoja, así que sin esto la tabla buscaba P-01 y mostraba «En
    # espera» aunque los resultados estuvieran guardados.
    propios = {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
    }
    try:
        return [ResultadoRequisito.model_validate({**d, **propios}) for d in datos]
    except Exception:  # noqa: BLE001
        log.exception("Precarga ilegible en %s: se evalúa normal", ruta)
        return None


def guardar(huella: str, tipo: str, resultados_datos: list[dict]) -> Path:
    """Guarda los `datos` de los Resultado de una oferta y área (los escribe el
    comando guardar_precarga a partir de un proceso ya evaluado)."""
    DIR_PRECARGA.mkdir(parents=True, exist_ok=True)
    ruta = _ruta(huella, tipo)
    ruta.write_text(json.dumps(resultados_datos, ensure_ascii=False), encoding="utf-8")
    return ruta


def huella_de(proponente: ProponenteMotor) -> str | None:
    """Expuesto para el comando que arma la precarga."""
    return _hash_oferta(proponente)
