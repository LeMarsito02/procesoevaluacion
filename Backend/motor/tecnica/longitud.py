"""Longitud intervenida de un contrato, leída en sus soportes (actas de
liquidación, de terminación o de recibo, certificaciones: pliego 3.5.6).

El RUP no trae longitudes: el pliego las pide en los documentos del
contrato (3.5.5 D). Primero se buscan frases explícitas ("Longitud
Intervenida: 2346,73 ML", "se pavimentaron 2,3 km de vía"); una cantidad de
la tabla de ítems de obra (preparación de la superficie, 4.623 ML) no es la
longitud de la vía. Si no hay, el modelo local lee el soporte y su respuesta
solo se acepta con una cita copiada tal cual del documento que trae la cifra
y la unidad. Lo que no se confirme va a revisión, nunca a "no cumple".
"""
from __future__ import annotations

import re

from motor.llm.cliente import cita_literal, consultar_json
from motor.procesamiento.pdf_utils import texto_completo
from motor.tecnica.rup import normalizar, numero

PAGINAS_POR_SOPORTE = 15
# Si un soporte es del contrato pero la longitud no está en sus primeras
# páginas (actas largas: la relación de longitudes va al final), se sigue
# leyendo solo ese documento.
PAGINAS_SOPORTE_DEL_CONTRATO = 40
# La unidad no puede ser de área ni de volumen ("METROS CUADRADOS" no es longitud).
_UNIDAD = r"(KMS?|KILOMETROS?|ML|MTS?|METROS?(?:\s+LINEALES)?)\b(?!\s*(?:CUADRADOS|CUBICOS|2|3|²|³))"
_VERBO = r"(?:INTERVEN|EJECUT|CONSTRU|PAVIMENT|MEJOR|REHABILIT|RECONSTRU|REPAVIMENT|ATENDID)\w*"
_LONGITUD_RE = re.compile(
    rf"LONGITUD(?:ES)?[^\n\d]{{0,60}}?{_VERBO}[^\n\d]{{0,40}}?(\d[\d.,]*)\s*{_UNIDAD}"
    rf"|{_VERBO}[^\n\d]{{0,15}}(?:UNA\s+)?LONGITUD[^\n\d]{{0,30}}?(\d[\d.,]*)\s*{_UNIDAD}"
    rf"|{_VERBO}[^\n\d]{{0,30}}?(\d[\d.,]*)\s*(KMS?|KILOMETROS?|METROS\s+LINEALES)\b"
    # La cifra escrita en letras y repetida entre paréntesis: "LONGITUD TOTAL
    # DE VIA INTERVENIDA FUE DE SEIS MIL … PUNTO CINCO METROS LINEALES (6.872.5) ML".
    rf"|LONGITUD(?:ES)?(?:[^\n]|\n(?!\s*\n)){{0,140}}?\(\s*(\d[\d.,]*)\s*\)\s*{_UNIDAD}"
)
# Área intervenida: no reemplaza la longitud (el pliego pide longitud, 3.5.5 D;
# el evaluador técnico la pide como aclaración), pero se reporta.
_AREA_RE = re.compile(
    rf"AREA(?:S)?\s+(?:TOTAL\s+)?{_VERBO}[^\n\d]{{0,40}}?(\d[\d.,]*)\s*(M2|M²|MTS?2|METROS\s+CUADRADOS)"
    rf"|(\d[\d.,]*)\s*(M2|M²|METROS\s+CUADRADOS)\s+(?:DE\s+)?(?:VIA\s+|PAVIMENTO\s+|CALZADA\s+)?{_VERBO}"
    rf"|{_VERBO}[^\n\d]{{0,30}}?(\d[\d.,]*)\s*(M2|M²|METROS\s+CUADRADOS)\b"
)
_PISTA_SOPORTE_RE = re.compile(r"EXPERIENCIA|CONTRATO|CERTIFIC|ACTA|3\.5|TECNIC|HABILITANTE|LIQUIDACION|TERMINACION|RECIBO")
_NO_ES_SOPORTE_RE = re.compile(r"\bRUP\b|REGISTRO UNICO|FORMATO\s*[1-9]\b|FORMA\s*\d|POLIZA|CEDULA|ANTECEDENTE|FINANCIER|RESIDUAL")


