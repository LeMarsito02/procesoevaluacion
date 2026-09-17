"""Requisitos nuevos definidos por una entidad con bloques (sin programar).

El documento se reconoce por frases de su título o encabezado; luego se
aplican los bloques configurados. Nunca se aprueba con un dato dudoso: si no
se puede leer algo (una fecha, un nombre), el requisito queda para revisión
con el motivo exacto.
"""
from __future__ import annotations

import re
from datetime import date

from dateutil.relativedelta import relativedelta

from motor.criterios import ConfigPersonalizado, RequisitoDefinicion
from motor.esquemas.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from motor.evaluacion.formato1 import _norm, obtener_tipo_proponente
from motor.evaluacion.proponente_plural import obtener_personas_a_verificar
from motor.integrations.drive import download_file_bytes
from motor.procesamiento.pdf_utils import extraer_texto
from motor.procesamiento.zip_utils import extraer_pdfs

MESES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7,
    "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}
_FECHA_RE = re.compile(
    r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b"
    r"|\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b"
    r"|\b(\d{1,2})\s+(?:DE\s+|DEL\s+MES\s+DE\s+)?(" + "|".join(MESES) + r")\s+(?:DE\s+|DEL\s+)?(\d{4})\b"
)
_CERCA_DE_EXPEDICION_RE = re.compile(r"EXPEDI|GENERAD|FECHA DE CONSULTA|FECHA Y HORA|FECHA:")


def _fecha(match: re.Match[str]) -> date | None:
    g = match.groups()
    try:
        if g[0]:
            return date(int(g[2]), int(g[1]), int(g[0]))
        if g[3]:
            return date(int(g[3]), int(g[4]), int(g[5]))
        return date(int(g[8]), MESES[g[7]], int(g[6]))
    except (ValueError, KeyError):
        return None


def fecha_expedicion(texto_norm: str) -> date | None:
    """Fecha cercana a "EXPEDICIÓN/GENERADO/FECHA"; si no hay, la primera fecha del documento."""
    for marca in _CERCA_DE_EXPEDICION_RE.finditer(texto_norm):
        cercana = _FECHA_RE.search(texto_norm, marca.start(), marca.start() + 120)
        if cercana and (f := _fecha(cercana)):
            return f
    for m in _FECHA_RE.finditer(texto_norm):
        if f := _fecha(m):
            return f
    return None


def _menciona(nombre: str, texto_norm: str) -> bool:
    """Todas las palabras significativas del nombre aparecen en el documento."""
    palabras = [p for p in re.findall(r"[A-Z0-9Ñ]+", _norm(nombre)) if len(p) >= 3 and p not in {"SAS", "LTDA", "S.A"}]
    return bool(palabras) and all(re.search(rf"\b{re.escape(p)}\b", texto_norm) for p in palabras)


def evaluar_config(
    pdfs: dict[str, bytes],
    config: ConfigPersonalizado,
    fecha_cierre: date,
    tipo_proponente: str | None,
    personas: list[str],
    nombre_proponente: str,
) -> tuple[bool, str | None, str | None]:
    """Devuelve (cumple, motivo, archivo). Separada de la descarga para poder probarla."""
    if config.aplica_a and tipo_proponente and tipo_proponente not in config.aplica_a:
        return True, "N.A. — el requisito no aplica a este tipo de proponente.", None

    frases = [_norm(f) for f in config.frases_documento]
    candidatos: list[tuple[str, str]] = []
    for nombre, contenido in pdfs.items():
        try:
            texto = _norm(extraer_texto(contenido, max_paginas=config.paginas))
        except Exception:  # noqa: BLE001
            continue
        if any(f in texto for f in frases):
            candidatos.append((nombre, texto))
    if not candidatos:
        return False, f"No se encontró el documento (se buscó: {', '.join(config.frases_documento)}).", None

    # Si hay varios, se elige el que pasa más bloques (ej. el certificado del representante correcto).
    mejor: tuple[int, str, list[str]] | None = None
    for nombre, texto in candidatos:
        faltas = _faltas(config, texto, fecha_cierre, personas, nombre_proponente)
        if mejor is None or len(faltas) < len(mejor[2]):
            mejor = (len(faltas), nombre, faltas)
        if not faltas:
            break
    _, archivo, faltas = mejor
    return (not faltas), ("; ".join(faltas) if faltas else None), archivo


def _faltas(config: ConfigPersonalizado, texto: str, fecha_cierre: date, personas: list[str], nombre_proponente: str) -> list[str]:
    faltas: list[str] = []
    for b in config.bloques:
        if b.tipo == "vigencia_maxima":
            f = fecha_expedicion(texto)
            if f is None:
                faltas.append(f"no se pudo leer la fecha de expedición — confirme manualmente que no supere {b.meses} meses")
            elif f < fecha_cierre - relativedelta(months=b.meses):
                faltas.append(
                    f"expedido el {f:%d/%m/%Y}, más de {b.meses} meses antes de la fecha de cierre ({fecha_cierre:%d/%m/%Y})"
                )
        elif b.tipo == "contiene":
            if not any(_norm(fr) in texto for fr in b.frases):
                faltas.append(f"no dice: {' / '.join(b.frases)}")
        elif b.tipo == "no_contiene":
            encontradas = [fr for fr in b.frases if _norm(fr) in texto]
            if encontradas:
                faltas.append(f"dice: {' / '.join(encontradas)}")
        elif b.tipo == "menciona_representante":
            if not personas:
                faltas.append("no se pudo identificar al representante legal para confirmarlo — revise manualmente")
            elif not any(_menciona(p, texto) for p in personas):
                faltas.append(f"no menciona al representante legal ({', '.join(personas)})")
        elif b.tipo == "menciona_proponente":
            if not _menciona(nombre_proponente, texto):
                faltas.append(f"no menciona al proponente ({nombre_proponente})")
    return faltas


def evaluar_requisito_personalizado(
    proponente: Proponente, proceso: ProcesoDocumentoBase, requisito: RequisitoDefinicion
) -> ResultadoRequisito:
    base = {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
        "requisito": requisito.numero,
    }
    try:
        pdfs = extraer_pdfs(download_file_bytes(proponente.drive_file_id))
    except Exception as exc:  # noqa: BLE001
        return ResultadoRequisito(**base, error=f"No se pudo descargar el archivo de Drive: {exc}")
    if not pdfs:
        return ResultadoRequisito(**base, error="El archivo del proponente no contiene PDFs legibles.")
    tipo = obtener_tipo_proponente(pdfs)
    necesita_personas = any(b.tipo == "menciona_representante" for b in requisito.config.bloques)
    personas = [n for n, _ in obtener_personas_a_verificar(pdfs, tipo, proceso.codigo_proceso)] if necesita_personas else []
    cumple, motivo, archivo = evaluar_config(pdfs, requisito.config, proceso.fecha_cierre, tipo, personas, proponente.nombre_proponente)
    return ResultadoRequisito(**base, cumple=cumple, motivo=motivo, archivo_evaluado=archivo, tipo_proponente=tipo, archivos_disponibles=sorted(pdfs))
