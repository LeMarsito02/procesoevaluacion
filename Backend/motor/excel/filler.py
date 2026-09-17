from __future__ import annotations

import io
import re

import openpyxl
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from motor.esquemas.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito

ENTIDAD_PREFIJO = "ICCU"
P_SHEET_RE = re.compile(r"^P-\d+$")
DATOS_SHEET_NAME = "DATOS PROCESO"

# Fila (en cada hoja P-XX) donde va la columna L (SI/NO/REVISAR) y N (archivo/
# motivo) de cada requisito, según la plantilla real de este proceso.
FILA_POR_REQUISITO: dict[int, int] = {
    1: 29,
    2: 33,
    3: 37,
    4: 41,
    5: 45,
    6: 49,
    7: 53,
    8: 57,
    9: 61,
    10: 65,
    11: 69,
    12: 73,
    13: 77,
    14: 81,
    15: 85,
    16: 89,
    17: 93,
    18: 97,
}


def _codigo_y_anio(codigo_proceso: str) -> tuple[str, str]:
    match = re.match(r"^(.*)-(\d{4})$", codigo_proceso.strip())
    if match:
        return match.group(1), match.group(2)
    return codigo_proceso.strip(), ""


def _codigo_completo(codigo_proceso: str) -> str:
    codigo_sin_anio, _ = _codigo_y_anio(codigo_proceso)
    return f"{ENTIDAD_PREFIJO}-{codigo_sin_anio}"


def _titulo_proceso(codigo_proceso: str) -> str:
    codigo_completo = _codigo_completo(codigo_proceso)
    _, anio = _codigo_y_anio(codigo_proceso)
    return f"EVALUACIÓN JURÍDICA - PROCESO {codigo_completo} DE {anio}" if anio else f"EVALUACIÓN JURÍDICA - PROCESO {codigo_completo}"


def _objeto_con_lotes(proceso: ProcesoDocumentoBase) -> str:
    partes = []
    objeto_general = proceso.objeto_general.strip()
    if objeto_general:
        partes.append(objeto_general.rstrip(". ") + ":")
    for lote in proceso.lotes:
        partes.append(f"{lote.numero}: {lote.objeto}")
    return "\n\n".join(partes)


