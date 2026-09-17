from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from dateutil.relativedelta import relativedelta

from motor.procesamiento.memoria_proponente import memo_por_pdfs
from motor.evaluacion.formato1 import (
    _clave_cache,
    _extraer_nombre_apertura,
    _extraer_representante_legal,
    _guardar_cache,
    _leer_cache,
    _nombres_coinciden,
    _norm,
    es_titulo_formato1,
    encontrar_formato1,
)
from motor.integrations.drive import download_file_bytes, get_file_metadata
from motor.esquemas.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from motor.procesamiento.pdf_utils import abrir_pdf, texto_pagina, extraer_texto
from motor.procesamiento.zip_utils import extraer_pdfs

# El certificado COPNIA (Consejo Profesional Nacional de Ingeniería) siempre
# trae este título, sin importar el nombre del archivo.
# Se exige el encabezado del CERTIFICADO ("CERTIFICADO DE VIGENCIA Y
# ANTECEDENTES DISCIPLINARIOS ... EL DIRECTOR GENERAL CERTIFICA"), no la
# sola mención del Consejo: la tarjeta profesional escaneada y el texto del
# aval dentro de la carta también la nombran, y tomarlos como certificado
# impedía encontrar el certificado real (confirmado en proponentes reales).
TITULO_COPNIA_RE = re.compile(
    r"VIGENCIA Y ANTECEDENTES DISCIPLINARIOS"
    r"|CONSEJO PROFESIONAL NACIONAL DE INGENIER[IÍ]A.{0,60}?CERTIFICA\b",
    re.DOTALL,
)

PISTAS_NOMBRE_COPNIA = ("copnia",)

# Cuántas páginas de cada PDF candidato se revisan: los proponentes suelen
# fusionar cédula + tarjeta profesional + COPNIA + REDAM en un solo archivo,
# así que el certificado puede no estar en la primera página.
PAGINAS_A_REVISAR = 6
# Hay proponentes que anexan el COPNIA de quien avala la oferta al final del
# mismo PDF de la carta de presentación (se confirmó uno real en la página 8,
# tras las 4 de la carta y 3 escaneadas): en ese archivo se revisa más.
PAGINAS_A_REVISAR_EN_CARTA = 20

NOMBRE_PROFESIONAL_RE = re.compile(r"QUE\s+([A-ZÑÁÉÍÓÚ][A-ZÑÁÉÍÓÚ\s.]+?),\s*IDENTIFICAD[OA]")
PROFESION_RE = re.compile(r"EN LA PROFESI[OÓ]N DE\s+([A-ZÑÁÉÍÓÚ][A-ZÑÁÉÍÓÚ\s]+?)\s+CON MATRICULA")
MATRICULA_RE = re.compile(r"MATRICULA PROFESIONAL\s+([\d\-]+)")
VIGENTE_RE = re.compile(r"MATRICULA PROFESIONAL SE ENCUENTRA VIGENTE")
SIN_ANTECEDENTES_RE = re.compile(r"NO TIENE ANTECEDENTES DISCIPLINARIOS")

MESES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}

# "...A LOS VEINTITRES (23) DIAS DEL MES DE JULIO DEL ANO DOS MIL VEINTISEIS (2026)."
FECHA_EXPEDICION_RE = re.compile(
    r"A LOS\s+\S+\s*\((\d{1,2})\)\s*D[IÍ]AS DEL MES DE\s+([A-ZÑ]+)\s+DEL A[NÑ]O\s+.*?\((\d{4})\)"
)


def _orden_busqueda_copnia(nombres: list[str]) -> list[str]:
    def pista(nombre: str) -> int:
        base = _norm(nombre.rsplit("/", 1)[-1])
        return 0 if any(p.upper() in base for p in PISTAS_NOMBRE_COPNIA) else 1

    return sorted(nombres, key=pista)


