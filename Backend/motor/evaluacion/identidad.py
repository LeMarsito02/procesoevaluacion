"""Copia del documento de identidad de los representantes (requisito que
agrega el pliego: "fotocopia del documento de identificación del
representante legal").

Se exige la cédula de cada representante a quien se le verifican
antecedentes (el del proponente o los del consorcio) y, si el parámetro
`identidad_suplente` está activo, también la del suplente que figure en el
certificado de existencia: un abogado rechazó una oferta porque "no fue
posible validar los antecedentes de la representante legal suplente ya que
no se aportó copia de la cédula".

La cédula suele venir escaneada: se reconoce por sus marcas (identificación
personal, índice derecho, NUIP, Registraduría) y se empareja con la persona
por su número (tolerando un dígito mal leído por el OCR) o por su nombre.
"""
from __future__ import annotations

import re
from datetime import date

from motor import criterios
from motor.evaluacion.camara_comercio import (
    PISTAS_EXISTENCIA,
    TITULO_EXISTENCIA_RE,
    _evaluar_proponente_camara,
    _texto_completo,
    encontrar_documentos,
)
from motor.evaluacion.formato1 import _nombres_coinciden, _norm
from motor.evaluacion.proponente_plural import obtener_personas_a_verificar
from motor.esquemas.proceso import PersonaAntecedente, ProcesoDocumentoBase, Proponente, ResultadoRequisito
from motor.procesamiento.memoria_proponente import memo_por_pdfs
from motor.llm.vision import LecturaVision
from motor.procesamiento.pdf_utils import abrir_pdf, texto_ocr_reforzado, texto_pagina

MARCAS_CEDULA_RE = re.compile(
    r"IDENTIFICACION\s+PERSONAL|INDICE\s+DERECHO|\bNUIP\b|REGISTRADUR[IA]A?\s+NACIONAL|REGISTRADOR\s+NACIONAL"
    r"|FECHA\s+Y\s+LUGAR\s+DE\s+NACIMIENTO|LUGAR\s+DE\s+NACIMIENTO|ESTATURA|G\.?\s?S\.?\s+RH"
)
# Documentos que citan cédulas sin ser la cédula.
NO_ES_CEDULA_RE = re.compile(
    r"CERTIFICA|PROCURADURIA|CONTRALORIA|POLICIA NACIONAL|MEDIDAS CORRECTIVAS|DEUDORES ALIMENTARIOS|CAMARA DE COMERCIO"
    r"|FORMATO\s+\d|CARTA DE PRESENTACION|SENORES"
)
PISTAS_CEDULA = ("cedula", "cc", "c.c", "identidad", "documento", "rl", "representante", "ci ", "id")
PAGINAS_CON_PISTA = 20
PAGINAS_SIN_PISTA = 6
PAGINAS_REFORZADAS = 4

# Suplente en el certificado de existencia: "REPRESENTANTE LEGAL SUPLENTE
# SANDRA STELLA MORENO BUITRAGO C.C. NO. 35.254.078", "GERENTE SUPLENTE
# CAROLINA CUELLAR PASTRANA C.C. NO. 1.075.303.013".
SUPLENTE_RE = re.compile(
    r"(?:REPRESENTANTE\s+LEGAL\s+SUPLENTE|SUPLENTE\s+DEL\s+(?:REPRESENTANTE\s+LEGAL|GERENTE)|GERENTE\s+SUPLENTE|SUBGERENTE)"
    r"\s+([A-ZÑ][A-ZÑ ]{5,60}?)\s+(?:C\.?\s?C\.?|CEDULA\s+DE\s+CIUDADANIA)\s*(?:NO\.?\s*)?(\d[\d.]{5,})"
)


def _digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


@memo_por_pdfs
def paginas_cedula(pdfs: dict[str, bytes]) -> list[tuple[str, str]]:
    """(archivo, texto) de las páginas que parecen una cédula."""
    return [(archivo, texto) for archivo, _, texto in paginas_cedula_numeradas(pdfs)]


