from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from motor import criterios
from motor.evaluacion.sanciones_rup import HAY_SANCIONES_RE, evaluar_sanciones, extraer_sanciones
from motor.procesamiento.memoria_proponente import memo_por_pdfs
from motor.evaluacion.formato1 import (
    _clave_cache,
    _guardar_cache,
    _leer_cache,
    _norm,
    _tokens_significativos,
    obtener_tipo_proponente,
)
from motor.integrations.drive import download_file_bytes, get_file_metadata
from motor.esquemas.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from motor.llm.cliente import cita_literal, consultar_json
from motor.procesamiento.pdf_utils import abrir_pdf, buscar_pagina, extraer_texto, texto_pagina
from motor.procesamiento.zip_utils import extraer_pdfs

# Cuántas páginas se revisan buscando el título. No basta con la primera:
# varios proponentes reales anteponen una carátula con el membrete de la
# empresa y el certificado real arranca en la página 2 o 3, y antes quedaban
# reportados como "no encontrado". Se recorre página por página cortando
# apenas calza, así que en el caso común (título en la página 1) el costo es
# el mismo.
PAGINAS_PARA_TITULO = 6

# Por defecto 1 mes; cada entidad lo ajusta (parámetro "camara_meses").
VIGENCIA_MAXIMA_MESES = 1

# Título con variantes reales confirmadas entre Cámaras de Comercio: Bogotá
# dice "...REGISTRO UNICO DE PROPONENTES" (sin "EN EL"), Valledupar dice
# "...EN EL REGISTRO DE PROPONENTES", Medellín solo dice "CERTIFICADO DE
# PROPONENTES". El ".{0,20}" tolera esas variaciones entre "CLASIFICACION"
# y "PROPONENTES" sin depender de una redacción exacta.
# El "CERTIFICADO DE" es opcional: hay cámaras que titulan el documento
# simplemente "EXISTENCIA Y REPRESENTACION LEGAL". Ampliarlo no abre la
# puerta a falsos positivos porque `encontrar_documentos` exige además que
# la misma página traiga el campo de fecha de expedición, que solo aparece
# en el certificado de verdad y no en documentos que lo mencionan de paso.
# Las sucursales de sociedad extranjera no tienen Certificado de Existencia:
# la Cámara expide en su lugar el "CERTIFICADO DE MATRICULA DE SUCURSAL DE
# SOCIEDAD EXTRANJERA", que cumple la misma función.
TITULO_EXISTENCIA_RE = re.compile(
    r"(?:CERTIFICADO DE\s+)?EXISTENCIA Y REPRESENTACION LEGAL"
    r"|CERTIFICADO DE MATRICULA DE SUCURSAL DE SOCIEDAD EXTRANJERA"
)
# Igual que con el Certificado de Existencia, el "CERTIFICADO DE" es
# opcional: Bucaramanga titula el documento "REGISTRO UNICO DE PROPONENTES -
# RUP" a secas. El filtro de fecha de expedición evita que esto agarre otros
# documentos que solo mencionan el RUP (por ejemplo el Formato 2).
# Además, el RUP de Bucaramanga (plataforma virtual) no trae título: solo se
# reconoce por los campos propios del registro de proponentes.
TITULO_RUP_RE = re.compile(
    r"CERTIFICADO DE (?:INSCRIPCION Y CLASIFICACION.{0,20})?PROPONENTES"
    r"|REGISTRO UNICO DE PROPONENTES"
    r"|NUMERO DEL PROPONENTE EN LA CAMARA DE COMERCIO"
    r"|FECHA DE INSCRIPCION EN EL REGISTRO DE (?:LOS )?PROPONENTES"
)

PISTAS_EXISTENCIA = ("existencia", "camara de comercio", "camara comercio", "rep legal", "representacion legal")
PISTAS_RUP = ("rup",)

MESES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}

# Confirmado con documentos reales de al menos 4 Cámaras de Comercio
# distintas, cada una con su propio formato:
#   - "FECHA EXPEDICION: 08/07/2026 - ..." (DD/MM/AAAA, Valledupar)
#   - "FECHA EXPEDICION: 2026/07/06 - ..." (AAAA/MM/DD, Barrancabermeja)
#   - "FECHA EXPEDICION: 20 DE JULIO DE 2026 HORA: ..." (Bogotá, Certificado
#     de Existencia)
#   - "CODIGO VERIFICACION: <codigo> 20 DE JULIO DE 2026 HORA ..." (Bogotá,
#     portada del RUP — sin ninguna etiqueta "fecha expedición")
# Se prueban en orden hasta que uno calce.
# Variaciones reales del encabezado de fecha, todas de cámaras distintas:
#   - "FECHA EXPEDICION: 08/07/2026"        (pegado)
#   - "FECHA EXPEDICION : 24/07/2026"       (espacio antes de los dos puntos)
#   - "LUGAR Y FECHA DE EXPEDICION: BUCARAMANGA, 2026/07/24"  (ciudad en medio)
# De ahí el prefijo opcional "LUGAR Y", el `\s*:?\s*` y el grupo opcional que
# se come el nombre de la ciudad antes de la fecha.
_PREFIJO_FECHA = r"(?:LUGAR Y\s+)?FECHA(?:\s+DE)?\s+EXPEDICION\s*:?\s*(?:[A-ZÑ][A-ZÑ .]*,\s*)?"
_FECHA_NUMERICA_RE = re.compile(_PREFIJO_FECHA + r"(\d{2,4})/(\d{2})/(\d{2,4})")
_FECHA_MES_TEXTO_RE = re.compile(_PREFIJO_FECHA + r"(\d{1,2})\s+DE\s+([A-Z]+)\s+DE\s+(\d{4})")
_FECHA_TRAS_CODIGO_VERIFICACION_RE = re.compile(
    r"CODIGO VERIFICACION:?\s*\S+\s+(\d{1,2})\s+DE\s+([A-Z]+)\s+DE\s+(\d{4})\s+HORA"
)


