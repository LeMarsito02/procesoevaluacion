"""Exportación de la evaluación en XLSX, CSV y PDF (RF-22).

El PDF sale del mismo Excel del informe, convertido con LibreOffice sin
pantalla: conserva la plantilla de la entidad tal cual. El CSV es la tabla de
resultados (una fila por proponente y requisito) con la decisión final, para
llevarla a otro sistema.
"""
from __future__ import annotations

import csv
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from evaluaciones.models import Evaluacion, Resultado, Revision

SEGUNDOS_CONVERSION = 180


class ErrorExportacion(Exception):
    pass


def _soffice() -> str:
    for nombre in ("soffice", "libreoffice"):
        ruta = shutil.which(nombre)
        if ruta:
            return ruta
    raise ErrorExportacion("El servidor no tiene LibreOffice para generar el PDF.")


def a_pdf(contenido: bytes, nombre: str) -> bytes:
    """Convierte un .xlsx o .docx a PDF. Cada conversión usa su propio perfil
    de LibreOffice, para que dos descargas a la vez no se bloqueen."""
    with tempfile.TemporaryDirectory(prefix="mievaluador-pdf-") as tmp:
        carpeta = Path(tmp)
        origen = carpeta / ("documento" + Path(nombre).suffix.lower())
        origen.write_bytes(contenido)
        try:
            subprocess.run(
                [_soffice(), f"-env:UserInstallation=file://{carpeta / 'perfil'}", "--headless", "--norestore",
                 "--convert-to", "pdf", "--outdir", str(carpeta), str(origen)],
                check=True, capture_output=True, timeout=SEGUNDOS_CONVERSION,
            )
        except subprocess.TimeoutExpired as exc:
            raise ErrorExportacion("La conversión a PDF tardó demasiado. Inténtelo de nuevo.") from exc
        except subprocess.CalledProcessError as exc:
            raise ErrorExportacion("No se pudo convertir el informe a PDF.") from exc
        pdf = carpeta / "documento.pdf"
        if not pdf.exists() or not pdf.read_bytes().startswith(b"%PDF"):
            raise ErrorExportacion("No se pudo convertir el informe a PDF.")
        return pdf.read_bytes()


def _texto(cumple: bool | None, revision: bool) -> str:
    if cumple is True:
        return "Cumple"
    if cumple is False:
        return "No cumple"
    return "En revisión" if revision else "No aplica"


def csv_resultados(evaluacion: Evaluacion) -> bytes:
    """Una fila por proponente y requisito. Separado por punto y coma y con
    BOM, que es como lo abre Excel en español sin dañar las tildes."""
    from evaluaciones.metricas import _titulos

    titulos = _titulos([evaluacion])
    revisiones = {(r.proponente_id, r.requisito): r for r in Revision.objects.filter(evaluacion=evaluacion).select_related("usuario")}
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    w.writerow(["Proceso", "Evaluación", "Hoja", "Proponente", "Requisito", "Título", "Resultado del sistema", "Motivo del sistema",
                "Decisión final", "Decidido por", "Nota de la revisión", "Documento evaluado"])
    filas = Resultado.objects.filter(evaluacion=evaluacion).select_related("proponente").order_by("proponente__hoja", "requisito")
    for r in filas:
        d = r.datos or {}
        rev = revisiones.get((r.proponente_id, r.requisito))
        sistema = _texto(d.get("cumple"), r.requiere_revision)
        if rev is not None:
            final, por, nota = _texto(rev.cumple, False), rev.usuario.nombre_completo, rev.nota
        else:
            final, por, nota = ("Pendiente de revisión" if r.requiere_revision else sistema), ("" if r.requiere_revision else "Sistema"), ""
        w.writerow([evaluacion.proceso.codigo, evaluacion.get_tipo_display(), r.proponente.hoja, r.proponente.nombre, r.requisito,
                    titulos.get((evaluacion.tipo, r.requisito), ""), sistema, d.get("motivo") or "", final, por, nota,
                    d.get("archivo_evaluado") or ""])
    return ("﻿" + salida.getvalue()).encode("utf-8")
