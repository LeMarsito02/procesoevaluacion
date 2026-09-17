"""Registro de tipos de evaluación.

Todos comparten el mismo flujo (proceso, asignación, fila, revisión,
aprobación, informe). Cada tipo declara si ya tiene motor automático y su
plantilla de informe. Para habilitar la evaluación técnica o la financiera
basta con implementar su evaluador en `motor/`, registrarlo aquí y marcar
`disponible=True`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cuentas.models import TipoArea

PLANTILLAS_DIR = Path(__file__).resolve().parent.parent / "motor" / "plantillas"


@dataclass(frozen=True)
class TipoEvaluacion:
    clave: str
    nombre: str
    descripcion: str
    # Hay motor automático: se puede poner en la fila de evaluación.
    disponible: bool
    plantilla: Path | None


TIPOS: dict[str, TipoEvaluacion] = {
    TipoArea.JURIDICA: TipoEvaluacion(
        clave=TipoArea.JURIDICA,
        nombre="Jurídica",
        descripcion="Requisitos habilitantes jurídicos: carta, COPNIA, Cámara de Comercio, póliza y antecedentes.",
        disponible=True,
        plantilla=PLANTILLAS_DIR / "plantilla_evaluacion_juridica.xlsx",
    ),
    TipoArea.TECNICA: TipoEvaluacion(
        clave=TipoArea.TECNICA,
        nombre="Técnica",
        descripcion="Experiencia, personal clave y capacidad técnica.",
        disponible=False,
        plantilla=None,
    ),
    TipoArea.FINANCIERA: TipoEvaluacion(
        clave=TipoArea.FINANCIERA,
        nombre="Financiera",
        descripcion="Indicadores financieros y organizacionales (liquidez, endeudamiento, cobertura, rentabilidad).",
        disponible=False,
        plantilla=None,
    ),
}

MENSAJE_EN_PREPARACION = (
    "La evaluación automática {nombre} está en preparación. Puede crearla y asignarla desde ya; "
    "se habilitará en cuanto el módulo esté listo."
)


def tipo(clave: str) -> TipoEvaluacion:
    return TIPOS[clave]
