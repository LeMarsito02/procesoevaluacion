from __future__ import annotations

import io
import re

import copy

import openpyxl
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.cell_range import CellRange

from pydantic import BaseModel, Field

from motor.esquemas.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito

DATOS_SHEET_NAME = "DATOS PROCESO"

# Fila (en cada hoja P-XX) donde va la columna L (SI/NO/REVISAR) y N (archivo/
# motivo) de cada requisito, según la plantilla jurídica de ejemplo.
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


class MapeoPlantilla(BaseModel):
    """Dónde escribe el informe dentro de una plantilla de Excel. Cada entidad
    sube su propia plantilla y ajusta este mapeo; los valores por defecto son
    los de la plantilla jurídica de ejemplo."""

    prefijo_codigo: str = Field("", description="Sigla de la entidad antepuesta al código del proceso")
    titulo: str = Field("EVALUACIÓN {tipo} - PROCESO {codigo}{de_anio}", description="Título de cada hoja de proponente")
    hoja_proponente_patron: str = Field(r"^P-\d+$", description="Expresión regular del nombre de las hojas por proponente")
    hoja_modelo: str | None = "MODELO"
    celda_titulo: str | None = "F3"
    celda_objeto: str | None = "C6"
    celda_nombre_proponente: str | None = "E10"
    columna_resultado: str = "L"
    columna_detalle: str = "N"
    filas_por_requisito: dict[int, int] = Field(default_factory=lambda: dict(FILA_POR_REQUISITO))
    hoja_resumen: str | None = "RESUMEN"
    celda_resumen: str | None = "B4"
    texto_cumple: str = "SI"
    texto_no_cumple: str = "NO"
    texto_revisar: str = "REVISAR"
    texto_no_aplica: str = "N.A."
    agregar_hoja_datos: bool = True
    # --- Cómo diligencia el abogado cada hoja (informes reales de ICCU-MC-019 y LP-022) ---
    # Número de orden del proponente.
    celda_numero: str | None = "D5"
    # Número y título de cada requisito, en la misma fila del resultado.
    columna_numero: str | None = "B"
    columna_titulo: str | None = "C"
    # La observación va debajo del requisito, en la franja combinada C:N.
    columna_observacion: str | None = "C"
    filas_hasta_observacion: int = 2
    # Integrantes del proponente plural: (celda del nombre, celda del % de participación).
    celdas_integrantes: list[tuple[str, str]] = Field(default_factory=lambda: [
        ("E12", "E14"), ("J12", "J14"), ("E16", "E18"), ("J16", "J18"), ("E20", "E22"), ("J20", "J22"),
    ])
    # Conclusión de la hoja (fórmula sobre la columna de resultados) y dónde la lee el resumen.
    celda_conclusion: str | None = "G105"
    celda_resumen_conclusion: str | None = "E6"
    hoja_indice: str | None = "CCCC"


MAPEO_POR_DEFECTO = MapeoPlantilla()


def _codigo_y_anio(codigo_proceso: str) -> tuple[str, str]:
    match = re.match(r"^(.*)-(\d{4})$", codigo_proceso.strip())
    if match:
        return match.group(1), match.group(2)
    return codigo_proceso.strip(), ""


def _codigo_completo(codigo_proceso: str, prefijo: str = "") -> str:
    codigo_sin_anio, _ = _codigo_y_anio(codigo_proceso)
    return f"{prefijo}-{codigo_sin_anio}" if prefijo else codigo_sin_anio


def _titulo_proceso(codigo_proceso: str, mapeo: MapeoPlantilla, tipo: str) -> str:
    _, anio = _codigo_y_anio(codigo_proceso)
    return mapeo.titulo.format(
        tipo=tipo.upper(),
        codigo=_codigo_completo(codigo_proceso, mapeo.prefijo_codigo),
        anio=anio,
        de_anio=f" DE {anio}" if anio else "",
    )


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
    wb: openpyxl.Workbook, proceso: ProcesoDocumentoBase, proponentes: list[Proponente], prefijo: str = ""
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
    ws["B3"] = _codigo_completo(proceso.codigo_proceso, prefijo)
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