@memo_por_pdfs
def paginas_cedula_numeradas(pdfs: dict[str, bytes]) -> list[tuple[str, int, str]]:
    """(archivo, número de página, texto) de las páginas que parecen una
    cédula. El número importa para mostrarle a la IA la página correcta: en un
    paquete de 30 páginas la cédula puede estar en la 7."""
    paginas = []
    for nombre, contenido in pdfs.items():
        base = nombre.rsplit("/", 1)[-1].lower()
        limite = PAGINAS_CON_PISTA if any(p in base for p in PISTAS_CEDULA) else PAGINAS_SIN_PISTA
        try:
            with abrir_pdf(contenido) as pdf:
                for page in pdf.pages[:limite]:
                    texto = texto_pagina(page)
                    numero = page.page_number
                    page.flush_cache()
                    texto_norm = _norm(texto)
                    if MARCAS_CEDULA_RE.search(texto_norm) and not NO_ES_CEDULA_RE.search(texto_norm):
                        paginas.append((nombre, numero, texto_norm))
        except Exception:  # noqa: BLE001
            continue
    return paginas


def _numero_en(numero: str, texto_norm: str) -> bool:
    """El número de cédula está en el texto, con a lo sumo un dígito mal
    leído (el OCR confunde 1/7, 0/8, 5/6…)."""
    if len(numero) < 6:
        return False
    for candidato in re.findall(r"\d[\d.,\s]{5,16}\d", texto_norm):
        d = _digitos(candidato)
        if d == numero:
            return True
        if len(d) == len(numero) and sum(a != b for a, b in zip(d, numero)) <= 1:
            return True
    return False


_ARCHIVO_CEDULA_RE = re.compile(r"CEDULA|\bC\.?\s?C\b|DOCUMENTO\s+DE\s+IDENTIDAD|\bDI\b|\bDCTO\b|\bDOC\b|IDENTIFICACION")


# Archivo de la cédula del representante legal: "CEDULA REPRESENTANTE
# LEGAL", "2. CEDULA REP LEGAL", "acedula-rl-consorcio", "Dcto Representante
# Legal".
_ARCHIVO_DEL_REPRESENTANTE_RE = re.compile(r"REPRESENTANTE|REP\.?\s*LEGAL|\bR\.?\s?L\b|\bRL\b|LEGAL")


def _es_suyo(nombre: str, numero: str, texto: str) -> bool:
    return (bool(numero) and _numero_en(numero, texto)) or _nombres_coinciden(nombre, " ".join(re.findall(r"[A-ZÑ]{2,}", texto)))


