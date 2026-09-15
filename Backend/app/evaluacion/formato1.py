from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pdfplumber

from app.integrations.drive import download_file_bytes, get_file_metadata
from app.models.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from app.procesamiento.zip_utils import extraer_pdfs

# El título interno del documento es siempre el mismo, sin importar cómo se
# llame el archivo dentro del zip del proponente.
TITULO_RE = re.compile(r"FORMATO\s*1\b.{0,15}CARTA\s+DE\s+PRESENTAC")

# Palabras que sugieren que un PDF podría ser el Formato 1; se revisan primero
# para no tener que abrir decenas de PDF no relacionados en cada proponente.
PISTAS_NOMBRE = ("formato 1", "formato1", "carta de presentac", "carta presentac", "presentacion de la oferta")

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "evaluaciones"

# Se incluye en la clave de caché: si se corrige la lógica de evaluación
# (ej. soporte para .rar, un regex), hay que subir este número para que los
# resultados viejos (evaluados con la lógica anterior) no se sigan sirviendo
# desde el caché como si fueran válidos.
VERSION_LOGICA = 14


def _clave_cache(proponente: Proponente, proceso: ProcesoDocumentoBase, md5: str | None, requisito: int = 1) -> str:
    payload = {
        "requisito": requisito,
        "version_logica": VERSION_LOGICA,
        "file_id": proponente.drive_file_id,
        "md5": md5,
        "codigo_proceso": proceso.codigo_proceso,
        "lotes": sorted(lote.numero for lote in proceso.lotes),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _leer_cache(clave: str) -> ResultadoRequisito | None:
    path = CACHE_DIR / f"{clave}.json"
    if not path.exists():
        return None
    try:
        return ResultadoRequisito.model_validate_json(path.read_text())
    except (ValueError, OSError):
        return None


def _guardar_cache(clave: str, resultado: ResultadoRequisito) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{clave}.json").write_text(resultado.model_dump_json())
    except OSError:
        pass


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", _strip_accents(text).upper()).strip()


def _orden_busqueda(nombres: list[str]) -> list[str]:
    """Prueba primero los archivos cuyo nombre ya sugiere que son el Formato 1,
    para no tener que abrir decenas de PDF sin relación en cada proponente."""

    def pista(nombre: str) -> int:
        base = _norm(nombre.rsplit("/", 1)[-1])
        return 0 if any(p.upper() in base for p in PISTAS_NOMBRE) else 1

    return sorted(nombres, key=pista)


def encontrar_formato1(pdfs: dict[str, bytes]) -> tuple[str, bytes] | None:
    """Busca, entre los PDF de un proponente, el que trae el título
    'Formato 1 - Carta de presentación de la oferta' en sus primeras páginas."""
    for nombre in _orden_busqueda(list(pdfs.keys())):
        contenido = pdfs[nombre]
        try:
            with pdfplumber.open(io.BytesIO(contenido)) as pdf:
                texto = ""
                for page in pdf.pages[:2]:
                    texto += (page.extract_text() or "") + "\n"
        except Exception:  # noqa: BLE001
            continue
        if TITULO_RE.search(_norm(texto)):
            return nombre, contenido
    return None


def _lote_mencionado(texto_norm: str, numero_lote: str) -> bool:
    """Busca el lote en el texto tolerando variaciones como 'LOTE 1', 'LOTES 1 Y 2'
    o 'LOTE No. 1', en vez de exigir el texto exacto 'LOTE 1'."""
    match_num = re.search(r"\d+", numero_lote)
    if not match_num:
        return _norm(numero_lote) in texto_norm
    num = match_num.group(0)
    patron = rf"(?:LOTES?|SEGMENTOS?)\b.{{0,25}}?\b{num}\b"
    return re.search(patron, texto_norm) is not None


SEPARADORES_RE = r"[\s\-‐-―]*"


def _codigo_regex(codigo: str) -> re.Pattern[str]:
    """Construye un patrón tolerante a espacios y distintos tipos de guion
    (ej. 'ICCU-CM-037-2026' también encuentra 'ICCU-CM-037 – 2026')."""
    partes = [p for p in re.split(r"[\s\-]+", codigo.strip()) if p]
    partes_escapadas = [re.escape(_norm(p)) for p in partes]
    return re.compile(SEPARADORES_RE.join(partes_escapadas))


def _codigo_variantes(codigo_proceso: str) -> list[re.Pattern[str]]:
    core = re.sub(r"^ICCU-", "", codigo_proceso.strip(), flags=re.IGNORECASE)
    variantes = {codigo_proceso.strip(), core, f"ICCU-{core}"}
    return [_codigo_regex(v) for v in variantes if v]


# "Nombre del representante legal JUAN JOSE ARAQUE BLANCO   C. C. No. ..."
# Algunos formatos meten un ":" o "_" (raya para llenar a mano) entre
# "LEGAL" y el nombre, ej. "LEGAL: LAYTON..." o "LEGAL _ DANIELA...". Otros
# omiten "LEGAL" y ponen en cambio la entidad, ej. "REPRESENTANTE DEL
# CONSORCIO: JUAN...". Y el corte antes de "C.C." tolera tanto espacio como
# dos puntos después ("C. C. No." o "C. C.:"). Esto suele aparecer cerca del
# cierre/firma de la carta.
NOMBRE_REPRESENTANTE_RE = re.compile(
    r"NOMBRE DEL REPRESENTANTE(?:\s+LEGAL|\s+DEL?\s+\w+)?\s*[\s:_]*([A-ZÑÁÉÍÓÚ][A-ZÑÁÉÍÓÚ.\s]*?)\s+C\.?\s?C\.?[\s:]"
)

# "Estimados señores: JUAN AMADO LIZARAZO, en mi calidad de representante
# legal de CONSORCIO..." — la declaración de quién firma, al inicio de la
# carta. Se ancla hacia adelante desde "Estimados señores" (no hacia atrás
# desde "en mi calidad de...") porque algunos proponentes meten una cláusula
# de identificación entre el nombre y esa frase, ej. "YO, NAIRA DEL CARMEN
# HERNANDEZ LUGO IDENTIFICADA CON CEDULA... DE LORICA, EN MI CALIDAD DE...":
# capturando hacia atrás desde "en mi calidad de" ahí se agarraría solo "DE
# LORICA" en vez del nombre real.
#
# Variantes reales encontradas: nombre entre corchetes de plantilla sin
# limpiar ("[NIDIA ESPERANZA ROJAS OBANDO]"), "REPRESENTANTE DEL..." sin la
# palabra "LEGAL", y personas naturales que dicen "EN MI CALIDAD DE
# PROPONENTE" en vez de tener un representante legal.
NOMBRE_APERTURA_RE = re.compile(
    r"ESTIMADOS SE[ÑN]ORES[:,]?\s*(?:YO,?\s+)?\[?\s*([A-ZÑÁÉÍÓÚ][A-ZÑÁÉÍÓÚ\s.]+?)\s*\]?\s*"
    r"(?:,|IDENTIFICAD[OA]|EN MI CALIDAD DE (?:REPRESENTANTE(?:\s+LEGAL)?(?:\s+DEL?)?|PROPONENTE))"
)

# Muchas plataformas de firma digital usan un ID genérico como nombre del
# certificado en vez del nombre real de la persona (ej. INT TERRA firmó con
# Adobe Sign / un certificado autofirmado con este patrón como CN).
_ID_GENERICO_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _extraer_representante_legal(texto_norm: str) -> str | None:
    match = NOMBRE_REPRESENTANTE_RE.search(texto_norm)
    if not match:
        return None
    nombre = re.sub(r"\s+", " ", match.group(1)).strip(" .")
    return nombre or None


def _extraer_nombre_apertura(texto_norm: str) -> str | None:
    match = NOMBRE_APERTURA_RE.search(texto_norm)
    if not match:
        return None
    nombre = re.sub(r"\s+", " ", match.group(1)).strip(" .,")
    return nombre or None


def _contenidos_firma_digital(pdf_bytes: bytes) -> list[bytes]:
    """Devuelve los blobs PKCS7 (/Contents) de cada campo de firma digital
    del PDF. Todo el acceso a los objetos de pikepdf ocurre aquí, dentro del
    'with', porque son proxies inválidos una vez se cierra el archivo."""
    try:
        import pikepdf
    except ImportError:
        return []
    try:
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            acroform = pdf.Root.get("/AcroForm")
            if not acroform or "/Fields" not in acroform:
                return []
            resultado = []
            for campo in acroform.Fields:
                if campo.get("/FT") != "/Sig" or "/V" not in campo:
                    continue
                contents = campo.V.get("/Contents")
                if contents:
                    resultado.append(bytes(contents))
            return resultado
    except Exception:  # noqa: BLE001
        return []


def _nombre_certificado(contents: bytes) -> str | None:
    """Si el blob PKCS7 trae un certificado con el nombre real de la
    persona (no un ID genérico de la plataforma de firma), lo devuelve."""
    try:
        from cryptography.hazmat.primitives.serialization import pkcs7
        from cryptography.x509.oid import NameOID
    except ImportError:
        return None

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            certs = pkcs7.load_der_pkcs7_certificates(contents)
    except ValueError:
        return None

    for cert in certs:
        for atributo in cert.subject:
            if atributo.oid == NameOID.COMMON_NAME:
                cn = str(atributo.value).strip()
                if cn and not _ID_GENERICO_RE.match(cn):
                    return cn
    return None


# "El Proponente es: Persona natural__ Persona jurídica nacional __X_ ...
# Unión Temporal ___ Consorcio __ Otro__" — una casilla marcada con X pegada
# a un guion bajo (ej. "__X_"), confirmado con documentos reales (persona
# jurídica y consorcio). Se busca por tabla, no por texto plano, porque el
# texto plano intercala las columnas de esta sección.
TIPO_PROPONENTE_PATRONES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"PERSONA NATURAL"), "persona_natural"),
    (re.compile(r"PERSONA JUR[IÍ]DICA NACIONAL"), "persona_juridica"),
    (re.compile(r"PERSONA JUR[IÍ]DICA EXTRANJERA"), "persona_juridica"),
    (re.compile(r"SUCURSAL DE SOCIEDAD EXTRANJERA"), "persona_juridica"),
    (re.compile(r"UNI[OÓ]N TEMPORAL"), "union_temporal"),
    (re.compile(r"CONSORCIO"), "consorcio"),
    (re.compile(r"OTRO"), "otro"),
]
# La "X" que marca la casilla no siempre está pegada a un guion bajo
# ("__X_"): se vieron documentos reales donde va suelta con solo un espacio
# ("Consorcio X"). Se exige que no haya letras pegadas a los lados (con
# guiones bajos o espacios sí) para no confundirla con la "x" que aparece
# dentro de palabras como "extranjera".
_MARCA_X_RE = re.compile(r"(?<![A-Za-zÑÁÉÍÓÚñáéíóú])[Xx](?![A-Za-zÑÁÉÍÓÚñáéíóú])")

