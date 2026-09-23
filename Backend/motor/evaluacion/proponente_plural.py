from __future__ import annotations

import re
from dataclasses import dataclass

from motor.procesamiento.memoria_proponente import memo_por_pdfs
from motor.evaluacion.formato1 import (
    MARCA_PERSONA_JURIDICA_RE,
    _clave_cache,
    _extraer_nombre_apertura,
    _extraer_representante_legal,
    _guardar_cache,
    _leer_cache,
    _codigo_variantes,
    _norm,
    en_encabezado,
    encontrar_formato1,
    extraer_cedula_representante,
    obtener_tipo_proponente,
)
from motor.integrations.drive import download_file_bytes, get_file_metadata
from motor.llm.cliente import aparece_en_texto, consultar_json
from motor.esquemas.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from motor.procesamiento.pdf_utils import extraer_texto
from motor.procesamiento.zip_utils import extraer_pdfs

# El título interno es siempre este, sin importar el nombre del archivo
# ("Formato 2 - Conformación...", "Acuerdo Consorcial...", "4. Conformación
# Consorcio...", etc. son solo nombres de archivo distintos para el mismo
# documento).
TITULO_FORMATO2_RE = re.compile(r"FORMATO\s*(?:NO\.?\s*)?2\b.{0,15}CONFORMACION DE PROPONENTE PLURAL")

# Muchos proponentes copian solo el subtítulo de la variante que usan
# ("FORMATO 2A — DOCUMENTO DE CONFORMACION DE CONSORCIO", "FORMATO NO. 2B –
# DOCUMENTO DE CONFORMACION DE UNION TEMPORAL") o ni siquiera el número.
# Como esa frase puede citarse en otros documentos, sin el título general
# solo se acepta en el encabezado (ver `en_encabezado`).
SUBTITULO_FORMATO2_RE = re.compile(r"DOCUMENTO DE CONFORMACION DE(?:L)? (?:CONSORCIO|UNION TEMPORAL)")


def es_titulo_formato2(texto_norm: str) -> bool:
    return bool(TITULO_FORMATO2_RE.search(texto_norm)) or en_encabezado(SUBTITULO_FORMATO2_RE, texto_norm)

PISTAS_NOMBRE_FORMATO2 = (
    "formato 2",
    "formato2",
    "conformacion de proponente plural",
    "conformacion consorcio",
    "conformacion union temporal",
    "acuerdo consorcial",
    "acuerdo union temporal",
    "documento consorcial",
)

# Los documentos reales revisados son cortos (2 páginas), pero se deja margen
# por si vienen fusionados con otro documento antes.
PAGINAS_A_REVISAR = 6

# "5. EL REPRESENTANTE DEL CONSORCIO ES MARIA FERNANDA GOMEZ PEREZ
# IDENTIFICADA CON CEDULA DE CIUDADANIA 52.371.321 DE BOGOTA D.C., QUIEN..."
# También se vieron variantes reales sin coma antes de "IDENTIFICADO", sin
# la palabra "IDENTIFICADO" (solo "CON CEDULA DE CIUDADANIA # ..."), y con
# "C. C. No." en vez de "CEDULA DE CIUDADANIA" escrito completo.
_CEDULA_RE = r"CON\s*(?:LA\s+)?(?:CEDULA DE CIUDADANIA|C\.?\s*C\.?)\s*(?:#|NO\.?)?\s*([\d.,]+)"
# Variantes vistas en documentos reales: "REPRESENTANTE DEL CONSORCIO ES:",
# "REPRESENTANTE LEGAL DEL CONSORCIO ES", "REPRESENTANTE LEGAL SUPLENTE DEL
# CONSORCIO ES", "REPRESENTANTE DE LA UNION TEMPORAL ES".
REPRESENTANTE_RE = re.compile(
    rf"REPRESENTANTE(?:\s+LEGAL)?(?:\s+PRINCIPAL)? (?:DEL CONSORCIO|DE LA UNION TEMPORAL) ES:?\s+"
    rf"([A-ZÑ][A-ZÑ .]+?),?\s*(?:IDENTIFICAD[OA]\s+)?{_CEDULA_RE}"
)
REPRESENTANTE_SUPLENTE_RE = re.compile(
    rf"REPRESENTANTE(?:\s+LEGAL)? SUPLENTE (?:DEL CONSORCIO|DE LA UNION TEMPORAL) ES:?\s+"
    rf"([A-ZÑ][A-ZÑ .]+?),?\s*(?:IDENTIFICAD[OA]\s+)?{_CEDULA_RE}"
)