def _tiene_fecha_expedicion(texto_norm: str) -> bool:
    return bool(
        _FECHA_NUMERICA_RE.search(texto_norm)
        or _FECHA_MES_TEXTO_RE.search(texto_norm)
        or _FECHA_TRAS_CODIGO_VERIFICACION_RE.search(texto_norm)
    )


def limite_expedicion_camara(fecha_cierre: date) -> tuple[date, str]:
    """(fecha de expedición más antigua aceptada, el plazo en palabras). Los
    pliegos tipo lo fijan en días calendario ("no mayor a treinta (30) días"):
    con el parámetro "camara_dias" se cuentan días exactos; sin él, meses."""
    dias = criterios.valor("camara_dias")
    if dias:
        return fecha_cierre - timedelta(days=dias), f"{dias} días calendario"
    meses = criterios.valor("camara_meses")
    return fecha_cierre - relativedelta(months=meses), f"{meses} {'mes' if meses == 1 else 'meses'}"


def _parsear_fecha_expedicion(texto_norm: str) -> date | None:
    match = _FECHA_NUMERICA_RE.search(texto_norm)
    if match:
        g1, g2, g3 = match.groups()
        try:
            if len(g1) == 4:
                return date(int(g1), int(g2), int(g3))
            return date(int(g3), int(g2), int(g1))
        except ValueError:
            return None

    for patron in (_FECHA_MES_TEXTO_RE, _FECHA_TRAS_CODIGO_VERIFICACION_RE):
        match = patron.search(texto_norm)
        if not match:
            continue
        dia_str, mes_texto, anio_str = match.groups()
        mes = MESES.get(mes_texto)
        if mes is None:
            continue
        try:
            return date(int(anio_str), mes, int(dia_str))
        except ValueError:
            return None
    return None


def _orden_busqueda(nombres: list[str], pistas: tuple[str, ...]) -> list[str]:
    def pista(nombre: str) -> int:
        base = _norm(nombre.rsplit("/", 1)[-1])
        return 0 if any(p.upper() in base for p in pistas) else 1

    return sorted(nombres, key=pista)


@memo_por_pdfs
def encontrar_documentos(pdfs: dict[str, bytes], titulo_re: re.Pattern[str], pistas: tuple[str, ...]) -> list[str]:
    """Devuelve los nombres de TODOS los PDF cuyo título calza — puede haber
    más de uno en un proponente plural (uno por cada integrante persona
    jurídica). Exige, además del título, que también aparezca 'FECHA
    EXPEDICION': se encontraron documentos reales (respuestas a preguntas
    del SECOP, cartas de composición accionaria) que solo MENCIONAN de
    pasada "el certificado de existencia y representación legal..." sin ser
    el certificado real — un certificado real siempre trae ese campo de
    fecha en el encabezado, esos otros documentos no."""
    def es_el_documento(texto: str) -> bool:
        texto_norm = _norm(texto)
        return bool(titulo_re.search(texto_norm)) and _tiene_fecha_expedicion(texto_norm)

    encontrados = []
    for nombre in _orden_busqueda(list(pdfs.keys()), pistas):
        try:
            if buscar_pagina(pdfs[nombre], es_el_documento, max_paginas=PAGINAS_PARA_TITULO) is not None:
                encontrados.append(nombre)
        except Exception:  # noqa: BLE001
            continue
    return _sin_copias(pdfs, encontrados, titulo_re)


# Los proponentes adjuntan copias del certificado de la empresa dentro de otros
# formatos (acreditación MIPYME, puntaje de industria nacional…), a veces solo
# las primeras páginas. Cada copia se evaluaba como un certificado aparte y
# bastaba una truncada para mandar el requisito a revisión. Lo que se exige es
# un certificado por empresa: se agrupan por NIT y se evalúa la copia en la que
# el certificado ocupa más páginas (el archivo del formato puede tener más
# páginas en total sin traer el certificado completo). Los integrantes de un
# consorcio tienen cada uno su NIT, así que todos se conservan.
# "NIT: 901500114-5", "NIT : 900439169-6" (Montería deja un espacio antes de
# los dos puntos), "N.I.T. 901.191.916-8". El primero del certificado es el de
# la sociedad: los que aparecen después son de terceros (revisor fiscal…).
NIT_CERTIFICADO_RE = re.compile(r"\b(?:NIT|N\.I\.T)\.?\s*:?\s*(\d[\d.]{7,}\d)")
RAZON_SOCIAL_RE = re.compile(r"RAZON SOCIAL\s*:\s*([A-Z0-9Ñ&][A-Z0-9Ñ&.,\- ]{2,80}?)\s+(?:NIT|N\.I\.T|SIGLA)\b")
CODIGO_VERIFICACION_RE = re.compile(r"CODIGO DE VERIFICACION:?\s*([A-Z0-9]{6,})")


@dataclass(frozen=True)
class Empresa:
    """Persona jurídica del proponente (él mismo, o un integrante del
    consorcio o unión temporal), tal como la identifica su certificado de
    existencia."""

    razon_social: str | None
    nit: str  # 9 dígitos, sin dígito de verificación

    @property
    def nombre(self) -> str:
        return self.razon_social or f"la empresa con NIT {self.nit}"