# La celda con el checklist de tipo de proponente trae las opciones juntas
# ("Persona natural__ Persona jurídica... Unión temporal___ Consorcio _X__
# Otro__"), pero su posición en la tabla varía entre versiones de la
# plantilla (a veces la etiqueta "El proponente es:" va en la misma fila,
# a veces en filas separadas con columnas distintas) — por eso no se busca
# por posición fija, sino por el contenido: una celda que mencione al menos
# 3 de los tipos posibles es, casi con certeza, este checklist y no otra
# cosa del formulario.
UMBRAL_TIPOS_EN_BLOQUE = 3


def _es_bloque_tipo_proponente(texto_norm: str) -> bool:
    return sum(1 for patron, _ in TIPO_PROPONENTE_PATRONES if patron.search(texto_norm)) >= UMBRAL_TIPOS_EN_BLOQUE


def _extraer_tipo_proponente(pdf: pdfplumber.PDF) -> str | None:
    for page in pdf.pages:
        try:
            tablas = page.extract_tables()
        except Exception:  # noqa: BLE001
            continue
        for tabla in tablas:
            for row in tabla:
                for celda in row or []:
                    if not celda or not _es_bloque_tipo_proponente(_norm(str(celda))):
                        continue
                    for linea in str(celda).split("\n"):
                        if not _MARCA_X_RE.search(linea):
                            continue
                        linea_norm = _norm(linea)
                        for patron, tipo in TIPO_PROPONENTE_PATRONES:
                            if patron.search(linea_norm):
                                return tipo
    return None


