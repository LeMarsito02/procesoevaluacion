"""Lectura del Formato 3 – Experiencia.

El Formato 3 no acredita la experiencia (lo dice el propio formato): es el
índice de los contratos que el proponente aporta, con el número consecutivo
de cada uno en el RUP y el integrante que lo aporta. Los valores oficiales
salen del RUP (ver rup.py); los del formato solo sirven para cotejar.

Se pide "preferiblemente en Excel", pero muchos lo traen solo en PDF. Las
dos formas se leen igual: una lista de filas de celdas (del Excel, o de la
tabla que pdfplumber reconoce en el PDF). Las columnas se ubican por el
texto del encabezado, no por posición: cada versión del formato las mueve.

Los proponentes llenan las celdas a su manera; se vio, por ejemplo, una sola
celda con los consecutivos de dos integrantes ("ISAIAS VARGAS GONZALEZ
CONSECUTIVO - 204 / V&M CONSECUTIVO - 065") y otra con el texto copiado del
RUP ("*** EXPERIENCIA No.88 : NÚMERO CONSECUTIVO DEL CONTRATO:490").
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from motor.tecnica.rup import normalizar, numero

# Columnas por palabras de su encabezado (normalizado). El orden importa:
# se prueba cada columna contra la primera clave que la describe.
_COLUMNAS: list[tuple[str, re.Pattern]] = [
    ("orden", re.compile(r"^NO\.? DE ORDEN|^ORDEN\b|^NO\.?\s*$")),
    ("consecutivo", re.compile(r"CONSECUTIVO")),
    ("tipo_experiencia", re.compile(r"EXPERIENCIA REQUERIDA")),
    ("contratante", re.compile(r"ENTIDAD CONTRATANTE|^CONTRATANTE")),
    ("contrato", re.compile(r"CONTRATO O RESOLUCION")),
    ("codigos", re.compile(r"CLASIFICADOR")),
    ("forma", re.compile(r"FORMAS? DE EJECUCION")),
    ("integrante", re.compile(r"INTEGRANTE")),
    ("inicio", re.compile(r"INICIACION|FECHA DE INICIO")),
    ("terminacion", re.compile(r"TERMINACION")),
    ("valor_afectado", re.compile(r"AFECTADO POR")),
    ("valor_rup", re.compile(r"REPORTADO EN EL RUP")),
    ("valor_smmlv", re.compile(r"VALOR TOTAL DEL CONTRATO EN SMMLV")),
    ("lotes", re.compile(r"LOTES?\b")),
]
_FIN_RE = re.compile(r"^(LA INFORMACION INCLUIDA|NOTA\b|CARACTERISTICAS DEL FORMATO|FIRMAS?\b)")
_CONSECUTIVO_RE = re.compile(r"CONSECUTIVO[^\d\n]{0,40}(\d{1,6})")
_NUMERO_SUELTO_RE = re.compile(r"(?<![\d.,])(\d{1,6})(?:\.0)?(?![\d.,])")
_PORCENTAJE_RE = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%")


@dataclass
class ContratoFormato3:
    orden: int
    consecutivos: list[str] = field(default_factory=list)
    texto_consecutivo: str = ""
    tipo_experiencia: str = ""
    contratante: str = ""
    numero_contrato: str = ""
    objeto: str = ""
    codigos: str = ""
    forma: str = ""
    porcentaje: str = ""
    integrante: str = ""
    inicio: date | None = None
    terminacion: date | None = None
    valor_rup: float | None = None
    valor_smmlv: float | None = None
    valor_afectado: float | None = None
    lotes: str = ""


@dataclass
class Formato3:
    archivo: str
    contratos: list[ContratoFormato3] = field(default_factory=list)


def _texto(celda) -> str:
    if celda is None:
        return ""
    if isinstance(celda, float) and celda.is_integer():
        celda = int(celda)
    return " ".join(str(celda).split())


def _fecha(celda) -> date | None:
    if isinstance(celda, datetime):
        return celda.date()
    if isinstance(celda, date):
        return celda
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", _texto(celda))
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def _valor(celda) -> float | None:
    if isinstance(celda, (int, float)):
        return float(celda)
    m = re.search(r"[\d][\d.,]*", _texto(celda).replace("$", ""))
    return numero(m.group(0)) if m else None


def consecutivos_de(texto: str) -> list[str]:
    """Los consecutivos del RUP escritos en una celda. Si la celda dice
    "CONSECUTIVO", solo cuentan los números que lo siguen (el "EXPERIENCIA
    No.88" copiado del RUP no es el consecutivo)."""
    norm = normalizar(texto)
    encontrados = _CONSECUTIVO_RE.findall(norm) if "CONSECUTIVO" in norm else _NUMERO_SUELTO_RE.findall(norm)
    vistos: list[str] = []
    for n in encontrados:
        n = n.lstrip("0") or "0"
        if n not in vistos:
            vistos.append(n)
    return vistos


def _mapa_de_columnas(filas: list[list]) -> tuple[int, dict[str, int]] | None:
    """La fila donde acaba el encabezado y la columna de cada campo.

    El encabezado ocupa dos filas y no siempre las mismas: unos formatos ponen
    el título completo arriba y debajo las columnas partidas ("No." / "Objeto"
    del contrato, "I,C,UT" / "%" de la forma de ejecución), y otros ponen
    arriba la primera palabra del título ("EXPERIENCIA") y en la fila del
    consecutivo el resto ("REQUERIDA PARA LA ACTIVIDAD") junto con las
    columnas partidas. Así que cada columna se busca en el título de arriba
    pegado al de la fila del consecutivo, y las columnas partidas en esa misma
    fila o en la de abajo."""
    for i, fila in enumerate(filas):
        textos = [normalizar(_texto(c)) for c in fila]
        if not any("CONSECUTIVO" in t for t in textos) or not any("CONTRATANTE" in t for t in textos):
            continue
        anterior = [normalizar(_texto(c)) for c in filas[i - 1]] if i else []
        siguiente = [normalizar(_texto(c)) for c in filas[i + 1]] if i + 1 < len(filas) else []
        titulos = [f"{anterior[j] if j < len(anterior) else ''} {t}".strip() for j, t in enumerate(textos)]
        columnas: dict[str, int] = {}
        for j, t in enumerate(titulos):
            for campo, patron in _COLUMNAS:
                if campo not in columnas and t and patron.search(t):
                    columnas[campo] = j
                    break
        for banda in (textos, siguiente):
            for j, t in enumerate(banda):
                if t in ("NO.", "NO", "NUMERO") and "contrato" in columnas:
                    columnas.setdefault("numero_contrato", j)
                elif t.startswith("OBJETO"):
                    columnas.setdefault("objeto", j)
                elif t.startswith("I,C") or t.startswith("I, C"):
                    columnas["forma"] = j
                elif t == "%":
                    columnas.setdefault("porcentaje", j)
                elif "REPORTADO EN EL RUP" in t:
                    columnas["valor_rup"] = j
                elif "VALOR TOTAL DEL CONTRATO EN SMMLV" in t:
                    columnas["valor_smmlv"] = j
        if "numero_contrato" not in columnas and "contrato" in columnas:
            columnas["numero_contrato"] = columnas["contrato"]
        if "objeto" not in columnas and "contrato" in columnas:
            columnas["objeto"] = columnas["contrato"] + 1
        return i, columnas
    return None


def leer_filas(filas: list[list], archivo: str) -> Formato3 | None:
    ubicado = _mapa_de_columnas(filas)
    if ubicado is None:
        return None
    inicio, col = ubicado
    formato = Formato3(archivo=archivo)

    def celda(fila, campo):
        j = col.get(campo)
        return fila[j] if j is not None and j < len(fila) else None

    pegada = False
    for fila in filas[inicio + 1:]:
        primero = next((normalizar(_texto(c)) for c in fila if _texto(c)), "")
        if _FIN_RE.match(primero):
            break
        texto_consecutivo = _texto(celda(fila, "consecutivo"))
        contratante = _texto(celda(fila, "contratante"))
        if not (texto_consecutivo or contratante):
            pegada = False
            continue
        numero_contrato = _texto(celda(fila, "numero_contrato"))
        objeto = _texto(celda(fila, "objeto"))
        fecha_inicio = _fecha(celda(fila, "inicio"))
        fecha_fin = _fecha(celda(fila, "terminacion"))
        if not (contratante.strip() or numero_contrato.strip() or objeto.strip() or fecha_inicio or fecha_fin):
            # Un contrato reportado con más de un consecutivo del RUP (uno por
            # integrante del plural) ocupa dos renglones: el segundo trae solo
            # el consecutivo. Es el mismo contrato, no uno nuevo, y solo cuenta
            # si viene pegado al anterior: más abajo ya están las firmas y las
            # notas, donde cualquier número suelto parecería un consecutivo.
            if pegada and formato.contratos and texto_consecutivo.strip():
                previo = formato.contratos[-1]
                previo.consecutivos.extend(c for c in consecutivos_de(texto_consecutivo)
                                           if c not in previo.consecutivos)
                previo.texto_consecutivo = f"{previo.texto_consecutivo} {texto_consecutivo}".strip()
            continue
        orden = _valor(celda(fila, "orden"))
        if orden is None:
            # Filas del encabezado o de títulos intermedios, sin número de orden.
            if not re.search(r"\d", texto_consecutivo):
                continue
            orden = len(formato.contratos) + 1
        pegada = True
        formato.contratos.append(ContratoFormato3(
            orden=int(orden),
            consecutivos=consecutivos_de(texto_consecutivo),
            texto_consecutivo=texto_consecutivo,
            tipo_experiencia=_texto(celda(fila, "tipo_experiencia")),
            contratante=contratante,
            numero_contrato=numero_contrato,
            objeto=objeto,
            codigos=_texto(celda(fila, "codigos")),
            forma=_texto(celda(fila, "forma")),
            porcentaje=_texto(celda(fila, "porcentaje")),
            integrante=_texto(celda(fila, "integrante")),
            inicio=fecha_inicio,
            terminacion=fecha_fin,
            valor_rup=_valor(celda(fila, "valor_rup")),
            valor_smmlv=_valor(celda(fila, "valor_smmlv")),
            valor_afectado=_valor(celda(fila, "valor_afectado")),
            lotes=_texto(celda(fila, "lotes")),
        ))
    return formato if _es_coherente(formato) else None


def _es_coherente(formato: Formato3) -> bool:
    """La lectura sirve o no sirve.

    Cuando el Formato 3 viene en PDF con el encabezado partido en varios
    renglones, el mapa de columnas se corre y sale un contrato por fila pero
    con los datos cambiados de sitio: el número de orden ocupa el lugar del
    consecutivo del RUP y el consecutivo el del valor. Evaluar con eso da
    resultados falsos y mensajes que culpan al proponente ("el consecutivo 1
    no se encontró en el RUP") de un error nuestro. Si la mitad de las filas
    salen sin contratante y sin objeto, la lectura no sirve y es mejor
    decirlo: el lote va a revisión."""
    if not formato.contratos:
        return False
    vacios = sum(1 for c in formato.contratos if not c.contratante.strip() and not c.objeto.strip())
    return vacios * 2 <= len(formato.contratos)


def leer_excel(contenido: bytes, archivo: str) -> Formato3 | None:
    import openpyxl

    try:
        libro = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
    except Exception:  # noqa: BLE001
        return None
    for hoja in libro.worksheets:
        filas = [list(f) for f in hoja.iter_rows(values_only=True, max_row=200)]
        if formato := leer_filas(filas, f"{archivo} ({hoja.title})"):
            return formato
    return None


_APILADAS_RE = re.compile(r"\d{1,2}(?: \d{1,2})+")
_MARCAS_DE_NOTA = {"INFORMACION", "INCLUIDA", "NOTA", "CARACTERISTICAS", "DILIGENCIAMIENTO"}


def _bandas_de_columnas(tabla) -> list[tuple[float, float]]:
    """El rango horizontal de cada columna, sin solaparse con la siguiente.

    La tabla del Formato 3 tiene columnas partidas en dos ("Contrato o
    resolución" en "No." y "Objeto"), y pdfplumber devuelve la ancha y la
    angosta como columnas distintas que se pisan. Recortando cada una hasta
    donde empieza la siguiente, el número del contrato y su objeto dejan de
    salir pegados en la misma celda."""
    bordes = [(c.bbox[0], c.bbox[2]) for c in tabla.columns]
    bandas = []
    for j, (x0, x1) in enumerate(bordes):
        siguiente = min((o for o, _ in bordes[j + 1:] if o > x0), default=x1)
        bandas.append((x0, max(min(x1, siguiente), x0 + 1)))
    return bandas


def _fin_del_cuerpo(page, tabla, arriba: float) -> float:
    """Dónde acaban los contratos y empieza la nota del pie del formato.

    Sin línea divisoria, la nota ("LA INFORMACIÓN INCLUIDA EN ESTE FORMATO
    ES...") queda dentro del último contrato y le ensucia el objeto. Se busca
    el primer renglón que traiga dos palabras de la nota; una sola podría
    estar en el objeto de un contrato."""
    zona = page.crop((tabla.bbox[0], arriba, tabla.bbox[2], tabla.bbox[3]), strict=False)
    renglones: dict[int, set[str]] = {}
    for palabra in zona.extract_words():
        limpia = normalizar(palabra["text"]).strip(":.,")
        if limpia in _MARCAS_DE_NOTA:
            renglones.setdefault(round(palabra["top"] / 3), set()).add(limpia)
    tops = [k * 3 for k, marcas in renglones.items() if len(marcas) >= 2]
    return min(tops, default=tabla.bbox[3])


def _filas_apiladas(page, tabla, arriba: float) -> list[list]:
    """Los contratos de una tabla sin líneas entre renglones, partidos por la
    altura de cada número de orden y leídos columna por columna. Las celdas de
    pdfplumber no sirven aquí: solo están delimitadas en las dos o tres
    columnas que sí tienen líneas, y el resto llega en blanco."""
    bandas = _bandas_de_columnas(tabla)
    if not bandas:
        return []
    abajo = _fin_del_cuerpo(page, tabla, arriba)
    x0, x1 = bandas[0]
    palabras = page.crop((x0, arriba, x1, tabla.bbox[3]), strict=False).extract_words()
    alturas = sorted(w["top"] for w in palabras
                     if re.fullmatch(r"\d{1,2}", w["text"]) and w["top"] < abajo)
    if not alturas:
        return []
    # El texto de cada contrato va alrededor de su número de orden: el corte
    # entre dos contratos es la mitad entre sus números.
    cortes = [min(arriba, alturas[0])] + [(a + b) / 2 for a, b in zip(alturas, alturas[1:])] + [abajo]
    filas: list[list] = []
    for k in range(len(alturas)):
        fila = []
        for cx0, cx1 in bandas:
            try:
                fila.append(page.crop((cx0, cortes[k], cx1, cortes[k + 1]), strict=False).extract_text() or "")
            except ValueError:
                fila.append("")
        filas.append(fila)
    return filas


def _filas_de_tabla(page, tabla) -> list[list]:
    """Las filas de la tabla. Si pdfplumber junta varios contratos en una sola
    fila (la columna del orden llega como "1 2 3" porque el PDF no trae líneas
    entre renglones), esa parte se vuelve a leer por geometría."""
    textos = tabla.extract()
    apilada = next((r for r, fila in enumerate(tabla.rows)
                    if _APILADAS_RE.fullmatch(" ".join((textos[r][0] or "").split()))), None)
    if apilada is None:
        return textos
    return textos[:apilada] + _filas_apiladas(page, tabla, tabla.rows[apilada].bbox[1])


_SUBTITULOS = ("NO.", "NO", "NUMERO", "%", "OBJETO")


def _contratos_legibles(formato: Formato3 | None) -> int:
    """Cuántos contratos salieron con lo mínimo para evaluarlos."""
    if formato is None:
        return 0
    return sum(1 for c in formato.contratos if c.contratante.strip() and c.objeto.strip())


def _filas_por_geometria_de(page, tabla) -> list[list]:
    """La tabla releída por columnas, para los PDF donde la zona de los
    contratos no trae ninguna línea: pdfplumber devuelve una sola celda con
    todo pegado ("1 515 EXPERIENCIA GENERAL") y el resto en blanco."""
    crudas = tabla.extract()
    ubicado = _mapa_de_columnas(crudas)
    if ubicado is None:
        return []
    inicio = ubicado[0]
    fin = inicio
    if inicio + 1 < min(len(crudas), len(tabla.rows)):
        siguiente = [normalizar(_texto(c)) for c in crudas[inicio + 1]]
        if any(t in _SUBTITULOS or t.startswith("I,C") for t in siguiente):
            fin = inicio + 1
    if fin >= len(tabla.rows):
        return []
    return crudas[:inicio + 1] + _filas_apiladas(page, tabla, tabla.rows[fin].bbox[3])


def leer_pdf(contenido: bytes, archivo: str) -> Formato3 | None:
    """La tabla del Formato 3 en PDF: la página del encabezado y las
    siguientes mientras sigan con una tabla del mismo número de columnas (el
    mismo archivo suele traer después los soportes de cada contrato)."""
    from motor.procesamiento.pdf_utils import abrir_pdf

    filas: list[list] = []
    columnas: int | None = None
    cabeza: tuple = ()
    try:
        with abrir_pdf(contenido) as pdf:
            for page in pdf.pages[:10]:
                tablas = page.find_tables()
                if columnas is None:
                    # En la misma página suele haber otra tabla con las notas al
                    # pie del formato, que también hablan del "consecutivo del
                    # RUP". La tabla de los contratos es la que trae todas las
                    # columnas; si se lee la de las notas, el formato entero
                    # queda ilegible y el lote se va a revisión sin motivo.
                    candidatas = []
                    for tabla in tablas:
                        extraida = tabla.extract()
                        if any("CONSECUTIVO" in normalizar(_texto(c)) for f in extraida for c in f):
                            candidatas.append((tabla, max((len(f) for f in extraida), default=0)))
                    if candidatas:
                        ancho = max(a for _, a in candidatas)
                        for tabla, a in candidatas:
                            if a == ancho:
                                columnas = ancho
                                cabeza = cabeza or (page, tabla)
                                filas.extend(_filas_de_tabla(page, tabla))
                else:
                    seguidas = [t for t in tablas if max((len(f) for f in t.extract()), default=0) == columnas]
                    if not seguidas:
                        break
                    for tabla in seguidas:
                        filas.extend(_filas_de_tabla(page, tabla))
                if not cabeza or page is not cabeza[0]:
                    page.flush_cache()
            formato = leer_filas(filas, archivo) if filas else None
            if cabeza and _contratos_legibles(formato) < len(formato.contratos if formato else [1]):
                # Con las celdas en blanco quedan contratos sin contratante ni
                # objeto, que el motor no puede evaluar y mandan el lote a
                # revisión. Vale reintentar leyendo la tabla por columnas, y se
                # queda la lectura que deje más contratos completos.
                otras = _filas_por_geometria_de(*cabeza)
                mejor = leer_filas(otras, archivo) if otras else None
                if _contratos_legibles(mejor) > _contratos_legibles(formato):
                    formato = mejor
            if cabeza:
                cabeza[0].flush_cache()
    except Exception:  # noqa: BLE001
        return None
    return formato


def porcentajes_de(texto: str) -> list[float]:
    return [v / 100 for p in _PORCENTAJE_RE.findall(texto) if (v := numero(p)) is not None]