def _km(valor: str, unidad: str) -> float | None:
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+[.,]\d{1,2}", valor.rstrip(".,")):
        # "5,041,56": miles y decimales con el mismo signo; la última
        # separación es la de los decimales (la lectura más baja).
        partes = re.split(r"[.,]", valor.rstrip(".,"))
        valor = "".join(partes[:-1]) + "," + partes[-1]
    v = numero(valor)
    if v is None:
        return None
    return v if unidad.startswith("K") else v / 1000


def longitudes_en(texto: str) -> list[float]:
    """Longitudes en km declaradas explícitamente en el texto."""
    encontradas = []
    for m in _LONGITUD_RE.finditer(normalizar(texto)):
        grupos = [g for g in m.groups() if g is not None]
        if len(grupos) >= 2 and (km := _km(grupos[0], grupos[1])) is not None and 0.01 <= km <= 500:
            encontradas.append(km)
    return encontradas


def areas_en(texto: str) -> list[float]:
    """Áreas intervenidas (m²) declaradas explícitamente."""
    encontradas = []
    for m in _AREA_RE.finditer(normalizar(texto)):
        valor = numero(next((g for g in m.groups()[::2] if g), ""))
        if valor is not None and valor >= 10:
            encontradas.append(valor)
    return encontradas


def numeros_del_contrato(numero_contrato: str) -> list[str]:
    """Los números que identifican el contrato en sus soportes ("278 DE 2019"
    -> ["278"]; "ICCU-CTO-688 DE 2023" -> ["688"]). Los años solo si no hay
    otro número."""
    grupos = [g.lstrip("0") for g in re.findall(r"\d+", numero_contrato) if len(g.lstrip("0")) >= 2]
    no_anos = [g for g in grupos if not (len(g) == 4 and 1990 <= int(g) <= 2035)]
    return no_anos or grupos


_PALABRAS_GENERICAS = {
    "MUNICIPIO", "DEPARTAMENTO", "ALCALDIA", "GOBERNACION", "INSTITUTO", "INFRAESTRUCTURA", "NACIONAL", "DESARROLLO",
    "FONDO", "LOCAL", "SECRETARIA", "EMPRESA", "AGENCIA", "CONCESIONES", "PUBLICAS", "OBRAS", "DISTRITAL", "MUNICIPAL",
    "DEPARTAMENTAL", "COLOMBIA", "REPUBLICA", "CONSORCIO", "UNION", "TEMPORAL",
}


def soportes_candidatos(pdfs: dict[str, bytes]) -> list[str]:
    """Documentos que pueden ser actas o certificaciones. Lo que no lo es se
    reconoce por el nombre del archivo, no por la carpeta (las actas suelen
    ir dentro de la carpeta "FORMATO 3")."""
    def no_es(a: str) -> bool:
        return bool(_NO_ES_SOPORTE_RE.search(normalizar(a.rsplit("/", 1)[-1])))

    candidatos = [a for a in pdfs if _PISTA_SOPORTE_RE.search(normalizar(a)) and not no_es(a)]
    return candidatos or [a for a in pdfs if not no_es(a)]


_INSTRUCCION_IA = (
    "Este texto es de los soportes de un contrato de obra vial (acta de liquidación, de terminación, de recibo o "
    "certificación). Di cuál es la LONGITUD DE VÍA INTERVENIDA en el contrato (construida, mejorada, pavimentada, "
    "rehabilitada o mantenida). No uses cantidades de ítems de obra (m2, m3, metros de tubería, cunetas, bordillos, "
    "demarcación, señalización) ni la longitud total de una vía de la que solo se intervino una parte. Si el texto no "
    "lo dice claramente, responde null. Un área en metros cuadrados NO es una longitud: si el texto solo trae el área "
    "intervenida, ponla aparte. Responde JSON: "
    '{"longitud": número o null, "unidad": "km" o "m", "cita": "frase copiada tal cual del texto donde aparece la longitud", '
    '"area_m2": número o null, "cita_area": "frase copiada tal cual donde aparece el área intervenida"}'
)
_PISTA_LONGITUD_RE = re.compile(r"LONGITUD|\bKMS?\b|KILOMETRO|\bML\b|METROS\s+LINEALES|K\s?\d+\s?\+\s?\d{3}|PR\s?\d+\s?\+")


