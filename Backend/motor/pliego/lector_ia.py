"""Lectura profunda del pliego con IA local: TODOS los requisitos
habilitantes jurídicos que el pliego exige, cada uno con su cita literal,
página, a quién aplica, qué documento lo acredita y sus condiciones.

El pliego es la fuente de la evaluación: aquí se entiende lo que pide, esté o
no preparado el motor para verificarlo. Luego `comparar` decide, requisito por
requisito, si lo verifica el motor (con los datos del pliego), si se arma una
verificación automática del documento o si queda para revisión.

Cómo se lee: el pliego completo se parte en sus secciones; las jurídicas (y
las generales que hablan de temas jurídicos) se mandan por trozos a un
modelo local (Ollama). Nada sale del servidor. El modelo, su contexto y el
tamaño de los trozos se configuran por entorno: en desarrollo `qwen3:4b` con
4096 tokens cabe en una GPU de 4 GB; en producción (L4 de 24 GB) se usa uno
mayor con trozos más grandes.

Todo lo que devuelve el modelo se valida contra el texto: una cita que no
aparece en el pliego se descarta (el modelo no puede inventar requisitos), y
se filtran causales de rechazo, obligaciones de ejecución y temas técnicos o
financieros.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections.abc import Callable

import requests
from pydantic import BaseModel, Field

from motor.pliego.lectura import Pagina, Seccion

URL = os.environ.get("LLM_URL", "http://localhost:11434")
MODELO = os.environ.get("PLIEGO_IA_MODELO", "qwen3:4b")
CONTEXTO = int(os.environ.get("PLIEGO_IA_CONTEXTO", "4096"))
TROZO = int(os.environ.get("PLIEGO_IA_TROZO", "3500"))
HABILITADO = os.environ.get("PLIEGO_IA_HABILITADO", "1") == "1"
# Cambia cuando cambia la forma de leer: las lecturas viejas se repiten.
VERSION = 3
TIEMPO_MAXIMO = float(os.environ.get("PLIEGO_IA_TIMEOUT", "600"))

INSTRUCCION = """Eres abogado experto en contratación estatal colombiana (Ley 80 de 1993, Decreto 1082 de 2015, documentos tipo de Colombia Compra Eficiente).
Recibes un fragmento de un pliego de condiciones. Extrae los requisitos habilitantes JURÍDICOS que el proponente debe acreditar con su OFERTA.

NO incluyas: requisitos técnicos, de experiencia, financieros, organizacionales ni de puntaje; causales de rechazo; obligaciones del contratista durante la ejecución; trámites de la entidad.