def cedula_de(pdfs: dict[str, bytes], nombre: str, cedula: str | None, principal: bool = False) -> str | None:
    """Archivo con la copia de la cédula de la persona, o None: una página de
    cédula con su número o su nombre (releída con el OCR reforzado si el
    normal no alcanza), o que está en un archivo llamado "cédula <su
    nombre>" o, si es el representante principal, "cédula representante
    legal" (el reverso de la cédula no trae ni nombre ni número)."""
    numero = _digitos(cedula or "")
    paginas = paginas_cedula(pdfs)
    for archivo, texto in paginas:
        if _es_suyo(nombre, numero, texto):
            return archivo
        base = _norm(archivo.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        if _ARCHIVO_CEDULA_RE.search(base) and _nombre_en_archivo(nombre, base):
            return archivo
        # La página ya es una cédula: si el archivo es "del representante
        # legal" ("Dcto Representante Legal", "EXISTENCIA Y RL"), es la suya.
        if principal and _ARCHIVO_DEL_REPRESENTANTE_RE.search(base):
            return archivo
    for archivo in dict.fromkeys(a for a, _ in paginas):
        try:
            reforzado = _norm(texto_ocr_reforzado(pdfs[archivo], max_paginas=PAGINAS_REFORZADAS))
        except Exception:  # noqa: BLE001
            continue
        if reforzado and _es_suyo(nombre, numero, reforzado):
            return archivo
    return None


def _nombre_en_archivo(nombre: str, base: str) -> bool:
    """El archivo (ya reconocido como cédula) es de esta persona: trae su
    nombre ("CEDULA JUAN JOSE ARAQUE"), su primer nombre ("CEDULA Y TARJETA
    DANIELA") o sus iniciales ("C.C., T.P. Y COPNIA JAL" = Juan Amado Lizarazo)."""
    palabras = set(re.findall(r"[A-ZÑ]{2,}", base))
    partes = [p for p in re.findall(r"[A-ZÑ]+", _norm(nombre)) if p not in {"DE", "DEL", "LA", "LOS", "Y"}]
    if not partes:
        return False
    if _nombres_coinciden(nombre, " ".join(palabras)):
        return True
    if len(partes[0]) >= 4 and partes[0] in palabras:
        return True
    iniciales = {"".join(p[0] for p in partes), "".join(p[0] for p in partes[:3]), partes[0][0] + "".join(p[0] for p in partes[-2:])}
    return any(len(i) >= 3 and i in palabras for i in iniciales)


def suplentes_del_certificado(pdfs: dict[str, bytes]) -> list[tuple[str, str]]:
    suplentes = []
    for nombre in encontrar_documentos(pdfs, TITULO_EXISTENCIA_RE, PISTAS_EXISTENCIA):
        texto = re.sub(r"\s+", " ", _norm(_texto_completo(pdfs, nombre)))
        for m in SUPLENTE_RE.finditer(texto):
            persona = (re.sub(r"\s+", " ", m.group(1)).strip(), _digitos(m.group(2)))
            if not any(_nombres_coinciden(persona[0], s[0]) for s in suplentes):
                suplentes.append(persona)
    return suplentes


# En el reverso de la cédula: "05-JUN-2001 CARTAGENA FECHA Y LUGAR DE
# EXPEDICION". La fecha viene antes de la etiqueta, con la ciudad en medio, y
# el OCR daña la etiqueta con frecuencia ("FECHA Y LUEGAR", "EXPEDICIONF.20").
MESES_CEDULA = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
                "JUL": 7, "AGO": 8, "SEP": 9, "SET": 9, "OCT": 10, "NOV": 11, "DIC": 12}
FECHA_CEDULA_RE = re.compile(r"(\d{1,2})\s?[-/.]\s?([A-Z]{3})\s?[-/.]\s?(\d{4})")
ETIQUETA_EXPEDICION_RE = re.compile(r"EXPEDICION|EXPEDIDA")
# Distancia máxima entre la fecha y la etiqueta (en medio va la ciudad).
CERCA_DE_LA_ETIQUETA = 70


def _fecha_de(match: re.Match[str]) -> date | None:
    mes = MESES_CEDULA.get(match.group(2))
    if not mes:
        return None
    try:
        fecha = date(int(match.group(3)), mes, int(match.group(1)))
    except ValueError:
        return None
    # Una cédula no se expide antes de 1960 ni después de hoy.
    return fecha if date(1960, 1, 1) <= fecha <= date.today() else None


# La etiqueta completa y sin daños del OCR: si está así, lo leído es de fiar.
ETIQUETA_LIMPIA_RE = re.compile(r"FECHA\s+Y\s+LUGAR\s+DE\s+EXPEDICION")


class LecturaFecha:
    """Qué fecha se leyó, de dónde y si se puede confiar en ella. Una fecha
    dudosa no sirve: consultar la página de la Policía con ella la rechaza y
    se gasta una consulta a una plataforma del Estado para nada."""

    def __init__(self, fecha: date | None, confiable: bool, fuente: str) -> None:
        self.fecha = fecha
        self.confiable = confiable
        self.fuente = fuente  # "ocr" | "ia" | "ninguna"

    def __repr__(self) -> str:  # pragma: no cover - ayuda al depurar
        return f"LecturaFecha({self.fecha}, confiable={self.confiable}, fuente={self.fuente!r})"