@memo_por_pdfs
def empresas_con_certificado(pdfs: dict[str, bytes]) -> list[Empresa]:
    """Una por cada certificado de existencia aportado (ya sin copias)."""
    empresas: dict[str, Empresa] = {}
    for nombre in encontrar_documentos(pdfs, TITULO_EXISTENCIA_RE, PISTAS_EXISTENCIA):
        try:
            texto_norm = _norm(extraer_texto(pdfs[nombre], max_paginas=PAGINAS_PARA_TITULO))
        except Exception:  # noqa: BLE001
            continue
        nit = NIT_CERTIFICADO_RE.search(texto_norm)
        if not nit:
            continue
        digitos = re.sub(r"\D", "", nit.group(1))[:9]
        razon = RAZON_SOCIAL_RE.search(texto_norm)
        empresas.setdefault(digitos, Empresa(razon.group(1).strip(" .,") if razon else None, digitos))
    return list(empresas.values())


def _identidad_y_extension(contenido: bytes, titulo_re: re.Pattern[str]) -> tuple[str | None, int]:
    """(NIT o código de verificación del certificado, páginas que ocupa el
    certificado dentro del archivo)."""
    identidad = None
    paginas_certificado = 0
    with abrir_pdf(contenido) as pdf:
        for page in pdf.pages[:MAX_PAGINAS_CERTIFICADO]:
            texto_norm = _norm(texto_pagina(page) or "")
            page.flush_cache()
            if titulo_re.search(texto_norm) or (identidad and identidad in re.sub(r"\D", "", texto_norm)):
                paginas_certificado += 1
            if identidad is None:
                nit = NIT_CERTIFICADO_RE.search(texto_norm)
                codigo = CODIGO_VERIFICACION_RE.search(texto_norm)
                if nit:
                    identidad = re.sub(r"\D", "", nit.group(1))[:9]
                elif codigo:
                    identidad = codigo.group(1)
    return identidad, paginas_certificado


def _sin_copias(pdfs: dict[str, bytes], nombres: list[str], titulo_re: re.Pattern[str]) -> list[str]:
    if len(nombres) < 2:
        return nombres
    elegido: dict[str, tuple[str, int]] = {}  # NIT -> (archivo, páginas del certificado)
    sin_identidad: list[str] = []
    for nombre in nombres:  # en orden de búsqueda: primero los que se llaman "existencia"
        try:
            identidad, paginas = _identidad_y_extension(pdfs[nombre], titulo_re)
        except Exception:  # noqa: BLE001
            identidad, paginas = None, 0
        if identidad is None:
            sin_identidad.append(nombre)
            continue
        actual = elegido.get(identidad)
        if actual is None or paginas > actual[1]:
            elegido[identidad] = (nombre, paginas)
    conservar = {archivo for archivo, _ in elegido.values()} | set(sin_identidad)
    return [n for n in nombres if n in conservar]


# Nunca se lee un certificado entero: hay RUP de cientos de páginas (algunos
# escaneados) y leerlos completos llevó un worker a ~8 GB de memoria y 4
# minutos en un proponente real. La información de existencia (objeto
# social, facultades, tipo de sociedad) está en las primeras páginas.
MAX_PAGINAS_CERTIFICADO = 40


def _texto_completo(pdfs: dict[str, bytes], nombre: str) -> str:
    return extraer_texto(pdfs[nombre], max_paginas=MAX_PAGINAS_CERTIFICADO)


def _texto_encabezado(pdfs: dict[str, bytes], nombre: str) -> str:
    """Primeras páginas: donde está la fecha de expedición (el documento
    solo se reconoce si la fecha aparece dentro de PAGINAS_PARA_TITULO)."""
    return extraer_texto(pdfs[nombre], max_paginas=PAGINAS_PARA_TITULO)


class ResultadoEvaluacionCamara:
    def __init__(self, cumple: bool, motivo: str | None, archivo: str | None) -> None:
        self.cumple = cumple
        self.motivo = motivo
        self.archivo = archivo


def _evaluar_vigencia_documentos(
    pdfs: dict[str, bytes], titulo_re: re.Pattern[str], pistas: tuple[str, ...], nombre_doc: str, fecha_cierre: date
) -> ResultadoEvaluacionCamara:
    """Patrón compartido por los Requisitos 6 (Certificado de Existencia) y 9
    (RUP): ambos exigen vigencia máxima de 1 mes contada desde el cierre, y
    ambos comparten el mismo formato de 'FECHA EXPEDICION'."""
    encontrados = encontrar_documentos(pdfs, titulo_re, pistas)
    if not encontrados:
        return ResultadoEvaluacionCamara(
            cumple=False,
            motivo=f"No se encontró el {nombre_doc} por título dentro de los documentos del proponente.",
            archivo=None,
        )

    limite, plazo = limite_expedicion_camara(fecha_cierre)
    motivos = []
    for nombre in encontrados:
        texto_norm = _norm(_texto_encabezado(pdfs, nombre))
        fecha = _parsear_fecha_expedicion(texto_norm)
        if fecha is None:
            motivos.append(
                f"no se pudo leer la fecha de expedición de '{nombre}' — confirma manualmente que no supere {plazo}"
            )
        elif fecha < limite:
            motivos.append(
                f"'{nombre}' fue expedido el {fecha.strftime('%d/%m/%Y')}, hace más de {plazo} "
                f"contado desde la fecha de cierre ({fecha_cierre.strftime('%d/%m/%Y')})"
            )

    cumple = not motivos
    return ResultadoEvaluacionCamara(cumple=cumple, motivo="; ".join(motivos) if motivos else None, archivo=encontrados[0])