def _fragmentos(texto: str, maximo: int = 6000) -> str:
    """Lo que rodea las menciones de longitud (el modelo local tiene poco contexto)."""
    trozos = []
    for m in _PISTA_LONGITUD_RE.finditer(texto):
        trozos.append(texto[max(0, m.start() - 300):m.end() + 300])
        if sum(len(t) for t in trozos) > maximo:
            break
    return "\n...\n".join(trozos)


def area_con_ia(texto: str) -> tuple[float | None, str | None]:
    """(m², cita) del área intervenida que leyó el modelo local, con la misma
    verificación de la cita que la longitud."""
    fragmento = _fragmentos(texto)
    respuesta = consultar_json(_INSTRUCCION_IA, fragmento) if fragmento else None
    if not isinstance(respuesta, dict) or respuesta.get("area_m2") in (None, "", 0):
        return None, None
    cita = str(respuesta.get("cita_area") or "")
    try:
        valor = float(str(respuesta["area_m2"]).replace(",", "."))
    except ValueError:
        return None, None
    cifras = [numero(c) for c in re.findall(r"\d[\d.,]*", normalizar(cita))]
    if not (cita_literal(cita, texto, minimo_palabras=2) and any(c is not None and abs(c - valor) < 1e-6 for c in cifras)
            and re.search(r"M2|M²|METROS\s+CUADRADOS|AREA", normalizar(cita))):
        return None, None
    return valor, " ".join(cita.split())[:240]


def longitud_con_ia(texto: str) -> tuple[float | None, str | None]:
    """(km, cita) que lee el modelo local. Se acepta solo si la cita está tal
    cual en el documento y trae la cifra y la unidad."""
    fragmento = _fragmentos(texto)
    if not fragmento:
        return None, None
    respuesta = consultar_json(_INSTRUCCION_IA, fragmento)
    if not isinstance(respuesta, dict) or respuesta.get("longitud") in (None, "", 0):
        return None, None
    cita = str(respuesta.get("cita") or "")
    try:
        valor = float(str(respuesta["longitud"]).replace(",", "."))
    except ValueError:
        return None, None
    if not cita_literal(cita, texto, minimo_palabras=2):
        return None, None
    cita_norm = normalizar(cita)
    cifras = [numero(c) for c in re.findall(r"\d[\d.,]*", cita_norm)]
    unidad = str(respuesta.get("unidad") or "").lower()
    km = valor if unidad.startswith("k") else valor / 1000
    en_cita = any(c is not None and (abs(c - valor) < 1e-6 or abs(c / 1000 - km) < 1e-6 or abs(c - km) < 1e-6) for c in cifras)
    unidad_en_cita = bool(re.search(r"\bKMS?\b|KILOMETRO|\bML\b|\bMTS?\b|METROS?", cita_norm))
    if not (en_cita and unidad_en_cita and 0.01 <= km <= 500):
        return None, None
    return km, " ".join(cita.split())[:240]


def _texto_soporte(pdfs: dict[str, bytes], textos: dict[str, str], archivo: str) -> str:
    """Texto del soporte; las páginas escaneadas, fila por fila (las actas
    traen la relación de longitudes en tablas)."""
    if archivo not in textos:
        try:
            textos[archivo] = normalizar(texto_completo(pdfs[archivo], max_paginas=PAGINAS_POR_SOPORTE))
        except Exception:  # noqa: BLE001
            textos[archivo] = ""
    return textos[archivo]


def _cita_el_contrato(archivo: str, texto: str, numeros: list[str], palabras: set[str]) -> bool:
    """El soporte cita el número del contrato (junto a la palabra
    "contrato", o en el nombre del archivo) y a su contratante."""
    cita_numero = any(
        re.search(rf"CONTRATO(?:[^\n]|\n(?!\s*\n)){{0,40}}?(?<!\d)0*{n}(?!\d)", texto) or re.search(rf"(?<!\d)0*{n}(?!\d)", normalizar(archivo))
        for n in numeros
    )
    return cita_numero and (not palabras or any(p in texto for p in palabras))