def nit_con_dv(nit: str | None) -> str:
    """El NIT con su dígito de verificación («901.869.180-7»). Si ya lo trae
    (10 dígitos) se respeta; lo que no parece un NIT se devuelve tal cual."""
    digitos = re.sub(r"\D", "", nit or "")
    if len(digitos) == 10:
        digitos, dv = digitos[:9], digitos[9]
    elif 6 <= len(digitos) <= 9:
        pesos = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)
        resto = sum(int(d) * p for d, p in zip(reversed(digitos), pesos)) % 11
        dv = str(resto if resto < 2 else 11 - resto)
    else:
        return nit or ""
    return f"{int(digitos):,}".replace(",", ".") + f"-{dv}"


def _nombre_documento(ruta: str) -> str:
    return ruta.rsplit("/", 1)[-1]


# Una ruta dentro de la oferta citada entre comillas: «'1 - JURIDICO.rar/7 - EXISTENCIA/EXISTENCIA - X.pdf'».
_RUTA_CITADA_RE = re.compile(r"'[^'\n]*/([^'/\n]+)'")


def _sin_rutas(texto: str) -> str:
    """En el informe el documento se nombra por su archivo, no por toda la ruta de carpetas."""
    return _RUTA_CITADA_RE.sub(lambda m: f"'{m.group(1)}'", texto)


def documentos_del_resultado(r: ResultadoRequisito) -> list[str]:
    """Los documentos que sostienen el resultado, como los ve quien revisa: el
    evaluado, los demás soportes y los añadidos a mano, sin los quitados."""
    todos = [r.archivo_evaluado, *r.archivos_soporte, *r.archivos_asociados]
    return list(dict.fromkeys(a for a in todos if a and a not in r.archivos_excluidos))


def _copiar_fila(ws, origen: int, destino: int, valores: bool = False) -> None:
    for celda in ws[origen]:
        nueva = ws.cell(row=destino, column=celda.column)
        if celda.has_style:
            nueva._style = copy.copy(celda._style)
        nueva.value = celda.value if valores else None
    ws.row_dimensions[destino].height = ws.row_dimensions[origen].height


def _ampliar_bloques(ws, filas: list[int], faltan: int, mapeo: MapeoPlantilla) -> list[int]:
    """Añade `faltan` requisitos más a la hoja, con el mismo formato que los que
    ya trae, y baja el pie (conclusión, nota, firma). La plantilla tiene 18 y un
    proceso puede pedir más: antes los que no cabían se quedaban fuera del informe."""
    paso = filas[1] - filas[0] if len(filas) > 1 else 4
    modelo, ultimo = filas[0], filas[-1]
    desde_pie = ultimo + paso
    corrimiento = faltan * paso
    pie = [rango for rango in list(ws.merged_cells.ranges) if rango.min_row >= desde_pie]
    for rango in pie:
        ws.unmerge_cells(str(rango))
    for fila in range(ws.max_row, desde_pie - 1, -1):
        _copiar_fila(ws, fila, fila + corrimiento, valores=True)
        for celda in ws[fila]:
            celda.value = None
    for rango in pie:
        movido = CellRange(str(rango))
        movido.shift(row_shift=corrimiento)
        ws.merge_cells(str(movido))
    del_modelo = [rango for rango in ws.merged_cells.ranges if modelo <= rango.min_row < modelo + paso]
    nuevas = []
    for i in range(1, faltan + 1):
        fila = ultimo + paso * i
        for k in range(paso):
            _copiar_fila(ws, modelo + k, fila + k)
        for rango in del_modelo:
            copia = CellRange(str(rango))
            copia.shift(row_shift=fila - modelo)
            ws.merge_cells(str(copia))
        nuevas.append(fila)
    for validacion in ws.data_validations.dataValidation:
        if f"{mapeo.columna_resultado}{modelo}" in str(validacion.sqref).split():
            for fila in nuevas:
                validacion.add(f"{mapeo.columna_resultado}{fila}")
    if ws.print_area:
        area = CellRange(str(ws.print_area[0] if isinstance(ws.print_area, list) else ws.print_area).split("!")[-1].replace("$", ""))
        area.expand(down=corrimiento)
        ws.print_area = area.coord
    return nuevas


