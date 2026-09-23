"""Los parámetros del proceso leídos del pliego con IA local.

Hasta ahora los parámetros técnicos y financieros salían de expresiones
regulares atadas a la redacción del documento tipo: cada pliego que cambiaba
una palabra ("ANTICIPO **O** PAGO ANTICIPADO", "N/A." en vez de "NO APLICA",
"72121400" en vez de "72 14 10") rompía una regla en silencio y el proceso
entero quedaba sin evaluar. Peor: una exigencia escrita libremente por la
entidad ("de edificaciones DECLARADAS COMO BIENES DE INTERÉS CULTURAL") no
la encuentra ninguna regla, porque no es una variante de formato sino un
requisito nuevo.

Aquí el pliego se lee como lo leería una persona: se le pregunta al modelo
local, sección por sección, qué exige el proceso, y **cada valor tiene que
venir con una cita literal que aparezca en el pliego**. Lo que el modelo no
pueda citar se descarta; nunca inventa un umbral.

La lectura no reemplaza a las reglas: las dos leen el mismo pliego y
`motor.pliego.fusion` las junta. Un valor que solo vio la IA queda marcado
como tal, y mientras una persona no lo confirme, lo que dependa de él no se
aprueba solo. Nada sale del servidor: el modelo es local (Ollama).
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable

import requests
from pydantic import BaseModel, Field

from motor.pliego.lectura import Seccion
from motor.pliego.lector_ia import URL, _cita_en, _norm, _palabras

MODELO = os.environ.get("PLIEGO_IA_MODELO", "qwen3:4b")
CONTEXTO = int(os.environ.get("PLIEGO_IA_CONTEXTO", "4096"))
TROZO = int(os.environ.get("PLIEGO_IA_TROZO", "3500"))
TIEMPO_MAXIMO = float(os.environ.get("PLIEGO_IA_TIMEOUT", "600"))
HABILITADO = os.environ.get("PLIEGO_PARAMETROS_IA", "1") == "1"
# Cambia cuando cambia la forma de leer: las lecturas viejas se repiten.
VERSION = 1


class Leido(BaseModel):
    """Un valor del pliego con el pedazo de texto del que salió."""

    valor: float | str | list[str] | None = None
    cita: str = ""
    seccion: str = ""


class ParametrosIA(BaseModel):
    """Lo que el pliego exige, en los términos del motor. Todo es opcional:
    lo que no se pudo leer se queda sin valor y va a revisión."""

    # Experiencia (por lote; la clave es el nombre del lote tal como lo
    # nombra el pliego, o "ÚNICO").
    experiencia_general: dict[str, Leido] = Field(default_factory=dict)
    experiencia_especifica: dict[str, Leido] = Field(default_factory=dict)
    condicion_objeto: dict[str, Leido] = Field(default_factory=dict)
    fraccion_un_contrato: dict[str, Leido] = Field(default_factory=dict)
    longitud_minima_km: dict[str, Leido] = Field(default_factory=dict)
    max_contratos: Leido | None = None
    clases_unspsc: Leido | None = None
    # Dinero y plazos.
    anticipo: Leido | None = None
    plazo_meses: dict[str, Leido] = Field(default_factory=dict)
    # Indicadores financieros.
    liquidez_min: Leido | None = None
    endeudamiento_max: Leido | None = None
    cobertura_min: Leido | None = None
    roa_min: Leido | None = None
    roe_min: Leido | None = None
    capital_trabajo_fraccion: Leido | None = None
    # Puntaje: clave del factor -> puntos (0 cuando el pliego dice que no aplica).
    puntajes: dict[str, Leido] = Field(default_factory=dict)
    # Secciones que se leyeron y las que el modelo no pudo responder.
    leidas: int = 0
    fallidas: int = 0


# --------------------------------------------------------------- preguntas

_COMUN = """Responde SOLO un objeto JSON, sin explicaciones.
Cada dato debe traer una "cita": una frase LITERAL copiada del fragmento donde aparece. Si el dato no está en el fragmento, NO lo incluyas: nunca lo deduzcas ni lo inventes.
Si el fragmento no trae ninguno de estos datos, responde {}."""

PREGUNTAS: dict[str, str] = {
    "experiencia": """Eres evaluador de procesos de obra pública en Colombia. Lee este fragmento del pliego y extrae los requisitos de EXPERIENCIA.