@memo_por_pdfs
def encontrar_copnias(pdfs: dict[str, bytes]) -> list[tuple[str, str]]:
    """Devuelve TODOS los certificados COPNIA del proponente, buscándolos por
    su título interno (sin importar el nombre del archivo ni si vienen
    fusionados con otros documentos: cédula, tarjeta profesional, REDAM...).

    Se devuelven todos, no solo el primero, porque hay proponentes que
    aportan el COPNIA de varios profesionales (se vio un caso real con dos:
    uno del representante legal y otro de un tercero). Quedarse con el
    primero que aparezca haría que el veredicto dependa del orden de los
    archivos dentro del zip, que es arbitrario."""
    encontrados: list[tuple[str, str]] = []
    for nombre in _orden_busqueda_copnia(list(pdfs.keys())):
        contenido = pdfs[nombre]
        try:
            with abrir_pdf(contenido) as pdf:
                limite = PAGINAS_A_REVISAR
                for indice, page in enumerate(pdf.pages[:PAGINAS_A_REVISAR_EN_CARTA]):
                    if indice >= limite:
                        break
                    texto = texto_pagina(page)
                    page.flush_cache()
                    texto_norm = _norm(texto)
                    if indice == 0 and es_titulo_formato1(texto_norm):
                        limite = PAGINAS_A_REVISAR_EN_CARTA
                    if TITULO_COPNIA_RE.search(texto_norm):
                        encontrados.append((nombre, texto))
                        break
        except Exception:  # noqa: BLE001
            continue
    return encontrados


def _elegir_copnia_del_profesional(
    pdfs: dict[str, bytes], personas: list[str]
) -> tuple[str, str] | None:
    """Entre todos los COPNIA aportados, elige el del profesional que avala
    o suscribe la propuesta (en ese orden de preferencia). Si ninguno
    coincide, devuelve el primero para poder reportar con precisión a
    nombre de quién está el que sí aportaron."""
    encontrados = encontrar_copnias(pdfs)
    if not encontrados:
        return None
    for persona in personas:
        for nombre_archivo, texto in encontrados:
            datos = extraer_datos_copnia(texto)
            if datos.nombre and _nombres_coinciden(datos.nombre, persona):
                return nombre_archivo, texto
    return encontrados[0]


# Aval del ingeniero dentro del Formato 1 (el Documento Base dice que "hace
# parte integral" de la carta): "...DEBIDO A QUE EL SUSCRIPTOR DE LA
# PRESENTE PROPUESTA NO ES INGENIERO MATRICULADO, YO CARLOS ANDRES LOPEZ RIOS,
# INGENIERO CON MATRICULA PROFESIONAL NO. ... AVALO LA PRESENTE PROPUESTA".
# Confirmado con cartas reales de varios proponentes; algunos además lo
# aportan como documento aparte ("Aval de la oferta - <nombre>.pdf").
AVAL_RE = re.compile(
    r"\bYO,?\s+([A-ZÑ][A-ZÑ .]{4,80}?),?\s+INGENIER[OA]\b.{0,250}?AVALO LA PRESENTE (?:PROPUESTA|OFERTA)",
    re.DOTALL,
)


@memo_por_pdfs
def obtener_avalista(pdfs: dict[str, bytes]) -> str | None:
    """Nombre del ingeniero que avala la oferta, si la carta (o un documento
    de aval aparte) lo trae; None si no hay aval (ej. el representante legal
    es ingeniero y firma él mismo)."""
    candidatos = []
    encontrado = encontrar_formato1(pdfs)
    if encontrado is not None:
        candidatos.append(encontrado[1])
    candidatos.extend(contenido for nombre, contenido in pdfs.items() if "AVAL" in _norm(nombre.rsplit("/", 1)[-1]))
    for contenido in candidatos:
        try:
            texto_norm = _norm(extraer_texto(contenido))
        except Exception:  # noqa: BLE001
            continue
        match = AVAL_RE.search(texto_norm)
        if match:
            nombre = re.sub(r"\s+", " ", match.group(1)).strip(" .,")
            if len(nombre.split()) >= 2:
                return nombre
    return None


def _parsear_fecha_copnia(texto_norm: str) -> date | None:
    match = FECHA_EXPEDICION_RE.search(texto_norm)
    if not match:
        return None
    dia, mes_texto, anio = match.groups()
    mes = MESES.get(mes_texto)
    if mes is None:
        return None
    try:
        return date(int(anio), mes, int(dia))
    except ValueError:
        return None


@dataclass
class DatosCopnia:
    nombre: str | None
    profesion: str | None
    matricula: str | None
    vigente: bool
    sin_antecedentes: bool
    fecha_expedicion: date | None


def extraer_datos_copnia(texto: str) -> DatosCopnia:
    texto_norm = _norm(texto)

    nombre_match = NOMBRE_PROFESIONAL_RE.search(texto_norm)
    nombre = re.sub(r"\s+", " ", nombre_match.group(1)).strip(" .") if nombre_match else None

    profesion_match = PROFESION_RE.search(texto_norm)
    profesion = re.sub(r"\s+", " ", profesion_match.group(1)).strip() if profesion_match else None

    matricula_match = MATRICULA_RE.search(texto_norm)
    matricula = matricula_match.group(1) if matricula_match else None

    return DatosCopnia(
        nombre=nombre,
        profesion=profesion,
        matricula=matricula,
        vigente=bool(VIGENTE_RE.search(texto_norm)),
        sin_antecedentes=bool(SIN_ANTECEDENTES_RE.search(texto_norm)),
        fecha_expedicion=_parsear_fecha_copnia(texto_norm),
    )


