"""Puntaje técnico (pliego, capítulo 4): factor de calidad, apoyo a la
industria nacional, vinculación de personas con discapacidad,
emprendimientos y empresas de mujeres y MIPYME.

Mismo criterio que en la experiencia: solo se otorga el puntaje que se pudo
verificar completo; lo demás va a revisión con lo que se encontró. Nunca se
quita un puntaje de forma automática.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from motor.evaluacion.camara_comercio import PISTAS_EXISTENCIA, TITULO_EXISTENCIA_RE, encontrar_documentos
from motor.evaluacion.personalizado import esta_firmado
from motor.procesamiento.pdf_utils import buscar_pagina
from motor.tecnica.experiencia import IntegranteTecnico
from motor.tecnica.rup import normalizar

PAGINAS_PARA_TITULO = 3
_ANCLA_FIRMA_RE = re.compile(r"^(ATENTAMENTE|FIRMA|LEGAL|FISCAL|CONTADOR|CONTADORA|APODERADO|C\.?C\.?|REPRESENTANTE|CORDIALMENTE)[:.,]?$")


def _escaneado(pdf) -> bool:
    """Todas las páginas son una imagen de página completa, sin texto."""
    for page in pdf.pages[:3]:
        alto, ancho = float(page.height or 1), float(page.width or 1)
        completa = any(float(i["width"]) > ancho * 0.8 and float(i["height"]) > alto * 0.8 for i in page.images)
        if page.chars or not completa:
            return False
    return True


def firmado(contenido: bytes) -> bool | None:
    """Firma digital, o una imagen junto a las palabras de firma
    ("Atentamente", "Representante Legal", "C.C.") y fuera del membrete. Cuando
    el texto del formato sigue en una segunda página, la firma queda arriba de
    esa página: por eso no basta con mirar la mitad de abajo. En un formulario
    escaneado (la página entera es una imagen) lo mira el modelo de visión
    local si está habilitado; si no, None: lo verifica una persona."""
    import os

    from motor.evaluacion.formato1 import _contenidos_firma_digital
    from motor.procesamiento.pdf_utils import abrir_pdf

    escaneado = False
    try:
        if _contenidos_firma_digital(contenido):
            return True
        with abrir_pdf(contenido) as pdf:
            escaneado = _escaneado(pdf)
            for page in [] if escaneado else pdf.pages[:6]:
                alto = float(page.height or 1)
                imagenes = [i for i in page.images if float(i.get("top", 0)) > alto * 0.12 and float(i.get("width", 0)) > 25]
                if imagenes:
                    anclas = [float(w["top"]) for w in page.extract_words() if _ANCLA_FIRMA_RE.match(normalizar(w["text"]))]
                    for imagen in imagenes:
                        arriba, abajo = float(imagen["top"]), float(imagen["bottom"])
                        if any(arriba - 150 <= y <= abajo + 150 for y in anclas):
                            page.flush_cache()
                            return True
                page.flush_cache()
    except Exception:  # noqa: BLE001
        pass
    if escaneado:
        if os.environ.get("VISION_EN_EVALUACION", "0") != "1":
            return None
        from motor.llm.vision import firma_manuscrita

        return firma_manuscrita(contenido)
    return esta_firmado(contenido)


def menciona_proceso(codigo: str, texto: str) -> bool:
    """El formato cita el número del proceso. En los escaneados el OCR daña
    la sigla ("/CCU-LP-022-2026"): basta con la parte que sigue a la sigla
    de la entidad (modalidad, número y año: "LP0222026")."""
    solo = lambda t: re.sub(r"[^A-Z0-9]", "", normalizar(t))  # noqa: E731
    partes = [p for p in re.split(r"[^A-Z0-9]+", normalizar(codigo)) if p]
    nucleo = "".join(partes[1:]) if len(partes) >= 3 else "".join(partes)
    return solo(codigo) in solo(texto) or (len(nucleo) >= 6 and nucleo in solo(texto))


def _texto_firma(firma: bool | None) -> str:
    return {True: "sí", False: "no se detectó", None: "escaneo, verifícala"}[firma]


@dataclass
class Factor:
    clave: str
    nombre: str
    puntaje_maximo: float
    # None: a revisión (no se pudo verificar); 0 solo lo pone una persona.
    puntaje: float | None = None
    archivo: str | None = None
    motivos: list[str] = field(default_factory=list)


def _buscar_formato(pdfs: dict[str, bytes], titulo: re.Pattern, pista: re.Pattern | None = None):
    """(archivo, texto normalizado) de los PDF cuyo título calza, uno a uno:
    primero los que lo sugieren por el nombre; quien llama se detiene en el
    primero que le sirve (recorrer los cien PDF de una oferta con OCR tarda)."""
    orden = sorted(pdfs, key=lambda a: not (pista and pista.search(normalizar(a))))
    for archivo in orden:
        try:
            texto = buscar_pagina(pdfs[archivo], lambda t: bool(titulo.search(normalizar(t))), max_paginas=PAGINAS_PARA_TITULO)
        except Exception:  # noqa: BLE001
            continue
        if texto is not None:
            yield archivo, normalizar(texto)


def _compromiso_firmado(
    pdfs: dict[str, bytes], factor: Factor, titulo: re.Pattern, pista: re.Pattern, exige: re.Pattern, codigo_proceso: str | None,
) -> Factor:
    """Formatos de compromiso bajo juramento (7A, 7C, 14): basta con que estén
    diligenciados para este proceso y firmados."""
    for archivo, texto in _buscar_formato(pdfs, titulo, pista):
        faltas = []
        if not exige.search(texto):
            faltas.append("no trae el compromiso bajo la gravedad de juramento")
        if codigo_proceso and not menciona_proceso(codigo_proceso, texto):
            faltas.append(f"no menciona el proceso {codigo_proceso}")
        firma = firmado(pdfs[archivo])
        if firma is None:
            faltas.append("es un escaneo: verifica la firma")
        elif not firma:
            faltas.append("no se detectó la firma")
        if not faltas:
            factor.puntaje, factor.archivo, factor.motivos = factor.puntaje_maximo, archivo, []
            return factor
        factor.archivo = factor.archivo or archivo
        factor.motivos = [f"{archivo}: {'; '.join(faltas)}"]
    if factor.archivo is None:
        factor.motivos.append("no se encontró el formato")
    return factor


_FORMATO7_PISTA = re.compile(r"FORMA\w*\s*7|CALIDAD|PONDERABLE|PUNTAJE")
_JURAMENTO = re.compile(r"GRAVEDAD\s+DE(?:L)?\s+JURAMENTO|BAJO\s+JURAMENTO")


def factor_calidad(pdfs: dict[str, bytes], codigo_proceso: str | None) -> list[Factor]:
    gerencia = _compromiso_firmado(
        pdfs, Factor("gerencia_proyectos", "4.2.1 Programa de gerencia de proyectos (Formato 7A)", 5),
        re.compile(r"FORMATO\s*7\s*A\b.{0,20}PROGRAMA\s+DE\s+GERENCIA|PROGRAMA\s+DE\s+GERENCIA\s+DE\s+PROYECTOS", re.S),
        _FORMATO7_PISTA, _JURAMENTO, codigo_proceso,
    )
    plan = _compromiso_firmado(
        pdfs, Factor("plan_calidad", "4.2.3 Plan de calidad (Formato 7C)", 5),
        re.compile(r"FORMATO\s*7\s*C\b.{0,20}PLAN\s+DE\s+CALIDAD", re.S),
        _FORMATO7_PISTA, re.compile(r"ISO|PLAN\s+DE\s+CALIDAD|COMPROM"), codigo_proceso,
    )
    ambiental = _compromiso_firmado(
        pdfs, Factor("criterios_ambientales", "4.2.4 Criterios ambientales y sociales (Formato 14)", 20),
        re.compile(r"FORMATO\s*14\b.{0,60}AMBIENTAL", re.S),
        re.compile(r"FORMA\w*\s*14|AMBIENTAL|PONDERABLE|PUNTAJE"), _JURAMENTO, codigo_proceso,
    )
    return [gerencia, plan, ambiental]


def mipyme(integrantes: list[IntegranteTecnico], plural: bool, minimo_participacion: float = 0.10) -> Factor:
    """4.7: el RUP de un integrante con participación ≥ 10 % (o del
    proponente individual) lo clasifica como micro, pequeña o mediana."""
    factor = Factor("mipyme", "4.7 MIPYME domiciliada en Colombia", 0.25)
    for i in integrantes:
        if i.rup is None or not i.rup.es_mipyme:
            continue
        if plural and (i.participacion is None or i.participacion < minimo_participacion - 1e-9):
            continue
        factor.puntaje = factor.puntaje_maximo
        factor.motivos = [f"{i.nombre}: {i.rup.tamano_empresa.lower()} según su RUP"]
        return factor
    sin_rup = [i.nombre for i in integrantes if i.rup is None]
    grandes = [f"{i.nombre} ({i.rup.tamano_empresa.lower() or 'sin tamaño'})" for i in integrantes if i.rup is not None]
    factor.motivos.append(
        "ningún integrante con al menos el 10 % de participación acredita ser MIPYME en su RUP"
        + (f"; RUP leídos: {', '.join(grandes)}" if grandes else "")
        + (f"; sin RUP: {', '.join(sin_rup)}" if sin_rup else "")
    )
    return factor


_FORMATO9A = re.compile(r"FORMATO\s*9\s*A\b.{0,30}SERVICIOS\s+NACIONALES|PROMOCION\s+DE\s+SERVICIOS\s+NACIONALES", re.S)
_FORMATO9B = re.compile(r"FORMATO\s*9\s*B\b.{0,40}COMPONENTE\s+NACIONAL", re.S)


_AL_MENOS_RE = re.compile(r"AL\s+MENOS\s+(?:EL\s+)?[^%\d\n]{0,40}?(\d{2,3}(?:[.,]\d+)?)\s*%")
_CEDULA_RE = re.compile(r"CEDULA\s+DE\s+CIUDADANIA|IDENTIFICACION\s+PERSONAL|REGISTRADURIA|DOCUMENTO\s+DE\s+IDENTIDAD")
_PISTA_CEDULA_RE = re.compile(r"CEDULA|\bCC\b|C\.C|DOCUMENTO|IDENTIDAD|IDENTIFICACION")
_MARCA_EMPRESA_RE = re.compile(r"\bS\.?\s?A\.?\s?S\b|\bLTDA\b|\bS\.?\s?A\b|LIMITADA|SOCIEDAD|E\.?\s?U\b|CORPORACION|FUNDACION|COOPERATIVA")


def _porcentaje_nacional(texto: str) -> float | None:
    valores = [float(v.replace(",", ".")) for v in _AL_MENOS_RE.findall(texto)]
    return max(valores) if valores else None


def _cedula_de(pdfs: dict[str, bytes], nombre: str) -> str | None:
    """Archivo con la cédula de una persona natural: la página dice que es una
    cédula y trae al menos dos palabras de su nombre."""
    palabras = [p for p in normalizar(nombre).split() if len(p) >= 3]
    for archivo, texto in _buscar_formato(pdfs, _CEDULA_RE, _PISTA_CEDULA_RE):
        if sum(1 for p in palabras if p in texto) >= min(2, len(palabras)):
            return archivo
    return None


def industria_nacional(
    pdfs: dict[str, bytes], integrantes: list[IntegranteTecnico], codigo_proceso: str | None,
) -> Factor:
    """4.3.2: Formato 9A firmado, con al menos el 90 % de personal colombiano,
    y de cada integrante el certificado de existencia (persona jurídica) o la
    cédula (persona natural)."""
    from motor.procesamiento.pdf_utils import extraer_texto

    factor = _compromiso_firmado(
        pdfs, Factor("industria_nacional", "4.3 Apoyo a la industria nacional (Formato 9A)", 20),
        _FORMATO9A, re.compile(r"FORMA\w*\s*9|INDUSTRIA|PONDERABLE|PUNTAJE"), _JURAMENTO, codigo_proceso,
    )
    if factor.puntaje is None:
        return factor
    texto_9a = next((t for a, t in _buscar_formato({factor.archivo: pdfs[factor.archivo]}, _FORMATO9A)), "")
    nacional = _porcentaje_nacional(texto_9a)
    if nacional is None or nacional < 90:
        factor.puntaje = None
        factor.motivos.append(
            "el Formato 9A no indica el porcentaje de personal colombiano" if nacional is None
            else f"el Formato 9A ofrece {nacional:g} % de personal colombiano (se exige al menos 90 %)"
        )
        return factor
    textos = {}
    for archivo in encontrar_documentos(pdfs, TITULO_EXISTENCIA_RE, PISTAS_EXISTENCIA):
        try:
            # Completo: hay PDF con los certificados de todos los integrantes seguidos.
            textos[archivo] = normalizar(extraer_texto(pdfs[archivo], max_paginas=60))
        except Exception:  # noqa: BLE001
            textos[archivo] = ""
    faltan = []
    for i in integrantes:
        nit = re.sub(r"\D", "", i.nit or (i.rup.nit if i.rup else ""))[:9]
        if nit and any(nit in re.sub(r"\D", "", t) for t in textos.values()):
            continue
        if any(normalizar(i.nombre)[:25] in t for t in textos.values()):
            continue
        if not _MARCA_EMPRESA_RE.search(normalizar(i.nombre)) and _cedula_de(pdfs, i.nombre):
            continue
        faltan.append(i.nombre)
    if faltan:
        factor.puntaje = None
        factor.motivos.append(
            f"no se encontró el certificado de existencia (o la cédula, si es persona natural) de: {', '.join(faltan)}"
        )
    return factor


_FORMATO8 = re.compile(r"FORMATO\s*8\b.{0,80}DISCAPACIDAD", re.S)
_PLANTA_RE = re.compile(r"PLANTA\s+DE\s+PERSONAL\s+(\d{1,5})\s+(\d{1,4})\b")
_MINTRABAJO_RE = re.compile(r"CONSTATACION\s+DE\s+VINCULACION|MINISTERIO\s+DE(?:L)?\s+TRABAJO.{0,600}DISCAPACIDAD", re.S)
_TOTAL_RE = re.compile(r"NUMERO\s+TOTAL\s+DE\s+TRABAJADORES\s*:?\s*(\d{1,5})\b")
_CON_DISCAPACIDAD_RE = re.compile(r"B\.\s*NUMERO\s+DE\s+TRABAJADORES\s+CON\s+DISCAPACIDAD\s*:?\s*(\d{1,4})\b")
_RAZON_SOCIAL_RE = re.compile(r"RAZON\s+SOCIAL\s*:?\s*(.{3,120}?)\s+IDENTIFICACION\s*:?\s*(?:NIT\.?|C\.?C\.?)?\s*([\d.\s-]{5,20})")
_VIGENCIA_CONSTANCIA_RE = re.compile(r"VIGENCIA\s+DE\s+LA\s+PRESENTE\s+CONSTANCIA\s+ES\s+DE\s+[A-Z]*\s*\(?0?(\d{1,2})\)?\s*MESES")
_DADO_DIAS_RE = re.compile(r"DADO\s+EN.{0,80}?\(?(\d{1,2})\)?\s+DIAS?\s+DEL\s+MES\s+DE\s+([A-Z]+)\s+DE(?:L)?\s+(\d{4})", re.S)
_DADO_FECHA_RE = re.compile(r"DADO\s+EN.{0,80}?\b(\d{1,2})\s+DE\s+([A-Z]+)\s+DE(?:L)?\s+(\d{4})", re.S)
_MESES = {m: i for i, m in enumerate(
    "ENERO FEBRERO MARZO ABRIL MAYO JUNIO JULIO AGOSTO SEPTIEMBRE OCTUBRE NOVIEMBRE DICIEMBRE".split(), 1)}
# Mínimo de trabajadores con discapacidad según el total de la planta (4.4).
_MINIMOS_DISCAPACIDAD = [(30, 1), (100, 2), (150, 3), (200, 4)]


def minimo_con_discapacidad(total: int) -> int:
    return next((m for tope, m in _MINIMOS_DISCAPACIDAD if total <= tope), 5)


def _mas_meses(fecha, meses: int):
    from datetime import date

    mes = fecha.month - 1 + meses
    ano, mes = fecha.year + mes // 12, mes % 12 + 1
    for dia in (fecha.day, 30, 29, 28):
        try:
            return date(ano, mes, dia)
        except ValueError:
            continue
    return None


@dataclass
class CertificadoDiscapacidad:
    archivo: str
    razon_social: str = ""
    identificacion: str = ""
    total: int | None = None
    con_discapacidad: int | None = None
    expedicion: object = None  # date
    vigencia_meses: int | None = None


def leer_certificado_discapacidad(archivo: str, texto: str) -> CertificadoDiscapacidad:
    """Constancia del Ministerio de Trabajo: a quién, cuántos trabajadores,
    cuántos con discapacidad, cuándo se expidió y su vigencia (la dice la
    propia constancia: "seis (6) meses contados a partir de la fecha de
    expedición")."""
    from datetime import date

    c = CertificadoDiscapacidad(archivo)
    if m := _RAZON_SOCIAL_RE.search(texto):
        c.razon_social, c.identificacion = " ".join(m.group(1).split()), re.sub(r"\D", "", m.group(2))
    if m := _TOTAL_RE.search(texto):
        c.total = int(m.group(1))
    if m := _CON_DISCAPACIDAD_RE.search(texto):
        c.con_discapacidad = int(m.group(1))
    if m := _VIGENCIA_CONSTANCIA_RE.search(texto):
        c.vigencia_meses = int(m.group(1))
    for patron in (_DADO_DIAS_RE, _DADO_FECHA_RE):
        m = None
        for m in patron.finditer(texto):
            pass  # la última: la de la firma, al final
        if m and m.group(2) in _MESES:
            try:
                c.expedicion = date(int(m.group(3)), _MESES[m.group(2)], int(m.group(1)))
                break
            except ValueError:
                continue
    return c


def _es_de(integrante: IntegranteTecnico, identificacion: str, texto: str) -> bool:
    nit = re.sub(r"\D", "", integrante.nit or (integrante.rup.nit if integrante.rup else ""))[:9]
    if nit and identificacion and (identificacion.startswith(nit) or nit.startswith(identificacion[:9])):
        return True
    if nit and nit in re.sub(r"\D", "", texto):
        return True
    propias = [p for p in re.findall(r"[A-Z0-9&]{3,}", normalizar(integrante.nombre).replace(".", "")) if p not in {"SAS", "LTDA"}]
    return bool(propias) and all(p in texto for p in propias)


def discapacidad(
    pdfs: dict[str, bytes], integrantes: list[IntegranteTecnico], lotes, plural: bool, fecha_cierre,
) -> Factor:
    """4.4: un punto si el integrante que cuenta (en plurales, el que aporta al
    menos el 40 % de la experiencia exigida) acredita con la constancia del
    Ministerio de Trabajo, vigente al cierre, el mínimo de trabajadores con
    discapacidad según su planta, y el Formato 8 firmado la certifica."""
    from motor.procesamiento.pdf_utils import extraer_texto

    factor = Factor("discapacidad", "4.4 Vinculación de personas con discapacidad (Formato 8)", 1)
    candidatos = list(integrantes)
    if plural:
        exigidos = [(l.aporte_por_integrante, l.valor_a_certificar) for l in lotes if l.valor_a_certificar]
        candidatos = [
            i for i in integrantes
            if exigidos and all(aportes.get(i.nombre, 0) >= 0.4 * base for aportes, base in exigidos)
        ]
        if not candidatos:
            factor.motivos.append("no se pudo establecer qué integrante aporta al menos el 40 % de la experiencia exigida")
            return factor
    certificados = []
    for archivo, _ in _buscar_formato(pdfs, _MINTRABAJO_RE, re.compile(r"DISCAPACI|MINTRABAJO|MINISTERIO|CONSTANCIA")):
        texto = normalizar(" ".join(extraer_texto(pdfs[archivo], max_paginas=3).split()))
        certificados.append((leer_certificado_discapacidad(archivo, texto), texto))
    formatos = []
    for archivo, _ in _buscar_formato(pdfs, _FORMATO8, re.compile(r"FORMA\w*\s*8|DISCAPACI")):
        texto = normalizar(" ".join(extraer_texto(pdfs[archivo], max_paginas=3).split()))
        formatos.append((archivo, texto))
    if not certificados:
        factor.motivos.append("no se encontró la constancia del Ministerio de Trabajo")
    if not formatos:
        factor.motivos.append("no se encontró el Formato 8")
    for integrante in candidatos:
        faltas = []
        suyos = [(c, t) for c, t in certificados if _es_de(integrante, c.identificacion, t)]
        formato = next(((a, t) for a, t in formatos if not plural or _es_de(integrante, "", t)), None)
        if not suyos:
            faltas.append("no hay constancia del Ministerio de Trabajo a su nombre")
        planta = _PLANTA_RE.search(formato[1]) if formato else None
        for cert, _ in suyos:
            faltas = []
            if cert.expedicion is None or cert.vigencia_meses is None:
                faltas.append(f"no se leyó la fecha de expedición o la vigencia de {cert.archivo}")
            else:
                vence = _mas_meses(cert.expedicion, cert.vigencia_meses)
                if not (cert.expedicion <= fecha_cierre and vence and vence >= fecha_cierre):
                    faltas.append(f"la constancia se expidió el {cert.expedicion:%d/%m/%Y} con vigencia de {cert.vigencia_meses} meses: no está vigente al cierre")
            total = int(planta.group(1)) if planta else cert.total
            if total is None or cert.con_discapacidad is None:
                faltas.append("no se leyó el número de trabajadores o de trabajadores con discapacidad")
            elif cert.con_discapacidad < minimo_con_discapacidad(total):
                faltas.append(f"{cert.con_discapacidad} con discapacidad en una planta de {total}: el mínimo es {minimo_con_discapacidad(total)}")
            if formato is None:
                faltas.append("no se encontró su Formato 8")
            elif (firma := firmado(pdfs[formato[0]])) is not True:
                faltas.append(f"firma del Formato 8: {_texto_firma(firma)}")
            if not faltas:
                factor.puntaje, factor.archivo = factor.puntaje_maximo, cert.archivo
                factor.motivos = [
                    f"{integrante.nombre}: constancia del Ministerio de Trabajo del {cert.expedicion:%d/%m/%Y} "
                    f"(vigente {cert.vigencia_meses} meses), {cert.con_discapacidad} con discapacidad en una planta de {total} "
                    f"(mínimo {minimo_con_discapacidad(total)}); Formato 8 firmado"
                ]
                return factor
        factor.motivos.append(f"{integrante.nombre}: {'; '.join(dict.fromkeys(faltas))}")
    return factor


_FORMATO12 = re.compile(r"FORMATO\s*12\s*[AB]?\b.{0,60}(?:EMPRENDIMIENTO|MUJER)", re.S)
_DECLARACION_ACCIONES_RE = re.compile(r"MAS\s+DEL\s+CINCUENTA\s+POR\s+CIENTO\s*\(?\s*50\s*%?\s*\)?\s*DE\s+LAS\s+ACCIONES")
_CUADRO_RE = re.compile(
    r"SIGUIENTE\s+CUADRO(.{0,2500}?)(?:DE\s+IGUAL\s+(?:MANERA|FORMA)|MANIFESTAMOS|EN\s+CONSTANCIA|ATENTAMENTE|CODIGO\s+CCE|FIRMA)", re.S
)
_DESDE_RE = re.compile(r"SE\s+HA\s+MANTENIDO\s+A\s+PARTIR\s+DE\s*:?\s*(\d{1,2})\s*(?:DE\s+([A-Z]+)\s+DE|[-/](\d{1,2})[-/])\s*(\d{4})")


def _mantenida_desde(texto: str):
    from datetime import date

    m = _DESDE_RE.search(texto)
    if not m:
        return None
    mes = _MESES.get(m.group(2) or "") or (int(m.group(3)) if m.group(3) else None)
    try:
        return date(int(m.group(4)), mes, int(m.group(1))) if mes else None
    except ValueError:
        return None


def emprendimiento_mujeres(pdfs: dict[str, bytes], integrantes: list[IntegranteTecnico], plural: bool, fecha_cierre=None) -> Factor:
    """4.6: se otorga solo con la opción de acciones (Formato 12A, más del 50 %
    de las acciones de mujeres durante el último año): el integrante tiene al
    menos 10 % de participación, el cuadro de accionistas suma más del 50 %,
    y el formato está firmado y lo suscriben el representante legal y el
    revisor fiscal o contador. Las otras opciones (cargos directivos, 12B)
    piden revisar más soportes: van a revisión."""
    from motor.procesamiento.pdf_utils import extraer_texto

    factor = Factor("mujeres", "4.6 Emprendimientos y empresas de mujeres (Formato 12)", 0.25)
    encontrados = 0
    for archivo, _ in _buscar_formato(pdfs, _FORMATO12, re.compile(r"FORMA\w*\s*12|MUJER|EMPRENDIMIENTO")):
        encontrados += 1
        texto = normalizar(" ".join(extraer_texto(pdfs[archivo], max_paginas=4).split()))
        factor.archivo = factor.archivo or archivo
        integrante = next((i for i in integrantes if _es_de(i, "", texto)), None)
        nombre = integrante.nombre if integrante else "integrante no identificado"
        if re.search(r"FORMATO\s*12\s*B|ESTABLECIMIENTO\s+DE\s+COMERCIO", texto):
            factor.motivos.append(f"{nombre}: Formato 12B (persona natural con establecimiento de comercio); verifica la cédula y la matrícula")
            continue
        if not _DECLARACION_ACCIONES_RE.search(texto.replace("(50%)", "(50 %)")):
            factor.motivos.append(
                f"{nombre}: Formato 12A por cargos directivos; verifica documentos de identidad, contratos o certificación "
                "laboral y aportes a seguridad social del último año de quienes ocupan esos cargos"
            )
            continue
        faltas = []
        if integrante is None:
            faltas.append("no se identificó a qué integrante corresponde")
        elif plural and (integrante.participacion is None or integrante.participacion < 0.10 - 1e-9):
            faltas.append("el integrante no tiene al menos el 10 % de participación")
        cuadro = _CUADRO_RE.search(texto)
        porcentajes = [float(v.replace(",", ".")) for v in re.findall(r"(\d{1,3}(?:[.,]\d+)?)\s*%", cuadro.group(1))] if cuadro else []
        suma = sum(porcentajes)
        if not porcentajes:
            faltas.append("no se leyeron los porcentajes del cuadro de accionistas")
        elif not (50 < suma <= 100.5):
            faltas.append(f"el cuadro de accionistas suma {suma:g} % (se exige más del 50 %)")
        desde = _mantenida_desde(texto)
        if desde and fecha_cierre and _mas_meses(desde, 12) > fecha_cierre:
            faltas.append(f"la mayoría de mujeres se mantiene desde el {desde:%d/%m/%Y}: menos de un año antes del cierre")
        if not re.search(r"REVISOR\s+FISCAL|CONTADOR", texto) or "REPRESENTANTE LEGAL" not in texto:
            faltas.append("no lo suscriben el representante legal y el revisor fiscal o contador")
        firma = firmado(pdfs[archivo])
        if firma is not True:
            faltas.append(f"firma: {_texto_firma(firma)}")
        if not faltas:
            factor.puntaje, factor.archivo = factor.puntaje_maximo, archivo
            factor.motivos = [f"{nombre}: Formato 12A, mujeres con {suma:g} % de las acciones durante el último año; firmado"]
            return factor
        factor.motivos.append(f"{nombre}: {'; '.join(faltas)}")
    if not encontrados:
        factor.motivos.append("no se encontró el Formato 12")
    return factor