# La tabla de integrantes sale desordenada en texto plano (nombres partidos
# en varias líneas), pero los porcentajes siempre quedan entre el
# encabezado "Compromiso (%)" y la nota al pie "El total de la columna...".
TABLA_INTEGRANTES_RE = re.compile(
    r"(?:NOMBRE DEL INTEGRANTE.*?\(%\)|INTEGRAD[OA] POR:?\s*NOMBRE\b.{0,40}?PARTICIPACION)\s*(?:\(\d\)\s*)?(.*?)"
    r"(?:EL TOTAL DE LA COLUMNA|\d+\.\s*(?:EL CONSORCIO|LA UNION TEMPORAL) SE DENOMINA)",
    re.DOTALL,
)

PORCENTAJE_CON_SIGNO_RE = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%")

# El símbolo "%" no siempre sobrevive la extracción de texto (se vio un caso
# real donde la tabla quedó como "EMPRESA A 90 INGENIERIA SAS ... 10",
# sin "%" pegado a ningún número). Este respaldo solo se usa cuando la tabla
# NO trae ningún "%" en absoluto — si trae al menos uno, se asume que el
# documento sí marca los porcentajes con "%" y cualquier número suelto es
# otra cosa (se vio un caso real donde el NIT "901.477.828-7" quedó pegado
# en la misma celda del integrante y un respaldo sin esta restricción lo
# contaba como "901%"). El lookahead exige que el número no siga
# encadenado a más dígitos/puntos/comas/letras, para no partir un NIT o un
# nombre como "9D SOLUCIONES...".
PORCENTAJE_SIN_SIGNO_RE = re.compile(r"\b(\d{1,3})(?![\d.,A-Za-zÑÁÉÍÓÚñáéíóú])")

TOLERANCIA_SUMA_PORCENTAJES = 1.5


def _orden_busqueda_formato2(nombres: list[str]) -> list[str]:
    def pista(nombre: str) -> int:
        base = _norm(nombre.rsplit("/", 1)[-1])
        return 0 if any(p.upper() in base for p in PISTAS_NOMBRE_FORMATO2) else 1

    return sorted(nombres, key=pista)


@memo_por_pdfs
def encontrar_formato2(pdfs: dict[str, bytes], codigo_proceso: str | None = None) -> tuple[str, str] | None:
    """Busca, entre los PDF del proponente, el Formato 2 (Conformación de
    Proponente Plural) por su título interno. Devuelve (nombre_archivo,
    texto_completo) o None.

    Con `codigo_proceso`, exige además que el documento mencione ese
    proceso: los proponentes adjuntan como experiencia los documentos
    consorciales de contratos anteriores, con el mismo título (se confirmó
    un caso real donde se tomaba el de un consorcio de otro contrato y se
    verificaban los antecedentes de un representante equivocado)."""
    variantes = _codigo_variantes(codigo_proceso) if codigo_proceso else None
    for nombre in _orden_busqueda_formato2(list(pdfs.keys())):
        contenido = pdfs[nombre]
        try:
            texto = extraer_texto(contenido, max_paginas=PAGINAS_A_REVISAR)
        except Exception:  # noqa: BLE001
            continue
        texto_norm = _norm(texto)
        if not es_titulo_formato2(texto_norm):
            continue
        if variantes is not None and not any(patron.search(texto_norm) for patron in variantes):
            continue
        return nombre, texto
    return None


@dataclass
class DatosProponentePlural:
    porcentajes: list[float]
    representante_principal: tuple[str, str] | None  # (nombre, cédula)
    representante_suplente: tuple[str, str] | None  # (nombre, cédula)