# La declaración de apertura de la carta ya dice explícitamente "en mi
# calidad de representante legal DEL CONSORCIO ..." o "DE LA UNIÓN TEMPORAL
# ...", y se usa como señal PRIORITARIA sobre la casilla "El Proponente es:"
# para detectar proponente plural: se encontró un caso real (Consorcio AJ
# 037) donde el proponente dejó marcada por error "Persona jurídica
# nacional" en la casilla, siendo evidentemente un Consorcio según su propia
# carta y su Formato 2 de conformación. Confiar en una casilla mal
# diligenciada y omitir por eso el Requisito 4 (Conformación de Proponente
# Plural) es un error más grave que evaluarlo de más, así que la
# declaración firmada gana cuando hay conflicto. No se usa para distinguir
# persona natural de jurídica porque ahí no hay ese mismo riesgo.
TIPO_PROPONENTE_FALLBACK_RE = re.compile(r"REPRESENTANTE LEGAL DEL?(?:\s+LA)?\s+(UNION TEMPORAL|CONSORCIO)\b")

_TIPO_PROPONENTE_FALLBACK_MAP = {"CONSORCIO": "consorcio", "UNION TEMPORAL": "union_temporal"}


def obtener_tipo_proponente(pdfs: dict[str, bytes]) -> str | None:
    """Encuentra el Formato 1 dentro de los PDF del proponente y determina si
    es persona natural, jurídica, consorcio o unión temporal. Lo usan otros
    requisitos (4, 5, 6, 12, 14-17) que necesitan saber si el proponente es
    individual o plural, sin tener que repetir la búsqueda del Formato 1 en
    cada uno."""
    encontrado = encontrar_formato1(pdfs)
    if encontrado is None:
        return None
    _, contenido = encontrado
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        tipo_casilla = _extraer_tipo_proponente(pdf)
        texto = "\n".join((page.extract_text() or "") for page in pdf.pages[:2])
    match = TIPO_PROPONENTE_FALLBACK_RE.search(_norm(texto))
    tipo_declaracion = _TIPO_PROPONENTE_FALLBACK_MAP[match.group(1)] if match else None
    return tipo_declaracion or tipo_casilla


