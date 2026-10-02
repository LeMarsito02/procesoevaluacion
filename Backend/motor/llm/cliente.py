"""Cliente del modelo de lenguaje LOCAL (Ollama) usado como respaldo.

Principios (ver conversación con el usuario, no negociables):
- El modelo solo EXTRAE datos o responde preguntas puntuales sobre un texto;
  la decisión cumple/no cumple la toma siempre el código.
- Todo lo que devuelve se verifica contra el texto literal del documento
  (ver `aparece_en_texto`); lo que no se puede verificar se descarta.
- Si el modelo no está disponible, tarda demasiado o responde basura, se
  devuelve None y el requisito sigue por el camino conservador (revisión
  humana). Nunca detiene una evaluación.
- Los documentos no salen del PC: Ollama corre en local.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

LLM_URL = os.environ.get("LLM_URL", "http://localhost:11434")
# La IA es local: solo se habla HTTP(S) con Ollama. Un LLM_URL mal puesto
# ("file:///…") no debe convertir la consulta en una lectura de disco.
if not LLM_URL.startswith(("http://", "https://")):
    raise ValueError("LLM_URL debe empezar por http:// o https://")
LLM_MODELO = os.environ.get("LLM_MODELO", "llama3.1:8b")
LLM_HABILITADO = os.environ.get("LLM_HABILITADO", "1") == "1"
# Ollama atiende una petición a la vez por defecto: con varios workers una
# consulta puede esperar en cola a las demás, de ahí el margen.
LLM_TIMEOUT_SEGUNDOS = float(os.environ.get("LLM_TIMEOUT_SEGUNDOS", "240"))
LLM_REINTENTOS = int(os.environ.get("LLM_REINTENTOS", "2"))
# Con 8192 tokens Ollama retuvo ~9,6 GB de RAM en la medición real y llevó el
# PC a usar toda la swap. Las secciones que se analizan (facultades, Formato 2,
# carátula de la póliza) caben en 6144.
LLM_CONTEXTO_TOKENS = int(os.environ.get("LLM_CONTEXTO_TOKENS", "6144"))
# ~3.5 caracteres por token en español; se deja espacio para instrucciones
# y respuesta.
MAX_CARACTERES_DOCUMENTO = int(LLM_CONTEXTO_TOKENS * 2.6)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "llm"

_SISTEMA = (
    "Eres un asistente que extrae datos de documentos legales colombianos para una evaluación jurídica. "
    "Responde únicamente con un objeto JSON válido con exactamente las claves pedidas. "
    "Copia nombres, números, fechas y citas EXACTAMENTE como aparecen en el documento, sin corregirlos ni completarlos. "
    "Si un dato no aparece en el documento, usa null. No inventes información."
)

# Si Ollama no responde, no se vuelve a intentar en cada requisito durante
# un rato: evita sumar minutos de timeouts cuando el servicio está apagado.
_NO_DISPONIBLE_HASTA = 0.0
_PAUSA_SI_NO_DISPONIBLE = 120.0


def _clave_cache(modelo: str, instruccion: str, documento: str) -> str:
    return hashlib.sha256(f"{modelo}\n{_SISTEMA}\n{instruccion}\n{documento}".encode()).hexdigest()


# Una sola consulta al modelo a la vez en toda la máquina (entre workers):
# consultas simultáneas hacen que Ollama reserve memoria para cada una y el
# modelo, que no cabe entero en la GPU, termina compitiendo por RAM.
# Vive en la carpeta de la app y no en /tmp: en /tmp otro usuario del servidor
# podría crear antes el archivo (o un enlace con ese nombre) y bloquear la IA o
# hacer que la app escriba donde no debe (hallazgo de Bandit B108).
_CANDADO_LLM = Path(os.environ.get("LLM_CANDADO", str(CACHE_DIR.parent / "llm.lock")))


def _llamar(instruccion: str, documento: str) -> str:
    _CANDADO_LLM.parent.mkdir(parents=True, exist_ok=True)
    with open(_CANDADO_LLM, "a") as candado:
        fcntl.flock(candado, fcntl.LOCK_EX)
        try:
            return _llamar_sin_candado(instruccion, documento)
        finally:
            fcntl.flock(candado, fcntl.LOCK_UN)


def _llamar_sin_candado(instruccion: str, documento: str) -> str:
    cuerpo = {
        "model": LLM_MODELO,
        "stream": False,
        "format": "json",
        "think": False,
        "keep_alive": os.environ.get("LLM_KEEP_ALIVE", "2m"),
        "options": {"temperature": 0, "num_ctx": LLM_CONTEXTO_TOKENS},
        "messages": [
            {"role": "system", "content": _SISTEMA},
            {"role": "user", "content": f"{instruccion}\n\nDOCUMENTO:\n{documento}"},
        ],
    }
    peticion = urllib.request.Request(
        f"{LLM_URL}/api/chat", data=json.dumps(cuerpo).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(peticion, timeout=LLM_TIMEOUT_SEGUNDOS) as respuesta:  # nosec B310 (esquema validado arriba)
        return json.load(respuesta)["message"]["content"]


def consultar_json(instruccion: str, documento: str) -> dict | None:
    """Pide al modelo local un JSON sobre `documento`. Devuelve el dict o
    None si el modelo no está disponible o no dio un JSON válido tras los
    reintentos. Las respuestas válidas se guardan en disco: la misma
    consulta sobre el mismo texto no se repite."""
    global _NO_DISPONIBLE_HASTA
    if not LLM_HABILITADO or time.monotonic() < _NO_DISPONIBLE_HASTA:
        return None

    documento = documento[:MAX_CARACTERES_DOCUMENTO]
    archivo_cache = CACHE_DIR / f"{_clave_cache(LLM_MODELO, instruccion, documento)}.json"
    if archivo_cache.exists():
        try:
            return json.loads(archivo_cache.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    for intento in range(LLM_REINTENTOS + 1):
        try:
            contenido = _llamar(instruccion, documento)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:  # modelo no instalado
                _NO_DISPONIBLE_HASTA = time.monotonic() + _PAUSA_SI_NO_DISPONIBLE
                return None
            time.sleep(2 * (intento + 1))
            continue
        except (urllib.error.URLError, ConnectionError) as exc:
            if isinstance(getattr(exc, "reason", None), (ConnectionRefusedError, FileNotFoundError)) or isinstance(
                exc, ConnectionRefusedError
            ):
                _NO_DISPONIBLE_HASTA = time.monotonic() + _PAUSA_SI_NO_DISPONIBLE
                return None
            time.sleep(2 * (intento + 1))
            continue
        except (TimeoutError, OSError):
            time.sleep(2 * (intento + 1))
            continue
        try:
            datos = json.loads(contenido)
        except json.JSONDecodeError:
            continue
        if not isinstance(datos, dict):
            continue
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            archivo_cache.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return datos
    return None


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.upper()).strip()


def solo_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


# Un número tal como se escribe en un documento: con separadores de miles
# (punto o coma, en grupos de tres) o seguido, y opcionalmente una parte decimal
# de uno o dos dígitos. No empieza a mitad de otro número.
_NUMERO_RE = re.compile(r"(?<!\d)(?<!\d[.,])(\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,](\d{1,2}))?(?!\d)")
_FECHA_VALOR_RE = re.compile(r"\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\s*")


def _numero_escrito(valor: str, texto: str) -> bool:
    """El número `valor` está escrito tal cual en el texto, como un número
    completo: misma parte entera y mismos decimales, con los separadores que
    sea. Antes se buscaban sus dígitos dentro de TODOS los dígitos del documento
    pegados, y así "$1.500.000.000,00" validaba 15.000.000.000 (diez veces más)
    o una fecha imposible: justo lo que esta verificación debe atajar."""
    m = _NUMERO_RE.search(valor)
    if m is None:
        return False
    entero, decimales = solo_digitos(m.group(1)), (m.group(2) or "").ljust(2, "0")
    if len(entero) < 4:
        return False
    for n in _NUMERO_RE.finditer(texto):
        entero_texto = solo_digitos(n.group(1))
        if entero_texto == entero and (n.group(2) or "").ljust(2, "0") == decimales:
            return True
        # NIT con el dígito de verificación pegado en el valor ("9001234567")
        # y separado en el documento ("900.123.456-7").
        dv = re.match(r"\s*-\s*(\d)(?!\d)", texto[n.end():])
        if dv and entero == entero_texto + dv.group(1):
            return True
    return False


def _fecha_escrita(dia: str, mes: str, anio: str, texto: str) -> bool:
    """La fecha existe y está en el texto como fecha: "29/11/2026",
    "29-11-2026", "29 11 2026" o "2026/11/29". Con separadores: una cifra
    pegada ("26301120") no es una fecha."""
    from datetime import date

    d, m, a = int(dia), int(mes), anio
    try:
        date(int(a), m, d)
    except ValueError:
        return False
    sep = r"(?:\s*[/\-.]\s*|\s+)"
    return bool(
        re.search(rf"(?<!\d)0?{d}{sep}0?{m}{sep}{a}(?!\d)", texto)
        or re.search(rf"(?<!\d){a}{sep}0?{m}{sep}0?{d}(?!\d)", texto)
    )


def aparece_en_texto(valor: str | None, texto: str, *, numerico: bool = False) -> bool:
    """Verificación anti-invención: el valor extraído por el modelo debe
    estar en el documento. Para números (cédulas, NIT, valores, fechas) tiene
    que estar escrito como un número completo, tolerando separadores
    distintos; para texto, todas sus palabras deben aparecer (el modelo puede
    reordenar un nombre "APELLIDOS NOMBRES" pero no inventar palabras)."""
    if not valor:
        return False
    if numerico:
        fecha = _FECHA_VALOR_RE.fullmatch(valor)
        if fecha:
            return _fecha_escrita(*fecha.groups(), texto)
        return _numero_escrito(valor, texto)
    texto_norm = _normalizar(texto)
    palabras = [p for p in re.findall(r"[A-Z0-9Ñ]+", _normalizar(valor)) if len(p) > 1]
    return bool(palabras) and all(re.search(rf"\b{re.escape(p)}\b", texto_norm) for p in palabras)


def cita_literal(cita: str | None, texto: str, minimo_palabras: int = 4) -> bool:
    """True si `cita` aparece de forma contigua en el texto (ignorando
    mayúsculas, tildes, espacios y signos)."""
    if not cita:
        return False
    limpiar = lambda s: " ".join(re.findall(r"[A-Z0-9Ñ]+", _normalizar(s)))  # noqa: E731
    cita_limpia = limpiar(cita)
    return len(cita_limpia.split()) >= minimo_palabras and cita_limpia in limpiar(texto)