# Palabras que aparecen en casi todos los objetos de obra: no distinguen un
# contrato de otro.
_PALABRAS_OBJETO_COMUNES = {
    "CONSTRUCCION", "MANTENIMIENTO", "MEJORAMIENTO", "REHABILITACION", "REPARACION", "ADECUACION", "CONTRATO",
    "CONTRATAR", "EJECUCION", "EJECUTAR", "REALIZAR", "PROYECTO", "PROYECTOS", "MUNICIPIO", "DEPARTAMENTO",
    "VIAS", "VIAL", "VIALES", "OBRA", "OBRAS", "CIVILES", "PUBLICA", "PUBLICO", "INFRAESTRUCTURA", "SERVICIOS",
    "MEDIANTE", "SISTEMA", "PRECIOS", "UNITARIOS", "ACTIVIDADES", "NECESARIAS", "INCLUIDA", "TERRITORIO",
    "NACIONAL", "GENERAL", "ESTUDIOS", "DISENOS", "SUMINISTRO", "INTERVENTORIA", "CORRESPONDIENTE",
}
# Palabras del objeto que tienen que aparecer en el soporte para darlo por suyo.
_MINIMO_PALABRAS_OBJETO = 5
_FRACCION_PALABRAS_OBJETO = 0.7


def _palabras_del_objeto(objeto: str) -> list[str]:
    palabras = [p for p in re.findall(r"[A-ZÑ]{6,}", normalizar(objeto)) if p not in _PALABRAS_OBJETO_COMUNES]
    # Las más largas son las que identifican el contrato (nombres de vías, veredas).
    vistas: list[str] = []
    for p in sorted(dict.fromkeys(palabras), key=len, reverse=True):
        vistas.append(p)
        if len(vistas) == 8:
            break
    return vistas


def _coinciden_objeto(objeto: str, texto: str) -> int:
    """Cuántas palabras que identifican al contrato trae el soporte."""
    palabras = _palabras_del_objeto(objeto)
    if len(palabras) < _MINIMO_PALABRAS_OBJETO:
        return 0
    coinciden = sum(1 for p in palabras if p in texto)
    return coinciden if coinciden >= max(_MINIMO_PALABRAS_OBJETO, len(palabras) * _FRACCION_PALABRAS_OBJETO) else 0


def _objeto_en(objeto: str, texto: str) -> bool:
    return _coinciden_objeto(objeto, texto) > 0


def _nombre_parecido(palabras: set[str], texto: str) -> bool:
    """El contratante aparece aunque el Formato 3 lo escriba con un error de
    digitación ("VALLEDUAR" por "VALLEDUPAR")."""
    if not palabras:
        return True
    del_texto = set(re.findall(r"[A-Z]{5,}", texto))
    for p in palabras:
        if p in del_texto:
            return True
        if any(abs(len(p) - len(q)) <= 1 and sum(1 for a, b in zip(p, q) if a != b) <= 1 and q[:4] == p[:4]
               for q in del_texto):
            return True
    return False


# El documento tiene que ser uno de los del pliego 3.5.6 (acta o
# certificación), no el propio Formato 3 ni el RUP.
_ES_ACTA_RE = re.compile(r"\bACTA\b|CERTIFIC|LIQUIDACION|RECIBO\s+(?:FINAL|DEFINITIVO)|TERMINACION|CONSTANCIA")
_ES_FORMATO3_RE = re.compile(r"FORMATO\s*(?:N[O°º]\.?\s*)?3\b|CCE-EICP-FM-04|EXPERIENCIA\s*[-–]\s*DOCUMENTO\s+TIPO")


def _puede_ser_acta(archivo: str, texto: str) -> bool:
    inicio = texto[:1500]
    return bool(_ES_ACTA_RE.search(inicio) or _ES_ACTA_RE.search(normalizar(archivo))) and not _ES_FORMATO3_RE.search(inicio)


def _es_del_contrato(archivo: str, texto: str, numeros: list[str], palabras: set[str], objeto: str) -> bool:
    """El documento habla de este contrato: cita su número junto al
    contratante o, si el Formato 3 lo escribe distinto, describe el mismo
    objeto (con casi todas las palabras que lo identifican)."""
    if numeros and _cita_el_contrato(archivo, texto, numeros, palabras):
        return True
    coinciden = _coinciden_objeto(objeto, texto)
    return bool(coinciden) and (coinciden >= 6 or _nombre_parecido(palabras, texto))


def _palabras_contratante(contratante: str) -> set[str]:
    return {p for p in re.findall(r"[A-Z]{5,}", normalizar(contratante))} - _PALABRAS_GENERICAS


