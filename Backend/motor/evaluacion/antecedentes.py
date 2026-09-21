from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from dateutil.relativedelta import relativedelta

from motor import criterios
from motor.procesamiento.memoria_proponente import memo_por_pdfs
from motor.evaluacion.formato1 import (
    _clave_cache,
    _guardar_cache,
    _leer_cache,
    _norm,
    _nombres_coinciden,
    obtener_tipo_proponente,
)
from motor.evaluacion.camara_comercio import Empresa, empresas_con_certificado
from motor.evaluacion.proponente_plural import (
    Integrante,
    datos_formato2,
    integrantes_formato2,
    obtener_personas_a_verificar,
)
from motor.integrations.drive import download_file_bytes, get_file_metadata
from motor.esquemas.proceso import PersonaAntecedente, ProcesoDocumentoBase, Proponente, ResultadoRequisito
from motor.procesamiento.pdf_utils import abrir_pdf, texto_pagina
from motor.procesamiento.zip_utils import extraer_pdfs, pdfs_con_aportados

# Se leen al menos estas páginas de cada PDF buscando algún certificado de
# antecedentes. Si aparece alguno, se sigue leyendo hasta
# PAGINAS_MAXIMAS_FUSIONADOS: hay proponentes que fusionan todos sus
# certificados en un solo PDF (se confirmó uno real de 10 páginas con
# Contraloría, Procuraduría, Policía, RNMC y REDAM de la empresa y del
# representante, con el de Policía en la página 5). Los PDF sin ningún
# certificado en sus primeras páginas (RUP, experiencia...) se dejan de leer
# ahí, para no recorrer documentos de cientos de páginas.
# Marca del formulario de preguntas del SECOP II (archivos CO1_OTLCNTNR_*),
# que se detectaba como certificado RNMC por mencionar el registro.
FORMULARIO_SECOP_RE = re.compile(r"THIS QUESTION REQUIRES|ESTA PREGUNTA REQUIERE ANEXAR|SOBRE UNICO")

PAGINAS_MINIMAS = 4
# Paquetes de antecedentes con portada, índice y cédula antes del primer
# certificado (se vio uno real de 22 páginas con Contraloría en la página 6):
# si el archivo o sus primeras páginas hablan de antecedentes, se sigue leyendo.
PISTA_PAQUETE_ANTECEDENTES_RE = re.compile(r"ANTECEDENTE|CONTRALOR|PROCURADUR|POLICIA|JUDICIAL|RNMC|REDAM")
# Se midió un paquete real con el RNMC en la página 21, que el límite anterior
# de 20 dejaba fuera: solo aplica a archivos que ya se ven como paquete de
# antecedentes, así que no obliga a recorrer documentos largos de otro tipo.
PAGINAS_MAXIMAS_FUSIONADOS = 32


def _solo_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


# Identidad = (nombre-o-None, cédula-o-None), extraídos del texto normalizado
# del propio certificado. Cada entidad tiene su propia redacción, así que no
# hay un único regex universal — pero la orquestación (buscar, emparejar con
# las personas requeridas, decidir cumple/no cumple) sí es compartida.
ExtractorIdentidad = Callable[[str], tuple[str | None, str | None]]


@dataclass(frozen=True)
class AntecedenteConfig:
    requisito: int
    entidad: str  # nombre para mensajes, ej. "REDAM", "Contraloría"
    titulo_re: re.Pattern[str]
    pistas_nombre: tuple[str, ...]
    frase_cumple_re: re.Pattern[str]
    extraer_identidad: ExtractorIdentidad


@dataclass(frozen=True)
class Certificado:
    archivo: str
    texto: str  # texto de la(s) página(s) de ESTE certificado, no del PDF entero
    requisitos: frozenset[int]  # a qué entidad(es) corresponde, por título


def _configs() -> tuple[AntecedenteConfig, ...]:
    return (CONFIG_REDAM, CONFIG_CONTRALORIA, CONFIG_PROCURADURIA, CONFIG_POLICIA, CONFIG_RNMC)


