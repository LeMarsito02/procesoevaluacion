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
_CANDADO_LLM = Path(os.environ.get("LLM_CANDADO", "/tmp/evaluador-juridico-llm.lock"))


def _llamar(instruccion: str, documento: str) -> str:
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
    with urllib.request.urlopen(peticion, timeout=LLM_TIMEOUT_SEGUNDOS) as respuesta:
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


def aparece_en_texto(valor: str | None, texto: str, *, numerico: bool = False) -> bool:
    """Verificación anti-invención: el valor extraído por el modelo debe
    estar en el documento. Para números (cédulas, valores, fechas) se
    comparan solo los dígitos, tolerando separadores distintos; para texto,
    todas sus palabras deben aparecer (el modelo puede reordenar un nombre
    "APELLIDOS NOMBRES" pero no inventar palabras)."""
    if not valor:
        return False
    if numerico:
        digitos = solo_digitos(valor)
        return len(digitos) >= 4 and digitos in solo_digitos(texto)
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