def evaluar_requisito6(pdfs: dict[str, bytes], fecha_cierre: date, tipo_proponente: str | None) -> ResultadoEvaluacionCamara:
    """Requisito 6: Certificado de Existencia y Representación Legal,
    expedido máximo 1 mes antes de la fecha de cierre. N.A. si el
    proponente es persona natural (no tiene Certificado de Existencia). Si
    es plural, se evalúan todos los certificados encontrados (uno por cada
    integrante persona jurídica)."""
    if tipo_proponente == "persona_natural":
        return ResultadoEvaluacionCamara(
            cumple=True, motivo="N.A. — persona natural, no aplica Certificado de Existencia y Representación Legal", archivo=None
        )
    return _evaluar_vigencia_documentos(
        pdfs, TITULO_EXISTENCIA_RE, PISTAS_EXISTENCIA, "Certificado de Existencia y Representación Legal", fecha_cierre
    )


def evaluar_requisito9(pdfs: dict[str, bytes], fecha_cierre: date) -> ResultadoEvaluacionCamara:
    """Requisito 9: RUP (Registro Único de Proponentes), expedido máximo 1
    mes antes de la fecha de cierre. Aplica a todos los tipos de
    proponente."""
    return _evaluar_vigencia_documentos(pdfs, TITULO_RUP_RE, PISTAS_RUP, "RUP", fecha_cierre)


# "OBJETO SOCIAL OBJETO SOCIAL. POR ACTA...LA SOCIEDAD TENDRA COMO OBJETO
# PRINCIPAL..." — se toma el texto que sigue al encabezado, igual que
# _extraer_objeto_carta hace con el objeto de la carta de presentación.
def _extraer_objeto_social(texto_norm: str) -> str | None:
    idx = texto_norm.find("OBJETO SOCIAL")
    if idx == -1:
        return None
    inicio = idx + len("OBJETO SOCIAL")
    return texto_norm[inicio : inicio + 1200].strip()


# Comparación por raíz de palabra (los primeros 3 caracteres), no por
# palabra exacta: un objeto social real (Cámara de Comercio de Bogotá)
# describía "...EL DISEÑO Y LA CONSTRUCCION DE REDES VIALES, CARRETERAS..."
# — relacionado de sobra con un proceso de interventoría de VÍAS, pero con
# comparación de palabras exactas la superposición daba 0 (“VIALES” ≠
# “VIAS”). Con raíces de 3 caracteres, "VIA" cubre "VIAS"/"VIAL"/"VIALES".
def _raiz(palabra: str) -> str:
    return palabra[:3]


def _proporcion_objeto_relacionado_laxo(objeto_social: str, objeto_base: str) -> float:
    raices_base = {_raiz(t) for t in _tokens_significativos(objeto_base)}
    if not raices_base:
        return 1.0
    raices_social = {_raiz(t) for t in _tokens_significativos(objeto_social)}
    comunes = raices_social & raices_base
    return len(comunes) / len(raices_base)


# Umbral mucho más bajo que el 0.5 del Requisito 1: ahí se compara el
# objeto de la CARTA (que normalmente copia casi textual el objeto del
# proceso) contra el objeto del proceso. Aquí se compara el objeto SOCIAL
# de la empresa (una descripción amplia y genérica de todas las
# actividades que puede realizar, redactada años antes de este proceso)
# contra el objeto específico del proceso — nunca van a compartir la
# mayoría de las palabras. Confirmado con proponentes reales del sector
# construcción/ingeniería (ya con la comparación por raíz): entre 0.14 y
# 0.43; un objeto social sintético claramente NO relacionado (venta de
# alimentos y ropa) dio 0.0 — el umbral solo necesita distinguir "algo" de
# "nada" en común.
PROPORCION_MINIMA_OBJETO_SOCIAL = 0.1


def evaluar_requisito7(
    pdfs: dict[str, bytes], objeto_base: str, tipo_proponente: str | None
) -> ResultadoEvaluacionCamara:
    """Requisito 7: el objeto social del Certificado de Existencia debe
    relacionarse con el objeto del proceso — reutiliza la comparación de
    palabras clave del Requisito 1 (Carta de presentación), pero con un
    umbral mucho más permisivo (ver PROPORCION_MINIMA_OBJETO_SOCIAL). N.A.
    si es persona natural."""
    if tipo_proponente == "persona_natural":
        return ResultadoEvaluacionCamara(
            cumple=True, motivo="N.A. — persona natural, no aplica objeto social", archivo=None
        )

    encontrados = encontrar_documentos(pdfs, TITULO_EXISTENCIA_RE, PISTAS_EXISTENCIA)
    if not encontrados:
        return ResultadoEvaluacionCamara(
            cumple=False,
            motivo="No se encontró el Certificado de Existencia y Representación Legal por título dentro de los documentos del proponente.",
            archivo=None,
        )

    motivos = []
    for nombre in encontrados:
        texto_norm = _norm(_texto_completo(pdfs, nombre))
        objeto_social = _extraer_objeto_social(texto_norm)
        proporcion = _proporcion_objeto_relacionado_laxo(objeto_social or "", objeto_base)
        if proporcion < PROPORCION_MINIMA_OBJETO_SOCIAL:
            motivos.append(f"el objeto social de '{nombre}' no se relaciona claramente con el objeto del proceso")

    cumple = not motivos
    return ResultadoEvaluacionCamara(cumple=cumple, motivo="; ".join(motivos) if motivos else None, archivo=encontrados[0])