@memo_por_pdfs
def leer_certificados(pdfs: dict[str, bytes]) -> list[Certificado]:
    """Recorre los PDF del proponente página por página y separa cada
    certificado de antecedentes que encuentre (de cualquier entidad), aunque
    vengan varios fusionados en un mismo archivo. Un certificado empieza en
    una página con título reconocible y puede seguir en la página siguiente
    si esta no trae título propio (ej. la frase de "sin novedades" o el pie
    quedan en la hoja 2)."""
    certificados: list[Certificado] = []
    for nombre, contenido in pdfs.items():
        try:
            with abrir_pdf(contenido) as pdf:
                actual: tuple[frozenset[int], list[str]] | None = None
                encontro_alguno = False
                es_paquete_antecedentes = bool(PISTA_PAQUETE_ANTECEDENTES_RE.search(_norm(nombre.rsplit("/", 1)[-1])))
                for indice, page in enumerate(pdf.pages[:PAGINAS_MAXIMAS_FUSIONADOS]):
                    if indice >= PAGINAS_MINIMAS and not encontro_alguno and not es_paquete_antecedentes:
                        break
                    texto = texto_pagina(page)
                    page.flush_cache()
                    texto_norm = _norm(texto)
                    if indice < PAGINAS_MINIMAS and PISTA_PAQUETE_ANTECEDENTES_RE.search(texto_norm):
                        es_paquete_antecedentes = True
                    requisitos = frozenset(c.requisito for c in _configs() if c.titulo_re.search(texto_norm))
                    if requisitos and FORMULARIO_SECOP_RE.search(texto_norm):
                        # El formulario de preguntas del SECOP cita los
                        # nombres de todos los certificados; no es uno.
                        requisitos = frozenset()
                    if requisitos:
                        if actual is not None:
                            certificados.append(Certificado(nombre, "\n".join(actual[1]), actual[0]))
                        actual = (requisitos, [texto])
                        encontro_alguno = True
                    elif actual is not None and len(actual[1]) == 1:
                        actual[1].append(texto)
                    elif actual is not None:
                        certificados.append(Certificado(nombre, "\n".join(actual[1]), actual[0]))
                        actual = None
                if actual is not None:
                    certificados.append(Certificado(nombre, "\n".join(actual[1]), actual[0]))
        except Exception:  # noqa: BLE001
            continue
    return certificados


def _cedulas_por_nombre(certificados: list[Certificado]) -> list[tuple[str, str]]:
    """Pares (nombre, cédula) de los certificados que traen ambos datos
    (Procuraduría, Policía, RNMC). Sirven para emparejar los certificados
    que solo traen cédula (REDAM, Contraloría) cuando la carta de
    presentación no declara la cédula del representante."""
    pares = []
    for certificado in certificados:
        texto_norm = _norm(certificado.texto)
        for config in _configs():
            if config.requisito not in certificado.requisitos:
                continue
            nombre, cedula = config.extraer_identidad(texto_norm)
            if nombre and cedula:
                pares.append((nombre, cedula))
    return pares


# Criterio del abogado: a la persona jurídica (por su NIT) solo se le exigen
# Contraloría y Procuraduría; Policía, RNMC y REDAM son de personas naturales.
REQUISITOS_PERSONA_JURIDICA = frozenset({14, 15})

# El certificado de una empresa se reconoce por el NIT, no por el nombre:
# Procuraduría: "LA PERSONA EBR INGENIERIA S.A.S. IDENTIFICADO(A) CON NIT NUMERO 9015001145"
# Contraloría:  "...DE LA PERSONA JURIDICA... NO. IDENTIFICACION 9018507983"
# A veces sin espacio: "IDENTIFICADO(A)CON NIT NUMERO 8909340411".
_NIT_PROCURADURIA_RE = re.compile(r"IDENTIFICAD[OA]\(A\)\s*CON\s+NIT\s+N[UÚ]MERO\s*(\d[\d.\-]*)")
_NIT_CONTRALORIA_RE = re.compile(r"PERSONA JURIDICA.{0,400}?NO\.?\s*IDENTIFICACION\s*(\d[\d.\-]*)", re.DOTALL)


def _nit_del_certificado(requisito: int, texto_norm: str) -> str | None:
    """Los 9 dígitos del NIT si el certificado es de una persona jurídica."""
    patron = {15: _NIT_PROCURADURIA_RE, 14: _NIT_CONTRALORIA_RE}.get(requisito)
    match = patron.search(texto_norm) if patron else None
    return _solo_digitos(match.group(1))[:9] if match else None