""" + _COMUN + """
{"lote": "número del lote al que aplica, o \"ÚNICO\" si el proceso no tiene lotes",
 "experiencia_general": "las actividades y el tipo de obra que deben haber ejecutado los contratos aportados",
 "cita_general": "frase literal de donde sale lo anterior",
 "experiencia_especifica": "la exigencia adicional que debe cumplir al menos uno de los contratos",
 "cita_especifica": "frase literal",
 "condicion_objeto": "SOLO la condición extra sobre QUÉ TIPO DE OBRA debe ser uno de los contratos, más allá de la experiencia general (ejemplo: \"declaradas como bienes de interés cultural\")",
 "cita_condicion": "frase literal",
 "porcentaje_un_contrato": número 0-100 del porcentaje del presupuesto oficial que debe alcanzar al menos un contrato,
 "cita_porcentaje": "frase literal",
 "longitud_minima_km": kilómetros mínimos intervenidos que debe acreditar,
 "cita_longitud": "frase literal",
 "maximo_contratos": número máximo de contratos que puede aportar el proponente,
 "cita_maximo": "frase literal"}""",
    "unspsc": """Eres evaluador de procesos de obra pública en Colombia. Lee este fragmento del pliego y extrae los códigos del clasificador de bienes y servicios (UNSPSC) en los que deben estar clasificados los contratos de experiencia.
""" + _COMUN + """
{"codigos": ["los códigos tal como aparecen escritos"], "cita": "frase literal"}""",
    "anticipo": """Eres evaluador de procesos de obra pública en Colombia. Lee este fragmento del pliego y di qué ANTICIPO entrega la entidad.
""" + _COMUN + """
{"anticipo_porcentaje": número 0-100 del valor del contrato que se entrega como anticipo, o 0 si el pliego dice expresamente que NO se entregará anticipo,
 "cita": "frase literal que habla del anticipo"}""",
    "plazo": """Eres evaluador de procesos de obra pública en Colombia. Lee este fragmento del pliego y di el PLAZO de ejecución del contrato.
""" + _COMUN + """
{"lote": "número del lote, o \"ÚNICO\"", "plazo_meses": número de meses del plazo de ejecución, "cita": "frase literal"}""",
    "financiera": """Eres evaluador financiero de procesos de obra pública en Colombia. Lee este fragmento del pliego y extrae los INDICADORES financieros exigidos.
""" + _COMUN + """
{"liquidez_minima": número, "cita_liquidez": "frase literal",
 "endeudamiento_maximo": número, "cita_endeudamiento": "frase literal",
 "cobertura_minima": número, "cita_cobertura": "frase literal",
 "rentabilidad_activo_minima": número, "cita_activo": "frase literal",
 "rentabilidad_patrimonio_minima": número, "cita_patrimonio": "frase literal",
 "porcentaje_capital_de_trabajo": número 0-100 del presupuesto menos el anticipo que se exige como capital de trabajo,
 "cita_capital": "frase literal"}
Los porcentajes como número entre 0 y 100 ("70%" -> 70) y las razones como vienen ("1,2" -> 1.2).""",
    "puntaje": """Eres evaluador de procesos de obra pública en Colombia. Lee este fragmento del pliego y extrae los PUNTOS que da cada factor de calificación.