# Redacciones reales de "el representante legal no tiene límite para
# contratar", confirmadas en certificados de este proceso: "SIN LIMITE DE
# CUANTIA" (Valledupar), "NO TENDRA RESTRICCIONES DE CONTRATACION POR RAZON
# DE LA NATURALEZA NI DE LA CUANTIA" (Barrancabermeja, texto legal de las
# S.A.S.), "QUIEN NO TENDRA RESTRICCIONES PARA CONTRATAR", "EL GERENTE NO
# TENDRA RESTRICCIONES EN CUANTO A LA CUANTIA O NATURALEZA DE LOS ACTOS O
# CONTRATOS", "PODRA CELEBRAR TODA CLASE DE CONTRATOS ... SIN RESERVA NI
# LIMITACION" y "EJECUTAR TODOS LOS ACTOS O CONTRATOS SIN NINGUN TIPO DE
# LIMITACION". Las de "sin limitación" exigen que se hable de contratos
# justo antes, para no confundirlas con otras (ej. un suplente que "podrá
# obrar ... sin ninguna limitación").
FACULTADES_SIN_LIMITE_PATRONES = [
    re.compile(r"SIN LIMITE(?:S)? DE CUANTIA"),
    re.compile(r"NO TENDR[AÁ]N?\s+(?:NINGUNA\s+)?RESTRICCION(?:ES)?\s+(?:DE\s+CONTRATACION|PARA\s+CONTRATAR|EN\s+CUANTO\s+A\s+LA\s+CUANTIA)"),
    re.compile(r"SIN RESTRICCION(?:ES)?.{0,40}CUANTIA"),
    re.compile(r"CONTRAT.{0,100}SIN (?:NINGUN[OA]? )?(?:TIPO DE )?(?:RESERVA NI |RESTRICCION NI )?LIMITACI"),
]

# Un límite de cuantía explícito siempre va a revisión humana: decidir si el
# proceso lo supera y si hay un acta de autorización válida es un juicio del
# abogado (así lo pidió).
LIMITE_CUANTIA_RE = re.compile(
    r"S\.?\s*M\.?\s*M\.?\s*L\.?\s*V|SALARIOS MINIMOS|HASTA POR (?:LA SUMA|UN VALOR|UN MONTO|\$)"
    r"|CUANTIA (?:SUPERIOR|MAYOR|QUE EXCEDA)|(?:SUPERIOR|SUPERIORES|MAYOR|MAYORES) A \$|QUE EXCEDA(?:N)? (?:DE )?\$"
)

# Sección del certificado con las facultades del representante legal: desde
# su encabezado hasta el de nombramientos (o un máximo de caracteres).
SECCION_FACULTADES_RE = re.compile(
    r"(?:FACULTADES Y LIMITACIONES DEL REPRESENTANTE LEGAL|FACULTADES DEL REPRESENTANTE LEGAL|FUNCIONES DEL (?:GERENTE|REPRESENTANTE LEGAL))"
    r"(.{0,9000}?)(?=NOMBRAMIENTOS|REVISORES? FISCAL|$)",
    re.DOTALL,
)
MAX_CARACTERES_SECCION_FACULTADES = 7000

_INSTRUCCION_FACULTADES = (
    "Lee las facultades del representante legal de esta sociedad y responde si el certificado le impone alguna "
    "restricción o límite para CELEBRAR CONTRATOS o PRESENTAR PROPUESTAS en procesos de contratación, ya sea por "
    "cuantía/monto (por ejemplo un tope en salarios mínimos o en pesos) o por requerir autorización previa de la "
    "junta directiva o asamblea para contratar. Las autorizaciones para otros actos (vender o gravar bienes, "
    "reformar estatutos, nombrar empleados) NO cuentan como restricción para contratar. "
    'Responde JSON: {"restriccion_para_contratar": true|false, "cita": "frase exacta del documento que la impone, o null"}'
)


# La Cámara de Medellín no usa encabezado de facultades: las describe bajo
# un encabezado "REPRESENTACION LEGAL" a secas (Barranquilla: "REPRESENTACION
# LEGAL ADMINISTRACION:"), justo antes de
# "NOMBRAMIENTOS" (se descarta el del título "...EXISTENCIA Y REPRESENTACION
# LEGAL" que se repite en cada página).
SECCION_REPRESENTACION_LEGAL_RE = re.compile(
    r"(?<!EXISTENCIA Y )REPRESENTACION LEGAL (?:[A-Z]+: )?(?:LA|EL|LOS) (.{0,9000}?)(?=NOMBRAMIENTOS|REVISORES? FISCAL|$)",
    re.DOTALL,
)


# El límite de cuantía viene en salarios mínimos ("100 SMMLV", "cien salarios
# mínimos mensuales legales vigentes") o en pesos ("$500.000.000"). Se lee el
# número para poder compararlo con el valor del proceso: si el límite lo
# cubre, el representante sí puede firmar y el requisito se aprueba.
LIMITE_EN_SALARIOS_RE = re.compile(
    r"(\d[\d.,]*)\s*(?:\(\s*[\d.,]+\s*\)\s*)?"
    r"(?:S\.?M\.?M\.?L\.?V|S\.?M\.?L\.?M\.?V|SALARIOS?\s+MINIMOS?)"
)
LIMITE_EN_PESOS_RE = re.compile(r"\$\s*(\d[\d.,]*)")