def extraer_datos_plural(texto: str) -> DatosProponentePlural:
    texto_norm = _norm(texto)

    porcentajes: list[float] = []
    tabla_match = TABLA_INTEGRANTES_RE.search(texto_norm)
    if tabla_match:
        # La marca de pie de nota "(1)" (referenciando la aclaración de que
        # deben sumar 100%) a veces queda pegada al final de la tabla misma,
        # no solo en el encabezado — se quita antes de leer números para que
        # no se cuente como un "1%" adicional. Algunas tablas también traen
        # su propia fila "TOTAL 100%", que si no se descarta se suma aparte
        # y duplica el resultado (ej. 90% + 10% + 100% = 200%).
        # Limitación conocida: en PDF de varias columnas, pdfplumber a veces
        # intercala el texto de la nota al pie ("...LA SUMA DE LOS
        # PORCENTAJES...DEBE SER IGUAL AL 100%.") en medio de la tabla en
        # vez de dejarlo después, y ese "100%" de la nota se cuenta como si
        # fuera un integrante más. No se detectó una forma confiable de
        # distinguirlo del contenido real sin un parseo de tabla más
        # sofisticado (por coordenadas) — cuando pasa, la suma da mal y el
        # caso queda (correctamente) para revisión humana, aunque el motivo
        # mostrado puede no reflejar el porcentaje real.
        contenido_tabla = re.sub(r"\(\d+\)", "", tabla_match.group(1))
        # La nota "...DEBE SER IGUAL AL 100%" a veces queda intercalada en
        # la tabla (PDF a dos columnas) y su 100% se contaba como integrante.
        contenido_tabla = re.sub(r"IGUAL\s+AL\s+100\s*%", "", contenido_tabla)
        contenido_tabla = re.sub(r"(?:TOTAL|SUMA)\s*\d{1,3}(?:[.,]\d+)?\s*%?", "", contenido_tabla)
        con_signo = PORCENTAJE_CON_SIGNO_RE.findall(contenido_tabla)
        if con_signo:
            porcentajes = [float(p.replace(",", ".")) for p in con_signo]
        else:
            porcentajes = [float(p) for p in PORCENTAJE_SIN_SIGNO_RE.findall(contenido_tabla)]

    principal_match = REPRESENTANTE_RE.search(texto_norm)
    representante_principal = None
    if principal_match:
        nombre = re.sub(r"\s+", " ", principal_match.group(1)).strip(" .")
        representante_principal = (nombre, principal_match.group(2))

    suplente_match = REPRESENTANTE_SUPLENTE_RE.search(texto_norm)
    representante_suplente = None
    if suplente_match:
        nombre = re.sub(r"\s+", " ", suplente_match.group(1)).strip(" .")
        representante_suplente = (nombre, suplente_match.group(2))

    return DatosProponentePlural(
        porcentajes=porcentajes,
        representante_principal=representante_principal,
        representante_suplente=representante_suplente,
    )


_INSTRUCCION_FORMATO2 = (
    "Este es el documento de conformación de un consorcio o unión temporal. Extrae los integrantes con su porcentaje "
    "de participación, y el representante legal designado (principal) y su suplente, con sus números de cédula. "
    'Responde JSON: {"integrantes": [{"nombre": str, "porcentaje": number}], '
    '"representante_principal": {"nombre": str|null, "cedula": str|null}, '
    '"representante_suplente": {"nombre": str|null, "cedula": str|null}}'
)


def _persona_verificada(dato: object, texto: str) -> tuple[str, str | None] | None:
    if not isinstance(dato, dict):
        return None
    nombre = dato.get("nombre")
    if not isinstance(nombre, str) or len(nombre.split()) < 2 or not aparece_en_texto(nombre, texto):
        return None
    cedula = dato.get("cedula")
    cedula_ok = cedula if isinstance(cedula, str) and aparece_en_texto(cedula, texto, numerico=True) else None
    return re.sub(r"\s+", " ", nombre).strip(" ."), cedula_ok