""" + _COMUN + """
{"factores": [{
  "factor": uno de: "gerencia_proyectos" (programa de gerencia de proyectos), "maquinaria" (disponibilidad y condiciones funcionales de maquinaria), "plan_calidad" (plan de calidad), "criterios_ambientales" (criterios ambientales y sociales), "industria_nacional" (apoyo a la industria nacional / servicios nacionales), "discapacidad" (vinculación de personas con discapacidad), "mujeres" (emprendimientos y empresas de mujeres), "mipyme" (mipyme domiciliada en Colombia),
  "puntos": número total de puntos que otorga ese factor,
  "no_aplica": true si el pliego dice que ese factor NO APLICA o N/A,
  "cita": "frase literal que nombra el factor y dice sus puntos (o que no aplica)"}]}""",
}

# A qué secciones se le hace cada pregunta: se pregunta solo donde el dato
# puede estar. Un modelo pequeño al que se le pregunta por el anticipo en la
# sección de experiencia responde cualquier cosa; preguntando donde toca,
# acierta. Además así se leen ~25 fragmentos en vez de 49.
_DONDE_PREGUNTAR: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("experiencia", ("tecnica",), r"EXPERIENCIA"),
    ("unspsc", ("tecnica", "general"), r"CLASIFICAD|UNSPSC"),
    ("anticipo", ("general", "juridica", "garantias"), r"ANTICIPO|FORMA\s+DE\s+PAGO|PAGO\s+ANTICIPADO"),
    ("plazo", ("general",), r"OBJETO|PLAZO|PRESUPUESTO"),
    ("financiera", ("financiera",), r"."),
    ("puntaje", ("puntaje",), r"."),
)


class TrozoParametros(BaseModel):
    pregunta: str
    seccion: str
    texto: str


def trozos(secciones: list[Seccion], ambitos: dict[str, str], largo: int = TROZO) -> list[TrozoParametros]:
    """Los pedazos de pliego que se leen y con qué pregunta (ver
    `_DONDE_PREGUNTAR`). Una sección larga se parte en trozos que se solapan
    un poco para no cortar una frase a la mitad."""
    salida: list[TrozoParametros] = []
    for s in secciones:
        ambito = ambitos.get(s.numero, "general")
        titulo = _norm(f"{s.numero} {s.titulo}")
        preguntas = [p for p, validos, patron in _DONDE_PREGUNTAR
                     if ambito in validos and re.search(patron, titulo)]
        if not preguntas:
            continue
        texto = f"{s.numero} {s.titulo}\n{s.texto}".strip()
        if len(texto.strip()) <= 80:
            continue
        paso = max(largo - 300, 500)
        for i in range(0, max(len(texto), 1), paso):
            parte = texto[i: i + largo]
            if len(parte.strip()) > 80:
                for pregunta in preguntas:
                    salida.append(TrozoParametros(pregunta=pregunta, seccion=f"{s.numero} {s.titulo}".strip(), texto=parte))
            if i + largo >= len(texto):
                break
    return salida


def _preguntar(instruccion: str, texto: str, modelo: str = MODELO) -> dict:
    r = requests.post(
        f"{URL}/api/chat",
        timeout=TIEMPO_MAXIMO,
        json={
            "model": modelo,
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0, "num_ctx": CONTEXTO},
            "messages": [{"role": "system", "content": instruccion}, {"role": "user", "content": texto}],
        },
    )
    r.raise_for_status()
    contenido = r.json()["message"]["content"]
    datos = json.loads(contenido)
    return datos if isinstance(datos, dict) else {}


# --------------------------------------------------------------- validación
#
# Un modelo pequeño rellena campos con lo primero que encuentra: puso el "97"
# de un número de página como puntaje y un anticipo de 0 % citando una frase
# que no habla de anticipo. Que la cita exista en el pliego no basta, porque
# la cita puede ser de otra parte del mismo fragmento. Así que se exige, para
# cada dato:
#   1. que el valor esté escrito DENTRO de la cita,
#   2. que la cita hable de ese tema (trae una palabra del campo),
#   3. que un cero venga de una negación explícita, nunca de un silencio,
#   4. que la cita no sea una línea del índice ("4.3 INDUSTRIA NACIONAL 97").
# Lo que no pasa las cuatro, se descarta: es preferible no leer un parámetro
# (va a revisión) a leerlo mal (aprobaría o rechazaría por un dato falso).

# Las actividades con que un pliego de obra describe la experiencia general.
_ACTIVIDADES_OBRA = (r"CONSTRUC|MANTENI|MEJORA|REHABILIT|ADECU|AMPLI|REMODEL|PAVIMENT|RESTAUR|CONSERV"
                     r"|INSTAL|REPAR|RECONSTRUC|INTERVEN|REFORZA|REPOTENCI|OPTIMIZ|TERMINACION")
# Un umbral siempre viene comparado: "liquidez mayor o igual a 1,2", "≥ 0,70".
_COMPARADOR_RE = re.compile(r">=|<=|>|<|≥|≤|MAYOR|MENOR|IGUAL|MINIM|MAXIM|SUPERIOR|INFERIOR|AL\s+MENOS|POR\s+LO\s+MENOS")
_INDICE_RE = re.compile(r"(?:\.\s*){4,}|\b\d{1,3}(?:\s+\d(?:\.\d+){1,3}\s+\d{1,3}){2,}")
_NEGACION_RE = re.compile(r"\bNO\s+(?:SE\s+)?(?:ENTREGARA|OTORGARA|HABRA|CONTEMPLA|APLICA|SE\s+EXIGE|SE\s+OTORGA)"
                          r"|\bNO\s+APLICA\b|\bN\s*/\s*A\b|\bSIN\s+ANTICIPO\b")
# Palabras que la cita debe traer para que el dato se acepte.
_TEMA: dict[str, str] = {
    "anticipo": r"ANTICIPO|PAGO\s+ANTICIPADO",
    "plazo": r"PLAZO|MES(?:ES)?\b|DURACION",
    "puntaje": r"PUNTO|PUNTAJE|ASIGNARA|OTORGARA|NO\s+APLICA|N\s*/\s*A",
    # La experiencia general es la lista de actividades de obra; la
    # específica y la condición de objeto siempre dicen "por lo menos uno".
    "experiencia_general": _ACTIVIDADES_OBRA,
    "experiencia_especifica": r"POR\s+LO\s+MENOS\s+UN|AL\s+MENOS\s+UN|UNO\s*\(\s*1\s*\)",
    "condicion_objeto": r"DECLARAD|DEBE\s+CORRESPONDER|DEBE\s+CONTEMPLAR|CORRESPONDER\s+O\s+CONTEMPLAR",
    "liquidez": r"LIQUIDEZ",
    "endeudamiento": r"ENDEUDAMIENTO",
    "cobertura": r"COBERTURA",
    "roa": r"RENTABILIDAD\s+(?:DEL|SOBRE\s+EL)?\s*ACTIVO",
    "roe": r"RENTABILIDAD\s+(?:DEL|SOBRE\s+EL)?\s*PATRIMONIO",
    "fraccion": r"PRESUPUESTO\s+OFICIAL|VALOR\s+DEL\s+PRESUPUESTO|%|POR\s+CIENTO",
    "longitud": r"LONGITUD|KILOMETRO|\bKM\b",
    "maximo": r"MAXIMO|CONTRATOS",
    "unspsc": r"CLASIFICAD|UNSPSC|CODIGO",
    "indicador": r"LIQUIDEZ|ENDEUDAMIENTO|COBERTURA|RENTABILIDAD|INDICADOR|CAPITAL\s+DE\s+TRABAJO|PATRIMONIO|ACTIVO",
}


def _numero(valor) -> float | None:
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _en_la_cita(numero: float, cita: str) -> bool:
    """El número está escrito en la cita (como entero, con decimales o con
    cero delante: "3", "03", "0,33", "33%")."""
    texto = _norm(cita).replace(",", ".")
    formas = {f"{numero:g}", f"{numero:.1f}", f"{numero:.2f}"}
    if numero == int(numero):
        formas |= {str(int(numero)), f"{int(numero):02d}"}
    return any(re.search(rf"(?<![\d.]){re.escape(f)}(?![\d])", texto) for f in formas)


def _cita_util(cita, trozo_texto: str, tema: str) -> str | None:
    """La cita sirve si está en el fragmento, habla del tema y no es una
    línea del índice."""
    texto = _texto(cita)
    if not texto or not _cita_en(texto, trozo_texto):
        return None
    norm = _norm(texto)
    if _INDICE_RE.search(norm) or not re.search(_TEMA[tema], norm):
        return None
    return texto


def _valor_numerico(valor, cita: str, tema: str, minimo: float, maximo: float, *, cero_si_niega: bool = False) -> float | None:
    """Un número del pliego: tiene que estar en la cita y dentro de rango. El
    cero solo se acepta cuando la cita niega expresamente ("no se entregará
    anticipo", "N/A")."""
    n = _numero(valor)
    if n is None or not minimo <= n <= maximo:
        return None
    if n == 0:
        return 0.0 if cero_si_niega and _NEGACION_RE.search(_norm(cita)) else None
    return n if _en_la_cita(n, cita) else None


def _fraccion(valor, cita: str, tema: str, *, cero_si_niega: bool = False) -> float | None:
    """Un porcentaje del pliego como fracción: 70 -> 0.70."""
    n = _valor_numerico(valor, cita, tema, 0.0, 100.0, cero_si_niega=cero_si_niega)
    return None if n is None else n / 100


def _texto(valor) -> str | None:
    texto = str(valor).strip() if valor is not None else ""
    if texto.lower() in ("", "null", "none", "n/a", "na", "no aplica", "-", "ninguno"):
        return None
    return texto


def _texto_de_la_cita(valor, cita: str, largo_minimo: int = 12) -> str | None:
    """Un texto que el modelo copió del pliego: sus palabras tienen que estar
    en la cita (si no, lo resumió o se lo inventó)."""
    texto = _texto(valor)
    if not texto or len(texto) < largo_minimo:
        return None
    palabras = _palabras(texto)
    if not palabras:
        return None
    en_cita = set(_palabras(cita))
    return texto if sum(w in en_cita for w in palabras) >= 0.7 * len(palabras) else None


def _lote(valor) -> str | None:
    """El nombre del lote como lo escribe el pliego, normalizado a "LOTE n" o
    "ÚNICO". Lo que no se parezca a un lote se descarta."""
    texto = _norm(_texto(valor) or "")
    if not texto or texto in ("UNICO", "UNICO LOTE", "LOTE UNICO", "N/A", "TODOS"):
        return "ÚNICO"
    if m := re.fullmatch(r"(?:LOTE\s*)?(?:N[O°º]\.?\s*)?(\d{1,2})", texto):
        return f"LOTE {int(m.group(1))}"
    if m := re.match(r"LOTE\s*(\d{1,2})\b", texto):
        return f"LOTE {int(m.group(1))}"
    return None


def _guardar(destino: dict[str, Leido], clave: str | None, valor, cita: str, seccion: str) -> None:
    """El primer valor leído manda: los trozos van en el orden del pliego y
    la primera vez que algo se dice suele ser donde se define."""
    if clave is None or valor is None or clave in destino:
        return
    destino[clave] = Leido(valor=valor, cita=cita[:300], seccion=seccion[:160])


def _poner(p: "ParametrosIA", campo: str, valor, cita: str, seccion: str) -> None:
    if valor is not None and getattr(p, campo) is None:
        setattr(p, campo, Leido(valor=valor, cita=cita[:300], seccion=seccion[:160]))


def _aplicar(datos: dict, trozo: TrozoParametros, p: "ParametrosIA") -> None:
    """Pasa a los parámetros lo que respondió el modelo. Cada dato se valida
    contra SU cita: el valor tiene que estar escrito en ella, la cita tiene
    que hablar del tema y estar en el fragmento, un cero exige una negación
    expresa y las líneas del índice se descartan."""
    def cita(clave: str, tema: str) -> str | None:
        return _cita_util(datos.get(clave), trozo.texto, tema)

    if trozo.pregunta == "experiencia":
        lote = _lote(datos.get("lote"))
        if lote is None:
            return
        for clave, destino, tema, nombre_cita in (
            ("experiencia_general", p.experiencia_general, "experiencia_general", "cita_general"),
            ("experiencia_especifica", p.experiencia_especifica, "experiencia_especifica", "cita_especifica"),
            ("condicion_objeto", p.condicion_objeto, "condicion_objeto", "cita_condicion"),
        ):
            if c := cita(nombre_cita, tema):
                valor = _texto_de_la_cita(datos.get(clave), c)
                if clave == "experiencia_general" and valor is not None:
                    # La lista de actividades, no una frase de trámite ("la
                    # información consignada en el RUP…").
                    if len(set(re.findall(_ACTIVIDADES_OBRA, _norm(valor)))) < 2:
                        valor = None
                _guardar(destino, lote, valor, c, trozo.seccion)
        if c := cita("cita_porcentaje", "fraccion"):
            _guardar(p.fraccion_un_contrato, lote, _fraccion(datos.get("porcentaje_un_contrato"), c, "fraccion"),
                     c, trozo.seccion)
        if c := cita("cita_longitud", "longitud"):
            _guardar(p.longitud_minima_km, lote,
                     _valor_numerico(datos.get("longitud_minima_km"), c, "longitud", 0.01, 999.0), c, trozo.seccion)
        if c := cita("cita_maximo", "maximo"):
            _poner(p, "max_contratos", _valor_numerico(datos.get("maximo_contratos"), c, "maximo", 1, 20),
                   c, trozo.seccion)
    elif trozo.pregunta == "unspsc":
        if c := cita("cita", "unspsc"):
            codigos = [re.sub(r"\D", "", str(x)) for x in (datos.get("codigos") or []) if str(x).strip()]
            # Solo los que están escritos en el pliego y son clase (no familia
            # "72120000" ni segmento "72000000").
            pegado = re.sub(r"\s+", "", _norm(trozo.texto))
            clases = sorted({x[:6] for x in codigos if len(x) in (6, 8) and x[4:6] != "00" and x in pegado})
            _poner(p, "clases_unspsc", clases or None, c, trozo.seccion)
    elif trozo.pregunta == "anticipo":
        if c := cita("cita", "anticipo"):
            _poner(p, "anticipo", _fraccion(datos.get("anticipo_porcentaje"), c, "anticipo", cero_si_niega=True),
                   c, trozo.seccion)
    elif trozo.pregunta == "plazo":
        lote = _lote(datos.get("lote"))
        if (c := cita("cita", "plazo")) and lote is not None:
            _guardar(p.plazo_meses, lote, _valor_numerico(datos.get("plazo_meses"), c, "plazo", 0.5, 120),
                     c, trozo.seccion)
    elif trozo.pregunta == "financiera":
        for campo, clave, nombre_cita, tema, tope, porcentaje in (
            ("liquidez_min", "liquidez_minima", "cita_liquidez", "liquidez", 20.0, False),
            ("endeudamiento_max", "endeudamiento_maximo", "cita_endeudamiento", "endeudamiento", 100.0, True),
            ("cobertura_min", "cobertura_minima", "cita_cobertura", "cobertura", 20.0, False),
            ("roa_min", "rentabilidad_activo_minima", "cita_activo", "roa", 100.0, True),
            ("roe_min", "rentabilidad_patrimonio_minima", "cita_patrimonio", "roe", 100.0, True),
        ):
            c = cita(nombre_cita, tema)
            # Sin comparador la cita no es el umbral, es la fórmula del
            # indicador (el OCR de esas fórmulas deja números sueltos que el
            # modelo confunde con el umbral: "Liquidez … 45").
            if c is None or not _COMPARADOR_RE.search(_norm(c)):
                continue
            n = _valor_numerico(datos.get(clave), c, tema, 0.001, tope)
            # Solo el endeudamiento y las rentabilidades se escriben en
            # porcentaje ("70 %" -> 0,70); la liquidez y la cobertura son
            # razones y se toman como vienen.
            _poner(p, campo, None if n is None else (n / 100 if porcentaje and n > 1 else n), c, trozo.seccion)
        if c := cita("cita_capital", "fraccion"):
            _poner(p, "capital_trabajo_fraccion",
                   _fraccion(datos.get("porcentaje_capital_de_trabajo"), c, "fraccion"), c, trozo.seccion)
    elif trozo.pregunta == "puntaje":
        for fila in datos.get("factores") or []:
            if not isinstance(fila, dict):
                continue
            clave = _norm(_texto(fila.get("factor")) or "").lower().replace(" ", "_")
            c = _cita_util(fila.get("cita"), trozo.texto, "puntaje")
            if clave not in FACTORES or c is None:
                continue
            # El nombre del factor tiene que estar en la cita misma: si no, un
            # "no aplica" de al lado apagaría un factor que sí puntúa.
            if not re.search(_NOMBRE_FACTOR[clave], _norm(c)):
                continue
            if fila.get("no_aplica") is True:
                puntos = 0.0 if _NEGACION_RE.search(_norm(c)) else None
            else:
                puntos = _valor_numerico(fila.get("puntos"), c, "puntaje", 0.01, 100.0)
                if puntos is not None and not _puntos_en_la_cita(puntos, c):
                    puntos = None
            _guardar(p.puntajes, clave, puntos, c, trozo.seccion)


# Un puntaje solo se acepta si la cita (o el título de su sección) nombra el
# factor: "No aplica la regla de origen" no puede volver N/A al plan de
# calidad por estar en el mismo fragmento.
_NOMBRE_FACTOR: dict[str, str] = {
    "gerencia_proyectos": r"GERENCIA\s+DE\s+PROYECTOS",
    "maquinaria": r"MAQUINARIA",
    "plan_calidad": r"PLAN\s+DE\s+CALIDAD",
    "criterios_ambientales": r"AMBIENTAL|SOSTENIBILIDAD|SOCIAL",
    "industria_nacional": r"INDUSTRIA\s+NACIONAL|SERVICIOS\s+NACIONALES|TRATO\s+NACIONAL|BIENES\s+NACIONALES",
    "discapacidad": r"DISCAPACIDAD",
    "mujeres": r"MUJER",
    "mipyme": r"MIPYME|MICRO,?\s+PEQUENA",
}


def _puntos_en_la_cita(puntos: float, cita: str) -> bool:
    """El número está en la cita como PUNTOS, no como cualquier otra cifra:
    "quince (15) puntos", "0.25 puntos". Sin esto se cuela el "90 %" del
    personal colombiano como si fuera el puntaje del factor."""
    texto = _norm(cita).replace(",", ".")
    formas = {f"{puntos:g}", f"{puntos:.1f}", f"{puntos:.2f}"}
    if puntos == int(puntos):
        formas.add(str(int(puntos)))
    return any(re.search(rf"(?<![\d.]){re.escape(f)}(?![\d])[^A-Z0-9]{{0,12}}PUNTO", texto) for f in formas)


FACTORES = ("gerencia_proyectos", "maquinaria", "plan_calidad", "criterios_ambientales",
            "industria_nacional", "discapacidad", "mujeres", "mipyme")


def leer(
    secciones: list[Seccion],
    ambitos: dict[str, str],
    progreso: Callable[[int, int], None] | None = None,
    modelo: str = MODELO,
) -> ParametrosIA:
    """Lee del pliego los parámetros del proceso. Nunca lanza: lo que el
    modelo no responda queda sin leer y se cuenta en `fallidas`."""
    partes = trozos(secciones, ambitos)
    p = ParametrosIA()
    for i, trozo in enumerate(partes, 1):
        try:
            datos = _preguntar(PREGUNTAS[trozo.pregunta], trozo.texto, modelo)
            _aplicar(datos, trozo, p)
            p.leidas += 1
        except (requests.RequestException, json.JSONDecodeError, KeyError, ValueError, TypeError):
            p.fallidas += 1
        if progreso is not None:
            progreso(i, len(partes))
    return p