class ResultadoEvaluacionCopnia:
    def __init__(
        self,
        cumple: bool,
        motivo: str | None,
        datos: DatosCopnia | None,
        archivo_copnia: str | None,
        representante_legal: str | None,
    ) -> None:
        self.cumple = cumple
        self.motivo = motivo
        self.datos = datos
        self.archivo_copnia = archivo_copnia
        self.representante_legal = representante_legal


ANTIGUEDAD_MAXIMA_MESES = 3


def evaluar_requisito2(
    pdfs: dict[str, bytes], fecha_cierre: date, representante_legal: str | None, avalista: str | None = None
) -> ResultadoEvaluacionCopnia:
    """Requisito 2: la propuesta debe estar suscrita por un ingeniero o, si
    quien la suscribe no lo es, avalada por uno (Documento Base, Ley 842 de
    2003 art. 20). El COPNIA debe ser del que avala o del que suscribe."""
    personas = [p for p in (avalista, representante_legal) if p]
    encontrado = _elegir_copnia_del_profesional(pdfs, personas)
    if encontrado is None:
        return ResultadoEvaluacionCopnia(
            cumple=False,
            motivo=(
                "No se encontró un certificado COPNIA (Consejo Profesional Nacional de Ingeniería) por título "
                "dentro de los documentos del proponente. Revisa manualmente."
            ),
            datos=None,
            archivo_copnia=None,
            representante_legal=representante_legal,
        )

    archivo_copnia, texto = encontrado
    datos = extraer_datos_copnia(texto)

    motivos = []
    if not datos.profesion:
        motivos.append("no se pudo leer la profesión certificada en el COPNIA")
    if not datos.matricula:
        motivos.append("no se pudo leer el número de matrícula profesional en el COPNIA")
    if not datos.vigente:
        motivos.append("el COPNIA no indica que la matrícula profesional se encuentre vigente")

    if datos.fecha_expedicion is None:
        motivos.append("no se pudo leer la fecha de expedición del COPNIA — confirma manualmente que no supere los 3 meses")
    elif datos.fecha_expedicion < fecha_cierre - relativedelta(months=ANTIGUEDAD_MAXIMA_MESES):
        motivos.append(
            f"el COPNIA fue expedido el {datos.fecha_expedicion.strftime('%d/%m/%Y')}, hace más de "
            f"{ANTIGUEDAD_MAXIMA_MESES} meses contados desde la fecha de cierre "
            f"({fecha_cierre.strftime('%d/%m/%Y')})"
        )

    if not datos.nombre or not personas:
        motivos.append(
            "no se pudo confirmar que el nombre del COPNIA coincida con quien firma o avala la propuesta — revisa manualmente"
        )
    elif not any(_nombres_coinciden(datos.nombre, persona) for persona in personas):
        quienes = f"quien firma ('{representante_legal}')" if representante_legal else ""
        if avalista:
            quienes = f"{quienes} ni con quien avala ('{avalista}')" if quienes else f"quien avala ('{avalista}')"
        motivos.append(f"el nombre en el COPNIA ('{datos.nombre}') no coincide con {quienes}")

    cumple = not motivos
    motivo = "; ".join(motivos) if motivos else None

    return ResultadoEvaluacionCopnia(
        cumple=cumple,
        motivo=motivo,
        datos=datos,
        archivo_copnia=archivo_copnia,
        representante_legal=representante_legal,
    )