def _numero(texto: str) -> float | None:
    """"500.000.000" o "500,000,000" → 500000000.0 (los certificados usan el
    punto como separador de miles, nunca decimales en estos montos)."""
    limpio = re.sub(r"[.,](?=\d{3}\b)", "", texto).replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


def _limite_en_pesos(fragmento: str) -> tuple[float | None, str]:
    """(monto del límite en pesos, cómo venía expresado). None si no se pudo
    leer, o si viene en salarios y la entidad no configuró el salario mínimo."""
    salarios = LIMITE_EN_SALARIOS_RE.search(fragmento)
    if salarios:
        cantidad = _numero(salarios.group(1))
        smmlv = criterios.valor("smmlv")
        if cantidad and smmlv:
            return cantidad * smmlv, f"{salarios.group(1)} salarios mínimos"
        return None, "salarios mínimos"
    pesos = LIMITE_EN_PESOS_RE.search(fragmento)
    if pesos:
        monto = _numero(pesos.group(1))
        if monto:
            return monto, f"${pesos.group(1)}"
    return None, ""


def _valor_de_referencia(proceso: ProcesoDocumentoBase) -> float | None:
    """El lote más costoso del proceso: si el límite del representante cubre
    ese valor, lo cubre para cualquier lote al que se presente."""
    valores = [lote.valor_presupuesto for lote in proceso.lotes if lote.valor_presupuesto]
    if valores:
        return float(max(valores))
    return None


def _seccion_facultades(texto_norm: str) -> str:
    match = SECCION_FACULTADES_RE.search(texto_norm) or SECCION_REPRESENTACION_LEGAL_RE.search(texto_norm)
    if not match:
        return ""
    return match.group(0)[:MAX_CARACTERES_SECCION_FACULTADES]


def _evaluar_facultades_certificado(
    nombre: str, texto_norm: str, valor_proceso: float | None = None
) -> tuple[bool, str | None]:
    """(cumple, motivo) para un Certificado de Existencia."""
    if any(patron.search(texto_norm) for patron in FACULTADES_SIN_LIMITE_PATRONES):
        return True, None

    seccion = _seccion_facultades(texto_norm)
    if not seccion:
        return False, (
            f"no se encontró la sección de facultades del representante legal en '{nombre}' — revisa manualmente "
            "si tiene límites para contratar"
        )

    limite = LIMITE_CUANTIA_RE.search(seccion)
    if limite:
        fragmento = seccion[max(0, limite.start() - 150) : limite.end() + 100]
        monto, expresado = _limite_en_pesos(fragmento)
        # Un límite que cubre el valor del proceso no impide contratar: el
        # abogado lo aprueba. Se compara contra el lote más costoso, así que
        # si alcanza para ese, alcanza para cualquiera al que se presente.
        if monto is not None and valor_proceso is not None and monto >= valor_proceso:
            return True, (
                f"'{nombre}' limita al representante legal a {expresado} (${monto:,.0f}), por encima del valor del "
                f"proceso (${valor_proceso:,.0f}): puede suscribir el contrato"
            )
        if monto is not None and valor_proceso is not None:
            return False, (
                f"'{nombre}' limita al representante legal a {expresado} (${monto:,.0f}), por debajo del valor del "
                f"proceso (${valor_proceso:,.0f}) — revisa si hay autorización de la asamblea o junta"
            )
        falta = " (la entidad no tiene configurado el salario mínimo)" if expresado == "salarios mínimos" else ""
        return False, (
            f"'{nombre}' menciona un posible límite de cuantía para el representante legal{falta} "
            f"(\"...{fragmento}...\") — revisa si el proceso lo supera y si hay autorización"
        )

    respuesta = consultar_json(_INSTRUCCION_FACULTADES, seccion)
    if respuesta is None or not isinstance(respuesta.get("restriccion_para_contratar"), bool):
        return False, (
            f"'{nombre}' no dice expresamente que el representante legal no tenga restricción para contratar y no se "
            "pudo analizar automáticamente — revisa manualmente"
        )
    if respuesta["restriccion_para_contratar"]:
        cita = respuesta.get("cita")
        if isinstance(cita, str) and cita_literal(cita, seccion):
            return False, f"'{nombre}' restringe al representante legal para contratar: \"{cita}\" — revisa manualmente"
        return False, (
            f"'{nombre}' podría restringir al representante legal para contratar (no se pudo ubicar la frase exacta) "
            "— revisa manualmente"
        )
    return True, (
        f"'{nombre}': las facultades del representante legal no mencionan límites de cuantía ni autorizaciones para "
        "contratar (analizado con IA local)"
    )


