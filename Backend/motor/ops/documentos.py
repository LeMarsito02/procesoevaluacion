"""Lista de verificación de los documentos que aporta el contratista de una
prestación de servicios.

Cada documento exigido se busca entre los PDF por lo que dice (y, si viene
escaneado y no se lee, por el nombre del archivo). De cada uno se revisa que
esté y que sea de la persona; los antecedentes usan la misma verificación de
la evaluación jurídica (que no reporten novedades y su fecha). La lista que
viene aquí es la del ICCU; cada entidad puede tener la suya.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from dateutil.relativedelta import relativedelta

from motor.evaluacion import antecedentes
from motor.ops.tiempo import fecha_de
from motor.ops.matricula import ES_CERTIFICADO_RE as ES_CERTIFICADO_MATRICULA_RE
from motor.ops.matricula import leer_matricula
from motor.ops.titulos import ES_TITULO_RE
from motor.procesamiento.pdf_utils import paginas_de_texto
from motor.tecnica.rup import normalizar

CUMPLE = "cumple"
FALTA = "falta"
REVISION = "revision"
NO_CUMPLE = "no_cumple"
NO_APLICA = "no_aplica"

# Páginas que se leen de cada archivo para saber qué documento es.
_PAGINAS_PARA_RECONOCER = 2


@dataclass(frozen=True)
class DocumentoExigido:
    clave: str
    nombre: str
    # Lo que dice el documento (texto normalizado de sus primeras páginas).
    contenido: re.Pattern[str] | None = None
    # Nombre del archivo, para los que llegan escaneados y no se leen.
    archivo: re.Pattern[str] | None = None
    # Número con el que la entidad pide el documento en su lista: los
    # contratistas nombran los archivos «7. Cédula», «14. Certificaciones»…
    numero: int | None = None
    # Debe nombrar a la persona o traer su cédula.
    nominal: bool = True
    # Verificación de antecedentes de la evaluación jurídica.
    antecedente: antecedentes.AntecedenteConfig | None = None
    # Frase que debe traer para cumplir (consultas en línea).
    frase_cumple: re.Pattern[str] | None = None
    # Solo se exige a hombres menores de 50 años.
    solo_si_exige_libreta: bool = False


def _re(patron: str) -> re.Pattern[str]:
    return re.compile(patron, re.S)


# Lista del ICCU, con su numeración. El orden importa cuando dos documentos se
# parecen: cada archivo se queda con el primero que reconoce.
DOCUMENTOS_ICCU: tuple[DocumentoExigido, ...] = (
    DocumentoExigido("disciplinarios", "Antecedentes disciplinarios (Procuraduría)", None, _re(r"DISCIPLINARIO|PROCURADUR"), 1,
                     antecedente=antecedentes.CONFIG_PROCURADURIA),
    DocumentoExigido("fiscales", "Antecedentes fiscales (Contraloría)", None, _re(r"FISCAL|CONTRALOR"), 2, antecedente=antecedentes.CONFIG_CONTRALORIA),
    DocumentoExigido("judiciales", "Antecedentes judiciales (Policía)", None, _re(r"JUDICIAL"), 3, antecedente=antecedentes.CONFIG_POLICIA),
    DocumentoExigido("medidas_correctivas", "Medidas correctivas (RNMC)", None, _re(r"MEDIDAS\s+CORRECTIVAS|RNMC"), 4, antecedente=antecedentes.CONFIG_RNMC),
    DocumentoExigido(
        "delitos_sexuales", "Consulta de inhabilidades por delitos sexuales",
        _re(r"INHABILIDADES\s+DE\s+QUIENES\s+HAYAN\s+SIDO\s+CONDENADOS\s+POR\s+DELITOS\s+SEXUALES"),
        _re(r"DELITOS\s+SEXUALES|CONSULTA\s+DE\s+INHABILIDADES"), 5, frase_cumple=_re(r"NO\s+REGISTRA\s+INHABILIDAD"),
    ),
    DocumentoExigido("redam", "Registro de deudores alimentarios morosos (REDAM)", None, _re(r"REDAM|ALIMENTARIOS"), 6, antecedente=antecedentes.CONFIG_REDAM),
    DocumentoExigido("cedula", "Cédula de ciudadanía", _re(r"CEDULA\s*DE\s*CIUDADANIA.{0,400}FECHA\s+DE\s+NACIMIENTO"), _re(r"\bCEDULA\b"), 7, nominal=False),
    # Antes de la libreta militar: el formato de hoja de vida también la nombra.
    DocumentoExigido(
        "hoja_de_vida_sigep", "Hoja de vida de la función pública", _re(r"FORMATO\s+UNICO.{0,60}HOJA\s+DE\s+VIDA"),
        _re(r"HOJA\s+DE\s+VIDA.{0,40}(?:SIGEP|DAFP|DATP|FUNCION\s+PUBLICA|COMPLETA|UNICA)"), 12, nominal=False,
    ),
    DocumentoExigido(
        "libreta_militar", "Libreta militar o constancia de su trámite",
        _re(r"DEFINICION\s+DE\s+SU\s+SITUACION\s+MILITAR|COMANDO\s+DE\s+RECLUTAMIENTO|TARJETA\s+DE\s+RESERVISTA"),
        _re(r"LIBRETA|MILITAR"), 8, solo_si_exige_libreta=True,
    ),
    DocumentoExigido("rut", "Registro Único Tributario (RUT)", _re(r"REGISTRO\s+UNICO\s+TRIBUTARIO"), _re(r"\bRUT\b|UNICO\s+TRIBUTARIO"), 9, nominal=False),
    # La declaración de bienes y rentas y el registro de conflictos de interés
    # son un mismo punto de la lista; a veces llegan en dos archivos.
    DocumentoExigido(
        "bienes_y_rentas", "Declaración de bienes y rentas y registro de conflictos de interés",
        _re(r"DECLARACION\s+(?:JURAMENTADA\s+)?DE\s+BIENES\s+Y\s+RENTAS|REGISTRO\s+DE\s+CONFLICTOS?\s+DE\s+INTERES"),
        _re(r"BIENES|CONFLICTO"), 18, nominal=False,
    ),
    DocumentoExigido("pension", "Afiliación a pensión", _re(r"FONDOS?\s+DE\s+PENSIONES|COLPENSIONES|ADMINISTRADORA\s+COLOMBIANA\s+DE\s+PENSIONES"),
                     _re(r"PENSION"), 11),
    DocumentoExigido("salud", "Afiliación a salud", _re(r"AFILIA\w+.{0,80}\b(?:EPS|POS|SALUD)\b|\bEPS\b.{0,300}AFILIAD|REGIMEN\s+CONTRIBUTIVO"),
                     _re(r"\bEPS\b|SALUD(?!\s+OCUPACIONAL)"), 10),
    DocumentoExigido("vigencia_matricula", "Certificado de vigencia y antecedentes de la matrícula profesional", ES_CERTIFICADO_MATRICULA_RE,
                     _re(r"ANTECEDENTES\s+DISCIPLINARIOS\s+(?:DE\s+LA\s+)?(?:TARJETA|MATRICULA|REGISTRO)|CONALTEL|COPNIA|CPNAA|CONALPE"), 16),
    DocumentoExigido("tarjeta_profesional", "Tarjeta o matrícula profesional", _re(r"MATRICULA\s+PROFESIONAL|TARJETA\s+PROFESIONAL"),
                     _re(r"TARJETA|MATRICULA|REGISTRO\s+PROFESIONAL"), 15, nominal=False),
    DocumentoExigido("titulos", "Títulos académicos", ES_TITULO_RE,
                     _re(r"DIPLOMA|TITULO|ACTA\s+DE\s+GRADO|FORMACION\s+ACADEMICA|CERTIFICADOS?\s+PROFESIONAL"), 19, nominal=False),
    DocumentoExigido("certificacion_bancaria", "Certificación bancaria", _re(r"CUENTA\s+(?:DE\s+)?(?:AHORROS?|CORRIENTE)"), _re(r"BANC|DAVIVIENDA"), 20),
    DocumentoExigido("lista_restrictiva", "Certificación de listas restrictivas", _re(r"LISTAS?\s+RESTRICTIVAS?"), _re(r"RESTRICTIVA|LAVADO"), 22),
    DocumentoExigido("suscripcion_contratos", "Declaración de contratos suscritos con entidades públicas",
                     _re(r"DECLARACION\s+DE\s+SUSCRIPCION\s+DE|CONTRATOS\s+(?:VIGENTES\s+)?SUSCRITOS\s+CON"), _re(r"SUSCRIPCION|CONTRATOS"), 23),
    DocumentoExigido("datos_personales", "Datos personales y autorización de tratamiento", _re(r"TRATAMIENTO\s+DE\s+DATOS"), _re(r"DATOS\s*PERSONALES"), 27),
    DocumentoExigido("examen_ocupacional", "Examen de salud ocupacional",
                     _re(r"APTITUD\s+(?:LABORAL|MEDICA)|EXAMEN\s+(?:MEDICO\s+)?(?:PRE)?\s*OCUPACIONAL|CONCEPTO\s+(?:MEDICO\s+)?DE\s+APTITUD"),
                     _re(r"OCUPACIONAL|EXAMEN\s+MEDICO"), 25),
    DocumentoExigido("inhabilidades", "Declaración de inhabilidades e incompatibilidades", _re(r"INHABILIDAD(?:ES)?\s+E\s+INCOMPATIBILIDAD"),
                     _re(r"INHABILIDAD|DECLARACION\s+JURAMENTADA"), 21),
    DocumentoExigido("propuesta", "Propuesta o carta de presentación", _re(r"\bPROPUESTA\b|CARTA\s+DE\s+PRESENTACION|PRESENTACION\s+DE\s+(?:LA\s+)?OFERTA"),
                     _re(r"PROPUESTA|CARTA|OFERTA"), 17, nominal=False),
    DocumentoExigido("constancia_sigep", "Constancia de publicación de la hoja de vida en SIGEP II", _re(r"\bS[IE]GEP\b"),
                     _re(r"S[IE]GEP|PUBLICACION\s+DE\s+LA\s+HOJA"), 24, nominal=False),
    DocumentoExigido("constancia_secop", "Constancia de registro en SECOP II", _re(r"SECOP\s*II|SECOP\.GOV\.CO"), _re(r"SECOP"), 26, nominal=False),
    DocumentoExigido(
        "certificaciones_laborales", "Certificaciones de experiencia",
        _re(r"\bCERTIFICA\b.{0,700}(?:CONTRATO|VINCULAD|HISTORIA\s+LABORAL|LABORO|PRESTO\s+SUS\s+SERVICIOS)"),
        _re(r"CERTIFICACION(?:ES)?\s+(?:DE\s+EXPERIENCIA\s+)?LABORAL|EXPERIENCIA"), 14, nominal=False,
    ),
    DocumentoExigido("hoja_de_vida", "Hoja de vida", _re(r"PERFIL\s+PROFESIONAL|HOJA\s+DE\s+VIDA|CURRICULUM"), _re(r"\bHV\b|HOJA\s+DE\s+VIDA"), 13, nominal=False),
)


@dataclass
class ResultadoDocumento:
    clave: str
    nombre: str
    estado: str
    motivo: str = ""
    archivo: str | None = None
    fecha: date | None = None
    # Otros archivos que son este mismo documento (certificaciones sueltas, un
    # punto de la lista entregado en dos partes).
    adicionales: list[str] = field(default_factory=list)


def _es_de_la_persona(texto_norm: str, nombre: str, cedula: str | None) -> bool:
    """Trae su cédula o su nombre. El nombre se da por visto con la mitad de
    sus palabras (al menos dos): en cartas y diplomas falta un nombre o se
    abrevia un apellido."""
    digitos = re.sub(r"\D", "", texto_norm)
    if cedula and len(solo := re.sub(r"\D", "", cedula)) >= 5 and solo in digitos:
        return True
    palabras = {p for p in normalizar(nombre).split() if len(p) > 2}
    presentes = sum(1 for p in palabras if re.search(rf"\b{re.escape(p)}\b", texto_norm))
    return presentes >= 2 and presentes * 2 >= len(palabras)


def _nombre_de_archivo(ruta: str) -> str:
    return normalizar(ruta.rsplit("/", 1)[-1].rsplit(".pdf", 1)[0]).replace("_", " ")


_NUMERO_DE_ARCHIVO_RE = re.compile(r"^\s*(\d{1,2})(?:\.\d)?(?=\D|$)")


def numero_de_archivo(ruta: str) -> int | None:
    m = _NUMERO_DE_ARCHIVO_RE.match(ruta.rsplit("/", 1)[-1])
    return int(m.group(1)) if m else None


@dataclass
class Clasificacion:
    asignados: dict[str, str] = field(default_factory=dict)  # clave → archivo
    # Reconocidos solo por el número del archivo, sin que su contenido lo confirme.
    por_numero: set[str] = field(default_factory=set)
    adicionales: dict[str, list[str]] = field(default_factory=dict)
    sin_reconocer: list[str] = field(default_factory=list)


def clasificar(
    textos: dict[str, str], exigidos: tuple[DocumentoExigido, ...] = DOCUMENTOS_ICCU, ya_usados: dict[str, str] | None = None,
) -> Clasificacion:
    """Qué archivo corresponde a cada documento exigido. `textos` es el texto
    normalizado de las primeras páginas de cada archivo; `ya_usados`, los que
    reconoció la verificación de antecedentes (clave → archivo).

    Se va de lo más seguro a lo menos: contenido y número a la vez; solo
    contenido; nombre del archivo y número; solo nombre; y, al final, solo el
    número de la lista (queda para que una persona lo confirme).
    """
    c = Clasificacion(asignados=dict(ya_usados or {}))
    libres = {a: t for a, t in textos.items() if a not in set(c.asignados.values())}

    def por_contenido(doc: DocumentoExigido, archivo: str) -> bool:
        return bool(doc.contenido and doc.contenido.search(libres[archivo]))

    def por_nombre(doc: DocumentoExigido, archivo: str) -> bool:
        return bool(doc.archivo and doc.archivo.search(_nombre_de_archivo(archivo)))

    def por_numero(doc: DocumentoExigido, archivo: str) -> bool:
        return doc.numero is not None and numero_de_archivo(archivo) == doc.numero

    fases = (
        lambda d, a: por_contenido(d, a) and por_numero(d, a),
        lambda d, a: por_nombre(d, a) and por_numero(d, a),
        por_contenido,
        por_nombre,
        por_numero,
    )
    for n, coincide in enumerate(fases):
        for archivo in list(libres):
            for doc in exigidos:
                if doc.clave not in c.asignados and coincide(doc, archivo):
                    c.asignados[doc.clave] = archivo
                    if n == len(fases) - 1:
                        c.por_numero.add(doc.clave)
                    del libres[archivo]
                    break
    # Lo que sobró y es otro archivo de un documento ya reconocido.
    por_clave = {d.clave: d for d in exigidos}
    for archivo in list(libres):
        for clave in c.asignados:
            doc = por_clave[clave]
            if (por_contenido(doc, archivo) or por_nombre(doc, archivo)) and (doc.numero is None or numero_de_archivo(archivo) in (None, doc.numero)):
                c.adicionales.setdefault(clave, []).append(archivo)
                del libres[archivo]
                break
    c.sin_reconocer = list(libres)
    return c


def leer_textos(pdfs: dict[str, bytes]) -> dict[str, str]:
    textos: dict[str, str] = {}
    for archivo, contenido in pdfs.items():
        try:
            textos[archivo] = normalizar("\n".join(paginas_de_texto(contenido, _PAGINAS_PARA_RECONOCER)))
        except Exception:  # noqa: BLE001
            textos[archivo] = ""
    return textos


def verificar_documentos(
    pdfs: dict[str, bytes], nombre: str, cedula: str | None, fecha_referencia: date | None = None,
    exige_libreta: bool | None = None, vigencia_meses: dict[str, int] | None = None,
    exigidos: tuple[DocumentoExigido, ...] = DOCUMENTOS_ICCU, textos: dict[str, str] | None = None,
) -> tuple[list[ResultadoDocumento], Clasificacion]:
    """La lista de verificación del contratista y cómo se repartieron los archivos.

    `fecha_referencia` es la fecha contra la que se mide la vigencia (la del
    estudio previo); `vigencia_meses` dice, por clave, cuántos meses antes de
    esa fecha puede haberse expedido un documento. `exige_libreta` en None
    significa que no se sabe si la persona es hombre menor de 50 años.
    """
    vigencia_meses = vigencia_meses or {}
    textos = leer_textos(pdfs) if textos is None else textos
    de_antecedentes = {d.clave: _antecedente(d, pdfs, nombre, cedula, fecha_referencia) for d in exigidos if d.antecedente}
    c = clasificar(textos, exigidos, {clave: r.archivo for clave, r in de_antecedentes.items() if r.archivo})

    resultados: list[ResultadoDocumento] = []
    for doc in exigidos:
        archivo = c.asignados.get(doc.clave)
        if doc.antecedente:
            resultado = de_antecedentes[doc.clave]
            if resultado.archivo is None and archivo:
                # El archivo está, pero no se pudo leer como certificado de esa entidad.
                resultado = ResultadoDocumento(doc.clave, doc.nombre, REVISION, "Está el archivo, pero no se pudo leer su contenido: revíselo.", archivo)
            resultados.append(resultado)
            continue
        if archivo is None:
            if doc.solo_si_exige_libreta and exige_libreta is False:
                resultados.append(ResultadoDocumento(doc.clave, doc.nombre, NO_APLICA, "Solo se exige a hombres menores de 50 años."))
            elif doc.solo_si_exige_libreta and exige_libreta is None:
                resultados.append(ResultadoDocumento(doc.clave, doc.nombre, REVISION, "No se encontró; se exige a hombres menores de 50 años."))
            else:
                resultados.append(ResultadoDocumento(doc.clave, doc.nombre, FALTA, "No se encontró entre los documentos."))
            continue
        texto = textos[archivo]
        resultado = ResultadoDocumento(doc.clave, doc.nombre, CUMPLE, archivo=archivo, adicionales=c.adicionales.get(doc.clave, []))
        if doc.clave in c.por_numero:
            resultado.estado, resultado.motivo = REVISION, "Se reconoció solo por el número del archivo: confirme que es este documento."
        elif doc.nominal and not _es_de_la_persona(texto, nombre, cedula):
            resultado.estado, resultado.motivo = REVISION, "No se pudo confirmar que el documento sea de la persona."
        elif doc.frase_cumple and not doc.frase_cumple.search(texto):
            resultado.estado, resultado.motivo = REVISION, "No se leyó la frase que confirma que no registra novedades."
        elif doc.clave == "vigencia_matricula" and (matricula := leer_matricula(texto)) and not matricula.sin_sanciones:
            resultado.estado, resultado.motivo = REVISION, "No se leyó que la persona esté libre de sanciones en su profesión."
        elif (meses := vigencia_meses.get(doc.clave)) and fecha_referencia:
            resultado.fecha = fecha_de(texto)
            if resultado.fecha is None:
                resultado.estado, resultado.motivo = REVISION, "No se pudo leer su fecha."
            elif resultado.fecha < fecha_referencia - relativedelta(months=meses):
                resultado.estado = NO_CUMPLE
                resultado.motivo = f"Es del {resultado.fecha:%d/%m/%Y}, más de {meses} meses antes del {fecha_referencia:%d/%m/%Y}."
        resultados.append(resultado)
    return resultados, c


def _antecedente(doc: DocumentoExigido, pdfs: dict[str, bytes], nombre: str, cedula: str | None, fecha_referencia: date | None) -> ResultadoDocumento:
    r = antecedentes.evaluar_antecedente(pdfs, doc.antecedente, [(nombre, cedula)], fecha_cierre=fecha_referencia)
    if r.cumple:
        return ResultadoDocumento(doc.clave, doc.nombre, CUMPLE, archivo=r.archivo)
    estado = r.personas[0].estado if r.personas else ""
    return ResultadoDocumento(doc.clave, doc.nombre, FALTA if estado == "falta" else REVISION, r.motivo or "", r.archivo)