def lectura_ocr(texto_norm: str) -> LecturaFecha:
    """Lo que el OCR alcanzó a leer. Es de fiar solo si la etiqueta salió
    completa ("FECHA Y LUGAR DE EXPEDICION") y hay una sola fecha pegada a
    ella; con la etiqueta rota ("FECHA Y LUEGAR", "EXPEDICIONF.20") los
    dígitos de al lado también suelen venir mal leídos."""
    fecha = fecha_expedicion_en(texto_norm)
    if fecha is None:
        return LecturaFecha(None, False, "ninguna")
    limpia = bool(ETIQUETA_LIMPIA_RE.search(re.sub(r"\s+", " ", texto_norm)))
    return LecturaFecha(fecha, limpia, "ocr")


def fecha_expedicion_en(texto_norm: str) -> date | None:
    """La fecha de expedición que dice el reverso de la cédula, o None si no
    está clara. Se toma la fecha que está pegada a la etiqueta "FECHA Y LUGAR
    DE EXPEDICION"; la de nacimiento queda descartada porque está junto a su
    propia etiqueta, lejos de esta."""
    texto = re.sub(r"\s+", " ", texto_norm)
    candidatas: list[date] = []
    for etiqueta in ETIQUETA_EXPEDICION_RE.finditer(texto):
        trozo = texto[max(0, etiqueta.start() - CERCA_DE_LA_ETIQUETA) : etiqueta.start()]
        encontradas = [f for m in FECHA_CEDULA_RE.finditer(trozo) if (f := _fecha_de(m))]
        # Se queda con la más pegada a la etiqueta; si hay dos distintas igual
        # de cerca no se afirma nada.
        if encontradas:
            candidatas.append(encontradas[-1])
    distintas = set(candidatas)
    return candidatas[0] if len(distintas) == 1 else None


def leer_fecha_expedicion(
    pdfs: dict[str, bytes], nombre: str, cedula: str | None, principal: bool = False
) -> LecturaFecha:
    """La fecha de expedición de la cédula de esa persona, leída de la copia
    que viene en la oferta (los proponentes la escanean por ambos lados). La
    pide el RNMC para consultar sus antecedentes.

    Primero el texto del PDF, luego el OCR reforzado y, si alguno de los dos
    quedó dudoso (o no leyó nada), la IA local mira la imagen: está mejor
    preparada para escaneos torcidos o con sombras, y una fecha mal leída
    significa una consulta perdida a la página del Estado.

    Solo se lee de una página que sea demostrablemente suya (trae su número o
    su nombre): una carpeta puede traer las cédulas de varias personas y una
    fecha de otro no sirve para consultar nada."""
    archivo = cedula_de(pdfs, nombre, cedula, principal=principal)
    if archivo is None:
        return LecturaFecha(None, False, "ninguna")
    numero = _digitos(cedula or "")
    dudosa = LecturaFecha(None, False, "ninguna")
    for nombre_archivo, texto in paginas_cedula(pdfs):
        if nombre_archivo != archivo or not _es_suyo(nombre, numero, texto):
            continue
        lectura = lectura_ocr(texto)
        if lectura.confiable:
            return lectura
        dudosa = lectura if lectura.fecha else dudosa
    try:
        reforzado = _norm(texto_ocr_reforzado(pdfs[archivo], max_paginas=PAGINAS_REFORZADAS))
    except Exception:  # noqa: BLE001
        reforzado = ""
    if reforzado and _es_suyo(nombre, numero, reforzado):
        lectura = lectura_ocr(reforzado)
        if lectura.confiable:
            return lectura
        dudosa = lectura if lectura.fecha else dudosa

    from motor.llm.vision import leer_cedula_detallado

    # Solo las páginas que parecen cédula, no las primeras del archivo: en un
    # paquete de documentos la cédula puede estar en cualquier página.
    paginas = [n for a, n, _ in paginas_cedula_numeradas(pdfs) if a == archivo]
    try:
        de_la_ia = leer_cedula_detallado(pdfs[archivo], cedula, paginas=paginas)
    except Exception:  # noqa: BLE001
        de_la_ia = LecturaVision(None)
    if de_la_ia.fecha is None:
        return dudosa
    # Se da por buena cuando dos miradas coinciden, o cuando la IA confirma lo
    # que el OCR había leído a medias. Una sola lectura se sugiere, no se usa.
    segura = de_la_ia.confirmada or de_la_ia.fecha == dudosa.fecha
    return LecturaFecha(de_la_ia.fecha, segura, "ia")