def evaluar_requisito3(
    pdfs: dict[str, bytes], fecha_cierre: date, personas: list[str] | None = None
) -> ResultadoEvaluacionCopnia:
    """Requisito 3: antecedentes disciplinarios del mismo ingeniero/arquitecto
    del Requisito 2. Usa el mismo COPNIA (el abogado confirmó que es el mismo
    documento), solo cambia el criterio: aquí importa que no tenga
    antecedentes y que esté vigente, no a nombre de quién está."""
    encontrado = _elegir_copnia_del_profesional(pdfs, personas or [])
    if encontrado is None:
        return ResultadoEvaluacionCopnia(
            cumple=False,
            motivo=(
                "No se encontró un certificado COPNIA (Consejo Profesional Nacional de Ingeniería) por título "
                "dentro de los documentos del proponente. Revisa manualmente."
            ),
            datos=None,
            archivo_copnia=None,
            representante_legal=None,
        )

    archivo_copnia, texto = encontrado
    datos = extraer_datos_copnia(texto)

    motivos = []
    if not datos.sin_antecedentes:
        motivos.append("el COPNIA no certifica que el profesional esté libre de antecedentes disciplinarios")

    if datos.fecha_expedicion is None:
        motivos.append("no se pudo leer la fecha de expedición del COPNIA — confirma manualmente que no supere los 3 meses")
    elif datos.fecha_expedicion < fecha_cierre - relativedelta(months=ANTIGUEDAD_MAXIMA_MESES):
        motivos.append(
            f"el COPNIA aportado no está en vigencia (expedido el {datos.fecha_expedicion.strftime('%d/%m/%Y')}, "
            f"hace más de {ANTIGUEDAD_MAXIMA_MESES} meses contados desde la fecha de cierre "
            f"{fecha_cierre.strftime('%d/%m/%Y')})"
        )

    cumple = not motivos
    motivo = "; ".join(motivos) if motivos else None

    return ResultadoEvaluacionCopnia(
        cumple=cumple, motivo=motivo, datos=datos, archivo_copnia=archivo_copnia, representante_legal=None
    )


def evaluar_proponente_requisito3(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    base = {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
        "requisito": 3,
    }

    try:
        metadata = get_file_metadata(proponente.drive_file_id)
    except Exception:  # noqa: BLE001
        metadata = None

    md5 = metadata.get("md5Checksum") if metadata else None
    clave_cache = _clave_cache(proponente, proceso, md5, requisito=3)
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

    personas = [p for p in (obtener_avalista(pdfs), _obtener_representante_legal(pdfs)) if p]
    resultado = evaluar_requisito3(pdfs, proceso.fecha_cierre, personas)
    datos = resultado.datos
    return finalizar(
        ResultadoRequisito(
            **base,
            cumple=resultado.cumple,
            motivo=resultado.motivo,
            archivo_evaluado=resultado.archivo_copnia,
            archivos_disponibles=sorted(pdfs.keys()) if resultado.archivo_copnia is None else [],
            matricula_profesional=datos.matricula if datos else None,
            profesion_certificada=datos.profesion if datos else None,
            copnia_vigente=datos.vigente if datos else None,
            copnia_sin_antecedentes=datos.sin_antecedentes if datos else None,
            copnia_fecha_expedicion=datos.fecha_expedicion if datos else None,
        ),
        cacheable=True,
    )


def _obtener_representante_legal(pdfs: dict[str, bytes]) -> str | None:
    """Repite el mismo análisis del Formato 1 (Requisito 1) para saber quién
    firma la propuesta. No vuelve a descargar nada: reutiliza los PDF ya
    extraídos del zip del proponente."""
    encontrado = encontrar_formato1(pdfs)
    if encontrado is None:
        return None
    _, contenido = encontrado
    texto_norm = _norm(extraer_texto(contenido))
    return _extraer_nombre_apertura(texto_norm) or _extraer_representante_legal(texto_norm)


def evaluar_proponente_requisito2(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    base = {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
        "requisito": 2,
    }

    try:
        metadata = get_file_metadata(proponente.drive_file_id)
    except Exception:  # noqa: BLE001
        metadata = None

    md5 = metadata.get("md5Checksum") if metadata else None
    clave_cache = _clave_cache(proponente, proceso, md5, requisito=2)
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

    representante_legal = _obtener_representante_legal(pdfs)
    resultado = evaluar_requisito2(pdfs, proceso.fecha_cierre, representante_legal, obtener_avalista(pdfs))

    datos = resultado.datos
    return finalizar(
        ResultadoRequisito(
            **base,
            cumple=resultado.cumple,
            motivo=resultado.motivo,
            archivo_evaluado=resultado.archivo_copnia,
            representante_legal=representante_legal,
            archivos_disponibles=sorted(pdfs.keys()) if resultado.archivo_copnia is None else [],
            matricula_profesional=datos.matricula if datos else None,
            profesion_certificada=datos.profesion if datos else None,
            copnia_vigente=datos.vigente if datos else None,
            copnia_sin_antecedentes=datos.sin_antecedentes if datos else None,
            copnia_fecha_expedicion=datos.fecha_expedicion if datos else None,
        ),
        cacheable=True,
    )