# A cada integrante persona natural de un consorcio se le piden todos menos el
# REDAM; el REDAM solo si además es representante o suplente del consorcio, y
# en ese caso ya está entre las personas a verificar.
REQUISITOS_INTEGRANTE_NATURAL = frozenset({14, 15, 16, 17})


def _puede_tener_integrantes_naturales(pdfs: dict[str, bytes], codigo_proceso: str | None) -> bool:
    """Solo vale la pena leer los integrantes (con el modelo local) si el
    Formato 2 tiene más integrantes que empresas con certificado de existencia,
    o si no se pudieron contar."""
    formato2 = datos_formato2(pdfs, codigo_proceso)
    integrantes = len(formato2[1].porcentajes) if formato2 else 0
    return integrantes == 0 or integrantes > len(empresas_con_certificado(pdfs))


def _con_integrantes_naturales(personas: list[tuple], integrantes: list[Integrante]) -> list[tuple]:
    todas = list(personas)
    for integrante in integrantes:
        if not integrante.persona_natural:
            continue
        cedula = _solo_digitos(integrante.identificacion) if integrante.identificacion else None
        repetida = any(
            _nombres_coinciden(integrante.nombre, p[0]) or (cedula and p[1] and _solo_digitos(p[1]) == cedula)
            for p in todas
        )
        if not repetida:
            todas.append((integrante.nombre, integrante.identificacion, "integrante"))
    return todas


def _mas_reciente(certificados: list[tuple[str, str]]) -> tuple[str, str] | None:
    """Entre varios certificados de la misma persona o empresa, el expedido más
    tarde: el evaluador pudo aportar uno nuevo porque el de la oferta ya no
    servía."""
    from motor.evaluacion.personalizado import fecha_expedicion

    if not certificados:
        return None
    if len(certificados) == 1:
        return certificados[0]
    con_fecha = [(fecha_expedicion(_norm(texto)), archivo, texto) for archivo, texto in certificados]
    fechadas = [c for c in con_fecha if c[0] is not None]
    if not fechadas:
        return certificados[0]
    fecha, archivo, texto = max(fechadas, key=lambda c: c[0])
    return archivo, texto


def _nit_texto(empresa: Empresa) -> str:
    return f" (NIT {empresa.nit})" if empresa.nit else ""


def _con_integrantes_juridicos(empresas: list[Empresa], integrantes: list[Integrante]) -> list[Empresa]:
    """Los integrantes jurídicos del Formato 2 que no aportaron certificado de
    existencia también deben tener sus antecedentes: si solo se miraran los
    certificados aportados, a esa empresa no se le exigiría nada y el
    requisito podría darse por cumplido sin su certificado.

    Cada integrante se empareja primero con el certificado de su NIT o de su
    razón social; los que quedan sueltos se emparejan con los certificados que
    no dicen a nombre de quién están (así el integrante toma ese nombre en vez
    de aparecer dos veces), y solo lo que sobra se agrega como empresa nueva."""
    juridicos = [i for i in integrantes if not i.persona_natural]
    if not juridicos:
        return list(empresas)
    todas = list(empresas)
    sueltos = []
    for integrante in juridicos:
        nit = _solo_digitos(integrante.identificacion or "")[:9]
        if any((nit and e.nit == nit) or _nombres_coinciden(integrante.nombre, e.razon_social or "") for e in todas):
            continue
        sueltos.append((integrante, nit))
    for indice, empresa in enumerate(todas):
        if empresa.razon_social or not sueltos:
            continue
        integrante, _ = sueltos.pop(0)
        todas[indice] = Empresa(integrante.nombre, empresa.nit)
    return todas + [Empresa(integrante.nombre, nit) for integrante, nit in sueltos]


def _con_roles(personas: list[tuple[str, str | None]], tipo_proponente: str | None) -> list[tuple[str, str | None, str]]:
    """Del consorcio: el primero es su representante y el segundo, el suplente.
    De una persona natural que se presenta sola, ella misma."""
    if tipo_proponente in ("consorcio", "union_temporal"):
        roles = ["representante_legal", "suplente"]
        return [(n, c, roles[i] if i < 2 else "integrante") for i, (n, c) in enumerate(personas)]
    rol = "proponente" if tipo_proponente == "persona_natural" else "representante_legal"
    return [(n, c, rol) for n, c in personas]