def evaluar_requisito8(
    pdfs: dict[str, bytes], tipo_proponente: str | None, valor_proceso: float | None = None
) -> ResultadoEvaluacionCamara:
    """Requisito 8: Facultades del representante legal. Cumple cuando el
    certificado dice expresamente que no hay restricción para contratar, o
    cuando sus facultades no imponen ningún límite (confirmado por el modelo
    local, sin montos ni topes detectados), y también cuando el límite que
    imponen cubre el valor del proceso. Un límite por debajo de ese valor, o
    uno que no se pueda cuantificar, queda para revisión humana. N.A. si es
    persona natural."""
    if tipo_proponente == "persona_natural":
        return ResultadoEvaluacionCamara(
            cumple=True, motivo="N.A. — persona natural, no aplica certificado de facultades", archivo=None
        )

    encontrados = encontrar_documentos(pdfs, TITULO_EXISTENCIA_RE, PISTAS_EXISTENCIA)
    if not encontrados:
        return ResultadoEvaluacionCamara(
            cumple=False,
            motivo="No se encontró el Certificado de Existencia y Representación Legal por título dentro de los documentos del proponente.",
            archivo=None,
        )

    no_cumple: list[str] = []
    notas: list[str] = []
    for nombre in encontrados:
        cumple_certificado, motivo = _evaluar_facultades_certificado(
            nombre, _norm(_texto_completo(pdfs, nombre)), valor_proceso
        )
        if not cumple_certificado:
            no_cumple.append(motivo or "")
        elif motivo:
            notas.append(motivo)

    if no_cumple:
        return ResultadoEvaluacionCamara(cumple=False, motivo="; ".join(no_cumple), archivo=encontrados[0])
    return ResultadoEvaluacionCamara(cumple=True, motivo="; ".join(notas) if notas else None, archivo=encontrados[0])


# Sección de sanciones del RUP, confirmada con RUP reales de este proceso:
# cuando una entidad reportó una sanción, el certificado trae al final un
# bloque "...EN RELACION CON LAS SANCIONES EN FIRMES ES LA SIGUIENTE:
# SANCIONES ENTIDAD QUE REPORTO LA SANCION: INSTITUTO NACIONAL DE VIAS ...
# DESCRIPCION DE LA SANCION: INCUMPLIMIENTO DEFINITIVO ... FECHA DE VIGENCIA
# DE LA SANCION: 2028/10/13". Sin sanciones ese bloque no existe: solo queda
# el encabezado genérico "REPORTE DE ... MULTAS, SANCIONES E INHABILIDADES EN
# FIRME" y el aviso legal final, que por eso no cuentan como sanción.
SANCION_REPORTADA_RE = re.compile(
    r"ENTIDAD QUE REPORTO LA (?:SANCION|MULTA|INHABILIDAD)|DESCRIPCION DE LA (?:SANCION|MULTA)"
)
DETALLE_SANCION_RE = re.compile(r"ENTIDAD QUE REPORTO LA (?:SANCION|MULTA|INHABILIDAD):?\s*(.{0,250})")
# La sección está siempre al final del RUP (se vio en la pág. 48 de 52, 187
# de 194 y 378 de 379). Se leen solo las últimas páginas: hay RUP de más de
# 500 páginas y leerlos completos dispara la memoria.
PAGINAS_FINALES_RUP = 12
MINIMO_TEXTO_PAGINAS_FINALES = 500


def _texto_paginas_finales(contenido: bytes) -> str:
    with abrir_pdf(contenido) as pdf:
        partes = []
        for page in pdf.pages[-PAGINAS_FINALES_RUP:]:
            partes.append(texto_pagina(page))
            page.flush_cache()
        return "\n".join(partes)


def evaluar_requisito10(pdfs: dict[str, bytes], fecha_cierre: date) -> ResultadoEvaluacionCamara:
    """Requisito 10: multas, sanciones y declaratorias de incumplimiento del RUP.

    No basta con que existan: se leen con detalle y se aplican las reglas del
    art. 58 de la Ley 2195 de 2022 (multas del último año) y del art. 90 de la
    Ley 1474 de 2011 (inhabilidad por incumplimiento reiterado). Ver
    motor/evaluacion/sanciones_rup.py. Se revisan todos los RUP encontrados
    (uno por integrante si el proponente es plural)."""
    encontrados = encontrar_documentos(pdfs, TITULO_RUP_RE, PISTAS_RUP)
    if not encontrados:
        return ResultadoEvaluacionCamara(
            cumple=False, motivo="No se encontró el RUP por título dentro de los documentos del proponente.", archivo=None
        )

    motivos = []
    informativos = []
    for nombre in encontrados:
        try:
            texto_norm = _norm(_texto_paginas_finales(pdfs[nombre]))
        except Exception:  # noqa: BLE001
            motivos.append(f"no se pudieron leer las últimas páginas de '{nombre}' — confirma manualmente")
            continue
        if not HAY_SANCIONES_RE.search(texto_norm):
            if len(texto_norm) < MINIMO_TEXTO_PAGINAS_FINALES:
                motivos.append(f"las últimas páginas de '{nombre}' no tienen texto legible — confirma manualmente")
            continue
        sanciones = extraer_sanciones(texto_norm)
        if not sanciones:
            motivos.append(f"'{nombre}' menciona multas o sanciones pero no se pudieron leer sus datos — revísalo manualmente")
            continue
        cumple, motivo = evaluar_sanciones(sanciones, fecha_cierre)
        if not cumple:
            motivos.append(f"'{nombre}': {motivo}")
        elif motivo:
            informativos.append(f"'{nombre}': {motivo}")

    if motivos:
        return ResultadoEvaluacionCamara(cumple=False, motivo="; ".join(motivos), archivo=encontrados[0])
    return ResultadoEvaluacionCamara(cumple=True, motivo="; ".join(informativos) or None, archivo=encontrados[0])