def _formula_conclusion(celdas: list[str]) -> str:
    """Lo mismo que la plantilla (un NO basta para no cumplir), más lo que le
    faltaba: algo sin decidir no puede salir como «CUMPLE»."""
    no = ",".join(f'{c}="NO"' for c in celdas)
    revisar = ",".join(f'{c}="REVISAR"' for c in celdas)
    return f'=+IF({celdas[0]}="","",IF(OR({no}),"NO CUMPLE",IF(OR({revisar}),"POR REVISAR","CUMPLE")))'


def _mover(celda: str, filas: int) -> str:
    m = re.fullmatch(r"([A-Z]+)(\d+)", celda)
    return f"{m.group(1)}{int(m.group(2)) + filas}" if m else celda


def _diligenciar_por_bloques(
    wb, mapeo: MapeoPlantilla, proponentes: list[Proponente], resultados: list[ResultadoRequisito],
    requisitos: list[tuple[int, str]], observaciones: dict[tuple[str, int], str],
    integrantes: dict[str, list[tuple[str, str]]],
) -> None:
    """Cada hoja como la llena el abogado: número y título de cada requisito del
    proceso (los de este pliego, en su orden), CUMPLE, nombre del documento y,
    debajo, la observación. Lo que no se evaluó queda en blanco: nunca con el
    «SI» que la plantilla trae escrito de ejemplo."""
    hoja_re = re.compile(mapeo.hoja_proponente_patron)
    base = sorted(set(mapeo.filas_por_requisito.values()))
    por_hoja: dict[str, dict[int, ResultadoRequisito]] = {}
    for r in resultados:
        por_hoja.setdefault(r.hoja, {})[r.requisito] = r
    usadas = {p.hoja for p in proponentes}
    faltan = max(0, len(requisitos) - len(base))
    corrimiento = faltan * (base[1] - base[0] if len(base) > 1 else 4)

    for nombre in [n for n in wb.sheetnames if hoja_re.match(n) and n not in usadas]:
        del wb[nombre]  # hojas de más de la plantilla: traen datos de ejemplo

    for proponente in proponentes:
        if proponente.hoja not in wb.sheetnames:
            continue
        ws = wb[proponente.hoja]
        filas = list(base)
        if faltan:
            filas += _ampliar_bloques(ws, base, faltan, mapeo)
        if mapeo.celda_numero:
            ws[mapeo.celda_numero] = proponente.numero_orden
        for (celda_nombre, celda_parte), (nombre_int, parte) in zip(mapeo.celdas_integrantes, integrantes.get(proponente.hoja, [])):
            ws[celda_nombre] = nombre_int
            ws[celda_parte] = parte
        de_la_hoja = por_hoja.get(proponente.hoja, {})
        for indice, fila in enumerate(filas):
            col_l, col_n = f"{mapeo.columna_resultado}{fila}", f"{mapeo.columna_detalle}{fila}"
            celda_obs = f"{mapeo.columna_observacion}{fila + mapeo.filas_hasta_observacion}" if mapeo.columna_observacion else None
            for celda in (col_l, col_n, celda_obs):
                if celda:
                    ws[celda] = None
            if indice >= len(requisitos):
                # Bloque que sobra en la plantilla: sin título ni resultado.
                for columna in (mapeo.columna_numero, mapeo.columna_titulo):
                    if columna:
                        ws[f"{columna}{fila}"] = None
                continue
            numero, titulo = requisitos[indice]
            if mapeo.columna_numero:
                ws[f"{mapeo.columna_numero}{fila}"] = numero
            if mapeo.columna_titulo:
                ws[f"{mapeo.columna_titulo}{fila}"] = titulo
            r = de_la_hoja.get(numero)
            if r is None:
                continue
            if r.error:
                ws[col_l] = mapeo.texto_revisar
                texto = f"No se pudo evaluar automáticamente: {r.error}"
            elif (r.motivo or "").startswith("N.A."):
                ws[col_l] = mapeo.texto_no_aplica
                texto = r.motivo or ""
            elif r.cumple:
                ws[col_l] = mapeo.texto_cumple
                texto = r.motivo or ""
            else:
                ws[col_l] = mapeo.texto_no_cumple
                texto = r.motivo or "No cumple."
            ws[col_n] = ", ".join(_nombre_documento(a) for a in documentos_del_resultado(r))
            ws[col_n].alignment = Alignment(wrap_text=True, vertical="center")
            decision = observaciones.get((proponente.hoja, numero), "")
            texto = " ".join(t for t in (_sin_rutas(texto).strip(), decision.strip()) if t)
            if celda_obs and texto:
                ws[celda_obs] = texto[:1500]
                ws[celda_obs].alignment = Alignment(wrap_text=True, vertical="top")
                # La franja C:N admite unas 120 letras por renglón.
                renglones = max(1, -(-len(texto[:1500]) // 120))
                ws.row_dimensions[fila + mapeo.filas_hasta_observacion].height = max(15.0, 15.0 * renglones)
        if mapeo.celda_conclusion:
            usadas_l = [f"{mapeo.columna_resultado}{f}" for f in filas[: len(requisitos)]]
            if usadas_l:
                ws[_mover(mapeo.celda_conclusion, corrimiento)] = _formula_conclusion(usadas_l)

    if mapeo.hoja_resumen and mapeo.hoja_resumen in wb.sheetnames:
        resumen = wb[mapeo.hoja_resumen]
        if mapeo.celda_resumen_conclusion and mapeo.celda_conclusion and corrimiento:
            resumen[mapeo.celda_resumen_conclusion] = _mover(mapeo.celda_conclusion, corrimiento)
        for fila in resumen.iter_rows(min_row=1):
            primera = fila[0].value
            if isinstance(primera, str) and hoja_re.match(primera.strip()) and primera.strip() not in usadas:
                for celda in fila:
                    celda.value = None
    if mapeo.hoja_indice and mapeo.hoja_indice in wb.sheetnames:
        indice_hoja = wb[mapeo.hoja_indice]
        vigentes = {int(re.sub(r"\D", "", h)) for h in usadas if re.sub(r"\D", "", h)}
        for celda in indice_hoja["A"]:
            m = re.fullmatch(r"P-0*(\d+)", str(celda.value or "").strip())
            if m and int(m.group(1)) not in vigentes:
                celda.value = None
                celda.hyperlink = None


def fill_template(
    template_path: str,
    proceso: ProcesoDocumentoBase,
    proponentes: list[Proponente] | None = None,
    resultados: list[ResultadoRequisito] | None = None,
    mapeo: MapeoPlantilla | None = None,
    tipo: str = "Jurídica",
    requisitos: list[tuple[int, str]] | None = None,
    observaciones: dict[tuple[str, int], str] | None = None,
    integrantes: dict[str, list[tuple[str, str]]] | None = None,
) -> bytes:
    """`requisitos`: (número, título) de los requisitos de ESTE proceso, en orden.
    Con ellos la hoja se diligencia por bloques, como el abogado (título,
    CUMPLE, documento y observación); sin ellos se escribe solo en las filas
    que el mapeo asigna a cada número de requisito (plantillas con mapeo propio).
    `observaciones`: la nota de la decisión humana por (hoja, requisito).
    `integrantes`: por hoja, (nombre con su NIT, % de participación)."""
    mapeo = mapeo or MAPEO_POR_DEFECTO
    wb = openpyxl.load_workbook(template_path)
    hoja_re = re.compile(mapeo.hoja_proponente_patron)

    titulo = _titulo_proceso(proceso.codigo_proceso, mapeo, tipo)
    objeto_texto = _objeto_con_lotes(proceso)

    hojas_a_actualizar = [name for name in wb.sheetnames if name == mapeo.hoja_modelo or hoja_re.match(name)]
    for name in hojas_a_actualizar:
        ws = wb[name]
        if mapeo.celda_titulo:
            ws[mapeo.celda_titulo] = titulo
        if mapeo.celda_objeto:
            ws[mapeo.celda_objeto] = objeto_texto

    if mapeo.hoja_resumen and mapeo.celda_resumen and mapeo.hoja_resumen in wb.sheetnames:
        resumen = wb[mapeo.hoja_resumen]
        codigo_completo = _codigo_completo(proceso.codigo_proceso, mapeo.prefijo_codigo)
        _, anio = _codigo_y_anio(proceso.codigo_proceso)
        actual = str(resumen[mapeo.celda_resumen].value or "")
        match = re.search(r" - (.*)$", actual)
        sufijo = match.group(1) if match else f"PRIMER INFORME DE EVALUACIÓN {tipo.upper()}"
        resumen[mapeo.celda_resumen] = f"PROCESO DE SELECCIÓN No. {codigo_completo} DE {anio} - {sufijo}"

    if mapeo.celda_nombre_proponente:
        for proponente in proponentes or []:
            if proponente.hoja in wb.sheetnames:
                wb[proponente.hoja][mapeo.celda_nombre_proponente] = proponente.nombre_proponente

    if requisitos:
        _diligenciar_por_bloques(wb, mapeo, proponentes or [], resultados or [], requisitos, observaciones or {}, integrantes or {})
    for resultado in ([] if requisitos else resultados or []):
        if resultado.hoja not in wb.sheetnames:
            continue
        fila = mapeo.filas_por_requisito.get(resultado.requisito)
        if fila is None:
            continue
        ws = wb[resultado.hoja]
        col_l, col_n = f"{mapeo.columna_resultado}{fila}", f"{mapeo.columna_detalle}{fila}"
        if resultado.error:
            ws[col_l] = mapeo.texto_revisar
            ws[col_n] = f"No se pudo evaluar automáticamente: {resultado.error}"
        elif resultado.cumple:
            ws[col_l] = mapeo.texto_cumple
            ws[col_n] = resultado.archivo_evaluado or resultado.motivo or ""
        else:
            ws[col_l] = mapeo.texto_no_cumple
            archivo = resultado.archivo_evaluado or "no se encontró el documento"
            ws[col_n] = f"{archivo} — NO CUMPLE: {resultado.motivo}"

    if mapeo.agregar_hoja_datos:
        _write_datos_proceso_sheet(wb, proceso, proponentes or [], mapeo.prefijo_codigo)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def inspeccionar_plantilla(contenido: bytes, mapeo: MapeoPlantilla | None = None) -> dict:
    """Revisa una plantilla subida: que abra, cuántas hojas de proponente tiene
    y qué texto hay en la fila de cada requisito (para confirmar el mapeo)."""
    mapeo = mapeo or MAPEO_POR_DEFECTO
    problemas: list[str] = []
    try:
        wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True)
    except Exception as exc:  # noqa: BLE001
        return {"valida": False, "problemas": [f"No se pudo abrir como Excel (.xlsx): {exc}"], "hojas": [], "hojas_proponente": 0, "filas": {}}
    try:
        hoja_re = re.compile(mapeo.hoja_proponente_patron)
    except re.error as exc:
        return {"valida": False, "problemas": [f"El patrón de hojas no es válido: {exc}"], "hojas": wb.sheetnames, "hojas_proponente": 0, "filas": {}}
    hojas_proponente = [n for n in wb.sheetnames if hoja_re.match(n)]
    if not hojas_proponente:
        problemas.append(
            f"No hay hojas de proponente que coincidan con «{mapeo.hoja_proponente_patron}». Hojas encontradas: "
            + ", ".join(wb.sheetnames[:12])
        )
    filas: dict[int, str] = {}
    if hojas_proponente:
        ws = wb[hojas_proponente[0]]
        maxima = max(mapeo.filas_por_requisito.values(), default=0)
        textos: dict[int, list[str]] = {}
        for fila in ws.iter_rows(min_row=1, max_row=maxima):
            for celda in fila:
                if getattr(celda, "row", None) in set(mapeo.filas_por_requisito.values()) and celda.value not in (None, ""):
                    textos.setdefault(celda.row, []).append(str(celda.value).strip())
        for requisito, fila in sorted(mapeo.filas_por_requisito.items()):
            etiqueta = " · ".join(t for t in textos.get(fila, []) if t)[:160]
            filas[requisito] = etiqueta
            if not etiqueta:
                problemas.append(f"La fila {fila} (requisito {requisito}) está vacía en la hoja {hojas_proponente[0]}.")
    wb.close()
    return {
        "valida": bool(hojas_proponente),
        "problemas": problemas,
        "hojas": wb.sheetnames,
        "hojas_proponente": len(hojas_proponente),
        "filas": filas,
    }