# REDAM: "SE EXPIDE EN BOGOTA EL 28/04/2026 … VALIDA HASTA: 27/07/2026". El
# certificado dice hasta cuándo vale; sin esa fecha, vale tres meses.
_REDAM_VALIDA_HASTA_RE = re.compile(r"VALID[OA]\s+HASTA\s*:?\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})")
MESES_VALIDEZ_REDAM = 3


def problema_de_vigencia(config: AntecedenteConfig, texto_norm: str, fecha_cierre: date | None) -> str | None:
    """Por qué el certificado no sirve por su fecha (None si sirve o no se
    revisa). El REDAM debe estar vigente al cierre; los demás, expedidos a
    lo sumo `antecedentes_meses` antes del cierre (la entidad además puede
    consultarlos en línea)."""
    from motor.evaluacion.personalizado import fecha_expedicion

    if fecha_cierre is None:
        return None
    expedicion = fecha_expedicion(texto_norm)
    if config.requisito == 5:
        m = _REDAM_VALIDA_HASTA_RE.search(texto_norm)
        try:
            hasta = date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None
        except ValueError:
            hasta = None
        if hasta is None and expedicion is not None:
            hasta = expedicion + relativedelta(months=MESES_VALIDEZ_REDAM)
        if hasta is None:
            return "no se pudo leer hasta cuándo es válido"
        if hasta < fecha_cierre:
            return f"venció el {hasta.strftime('%d/%m/%Y')}, antes del cierre ({fecha_cierre.strftime('%d/%m/%Y')})"
        return None
    meses = criterios.valor("antecedentes_meses")
    if not meses:
        return None
    if expedicion is None:
        return "no se pudo leer su fecha de expedición"
    if expedicion < fecha_cierre - relativedelta(months=meses):
        return (
            f"fue expedido el {expedicion.strftime('%d/%m/%Y')}, más de {meses} mes{'es' if meses > 1 else ''} antes del "
            f"cierre ({fecha_cierre.strftime('%d/%m/%Y')}) — la entidad puede consultarlo en línea"
        )
    return None


class _Certificado:
    """Par (archivo, texto) del certificado elegido para una empresa."""

    def __init__(self, archivo: str, texto: str) -> None:
        self.archivo = archivo
        self.texto = texto


class ResultadoEvaluacionAntecedente:
    def __init__(
        self, cumple: bool, motivo: str | None, archivo: str | None, personas: list[PersonaAntecedente] | None = None
    ) -> None:
        self.cumple = cumple
        self.motivo = motivo
        self.archivo = archivo
        # El resultado de cada persona y empresa, para la tabla de antecedentes.
        self.personas = personas or []