def _porcentajes_verificados(integrantes: object, texto: str) -> list[float]:
    """Porcentajes del modelo aceptados solo si TODOS aparecen escritos como
    porcentaje en el documento ("70%", "70,0 %") junto a un integrante cuyo
    nombre sí está en el texto."""
    if not isinstance(integrantes, list) or len(integrantes) < 2:
        return []
    texto_norm = _norm(texto)
    porcentajes = []
    for integrante in integrantes:
        if not isinstance(integrante, dict):
            return []
        nombre, porcentaje = integrante.get("nombre"), integrante.get("porcentaje")
        if not isinstance(nombre, str) or not aparece_en_texto(nombre, texto):
            return []
        if not isinstance(porcentaje, (int, float)) or not 0 < porcentaje <= 100:
            return []
        entero = int(porcentaje)
        if not re.search(rf"(?<![\d.,]){entero}(?:[.,]\d+)?\s*%", texto_norm):
            return []
        porcentajes.append(float(porcentaje))
    return porcentajes


@memo_por_pdfs
def datos_formato2(
    pdfs: dict[str, bytes], codigo_proceso: str | None = None
) -> tuple[str, DatosProponentePlural, bool] | None:
    """(archivo, datos, se_usó_IA) del Formato 2, o None si no se encontró.
    Primero las reglas; lo que no logren leer lo intenta el modelo local, y
    cada dato suyo se verifica contra el texto del documento."""
    encontrado = encontrar_formato2(pdfs, codigo_proceso)
    if encontrado is None:
        return None
    archivo, texto = encontrado
    datos = extraer_datos_plural(texto)
    if datos.porcentajes and datos.representante_principal:
        return archivo, datos, False

    respuesta = consultar_json(_INSTRUCCION_FORMATO2, texto)
    if not respuesta:
        return archivo, datos, False
    uso_ia = False
    porcentajes = datos.porcentajes
    if not porcentajes:
        porcentajes = _porcentajes_verificados(respuesta.get("integrantes"), texto)
        uso_ia = uso_ia or bool(porcentajes)
    principal, suplente = datos.representante_principal, datos.representante_suplente
    if principal is None:
        principal = _persona_verificada(respuesta.get("representante_principal"), texto)
        suplente = suplente or _persona_verificada(respuesta.get("representante_suplente"), texto)
        uso_ia = uso_ia or principal is not None
    return (
        archivo,
        DatosProponentePlural(porcentajes=porcentajes, representante_principal=principal, representante_suplente=suplente),
        uso_ia,
    )


class ResultadoEvaluacionPlural:
    def __init__(
        self,
        cumple: bool,
        motivo: str | None,
        datos: DatosProponentePlural | None,
        archivo_formato2: str | None,
    ) -> None:
        self.cumple = cumple
        self.motivo = motivo
        self.datos = datos
        self.archivo_formato2 = archivo_formato2


def evaluar_requisito4(
    pdfs: dict[str, bytes], tipo_proponente: str | None, codigo_proceso: str | None = None
) -> ResultadoEvaluacionPlural:
    """Requisito 4: Conformación de Proponente Plural (Formato 2). N.A. si el
    proponente es individual (persona natural o jurídica); si es Consorcio o
    Unión Temporal, debe aportar el Formato 2 con los integrantes y sus
    porcentajes de participación (deben sumar 100%) y el representante legal
    designado para el consorcio/UT."""
    if tipo_proponente is None:
        return ResultadoEvaluacionPlural(
            cumple=False,
            motivo=("No se pudo determinar si el proponente es plural: no se leyó el tipo en la carta de presentación "
                    "(Formato 1) ni el nombre lo indica. Revísalo: si es consorcio o unión temporal, verifica el Formato 2."),
            datos=None,
            archivo_formato2=None,
        )
    if tipo_proponente not in ("consorcio", "union_temporal"):
        return ResultadoEvaluacionPlural(
            cumple=True,
            motivo="N.A. — persona natural o jurídica individual",
            datos=None,
            archivo_formato2=None,
        )

    encontrado = datos_formato2(pdfs, codigo_proceso)
    if encontrado is None:
        return ResultadoEvaluacionPlural(
            cumple=False,
            motivo=(
                "El proponente es Consorcio/Unión Temporal pero no se encontró el Formato 2 (Conformación de "
                "Proponente Plural) por título dentro de sus documentos. Revisa manualmente."
            ),
            datos=None,
            archivo_formato2=None,
        )

    archivo_formato2, datos, uso_ia = encontrado

    motivos = []
    if not datos.porcentajes:
        motivos.append(
            "no se pudieron leer los porcentajes de participación de los integrantes en el Formato 2 — "
            "confirma manualmente que sumen 100%"
        )
    elif abs(sum(datos.porcentajes) - 100) > TOLERANCIA_SUMA_PORCENTAJES:
        motivos.append(
            f"los porcentajes de participación de los integrantes suman {sum(datos.porcentajes):g}%, no 100%"
        )

    if datos.representante_principal is None:
        motivos.append(
            "no se pudo identificar en el Formato 2 quién es el representante legal designado del "
            "consorcio/unión temporal — revisa manualmente"
        )

    cumple = not motivos
    motivo = "; ".join(motivos) if motivos else None
    if uso_ia:
        nota = "datos del Formato 2 leídos con IA local y verificados contra el texto"
        motivo = f"{motivo} ({nota})" if motivo else nota

    return ResultadoEvaluacionPlural(cumple=cumple, motivo=motivo, datos=datos, archivo_formato2=archivo_formato2)


