from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

import pdfplumber
from dateutil.relativedelta import relativedelta

from motor.esquemas.proceso import GarantiaSeriedad, Lote, ProcesoDocumentoBase

MONEY_RE = re.compile(r"\$\s*([\d.,]+)")
MONTHS_RE = re.compile(r"\((\d+)\)\s*MES", re.IGNORECASE)
PERCENT_RE = re.compile(r"\((\d+(?:[.,]\d+)?)\s*%\)")
LOTE_ROW_RE = re.compile(r"^(LOTE\s*\d+|SEGMENTO\s*\d+)", re.IGNORECASE)

DEFAULT_VIGENCIA_MESES = 3
DEFAULT_PORCENTAJE = 0.10


def _norm(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _parse_money(text: str | None) -> float | None:
    if not text:
        return None
    match = MONEY_RE.search(text)
    if not match:
        return None
    raw = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_months(text: str | None) -> int | None:
    if not text:
        return None
    match = MONTHS_RE.search(text)
    return int(match.group(1)) if match else None


@dataclass
class ParsedLote:
    numero: str
    objeto: str
    plazo_meses: int | None
    valor_presupuesto: float | None
    lugar_ejecucion: str | None


@dataclass
class ParsedGarantia:
    vigencia_meses: int | None
    porcentaje: float | None
    base_calculo: str
    raw_vigencia: str = ""
    raw_valor: str = ""


@dataclass
class ParseResult:
    objeto_general: str
    lotes: list[ParsedLote] = field(default_factory=list)
    garantia: ParsedGarantia | None = None


def _find_budget_rows(pdf: pdfplumber.PDF) -> tuple[str, list[ParsedLote]]:
    objeto_general = ""
    lotes: list[ParsedLote] = []
    heading_page_idx = None
    fallback_page_idx = None

    # A table-of-contents entry also contains the heading text (with a dot
    # leader and page number), so prefer a page where the "OBJETO:" paragraph
    # itself can be found; only fall back to the first heading match otherwise.
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if "OBJETO, PRESUPUESTO OFICIAL" not in _strip_accents(text.upper()):
            continue
        if fallback_page_idx is None:
            fallback_page_idx = i
        match = re.search(r"OBJETO:\s*(.*?)\n\s*N[uú]mero", text, re.DOTALL)
        if match:
            heading_page_idx = i
            objeto_general = _norm(match.group(1))
            break

    if heading_page_idx is None:
        heading_page_idx = fallback_page_idx

    if heading_page_idx is None:
        return objeto_general, lotes

    for i in range(heading_page_idx, min(heading_page_idx + 6, len(pdf.pages))):
        page = pdf.pages[i]
        for table in page.extract_tables():
            for row in table:
                if not row or row[0] is None:
                    continue
                first_cell = _norm(row[0])
                if not LOTE_ROW_RE.match(first_cell):
                    continue
                lotes.append(
                    ParsedLote(
                        numero=first_cell,
                        objeto=_norm(row[1]) if len(row) > 1 else "",
                        plazo_meses=_parse_months(row[2] if len(row) > 2 else None),
                        valor_presupuesto=_parse_money(row[3] if len(row) > 3 else None),
                        lugar_ejecucion=_norm(row[4]) if len(row) > 4 else None,
                    )
                )
        if i > heading_page_idx and re.search(
            r"1\.2\.?\s+DOCUMENTOS DEL PROCESO", page.extract_text() or "", re.IGNORECASE
        ):
            break

    if not lotes:
        unico = _objeto_unico(pdf, heading_page_idx)
        if unico is not None:
            lotes.append(unico)
            objeto_general = objeto_general or unico.objeto

    for lote in lotes:
        lote.lugar_ejecucion = lote.lugar_ejecucion or None

    return objeto_general, lotes


_DINERO_CELDA_RE = re.compile(r"\$\s*\d[\d.,]*")


def _objeto_unico(pdf: pdfplumber.PDF, desde: int) -> ParsedLote | None:
    """Pliegos de un solo objeto (sin lotes), como los de obra pública: una
    tabla "Objeto del proyecto | Plazo | Valor presupuesto oficial | Lugar".
    Las columnas de los datos no siempre calzan con las del encabezado, así
    que cada dato se reconoce por su forma: el valor por el signo $, el plazo
    por los meses, el objeto como el texto más largo y el lugar, lo que queda."""
    # Se empieza en la primera página que nombra la sección (puede ser el índice).
    for i in range(desde, min(desde + 8, len(pdf.pages))):
        for table in pdf.pages[i].extract_tables():
            texto = _strip_accents(" ".join(c or "" for fila in table for c in fila).upper())
            if "OBJETO" not in texto or "PRESUPUESTO" not in texto:
                continue
            for row in table:
                celdas = [_norm(c) for c in row if c and _norm(c)]
                valor = next((c for c in celdas if _DINERO_CELDA_RE.search(c)), None)
                if valor is None:
                    continue
                plazo = next((c for c in celdas if re.search(r"\bMES", _strip_accents(c.upper()))), None)
                resto = [c for c in celdas if c not in (valor, plazo)]
                objeto = max(resto, key=len) if resto else ""
                lugar = next((c for c in resto if c != objeto), None)
                return ParsedLote(
                    numero="ÚNICO",
                    objeto=objeto,
                    plazo_meses=_parse_months(plazo),
                    valor_presupuesto=_parse_money(_DINERO_CELDA_RE.search(valor).group(0)),
                    lugar_ejecucion=lugar,
                )
    return None


def _row_condicion(row: list[str | None]) -> str:
    non_empty = [c for c in row[1:] if c]
    return _norm(non_empty[0]) if non_empty else ""


def _find_garantia_seriedad(pdf: pdfplumber.PDF) -> ParsedGarantia | None:
    # The heading text also shows up as a table-of-contents entry earlier in
    # the document, which has no characteristics table. Check every page
    # that mentions the heading and keep the first one that actually yields
    # a "Vigencia" and/or "Valor Asegurado" row.
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if "GARANTIA DE SERIEDAD DE LA OFERTA" not in _strip_accents(text.upper()):
            continue

        window_pages = [page]
        if i + 1 < len(pdf.pages):
            window_pages.append(pdf.pages[i + 1])

        vigencia_meses: int | None = None
        raw_vigencia = ""
        porcentaje: float | None = None
        raw_valor = ""

        for p in window_pages:
            for table in p.extract_tables():
                for row in table:
                    if not row or row[0] is None:
                        continue
                    label = _strip_accents(_norm(row[0])).lower()
                    condicion = _row_condicion(row)

                    if vigencia_meses is None and label.startswith("vigencia"):
                        m = re.search(r"(\d+)\s*mes", condicion, re.IGNORECASE)
                        if m:
                            vigencia_meses = int(m.group(1))
                            raw_vigencia = condicion

                    if porcentaje is None and "valor" in label and "asegurado" in label:
                        m = PERCENT_RE.search(condicion)
                        if m:
                            porcentaje = float(m.group(1).replace(",", ".")) / 100
                            raw_valor = condicion

            if vigencia_meses is not None and porcentaje is not None:
                break

        if vigencia_meses is None and porcentaje is None:
            # Likely the table-of-contents entry; keep looking.
            continue

        combined_text = _strip_accents("\n".join((p.extract_text() or "") for p in window_pages)).lower()
        base_calculo = "lote_mayor_valor" if "mayor valor" in combined_text else "presupuesto_total"

        return ParsedGarantia(
            vigencia_meses=vigencia_meses,
            porcentaje=porcentaje,
            base_calculo=base_calculo,
            raw_vigencia=raw_vigencia,
            raw_valor=raw_valor,
        )

    return None


def parse_documento_base(pdf_bytes: bytes) -> ParseResult:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        objeto_general, lotes = _find_budget_rows(pdf)
        garantia = _find_garantia_seriedad(pdf)
    return ParseResult(objeto_general=objeto_general, lotes=lotes, garantia=garantia)


def build_proceso(codigo_proceso: str, fecha_cierre: date, pdf_bytes: bytes) -> ProcesoDocumentoBase:
    parsed = parse_documento_base(pdf_bytes)
    advertencias: list[str] = []

    if not parsed.lotes:
        advertencias.append(
            "No se pudieron identificar lotes/segmentos en la tabla de objeto y presupuesto del Documento Base. "
            "Revise el documento manualmente."
        )

    lotes: list[Lote] = []
    for pl in parsed.lotes:
        if pl.valor_presupuesto is None:
            advertencias.append(f"No se pudo leer el valor del Presupuesto Oficial de {pl.numero}; revíselo manualmente.")
        if pl.plazo_meses is None:
            advertencias.append(f"No se pudo leer el plazo en meses de {pl.numero}; revíselo manualmente.")
        lotes.append(
            Lote(
                numero=pl.numero,
                objeto=pl.objeto,
                plazo_meses=pl.plazo_meses or 0,
                valor_presupuesto=pl.valor_presupuesto or 0.0,
                lugar_ejecucion=pl.lugar_ejecucion,
            )
        )

    if parsed.garantia is None:
        advertencias.append(
            "No se encontró el numeral de Garantía de Seriedad de la Oferta en el documento; "
            f"se usan valores por defecto ({DEFAULT_VIGENCIA_MESES} meses, {DEFAULT_PORCENTAJE:.0%})."
        )
        vigencia_meses = DEFAULT_VIGENCIA_MESES
        porcentaje = DEFAULT_PORCENTAJE
        base_calculo = "lote_mayor_valor" if len(lotes) > 1 else "presupuesto_total"
    else:
        vigencia_meses = parsed.garantia.vigencia_meses
        porcentaje = parsed.garantia.porcentaje
        base_calculo = parsed.garantia.base_calculo
        if vigencia_meses is None:
            advertencias.append(
                f"No se pudo leer la vigencia de la Garantía de Seriedad; se asumen {DEFAULT_VIGENCIA_MESES} meses."
            )
            vigencia_meses = DEFAULT_VIGENCIA_MESES
        if porcentaje is None:
            advertencias.append(
                f"No se pudo leer el porcentaje del valor asegurado de la Garantía de Seriedad; se asume {DEFAULT_PORCENTAJE:.0%}."
            )
            porcentaje = DEFAULT_PORCENTAJE

    presupuesto_total = sum(l.valor_presupuesto for l in lotes)

    if lotes:
        lote_mayor = max(lotes, key=lambda l: l.valor_presupuesto)
    else:
        lote_mayor = None

    if base_calculo == "lote_mayor_valor" and lote_mayor is not None:
        valor_base = lote_mayor.valor_presupuesto
        lote_base = lote_mayor.numero
    else:
        valor_base = presupuesto_total
        lote_base = None

    valor_asegurado = round(valor_base * porcentaje, 2)
    fecha_vencimiento = fecha_cierre + relativedelta(months=vigencia_meses)

    garantia_seriedad = GarantiaSeriedad(
        vigencia_meses=vigencia_meses,
        porcentaje=porcentaje,
        base_calculo=base_calculo,
        lote_base=lote_base,
        valor_base=valor_base,
        valor_asegurado=valor_asegurado,
        fecha_cierre=fecha_cierre,
        fecha_vencimiento=fecha_vencimiento,
    )

    return ProcesoDocumentoBase(
        codigo_proceso=codigo_proceso,
        fecha_cierre=fecha_cierre,
        objeto_general=parsed.objeto_general,
        lotes=lotes,
        lote_mayor_valor=lote_mayor.numero if lote_mayor else "",
        presupuesto_total=presupuesto_total,
        garantia_seriedad=garantia_seriedad,
        advertencias=advertencias,
    )