def evaluar_antecedente(
    pdfs: dict[str, bytes],
    config: AntecedenteConfig,
    personas: list[tuple],
    empresas: list[Empresa] | None = None,
    plural: bool = False,
    fecha_cierre: date | None = None,
) -> ResultadoEvaluacionAntecedente:
    """Verifica que se haya aportado el certificado de `config.entidad` para
    cada persona en `personas` —(nombre, cédula) o (nombre, cédula, rol)— y,
    si el requisito aplica a personas jurídicas, para cada empresa en
    `empresas` (por su NIT). Ninguno puede reportar novedades. Además del
    resultado global, devuelve el de cada una."""
    empresas = list(empresas or []) if config.requisito in REQUISITOS_PERSONA_JURIDICA else []
    if not personas and not empresas:
        return ResultadoEvaluacionAntecedente(
            cumple=False,
            motivo=(
                "No se pudo identificar al representante legal (ni al del consorcio/unión temporal) para "
                f"verificar su {config.entidad} — revisa manualmente."
            ),
            archivo=None,
        )

    certificados = leer_certificados(pdfs)
    candidatos = [c for c in certificados if config.requisito in c.requisitos]
    identidades = [(c.archivo, c.texto, *config.extraer_identidad(_norm(c.texto))) for c in candidatos]
    pares_conocidos = _cedulas_por_nombre(certificados)

    faltantes: list[str] = []
    resultados: list[PersonaAntecedente] = []
    archivo_evaluado: str | None = None
    for persona in personas:
        nombre_persona, cedula_persona = persona[0], persona[1]
        rol = persona[2] if len(persona) > 2 else "representante_legal"
        if not cedula_persona:
            cedula_persona = next(
                (cedula for nombre, cedula in pares_conocidos if _nombres_coinciden(nombre, nombre_persona)), None
            )
        cedula_persona_digitos = _solo_digitos(cedula_persona) if cedula_persona else None
        suyos = []
        for archivo, texto, nombre_doc, cedula_doc in identidades:
            if cedula_persona_digitos and cedula_doc:
                # Con ambas cédulas manda la cédula: dos personas pueden
                # compartir nombre y apellido, no número de documento.
                coincide = _solo_digitos(cedula_doc) == cedula_persona_digitos
            else:
                coincide = nombre_doc is not None and _nombres_coinciden(nombre_doc, nombre_persona)
            if coincide:
                suyos.append((archivo, texto))
        # Si la persona tiene varios certificados (el de la oferta y el que el
        # evaluador consultó después), manda el más reciente.
        encontrado = _mas_reciente(suyos)
        base = {"nombre": nombre_persona, "documento": cedula_persona_digitos, "tipo": "natural", "rol": rol}
        if encontrado is None:
            faltantes.append(f"no se aportó el certificado de {config.entidad} de {nombre_persona}")
            resultados.append(PersonaAntecedente(**base, estado="falta"))
            continue
        archivo, texto = encontrado
        if archivo_evaluado is None:
            archivo_evaluado = archivo
        if not config.frase_cumple_re.search(_norm(texto)):
            faltantes.append(
                f"el certificado de {config.entidad} de {nombre_persona} no confirma que esté libre de novedades"
            )
            resultados.append(PersonaAntecedente(**base, estado="con_novedad", archivo=archivo))
        elif vencido := problema_de_vigencia(config, _norm(texto), fecha_cierre):
            faltantes.append(f"el certificado de {config.entidad} de {nombre_persona} {vencido}")
            resultados.append(PersonaAntecedente(**base, estado="vencido", archivo=archivo))
        else:
            resultados.append(PersonaAntecedente(**base, estado="cumple", archivo=archivo))

    for empresa in empresas:
        base = {"nombre": empresa.nombre, "documento": empresa.nit or None, "tipo": "juridica",
                "rol": "integrante" if plural else "proponente"}
        # Sin NIT (integrante del Formato 2 que no aportó certificado de
        # existencia) no se puede emparejar el certificado: queda para revisar.
        suyo_par = _mas_reciente([
            (c.archivo, c.texto)
            for c in candidatos
            if empresa.nit and _nit_del_certificado(config.requisito, _norm(c.texto)) == empresa.nit
        ])
        suyo = _Certificado(*suyo_par) if suyo_par else None
        if suyo is None:
            faltantes.append(f"no se aportó el certificado de {config.entidad} de {empresa.nombre}{_nit_texto(empresa)}")
            resultados.append(PersonaAntecedente(**base, estado="falta"))
            continue
        if archivo_evaluado is None:
            archivo_evaluado = suyo.archivo
        if not config.frase_cumple_re.search(_norm(suyo.texto)):
            faltantes.append(
                f"el certificado de {config.entidad} de {empresa.nombre}{_nit_texto(empresa)} no confirma que esté "
                "libre de novedades"
            )
            resultados.append(PersonaAntecedente(**base, estado="con_novedad", archivo=suyo.archivo))
        elif vencido := problema_de_vigencia(config, _norm(suyo.texto), fecha_cierre):
            faltantes.append(f"el certificado de {config.entidad} de {empresa.nombre}{_nit_texto(empresa)} {vencido}")
            resultados.append(PersonaAntecedente(**base, estado="vencido", archivo=suyo.archivo))
        else:
            resultados.append(PersonaAntecedente(**base, estado="cumple", archivo=suyo.archivo))

    if not candidatos:
        # Mismo motivo de siempre: no hay ningún certificado de esta entidad en la oferta.
        motivo = f"No se encontró el certificado de {config.entidad} por título dentro de los documentos del proponente."
        return ResultadoEvaluacionAntecedente(cumple=False, motivo=motivo, archivo=None, personas=resultados)
    cumple = not faltantes
    motivo = "; ".join(faltantes) if faltantes else None
    return ResultadoEvaluacionAntecedente(cumple=cumple, motivo=motivo, archivo=archivo_evaluado, personas=resultados)