@dataclass(frozen=True)
class Integrante:
    nombre: str
    identificacion: str | None
    persona_natural: bool


_INSTRUCCION_INTEGRANTES = (
    "Este es el documento de conformación de un consorcio o unión temporal. Lista TODOS sus integrantes, con el "
    "nombre completo tal como aparece (razón social si es empresa) y su número de identificación (NIT o cédula) si "
    'aparece. Responde JSON: {"integrantes": [{"nombre": str, "identificacion": str|null}]}'
)


_PORCENTAJE_CELDA_RE = re.compile(r"^\s*(\d{1,3}(?:[.,]\d+)?)\s*%\s*$")
_NIT_CELDA_RE = re.compile(r"\bN\.?I\.?T\.?\s*(?:NO\.?|N[°º])?\s*:?\s*(\d[\d.\s]{6,}\d(?:\s*[-–]\s*\d)?)")


# NIT pegado al final del nombre sin la palabra "NIT": "V2 INGENIERIA S.A.S. 900.657.246-1".
_NIT_FINAL_RE = re.compile(r"\s(\d{3}\.?\d{3}\.?\d{3}\s*[-–]\s*\d)\s*$")


def _celda_del_nombre(celdas: list[str]) -> str:
    """Si la fila trae otras columnas (actividades a cargo de cada integrante),
    la celda del nombre es la que tiene forma societaria o NIT; si ninguna la
    tiene, la más corta con forma de nombre de persona (2 a 6 palabras sin
    números). Si no se puede elegir, se unen."""
    if len(celdas) <= 1:
        return celdas[0] if celdas else ""
    con_marca = [c for c in celdas if MARCA_PERSONA_JURIDICA_RE.search(c) or _NIT_CELDA_RE.search(c)]
    if len(con_marca) == 1:
        return con_marca[0]
    persona = [c for c in celdas if 2 <= len(c.split()) <= 6 and not re.search(r"\d", c)]
    if persona:
        return min(persona, key=len)
    return " ".join(celdas)