def _formato_pesos(valor: float) -> str:
    return f"$ {valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _write_datos_proceso_sheet(
    wb: openpyxl.Workbook, proceso: ProcesoDocumentoBase, proponentes: list[Proponente]
) -> None:
    if DATOS_SHEET_NAME in wb.sheetnames:
        del wb[DATOS_SHEET_NAME]
    ws = wb.create_sheet(DATOS_SHEET_NAME, 0)

    bold = Font(bold=True)
    title_font = Font(bold=True, size=13)
    wrap = Alignment(wrap_text=True, vertical="top")

    ws["A1"] = "DATOS DEL PROCESO (extraídos del Documento Base)"
    ws["A1"].font = title_font

    ws["A3"] = "Código del proceso"
    ws["B3"] = _codigo_completo(proceso.codigo_proceso)
    ws["A4"] = "Fecha de cierre"
    ws["B4"] = proceso.fecha_cierre.strftime("%d/%m/%Y")
    ws["A5"] = "Objeto general"
    ws["B5"] = proceso.objeto_general
    ws["B5"].alignment = wrap

    for coord in ("A3", "A4", "A5"):
        ws[coord].font = bold

    headers = ["Lote", "Objeto", "Plazo (meses)", "Valor Presupuesto Oficial", "Lugar de ejecución"]
    header_row = 7
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.font = bold

    row = header_row + 1
    for lote in proceso.lotes:
        ws.cell(row=row, column=1, value=lote.numero)
        objeto_cell = ws.cell(row=row, column=2, value=lote.objeto)
        objeto_cell.alignment = wrap
        ws.cell(row=row, column=3, value=lote.plazo_meses)
        valor_cell = ws.cell(row=row, column=4, value=lote.valor_presupuesto)
        valor_cell.number_format = '"$" #,##0.00'
        ws.cell(row=row, column=5, value=lote.lugar_ejecucion or "")
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Lote de mayor valor").font = bold
    ws.cell(row=row, column=2, value=proceso.lote_mayor_valor)
    row += 1
    ws.cell(row=row, column=1, value="Presupuesto Oficial total").font = bold
    total_cell = ws.cell(row=row, column=2, value=proceso.presupuesto_total)
    total_cell.number_format = '"$" #,##0.00'

    row += 2
    ws.cell(row=row, column=1, value="GARANTÍA DE SERIEDAD DE LA OFERTA").font = title_font
    row += 1
    g = proceso.garantia_seriedad
    campos = [
        ("Base de cálculo", "Lote de mayor valor" if g.base_calculo == "lote_mayor_valor" else "Presupuesto Oficial total"),
        ("Lote base", g.lote_base or "-"),
        ("Valor base", g.valor_base),
        ("Porcentaje asegurado", f"{g.porcentaje:.0%}"),
        ("Valor asegurado requerido", g.valor_asegurado),
        ("Fecha de cierre", g.fecha_cierre.strftime("%d/%m/%Y")),
        ("Vigencia requerida", f"{g.vigencia_meses} meses contados desde la fecha de cierre"),
        ("Fecha de vencimiento mínima de la garantía", g.fecha_vencimiento.strftime("%d/%m/%Y")),
    ]
    for label, value in campos:
        ws.cell(row=row, column=1, value=label).font = bold
        cell = ws.cell(row=row, column=2, value=value)
        if label in ("Valor base", "Valor asegurado requerido"):
            cell.number_format = '"$" #,##0.00'
        row += 1

    if proponentes:
        row += 1
        ws.cell(row=row, column=1, value="PROPONENTES (desde Google Drive)").font = title_font
        row += 1
        for header, col in (("No.", 1), ("Hoja", 2), ("Proponente", 3), ("Archivo en Drive", 4)):
            ws.cell(row=row, column=col, value=header).font = bold
        row += 1
        for proponente in proponentes:
            ws.cell(row=row, column=1, value=proponente.numero_orden)
            ws.cell(row=row, column=2, value=proponente.hoja)
            ws.cell(row=row, column=3, value=proponente.nombre_proponente)
            ws.cell(row=row, column=4, value=proponente.nombre_archivo)
            row += 1

    if proceso.advertencias:
        row += 1
        ws.cell(row=row, column=1, value="ADVERTENCIAS DE EXTRACCIÓN").font = title_font
        row += 1
        for advertencia in proceso.advertencias:
            cell = ws.cell(row=row, column=1, value=f"- {advertencia}")
            cell.alignment = wrap
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
            row += 1

    column_widths = [28, 55, 16, 24, 22]
    for i, width in enumerate(column_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def fill_template(
    template_path: str,
    proceso: ProcesoDocumentoBase,
    proponentes: list[Proponente] | None = None,
    resultados: list[ResultadoRequisito] | None = None,
) -> bytes:
    wb = openpyxl.load_workbook(template_path)

    titulo = _titulo_proceso(proceso.codigo_proceso)
    objeto_texto = _objeto_con_lotes(proceso)

    hojas_a_actualizar = [name for name in wb.sheetnames if name == "MODELO" or P_SHEET_RE.match(name)]
    for name in hojas_a_actualizar:
        ws = wb[name]
        ws["F3"] = titulo
        ws["C6"] = objeto_texto

    if "RESUMEN" in wb.sheetnames:
        resumen = wb["RESUMEN"]
        codigo_completo = _codigo_completo(proceso.codigo_proceso)
        _, anio = _codigo_y_anio(proceso.codigo_proceso)
        actual = str(resumen["B4"].value or "")
        match = re.search(r" - (.*)$", actual)
        sufijo = match.group(1) if match else "PRIMER INFORME DE EVALUACIÓN JURIDICA"
        resumen["B4"] = f"PROCESO DE SELECCIÓN No. {codigo_completo} DE {anio} - {sufijo}"

    for proponente in proponentes or []:
        if proponente.hoja in wb.sheetnames:
            wb[proponente.hoja]["E10"] = proponente.nombre_proponente

    for resultado in resultados or []:
        if resultado.hoja not in wb.sheetnames:
            continue
        fila = FILA_POR_REQUISITO.get(resultado.requisito)
        if fila is None:
            continue
        ws = wb[resultado.hoja]
        col_l, col_n = f"L{fila}", f"N{fila}"
        if resultado.error:
            ws[col_l] = "REVISAR"
            ws[col_n] = f"No se pudo evaluar automáticamente: {resultado.error}"
        elif resultado.cumple:
            ws[col_l] = "SI"
            ws[col_n] = resultado.archivo_evaluado or resultado.motivo or ""
        else:
            ws[col_l] = "NO"
            archivo = resultado.archivo_evaluado or "no se encontró el documento"
            ws[col_n] = f"{archivo} — NO CUMPLE: {resultado.motivo}"

    _write_datos_proceso_sheet(wb, proceso, proponentes or [])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