def _tokens_nombre(nombre: str) -> set[str]:
    return {t for t in _norm(nombre).split() if len(t) > 1}


def _nombres_coinciden(nombre_certificado: str, nombre_declarado: str) -> bool:
    tokens_cert = _tokens_nombre(nombre_certificado)
    tokens_decl = _tokens_nombre(nombre_declarado)
    if not tokens_cert or not tokens_decl:
        return False
    comunes = tokens_cert & tokens_decl
    # Al menos dos palabras en común (ej. nombre + apellido) para evitar
    # falsos positivos por una coincidencia casual de una sola palabra.
    return len(comunes) >= min(2, len(tokens_decl))


STOPWORDS_OBJETO = {
    "DE", "LA", "EL", "LOS", "LAS", "Y", "EN", "PARA", "DEL", "AL", "A", "QUE", "CON", "SU", "SUS",
    "UN", "UNA", "SE", "ES", "POR", "LO", "O", "E",
}


def _extraer_objeto_carta(texto_norm: str) -> str | None:
    idx = texto_norm.find("OBJETO:")
    if idx == -1:
        return None
    inicio = idx + len("OBJETO:")
    return texto_norm[inicio : inicio + 700].strip()


def _tokens_significativos(texto: str) -> set[str]:
    return {t for t in re.findall(r"[A-ZÑÁÉÍÓÚ]+", texto) if len(t) > 2 and t not in STOPWORDS_OBJETO}