def soporte_del_contrato(pdfs: dict[str, bytes], textos: dict[str, str], numero_contrato: str, contratante: str,
                         objeto: str = "") -> str | None:
    """Acta o certificación del contrato (3.5.6)."""
    numeros = numeros_del_contrato(numero_contrato)
    palabras = _palabras_contratante(contratante)
    for archivo in soportes_candidatos(pdfs):
        texto = _texto_soporte(pdfs, textos, archivo)
        if _puede_ser_acta(archivo, texto) and _es_del_contrato(archivo, texto, numeros, palabras, objeto):
            return archivo
    return None


def longitud_del_contrato(
    pdfs: dict[str, bytes], textos: dict[str, str], numero_contrato: str, contratante: str, objeto: str = "",
) -> tuple[float | None, str | None, str | None]:
    """(mayor longitud en km encontrada, archivo, cita si la leyó la IA local)
    en los soportes que citan el número del contrato. Primero las frases
    explícitas; si no hay, el modelo local con verificación de la cita.
    `textos` es la memoria de los textos ya leídos."""
    numeros = numeros_del_contrato(numero_contrato)
    palabras = _palabras_contratante(contratante)
    if not numeros and not objeto:
        return None, None, None
    mejor: tuple[float | None, str | None] = (None, None)
    citados: list[str] = []
    for archivo in soportes_candidatos(pdfs):
        texto = _texto_soporte(pdfs, textos, archivo)
        # El número del contrato junto a la palabra "contrato" (un 688 suelto
        # puede ser un valor o una cantidad de otro contrato), en la carpeta, o
        # el mismo objeto.
        if not _es_del_contrato(archivo, texto, numeros, palabras, objeto):
            continue
        citados.append(archivo)
        longitudes = longitudes_en(texto)
        if longitudes and (mejor[0] is None or max(longitudes) > mejor[0]):
            mejor = (max(longitudes), archivo)
    if mejor[0] is None:
        for archivo in citados:
            clave = f"{archivo}#completo"
            if clave not in textos:
                try:
                    textos[clave] = normalizar(texto_completo(pdfs[archivo], max_paginas=PAGINAS_SOPORTE_DEL_CONTRATO))
                except Exception:  # noqa: BLE001
                    textos[clave] = textos[archivo]
            longitudes = longitudes_en(textos[clave])
            if longitudes and (mejor[0] is None or max(longitudes) > mejor[0]):
                mejor = (max(longitudes), archivo)
    if mejor[0] is not None:
        return mejor[0], mejor[1], None
    # Los soportes con más menciones de longitud primero; como mucho tres.
    for archivo in sorted(citados, key=lambda a: -len(_PISTA_LONGITUD_RE.findall(textos[a])))[:3]:
        km, cita = longitud_con_ia(textos.get(f"{archivo}#completo", textos[archivo]))
        if km is not None:
            return km, archivo, cita
    return None, None, None


def area_del_contrato(
    pdfs: dict[str, bytes], textos: dict[str, str], numero_contrato: str, contratante: str,
) -> tuple[float | None, str | None, str | None]:
    """(m², archivo, cita) del área intervenida en los soportes del contrato,
    cuando no traen la longitud: el evaluador lo reporta y pide aclaración.
    Usa los textos que ya leyó `longitud_del_contrato`."""
    numeros = numeros_del_contrato(numero_contrato)
    palabras = {p for p in re.findall(r"[A-Z]{5,}", normalizar(contratante))} - _PALABRAS_GENERICAS
    citados = []
    for archivo, texto in textos.items():
        if archivo not in pdfs:
            continue
        cita_numero = any(
            re.search(rf"CONTRATO(?:[^\n]|\n(?!\s*\n)){{0,40}}?(?<!\d)0*{n}(?!\d)", texto) or re.search(rf"(?<!\d)0*{n}(?!\d)", normalizar(archivo))
            for n in numeros
        )
        if cita_numero and (not palabras or any(p in texto for p in palabras)):
            citados.append(archivo)
            if areas := areas_en(texto):
                return max(areas), archivo, None
    for archivo in citados[:3]:
        m2, cita = area_con_ia(textos[archivo])
        if m2 is not None:
            return m2, archivo, cita
    return None, None, None