def _integrantes_de_tabla(contenido: bytes) -> list[Integrante]:
    """Integrantes leídos de la tabla "Nombre del integrante / Compromiso (%)"
    por coordenadas (pdfplumber). Cada fila con porcentaje abre un integrante;
    las filas siguientes sin porcentaje son el resto de su nombre (renglones
    partidos) o su NIT. Vacía si no hay tabla legible."""
    from motor.procesamiento.pdf_utils import abrir_pdf

    with abrir_pdf(contenido) as pdf:
        for page in pdf.pages[:PAGINAS_A_REVISAR]:
            for tabla in page.extract_tables():
                filas = [[re.sub(r"\s+", " ", c or "").strip() for c in fila] for fila in tabla]
                if not any("NOMBRE DEL INTEGRANTE" in _norm(" ".join(f)) for f in filas):
                    continue
                crudos: list[dict] = []
                for fila in filas:
                    celdas = [c for c in fila if c]
                    texto = _norm(" ".join(celdas))
                    # La fila del total ("TOTAL", "PORCENTAJE TOTAL 100%") no es un integrante.
                    if not celdas or "NOMBRE DEL INTEGRANTE" in texto or re.match(r"^(?:TOTAL|\(%\))", texto) \
                            or re.search(r"\bPORCENTAJE\s+TOTAL\b", texto):
                        continue
                    porcentaje = next((c for c in celdas if _PORCENTAJE_CELDA_RE.match(c)), None)
                    otras = [_norm(c) for c in celdas if not _PORCENTAJE_CELDA_RE.match(c)]
                    resto = _celda_del_nombre(otras)
                    nit = _NIT_CELDA_RE.search(resto) or _NIT_FINAL_RE.search(resto)
                    nombre = _NIT_FINAL_RE.sub("", _NIT_CELDA_RE.sub("", resto)).strip(" .,:-")
                    if porcentaje is not None:
                        crudos.append({"nombre": nombre, "nit": nit.group(1) if nit else None})
                    elif crudos:
                        if nombre and not crudos[-1]["nit"] and not nit:
                            crudos[-1]["nombre"] = f"{crudos[-1]['nombre']} {nombre}".strip()
                        if nit and not crudos[-1]["nit"]:
                            crudos[-1]["nit"] = nit.group(1)
                integrantes = [
                    Integrante(re.sub(r"\s+", " ", c["nombre"]), c["nit"], not MARCA_PERSONA_JURIDICA_RE.search(c["nombre"]) and not c["nit"])
                    for c in crudos
                    if len(c["nombre"].split()) >= 2
                ]
                if len(integrantes) >= 2:
                    return integrantes
            page.flush_cache()
    return []


@memo_por_pdfs
def integrantes_formato2(pdfs: dict[str, bytes], codigo_proceso: str | None = None) -> list[Integrante]:
    """Integrantes del consorcio o unión temporal según su Formato 2. Primero
    se lee la tabla de integrantes por coordenadas; si no se puede, el modelo
    local, y cada nombre suyo se acepta solo si todas sus palabras están en la
    tabla. Si ninguno funciona, devuelve una lista vacía."""
    encontrado = encontrar_formato2(pdfs, codigo_proceso)
    if encontrado is None:
        return []
    archivo, texto = encontrado
    try:
        de_tabla = _integrantes_de_tabla(pdfs[archivo])
    except Exception:  # noqa: BLE001
        de_tabla = []
    if de_tabla:
        return de_tabla
    # Respaldo: el modelo local (lento en CPU, por eso solo si la tabla no se leyó).
    # Cada nombre se verifica contra la tabla de integrantes, no contra todo el
    # documento: el representante del consorcio y el nombre del propio
    # consorcio también aparecen en él y el modelo a veces los lista.
    tabla = TABLA_INTEGRANTES_RE.search(_norm(texto))
    referencia = tabla.group(1) if tabla else texto
    # Se le manda el documento completo: con solo la tabla (que sale mezclada
    # por el diseño a dos columnas) partía mal los nombres.
    respuesta = consultar_json(_INSTRUCCION_INTEGRANTES, texto)
    lista = respuesta.get("integrantes") if isinstance(respuesta, dict) else None
    if not isinstance(lista, list):
        return []
    integrantes: list[Integrante] = []
    for dato in lista:
        if not isinstance(dato, dict):
            continue
        nombre = dato.get("nombre")
        if not isinstance(nombre, str) or len(nombre.split()) < 2 or not aparece_en_texto(nombre, referencia):
            continue
        if re.match(r"\s*(?:CONSORCIO|UNION TEMPORAL)\b", _norm(nombre)) or "%" in nombre:
            continue
        nombre = re.sub(r"\s+", " ", _norm(nombre)).strip(" .,")
        identificacion = dato.get("identificacion")
        if not (isinstance(identificacion, str) and aparece_en_texto(identificacion, texto, numerico=True)):
            identificacion = None
        integrantes.append(Integrante(nombre, identificacion, not MARCA_PERSONA_JURIDICA_RE.search(nombre)))
    return integrantes