def _proporcion_objeto_relacionado(objeto_carta: str, objeto_base: str) -> float:
    """Qué fracción de las palabras clave del objeto del Documento Base
    también aparece en el objeto declarado en la carta del proponente."""
    tokens_base = _tokens_significativos(objeto_base)
    if not tokens_base:
        return 1.0
    tokens_carta = _tokens_significativos(objeto_carta)
    comunes = tokens_carta & tokens_base
    return len(comunes) / len(tokens_base)


class ResultadoEvaluacionFormato1:
    def __init__(
        self,
        cumple: bool,
        motivo: str | None,
        lotes_encontrados: list[str],
        numero_proceso_encontrado: bool,
        firma_detectada: bool,
        representante_legal: str | None = None,
        firma_nombre_certificado: str | None = None,
        firma_confirmada: bool | None = None,
        objeto_relacionado: bool | None = None,
        tipo_proponente: str | None = None,
    ) -> None:
        self.cumple = cumple
        self.motivo = motivo
        self.lotes_encontrados = lotes_encontrados
        self.numero_proceso_encontrado = numero_proceso_encontrado
        self.firma_detectada = firma_detectada
        self.representante_legal = representante_legal
        self.firma_nombre_certificado = firma_nombre_certificado
        self.firma_confirmada = firma_confirmada
        self.tipo_proponente = tipo_proponente
        self.objeto_relacionado = objeto_relacionado


def evaluar_formato1(pdf_bytes: bytes, proceso: ProcesoDocumentoBase) -> ResultadoEvaluacionFormato1:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        texto_completo = ""
        tiene_imagen = False
        for page in pdf.pages:
            texto_completo += (page.extract_text() or "") + "\n"
            if page.images:
                tiene_imagen = True
        tipo_proponente = _extraer_tipo_proponente(pdf)

    texto_norm = _norm(texto_completo)

    lotes_encontrados = [lote.numero for lote in proceso.lotes if _lote_mencionado(texto_norm, lote.numero)]

    variantes = _codigo_variantes(proceso.codigo_proceso)
    numero_proceso_ok = any(patron.search(texto_norm) for patron in variantes)

    # El objeto que declara la carta debe corresponder al objeto del
    # Documento Base (evita, ej., una carta reciclada de otro proceso que
    # por casualidad menciona el mismo número de lote).
    objeto_carta = _extraer_objeto_carta(texto_norm)
    proporcion_objeto = _proporcion_objeto_relacionado(objeto_carta or "", proceso.objeto_general)
    objeto_relacionado = proporcion_objeto >= 0.5

    # La verificación de "es el representante legal" es por texto, no por
    # criptografía: se cruza el nombre declarado al inicio de la carta ("X,
    # en mi calidad de representante legal de...") con el nombre que aparece
    # junto al cierre/firma ("Nombre del representante legal: X"). La
    # mayoría de las plataformas de firma digital no incluyen el nombre real
    # en el certificado (usan un ID genérico), así que esa vía no es
    # confiable como único criterio — se guarda solo como dato informativo.
    nombre_apertura = _extraer_nombre_apertura(texto_norm)
    nombre_cierre = _extraer_representante_legal(texto_norm)
    representante_legal = nombre_apertura or nombre_cierre

    contenidos_firma = _contenidos_firma_digital(pdf_bytes)
    tiene_firma_digital = bool(contenidos_firma)
    tiene_firma = tiene_imagen or tiene_firma_digital

    nombre_certificado = None
    for contents in contenidos_firma:
        nombre_certificado = _nombre_certificado(contents)
        if nombre_certificado:
            break

    firma_confirmada: bool | None
    if nombre_apertura and nombre_cierre:
        firma_confirmada = _nombres_coinciden(nombre_apertura, nombre_cierre)
    else:
        firma_confirmada = None

    motivos = []
    if not lotes_encontrados:
        motivos.append("no menciona ninguno de los lotes del Documento Base")
    if not numero_proceso_ok:
        motivos.append(f"no menciona el número de proceso ({proceso.codigo_proceso})")
    if not objeto_relacionado:
        motivos.append(
            f"el objeto descrito en la carta no parece corresponder al objeto del Documento Base "
            f"(coincidencia de palabras clave: {proporcion_objeto:.0%})"
        )

    if not tiene_firma:
        motivos.append("no se encontró ninguna firma (ni imagen ni firma digital) en el documento")

    if firma_confirmada is False:
        motivos.append(
            f"el nombre declarado como representante legal al inicio ('{nombre_apertura}') no coincide con el "
            f"nombre que aparece junto al cierre/firma ('{nombre_cierre}')"
        )
    elif nombre_apertura is None and nombre_cierre is None:
        motivos.append(
            "no se pudo identificar el nombre del representante legal en el documento — revísalo manualmente"
        )
    elif firma_confirmada is None:
        # Solo se encontró el nombre en uno de los dos lugares (apertura o
        # cierre); no es necesariamente un error, pero hay que confirmarlo.
        motivos.append(
            f"el nombre del representante legal ('{representante_legal}') solo se encontró en una parte del "
            f"documento — confirma manualmente que coincide en toda la carta"
        )

    cumple = not motivos
    motivo = "; ".join(motivos) if motivos else None

    return ResultadoEvaluacionFormato1(
        cumple=cumple,
        motivo=motivo,
        lotes_encontrados=lotes_encontrados,
        numero_proceso_encontrado=numero_proceso_ok,
        firma_detectada=tiene_firma,
        representante_legal=representante_legal,
        firma_nombre_certificado=nombre_certificado,
        firma_confirmada=firma_confirmada,
        objeto_relacionado=objeto_relacionado,
        tipo_proponente=tipo_proponente,
    )