def fecha_expedicion_cedula(pdfs: dict[str, bytes], nombre: str, cedula: str | None, principal: bool = False) -> date | None:
    """Solo la fecha cuando es de fiar (para guardarla sin que nadie la revise)."""
    lectura = leer_fecha_expedicion(pdfs, nombre, cedula, principal=principal)
    return lectura.fecha if lectura.confiable else None


class ResultadoIdentidad:
    def __init__(self, cumple: bool, motivo: str | None, archivo: str | None,
                 personas: list[PersonaAntecedente] | None = None) -> None:
        self.cumple = cumple
        self.motivo = motivo
        self.archivo = archivo
        # Cada persona a la que se le exige la copia de su documento, con la
        # fecha de expedición que dice el reverso (la pide el RNMC).
        self.personas = personas or []


def evaluar_identidad(pdfs: dict[str, bytes], proceso: ProcesoDocumentoBase, tipo_proponente: str | None) -> ResultadoIdentidad:
    personas = [(n, c) for n, c in obtener_personas_a_verificar(pdfs, tipo_proponente, proceso.codigo_proceso)]
    if not personas:
        return ResultadoIdentidad(
            cumple=False,
            motivo="no se pudo identificar al representante legal para buscar la copia de su documento de identidad — revisa manualmente",
            archivo=None,
        )
    if criterios.valor("identidad_suplente") and tipo_proponente not in ("consorcio", "union_temporal", "persona_natural"):
        for suplente in suplentes_del_certificado(pdfs):
            if not any(_nombres_coinciden(suplente[0], p[0]) for p in personas):
                personas.append(suplente)
    faltan, archivo = [], None
    detalle: list[PersonaAntecedente] = []
    rol = "proponente" if tipo_proponente == "persona_natural" else "representante_legal"
    for indice, (nombre, cedula) in enumerate(personas):
        encontrado = cedula_de(pdfs, nombre, cedula, principal=indice == 0)
        fecha = None
        if encontrado is None:
            faltan.append(nombre)
        else:
            archivo = archivo or encontrado
            # La fecha solo si la página es suya (trae su número o su nombre).
            fecha = next(
                (f for a, texto in paginas_cedula(pdfs)
                 if a == encontrado and _es_suyo(nombre, _digitos(cedula or ""), texto) and (f := fecha_expedicion_en(texto))),
                None,
            )
        detalle.append(PersonaAntecedente(
            nombre=nombre,
            documento=cedula or None,
            tipo="natural",
            rol=rol if indice == 0 else ("suplente" if indice == 1 else "integrante"),
            estado="cumple" if encontrado else "falta",
            archivo=encontrado,
            fecha_expedicion_documento=fecha,
        ))
    if faltan:
        return ResultadoIdentidad(
            cumple=False,
            motivo=(
                f"no se encontró la copia del documento de identidad de {', '.join(faltan)} — confirma si se aportó "
                "(la cédula escaneada puede no leerse)"
            ),
            archivo=archivo,
            personas=detalle,
        )
    return ResultadoIdentidad(cumple=True, motivo=None, archivo=archivo, personas=detalle)


def evaluar_proponente_identidad(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_camara(20, evaluar_identidad, proponente, proceso)