Responde SOLO un objeto JSON, sin texto adicional:
{"requisitos": [{
  "requisito": "qué se exige, en una frase",
  "documento": "documento con que se acredita (o null si es una condición sin documento)",
  "titulo_documento": ["frases con que suele titularse ese documento, ej. CERTIFICADO DE EXISTENCIA Y REPRESENTACION LEGAL"],
  "expide": "entidad que lo expide o null",
  "aplica_a": ["persona_natural" | "persona_juridica" | "plural" | "cada_integrante" | "extranjero" | "todos"],
  "vigencia_dias": número de días de antigüedad máxima o null,
  "vigencia_meses": número de meses de antigüedad máxima o null,
  "condiciones": ["otras condiciones: firmas, contenido que debe decir, valores"],
  "cita": "frase LITERAL corta copiada del fragmento"
}]}
Si el fragmento no trae requisitos jurídicos: {"requisitos": []}"""

APLICA_A = ("persona_natural", "persona_juridica", "plural", "cada_integrante", "extranjero", "todos")

# Secciones generales que igual se leen: hablan de temas jurídicos.
_TEMA_JURIDICO_RE = re.compile(
    r"EXISTENCIA|REPRESENTACION LEGAL|CAPACIDAD JURIDICA|PROPONENTE PLURAL|CONSORCIO|UNION TEMPORAL|RUP\b|REGISTRO UNICO"
    r"|ANTECEDENTES|INHABILIDAD|REDAM|SEGURIDAD SOCIAL|APORTES|GARANTIA DE SERIEDAD|APODERADO|EXTRANJER|APOSTILL"
    r"|CARTA DE PRESENTACION|AVAL|MATRICULA PROFESIONAL|DOCUMENTO DE IDENTIFICACION|MIPYME"
)
# Lo que el modelo a veces trae y no es un requisito habilitante de la oferta.
_NO_ES_REQUISITO_RE = re.compile(
    r"CAUSAL(?:ES)? DE RECHAZO|SERA RECHAZAD|SE RECHAZARA|NO PODRAN PARTICIPAR|DURANTE LA EJECUCION|EL CONTRATISTA DEBERA"
    r"|ADJUDICATARIO DEBERA|PARA LA SUSCRIPCION DEL CONTRATO|PARA EL PERFECCIONAMIENTO|LA ENTIDAD (?:DEBE|DEBERA|VERIFICARA|CONSULTARA)"
    r"|EXPERIENCIA|CAPACIDAD FINANCIERA|CAPACIDAD ORGANIZACIONAL|CAPACIDAD RESIDUAL|INDICADOR|PUNTAJE|PUNTOS|FACTOR DE CALIDAD"
    r"|OFERTA ECONOMICA|\bAIU\b|ADMINISTRACION, IMPREVISTOS|MANIFESTA\w* (?:DE |SU )?INTERES|SMMLV|VALORES CONVERTIDOS"
    r"|EMPRENDIMIENTO|EMPRESAS? DE MUJERES|DESEMPATE|ADJUDICATARIO|EL CONTRATISTA|CADA PAGO|FECHA (?:Y HORA )?DE CIERRE"
    r"|ENTREGUEN SU OFERTA|MISMOS INTEGRANTES|IDIOMA|TRADUCCION|CONVERTID"
    # Remisiones genéricas ("acreditar el cumplimiento de los requisitos
    # definidos en el anexo"): no dicen qué se exige.
    r"|^(?:EL PROPONENTE DEBE )?ACREDITAR EL CUMPLIMIENTO DE LOS REQUISITOS (?:DEFINIDOS|ESTABLECIDOS|SENALADOS|PREVISTOS)"
)
# Requisitos solo para proponentes extranjeros: no se le exigen a uno
# nacional; se muestran juntos como aclaración.
EXTRANJEROS_RE = re.compile(r"EXTRANJER|APOSTILL|LEGALIZ|CONSULAR|PASAPORTE|SIN DOMICILIO|SIN SUCURSAL|EXTERIOR")


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").upper())
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip()


def _palabras(texto: str) -> list[str]:
    return [w for w in re.findall(r"[A-Z0-9]{3,}", _norm(texto))]


class RequisitoPliego(BaseModel):
    id: str
    requisito: str
    documento: str | None = None
    titulo_documento: list[str] = Field(default_factory=list)
    expide: str | None = None
    aplica_a: list[str] = Field(default_factory=list)
    vigencia_dias: int | None = None
    vigencia_meses: int | None = None
    condiciones: list[str] = Field(default_factory=list)
    cita: str
    seccion: str
    pagina: int
    # Clave del catálogo del motor que lo verifica, o None (verificación del
    # documento armada desde el pliego, o revisión).
    verificacion: str | None = None


class Trozo(BaseModel):
    seccion: str
    titulo: str
    texto: str
    pagina: int


# Documentos jurídicos que una sección no jurídica puede exigir de paso
# ("D. Los proponentes obligados a estar inscritos en el RUP deben aportar
# certificado…" dentro de "3.1 GENERALIDADES").
_DOCUMENTO_JURIDICO_RE = re.compile(
    r"REGISTRO UNICO DE PROPONENTES|\bRUP\b|REDAM|DEUDORES ALIMENTARIOS|EXISTENCIA Y REPRESENTACION|GARANTIA DE SERIEDAD"
    r"|ANTECEDENTES (?:FISCALES|DISCIPLINARIOS|JUDICIALES)|SEGURIDAD SOCIAL|CARTA DE PRESENTACION"
)
_TITULO_NO_JURIDICO_RE = re.compile(
    r"EXPERIENCIA|FINANCIER|ORGANIZACIONAL|PUNTAJE|FACTOR|DESEMPATE|MIPYME|ECONOMICA|CALIDAD|CRITERIO|CIERRE|RETIRO|APERTURA"
)
LARGO_SECCION_DE_PASO = 6000


def _se_lee(s: Seccion, ambito: str) -> bool:
    titulo = _norm(s.titulo)
    if ambito == "juridica":
        return True
    if ambito == "general" and _TEMA_JURIDICO_RE.search(titulo):
        return True
    if ambito == "garantias":  # solo la de seriedad es habilitante
        return "SERIEDAD" in titulo
    return (ambito in ("general", "puntaje") and len(s.texto) <= LARGO_SECCION_DE_PASO
            and not _TITULO_NO_JURIDICO_RE.search(titulo) and bool(_DOCUMENTO_JURIDICO_RE.search(_norm(s.texto))))


def trozos(secciones: list[Seccion], ambitos: dict[str, str], largo: int = TROZO) -> list[Trozo]:
    """Los trozos que se leen: las secciones jurídicas completas y las
    generales cuyo título trata un tema jurídico (nunca las técnicas,
    financieras o de puntaje). Una sección larga se parte en trozos que se
    solapan un poco para no cortar un requisito a la mitad."""
    salida = []
    for s in secciones:
        if not _se_lee(s, ambitos.get(s.numero, "general")):
            continue
        texto = f"{s.numero} {s.titulo}\n{s.texto}".strip()
        paso = max(largo - 300, 500)
        for i in range(0, max(len(texto), 1), paso):
            parte = texto[i : i + largo]
            if len(parte.strip()) > 80:
                salida.append(Trozo(seccion=f"{s.numero} {s.titulo}".strip(), titulo=s.titulo, texto=parte, pagina=s.pagina))
            if i + largo >= len(texto):
                break
    return salida


def _preguntar(texto: str, modelo: str = MODELO) -> str:
    r = requests.post(
        f"{URL}/api/chat",
        timeout=TIEMPO_MAXIMO,
        json={
            "model": modelo,
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0, "num_ctx": CONTEXTO},
            "messages": [{"role": "system", "content": INSTRUCCION}, {"role": "user", "content": texto}],
        },
    )
    r.raise_for_status()
    return r.json()["message"]["content"]


def _cita_en(cita: str, texto: str) -> bool:
    """La cita está en el trozo (con tolerancia a espacios, tildes y alguna
    palabra distinta): el modelo no puede traer requisitos que no están."""
    palabras = _palabras(cita)
    if len(palabras) < 3:
        return False
    objetivo = set(_palabras(texto))
    return sum(w in objetivo for w in palabras) >= 0.8 * len(palabras)


def _entero(valor) -> int | None:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return None
    return n if 0 < n < 3650 else None


def _limpiar(crudo: dict, trozo: Trozo, pagina_de: Callable[[str, int], int]) -> RequisitoPliego | None:
    requisito = str(crudo.get("requisito") or "").strip()
    cita = str(crudo.get("cita") or "").strip()
    if len(requisito) < 8 or not _cita_en(cita, trozo.texto):
        return None
    if _NO_ES_REQUISITO_RE.search(_norm(requisito + " " + cita)):
        return None
    aplica = [a for a in (crudo.get("aplica_a") or []) if a in APLICA_A] or ["todos"]
    titulos = [str(t).strip() for t in (crudo.get("titulo_documento") or []) if isinstance(t, str) and len(t.strip()) >= 6]
    condiciones = [str(c).strip() for c in (crudo.get("condiciones") or []) if isinstance(c, str) and c.strip()]
    documento = crudo.get("documento")
    return RequisitoPliego(
        id=hashlib.sha1(_norm(requisito + (documento or "")).encode()).hexdigest()[:12],
        requisito=requisito[:300],
        documento=str(documento).strip()[:200] if documento else None,
        titulo_documento=titulos[:4],
        expide=str(crudo.get("expide")).strip()[:120] if crudo.get("expide") else None,
        aplica_a=aplica,
        vigencia_dias=_entero(crudo.get("vigencia_dias")),
        vigencia_meses=_entero(crudo.get("vigencia_meses")),
        condiciones=condiciones[:6],
        cita=cita[:400],
        seccion=trozo.seccion[:160],
        pagina=pagina_de(cita, trozo.pagina),
    )


def _clave(r: RequisitoPliego) -> set[str]:
    return set(_palabras(r.requisito + " " + (r.documento or "")))


def _sin_repetidos(requisitos: list[RequisitoPliego]) -> list[RequisitoPliego]:
    """Une los que dicen lo mismo (mismo requisito leído en dos trozos o
    repetido en el pliego): se queda con el más completo y suma condiciones."""
    unicos: list[RequisitoPliego] = []
    for r in requisitos:
        clave = _clave(r)
        for u in unicos:
            otra = _clave(u)
            if clave and otra and len(clave & otra) / len(clave | otra) >= 0.6:
                u.condiciones = list(dict.fromkeys(u.condiciones + r.condiciones))[:8]
                u.vigencia_dias = u.vigencia_dias or r.vigencia_dias
                u.vigencia_meses = u.vigencia_meses or r.vigencia_meses
                u.titulo_documento = list(dict.fromkeys(u.titulo_documento + r.titulo_documento))[:4]
                break
        else:
            unicos.append(r)
    return unicos


# "personas naturales o jurídicas nacionales o extranjeras" habla de todos.
_NACIONAL_O_EXTRANJERO_RE = re.compile(r"NACIONAL(?:ES)?\s+(?:O|Y|U)\s+EXTRANJER\w*|EXTRANJER\w*\s+(?:O|Y)\s+NACIONAL(?:ES)?")


def es_de_extranjeros(r: "RequisitoPliego") -> bool:
    texto = _NACIONAL_O_EXTRANJERO_RE.sub(" ", _norm(f"{r.requisito} {r.documento or ''} {r.cita}"))
    return "extranjero" in r.aplica_a or bool(EXTRANJEROS_RE.search(texto))


def leer(
    secciones: list[Seccion],
    ambitos: dict[str, str],
    paginas: list[Pagina],
    progreso: Callable[[int, int], None] | None = None,
    modelo: str = MODELO,
) -> list[RequisitoPliego]:
    """Todos los requisitos jurídicos del pliego según la IA, ya validados,
    filtrados, sin repetidos y con la verificación del motor que les
    corresponde (si la hay)."""
    from motor.pliego.catalogo import verificacion_de

    def pagina_de(cita: str, inicio: int) -> int:
        palabras = set(_palabras(cita))
        mejor, puntaje = inicio, 0
        for p in paginas:
            if p.numero < inicio:
                continue
            en = len(palabras & set(_palabras(p.texto)))
            if en > puntaje:
                mejor, puntaje = p.numero, en
            if puntaje >= 0.9 * len(palabras):
                break
        return mejor

    lista = trozos(secciones, ambitos)
    encontrados: list[RequisitoPliego] = []
    fallidos = 0
    for n, trozo in enumerate(lista, 1):
        try:
            crudo = _preguntar(f"{trozo.seccion}\n{trozo.texto}", modelo)
            m = re.search(r"\{.*\}", crudo, re.S)
            datos = json.loads(m.group(0)).get("requisitos") if m else []
        except requests.RequestException:
            fallidos += 1
            datos = []
        except (ValueError, AttributeError):
            datos = []
        for crudo_req in datos if isinstance(datos, list) else []:
            if isinstance(crudo_req, dict) and (r := _limpiar(crudo_req, trozo, pagina_de)) is not None:
                encontrados.append(r)
        if progreso:
            progreso(n, len(lista))
    # Si la IA no respondió en la mayoría de trozos, la lectura no sirve: un
    # "0 requisitos" haría creer que el pliego no exige nada.
    if lista and fallidos > len(lista) // 2:
        raise RuntimeError(f"La IA no respondió en {fallidos} de {len(lista)} partes del pliego")
    unicos = _sin_repetidos(encontrados)
    for r in unicos:
        r.verificacion = verificacion_de(r)
    return unicos


def disponible() -> bool:
    if not HABILITADO:
        return False
    try:
        return requests.get(f"{URL}/api/tags", timeout=5).ok
    except requests.RequestException:
        return False