def _evaluar_proponente_antecedente(
    config: AntecedenteConfig, proponente: Proponente, proceso: ProcesoDocumentoBase
) -> ResultadoRequisito:
    """Lógica compartida por los 5 evaluadores de antecedentes. No se expone
    directamente como evaluador de un requisito: cada uno de
    `evaluar_proponente_requisitoN` de más abajo es una función de módulo
    (no un closure) que la llama con su propio config, porque
    ProcessPoolExecutor necesita poder *picklear* la función por su nombre
    calificado — un closure generado dinámicamente no se puede serializar y
    revienta con PicklingError al enviarlo al pool de procesos."""
    base = {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
        "requisito": config.requisito,
    }

    try:
        metadata = get_file_metadata(proponente.drive_file_id)
    except Exception:  # noqa: BLE001
        metadata = None

    md5 = metadata.get("md5Checksum") if metadata else None
    clave_cache = _clave_cache(proponente, proceso, md5, requisito=config.requisito)
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

    pdfs = pdfs_con_aportados(zip_bytes, proponente)
    if not pdfs:
        return finalizar(
            ResultadoRequisito(**base, error="El archivo del proponente no contiene PDFs legibles (¿zip dañado?)."),
            cacheable=False,
        )

    tipo_proponente = obtener_tipo_proponente(pdfs)
    personas = _con_roles(obtener_personas_a_verificar(pdfs, tipo_proponente, proceso.codigo_proceso), tipo_proponente)
    if (
        tipo_proponente in ("consorcio", "union_temporal")
        and config.requisito in REQUISITOS_INTEGRANTE_NATURAL
        and _puede_tener_integrantes_naturales(pdfs, proceso.codigo_proceso)
    ):
        personas = _con_integrantes_naturales(personas, integrantes_formato2(pdfs, proceso.codigo_proceso))
    empresas = (
        empresas_con_certificado(pdfs)
        if config.requisito in REQUISITOS_PERSONA_JURIDICA and tipo_proponente != "persona_natural"
        else []
    )
    if empresas is not None and config.requisito in REQUISITOS_PERSONA_JURIDICA and tipo_proponente in ("consorcio", "union_temporal"):
        empresas = _con_integrantes_juridicos(empresas, integrantes_formato2(pdfs, proceso.codigo_proceso))
    resultado = evaluar_antecedente(
        pdfs, config, personas, empresas, plural=tipo_proponente in ("consorcio", "union_temporal"),
        fecha_cierre=proceso.fecha_cierre,
    )

    # La fecha de expedición de cada cédula que venga en la oferta queda en la
    # ficha de la persona: la piden las páginas de consulta (RNMC, Policía).
    from motor.evaluacion.identidad import fecha_de_la_persona

    for persona in resultado.personas:
        if persona.tipo == "natural" and persona.fecha_expedicion_documento is None:
            persona.fecha_expedicion_documento = fecha_de_la_persona(pdfs, persona.nombre, persona.documento)

    return finalizar(
        ResultadoRequisito(
            **base,
            cumple=resultado.cumple,
            motivo=resultado.motivo,
            archivo_evaluado=resultado.archivo,
            archivos_disponibles=sorted(pdfs.keys()) if resultado.archivo is None else [],
            tipo_proponente=tipo_proponente,
            personas_antecedente=resultado.personas,
        ),
        cacheable=True,
    )


# ---------------------------------------------------------------------------
# Configuraciones por entidad, confirmadas contra documentos reales de varios
# proponentes de este proceso (no contra el Segundo Informe).
# ---------------------------------------------------------------------------

# REDAM (Requisito 5): "...con número de identificación CC 12345678 NO SE
# ENCUENTRA INSCRITO EN EL REGISTRO DE DEUDORES ALIMENTARIOS MOROSOS" — solo
# trae cédula, no nombre.
_CEDULA_CC_RE = re.compile(r"\bCC\s*(\d[\d.]*)")