def _evaluar_proponente_camara(
    requisito: int, evaluador, proponente: Proponente, proceso: ProcesoDocumentoBase
) -> ResultadoRequisito:
    """Descarga+cachea el zip del proponente y delega en `evaluador`, que
    recibe (pdfs, tipo_proponente) y devuelve un ResultadoEvaluacionCamara.
    Función de módulo (no closure) para que sea picklable por
    ProcessPoolExecutor — el mismo bug que ya rompió los evaluadores de
    antecedentes con un closure similar."""
    base = {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
        "requisito": requisito,
    }

    try:
        metadata = get_file_metadata(proponente.drive_file_id)
    except Exception:  # noqa: BLE001
        metadata = None

    md5 = metadata.get("md5Checksum") if metadata else None
    clave_cache = _clave_cache(proponente, proceso, md5, requisito=requisito)
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

    tipo_proponente = obtener_tipo_proponente(pdfs)
    resultado = evaluador(pdfs, proceso, tipo_proponente)

    return finalizar(
        ResultadoRequisito(
            **base,
            cumple=resultado.cumple,
            motivo=resultado.motivo,
            archivo_evaluado=resultado.archivo,
            archivos_disponibles=sorted(pdfs.keys()) if resultado.archivo is None else [],
            tipo_proponente=tipo_proponente,
        ),
        cacheable=True,
    )


def evaluar_proponente_requisito6(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_camara(
        6, lambda pdfs, proceso, tipo: evaluar_requisito6(pdfs, proceso.fecha_cierre, tipo), proponente, proceso
    )


def evaluar_proponente_requisito7(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_camara(
        7, lambda pdfs, proceso, tipo: evaluar_requisito7(pdfs, proceso.objeto_general, tipo), proponente, proceso
    )


def evaluar_proponente_requisito8(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_camara(
        8, lambda pdfs, proceso, tipo: evaluar_requisito8(pdfs, tipo, _valor_de_referencia(proceso)), proponente, proceso
    )


def evaluar_proponente_requisito9(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_camara(
        9, lambda pdfs, proceso, tipo: evaluar_requisito9(pdfs, proceso.fecha_cierre), proponente, proceso
    )


def evaluar_proponente_requisito10(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_camara(
        10, lambda pdfs, proceso, tipo: evaluar_requisito10(pdfs, proceso.fecha_cierre), proponente, proceso
    )


# "ORGANIZACION JURIDICA: SOCIEDAD POR ACCIONES SIMPLIFICADA CATEGORIA :
# PERSONA JURIDICA PRINCIPAL NIT :..." — confirmado con un Certificado de
# Existencia real (EMPRESA DOS SAS). "SOCIEDAD ANONIMA" y "SOCIEDAD POR ACCIONES
# SIMPLIFICADA" (S.A.S.) son frases completamente distintas en español, así
# que basta buscar la primera literalmente sin riesgo de confundirla con
# S.A.S. No se encontró en los documentos reales revisados un proponente
# que sea efectivamente una S.A. (todos eran S.A.S.), así que esta parte no
# se pudo validar contra un caso real — queda como limitación conocida.
SOCIEDAD_ANONIMA_RE = re.compile(r"SOCIEDAD ANONIMA(?!\s*SIMPLIFICADA)")
SOCIEDAD_ABIERTA_RE = re.compile(r"\bABIERTA\b")
SOCIEDAD_CERRADA_RE = re.compile(r"\bCERRADA\b")


def evaluar_requisito18(pdfs: dict[str, bytes], tipo_proponente: str | None) -> ResultadoEvaluacionCamara:
    """Requisito 18: Certificado de Revisor Fiscal indicando si la sociedad
    es abierta o cerrada. N.A. si el proponente no es una Sociedad Anónima
    (S.A.) — incluye personas naturales y cualquier otro tipo societario
    (S.A.S., Ltda., etc.), que no están obligados a este certificado. No
    validado contra un proponente S.A. real (limitación conocida, ver
    comentario en SOCIEDAD_ANONIMA_RE)."""
    if tipo_proponente == "persona_natural":
        return ResultadoEvaluacionCamara(cumple=True, motivo="N.A. — persona natural", archivo=None)

    encontrados = encontrar_documentos(pdfs, TITULO_EXISTENCIA_RE, PISTAS_EXISTENCIA)
    if not encontrados:
        return ResultadoEvaluacionCamara(
            cumple=False,
            motivo="No se encontró el Certificado de Existencia y Representación Legal por título dentro de los documentos del proponente.",
            archivo=None,
        )

    es_sociedad_anonima = False
    for nombre in encontrados:
        texto_norm = _norm(_texto_completo(pdfs, nombre))
        if SOCIEDAD_ANONIMA_RE.search(texto_norm):
            es_sociedad_anonima = True
            if SOCIEDAD_ABIERTA_RE.search(texto_norm) or SOCIEDAD_CERRADA_RE.search(texto_norm):
                return ResultadoEvaluacionCamara(cumple=True, motivo=None, archivo=nombre)

    if not es_sociedad_anonima:
        return ResultadoEvaluacionCamara(
            cumple=True, motivo="N.A. — el proponente no es una Sociedad Anónima (S.A.)", archivo=None
        )

    return ResultadoEvaluacionCamara(
        cumple=False,
        # Criterio del abogado: sin la certificación que diga si la S.A. es
        # abierta o cerrada, el requisito no se aprueba.
        motivo=(
            "El proponente es una Sociedad Anónima (S.A.) y no se encontró la certificación que indique si es abierta "
            "o cerrada: sin ella el requisito no se aprueba. Si el proponente la aportó en otro documento, verifícala."
        ),
        archivo=encontrados[0],
    )


def evaluar_proponente_requisito18(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_camara(18, lambda pdfs, proceso, tipo: evaluar_requisito18(pdfs, tipo), proponente, proceso)