def evaluar_proponente(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    base = {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
    }

    try:
        metadata = get_file_metadata(proponente.drive_file_id)
    except Exception:  # noqa: BLE001
        metadata = None

    md5 = metadata.get("md5Checksum") if metadata else None
    clave_cache = _clave_cache(proponente, proceso, md5)
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
        # Error de red/descarga: no se cachea, puede ser transitorio.
        return ResultadoRequisito(**base, error=f"No se pudo descargar el archivo de Drive: {exc}")

    pdfs = extraer_pdfs(zip_bytes)
    if not pdfs:
        return finalizar(
            ResultadoRequisito(**base, error="El archivo del proponente no contiene PDFs legibles (¿zip dañado?)."),
            cacheable=False,
        )

    encontrado = encontrar_formato1(pdfs)
    if encontrado is None:
        return finalizar(
            ResultadoRequisito(
                **base,
                cumple=False,
                motivo=(
                    "No se encontró el Formato 1 - Carta de presentación de la oferta por título dentro del "
                    "documento (puede ser un escaneo con mal OCR). Revisa manualmente entre los archivos del "
                    "proponente."
                ),
                archivos_disponibles=sorted(pdfs.keys()),
            ),
            cacheable=True,
        )

    nombre_archivo, contenido = encontrado
    try:
        resultado = evaluar_formato1(contenido, proceso)
    except Exception as exc:  # noqa: BLE001
        return finalizar(
            ResultadoRequisito(**base, archivo_evaluado=nombre_archivo, error=f"No se pudo leer el PDF encontrado: {exc}"),
            cacheable=False,
        )

    return finalizar(
        ResultadoRequisito(
            **base,
            cumple=resultado.cumple,
            motivo=resultado.motivo,
            archivo_evaluado=nombre_archivo,
            lotes_encontrados=resultado.lotes_encontrados,
            numero_proceso_encontrado=resultado.numero_proceso_encontrado,
            objeto_relacionado=resultado.objeto_relacionado,
            tipo_proponente=resultado.tipo_proponente,
            firma_detectada=resultado.firma_detectada,
            representante_legal=resultado.representante_legal,
            firma_nombre_certificado=resultado.firma_nombre_certificado,
            firma_confirmada=resultado.firma_confirmada,
        ),
        cacheable=True,
    )


def evaluar_proponentes(
    proponentes: list[Proponente], proceso: ProcesoDocumentoBase, max_workers: int = 4
) -> list[ResultadoRequisito]:
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        resultados = list(executor.map(lambda p: evaluar_proponente(p, proceso), proponentes))
    return sorted(resultados, key=lambda r: r.numero_orden)