def _identidad_redam(texto_norm: str) -> tuple[str | None, str | None]:
    match = _CEDULA_CC_RE.search(texto_norm)
    return None, match.group(1) if match else None


CONFIG_REDAM = AntecedenteConfig(
    requisito=5,
    entidad="REDAM (Registro de Deudores Alimentarios Morosos)",
    titulo_re=re.compile(r"DEUDORES ALIMENTARIOS MOROSOS"),
    pistas_nombre=("redam",),
    frase_cumple_re=re.compile(r"NO SE ENCUENTRA INSCRITO EN EL REGISTRO DE DEUDORES ALIMENTARIOS MOROSOS"),
    extraer_identidad=_identidad_redam,
)

# Contraloría (Requisito 14): "...No. Identificación 11223344...NO SE
# ENCUENTRA REPORTADO COMO RESPONSABLE FISCAL" — igual que REDAM, solo cédula.
_CEDULA_IDENTIFICACION_RE = re.compile(r"NO\.?\s*IDENTIFICACION\s*(\d[\d.]*)")


def _identidad_contraloria(texto_norm: str) -> tuple[str | None, str | None]:
    match = _CEDULA_IDENTIFICACION_RE.search(texto_norm)
    return None, match.group(1) if match else None


CONFIG_CONTRALORIA = AntecedenteConfig(
    requisito=14,
    entidad="Contraloría (Boletín de Responsables Fiscales)",
    titulo_re=re.compile(r"BOLETIN DE RESPONSABLES FISCALES|CONTRALORIA DELEGADA PARA RESPONSABILIDAD FISCAL"),
    pistas_nombre=("contraloria",),
    frase_cumple_re=re.compile(r"NO SE ENCUENTRA REPORTADO COMO RESPONSABLE FISCAL"),
    extraer_identidad=_identidad_contraloria,
)

# Procuraduría (Requisito 15): "...el(la) señor(a) MARIA FERNANDA GOMEZ
# PEREZ identificado(a) con Cédula de ciudadanía número 12345678...NO
# REGISTRA SANCIONES NI INHABILIDADES VIGENTES" — trae nombre y cédula, pero
# solo cuando el certificado es de una PERSONA (el de la empresa dice
# "la persona <razón social> identificado(a) con NIT número...", que este
# patrón ignora a propósito al exigir "CEDULA DE CIUDADANIA").
_PROCURADURIA_PERSONA_RE = re.compile(
    r"SE[ÑN]OR\(A\)\s+([A-ZÑ][A-ZÑ .]+?)\s+IDENTIFICAD[OA]\(A\)\s+CON C[EÉ]DULA DE CIUDADAN[IÍ]A N[UÚ]MERO\s*(\d[\d.]*)"
)


def _identidad_procuraduria(texto_norm: str) -> tuple[str | None, str | None]:
    match = _PROCURADURIA_PERSONA_RE.search(texto_norm)
    if not match:
        return None, None
    nombre = re.sub(r"\s+", " ", match.group(1)).strip(" .")
    return nombre or None, match.group(2)


CONFIG_PROCURADURIA = AntecedenteConfig(
    requisito=15,
    entidad="Procuraduría (Registro de Sanciones e Inhabilidades - SIRI)",
    titulo_re=re.compile(r"REGISTRO DE SANCIONES E INHABILIDADES|PROCURADURIA GENERAL DE LA NACION"),
    pistas_nombre=("procuradur",),
    frase_cumple_re=re.compile(r"NO REGISTRA SANCIONES NI INHABILIDADES VIGENTES"),
    extraer_identidad=_identidad_procuraduria,
)

# Policía Nacional — antecedentes judiciales (Requisito 16): "...el ciudadano
# identificado con: Cédula de Ciudadanía Nº 12345678 Apellidos y Nombres:
# GOMEZ PEREZ MARIA FERNANDA NO TIENE ASUNTOS PENDIENTES CON LAS
# AUTORIDADES JUDICIALES". En escaneados el OCR cambia "Nº" por "N*" u otro
# signo, así que se acepta cualquier signo corto después de la N.
_POLICIA_JUDICIAL_RE = re.compile(
    r"CEDULA DE CIUDADAN[IÍ]A N(?:[^\d\s]{0,3}|9\.)\s*(\d[\d.]*)\s*APELLIDOS Y NOMBRES:?\s*([A-ZÑ][A-ZÑ .]+?)\s+NO TIENE"
)