@memo_por_pdfs
def obtener_personas_a_verificar(
    pdfs: dict[str, bytes], tipo_proponente: str | None, codigo_proceso: str | None = None
) -> list[tuple[str, str | None]]:
    """Devuelve la lista de personas cuyos antecedentes (REDAM, Contraloría,
    Procuraduría, Policía, RNMC) hay que verificar: el representante legal
    declarado en el Formato 1 si el proponente es individual, o el
    representante + suplente del consorcio/UT (Formato 2) si es plural — el
    abogado aclaró que en ese caso se revisan estas 2 personas, no cada
    integrante. Cada elemento es (nombre, cédula-o-None); si no se pudo
    identificar a nadie, devuelve una lista vacía."""
    if tipo_proponente not in ("consorcio", "union_temporal"):
        return _representante_formato1(pdfs)

    encontrado = datos_formato2(pdfs, codigo_proceso)
    personas: list[tuple[str, str | None]] = []
    if encontrado is not None:
        _, datos, _ = encontrado
        if datos.representante_principal:
            personas.append(datos.representante_principal)
        if datos.representante_suplente:
            personas.append(datos.representante_suplente)
    if not personas:
        # Sin Formato 2 legible, quien firma la carta (Formato 1) en nombre
        # del consorcio/UT es su representante: se verifica al menos a esa
        # persona en vez de no verificar a nadie. El Requisito 4 sigue
        # reportando aparte que falta/no se leyó el Formato 2.
        personas = _representante_formato1(pdfs)
    return personas


def _representante_formato1(pdfs: dict[str, bytes]) -> list[tuple[str, str | None]]:
    encontrado_f1 = encontrar_formato1(pdfs)
    if encontrado_f1 is None:
        return []
    _, contenido = encontrado_f1
    texto = extraer_texto(contenido)
    texto_norm = _norm(texto)
    nombre = _extraer_representante_legal(texto_norm) or _extraer_nombre_apertura(texto_norm)
    if nombre:
        return [(nombre, extraer_cedula_representante(texto_norm))]
    respuesta = consultar_json(_INSTRUCCION_FORMATO1, texto)
    persona = _persona_verificada(respuesta, texto) if respuesta else None
    return [persona] if persona else []


_INSTRUCCION_FORMATO1 = (
    "Esta es la carta de presentación de una oferta. Extrae el nombre completo y el número de cédula de la persona "
    "que la presenta y firma como representante legal del proponente (o como proponente, si es persona natural). "
    'Responde JSON: {"nombre": str|null, "cedula": str|null}'
)


def evaluar_proponente_requisito4(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    base = {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
        "requisito": 4,
    }

    try:
        metadata = get_file_metadata(proponente.drive_file_id)
    except Exception:  # noqa: BLE001
        metadata = None

    md5 = metadata.get("md5Checksum") if metadata else None
    clave_cache = _clave_cache(proponente, proceso, md5, requisito=4)
    if md5:
        cacheado = _leer_cache(clave_cache)
        if cacheado is not None:
            return cacheado

    def finalizar(resultado: ResultadoRequisito, *, cacheable: bool) -> ResultadoRequisito:
        if cacheable and md5:
            _guardar_cache(clave_cache, resultado)
        return resultado

    try:
        zip_bytes = download_file_bytes(proponente.drive_file_id, metadata=metadata)
    except Exception as exc:  # noqa: BLE001
        return ResultadoRequisito(**base, error=f"No se pudo descargar el archivo de Drive: {exc}")

    pdfs = extraer_pdfs(zip_bytes)
    if not pdfs:
        return finalizar(
            ResultadoRequisito(**base, error="El archivo del proponente no contiene PDFs legibles (¿zip dañado?)."),
            cacheable=False,
        )

    tipo_proponente = obtener_tipo_proponente(pdfs, proponente.nombre_proponente)
    resultado = evaluar_requisito4(pdfs, tipo_proponente, proceso.codigo_proceso)

    return finalizar(
        ResultadoRequisito(
            **base,
            cumple=resultado.cumple,
            motivo=resultado.motivo,
            archivo_evaluado=resultado.archivo_formato2,
            archivos_disponibles=sorted(pdfs.keys()) if resultado.archivo_formato2 is None else [],
            tipo_proponente=tipo_proponente,
        ),
        cacheable=True,
    )