def _identidad_policia_judicial(texto_norm: str) -> tuple[str | None, str | None]:
    match = _POLICIA_JUDICIAL_RE.search(texto_norm)
    if not match:
        return None, None
    nombre = re.sub(r"\s+", " ", match.group(2)).strip(" .")
    return nombre or None, match.group(1)


CONFIG_POLICIA = AntecedenteConfig(
    requisito=16,
    entidad="Policía Nacional (antecedentes judiciales)",
    titulo_re=re.compile(r"CONSULTA EN LINEA DE ANTECEDENTES PENALES Y REQUERIMIENTOS JUDICIALES"),
    pistas_nombre=("policia", "antecedentes penales", "antecedentes judiciales"),
    frase_cumple_re=re.compile(r"NO TIENE ASUNTOS PENDIENTES CON LAS AUTORIDADES JUDICIALES"),
    extraer_identidad=_identidad_policia_judicial,
)

# RNMC — multas / medidas correctivas (Requisito 17): "...el ciudadano con
# Cédula de Ciudadanía Nº. 12345678 y Nombre: MARIA FERNANDA GOMEZ PEREZ.
# NO TIENE MEDIDAS CORRECTIVAS PENDIENTES POR CUMPLIR" (otra versión omite
# "y Nombre:": "...Nº. 87654321 ANA LUCIA TORRES DIAZ. NO TIENE...") — el de la empresa
# dice "...para - NIT, sin digito de verificación: N. ...", que este patrón
# ignora a propósito al exigir "CEDULA DE CIUDADANIA".
# El RNMC tiene dos redacciones para persona natural: con el nombre junto a la
# cédula, y otra que solo trae la cédula ("EL CIUDADANO CON CEDULA DE
# CIUDADANIA NO. 12345 . NO TIENE MEDIDAS..."). En la segunda el nombre no
# aparece, pero la cédula sola basta para saber de quién es el certificado.
_RNMC_PERSONA_RE = re.compile(
    r"CIUDADANO CON C[EÉ]DULA DE CIUDADAN[IÍ]A N(?:[^\d\s]{0,3}|9\.)\s*(\d[\d.]*)\s*\.?\s*"
    r"(?:Y NOMBRE:?\s*([A-ZÑ][A-ZÑ .]+?)\.|([A-ZÑ][A-ZÑ .]+?)\.\s*NO TIENE)?"
)


def _identidad_rnmc(texto_norm: str) -> tuple[str | None, str | None]:
    match = _RNMC_PERSONA_RE.search(texto_norm)
    if not match:
        return None, None
    crudo = match.group(2) or match.group(3)
    nombre = re.sub(r"\s+", " ", crudo).strip(" .") if crudo else None
    return nombre or None, match.group(1)


CONFIG_RNMC = AntecedenteConfig(
    requisito=17,
    entidad="RNMC (Registro Nacional de Medidas Correctivas)",
    titulo_re=re.compile(r"SISTEMA REGISTRO NACIONAL DE MEDIDAS CORRECTIVAS|REGISTRO NACIONAL DE MEDIDAS CORRECTIVAS\s*RNMC"),
    pistas_nombre=("rnmc", "medidas correctivas"),
    frase_cumple_re=re.compile(r"NO TIENE MEDIDAS CORRECTIVAS PENDIENTES POR CUMPLIR"),
    extraer_identidad=_identidad_rnmc,
)

def evaluar_proponente_requisito5(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_antecedente(CONFIG_REDAM, proponente, proceso)


def evaluar_proponente_requisito14(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_antecedente(CONFIG_CONTRALORIA, proponente, proceso)


def evaluar_proponente_requisito15(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_antecedente(CONFIG_PROCURADURIA, proponente, proceso)


def evaluar_proponente_requisito16(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_antecedente(CONFIG_POLICIA, proponente, proceso)


def evaluar_proponente_requisito17(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    return _evaluar_proponente_antecedente(CONFIG_RNMC, proponente, proceso)
