"""Consulta del Registro Nacional de Obras Civiles Inconclusas (Ley 2020 de
2020), que administra la Contraloría: https://obrasinconclusas.contraloria.gov.co

La página no pide captcha: el aplicativo consulta una API pública por NIT o
cédula. Una anotación vigente de un integrante descuenta un punto del factor
de calidad (pliego 4.2); aquí solo se consulta, y lo que se encuentre lo
decide una persona.

El servidor no envía su certificado intermedio (Sectigo OV R36): se agrega
al conjunto de autoridades en vez de desactivar la verificación.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import certifi
import requests

URL = "https://obrasinconclusas.contraloria.gov.co/api/contractor/certificate-data"
PAGINA = "https://obrasinconclusas.contraloria.gov.co/"
TIEMPO_MAXIMO = 45
_INTERMEDIO = Path(__file__).resolve().parent / "certificados" / "sectigo_ov_r36.pem"
_CACHE = Path(__file__).resolve().parent.parent.parent / "cache" / "consultas"


@dataclass
class ResultadoConsulta:
    identificacion: str
    nombre: str
    consultado: bool
    obras: list[dict] = field(default_factory=list)
    error: str | None = None


def _autoridades() -> str:
    destino = _CACHE / "autoridades_obras_inconclusas.pem"
    if not destino.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(Path(certifi.where()).read_text() + "\n" + _INTERMEDIO.read_text())
    return str(destino)


def identificacion_para_consulta(nit: str | None) -> str | None:
    """Número sin dígito de verificación, como lo guarda el registro
    ("829.001.061-1" -> "829001061")."""
    if not nit:
        return None
    base = re.split(r"\s*-\s*", nit.strip())[0]
    digitos = re.sub(r"\D", "", base)
    if len(digitos) == 10 and digitos.startswith(("8", "9")):
        digitos = digitos[:9]  # NIT con el dígito de verificación pegado
    return digitos if 5 <= len(digitos) <= 10 else None


def consultar(identificacion: str, nombre: str = "") -> ResultadoConsulta:
    cache = _CACHE / f"obras_inconclusas_{identificacion}_{date.today():%Y%m%d}.json"
    if cache.exists():
        datos = json.loads(cache.read_text())
    else:
        try:
            respuesta = requests.get(URL, params={"nit": identificacion}, timeout=TIEMPO_MAXIMO, verify=_autoridades(),
                                     headers={"User-Agent": "MiEvaluador (consulta de obras inconclusas)"})
            respuesta.raise_for_status()
            datos = respuesta.json()
        except (requests.RequestException, ValueError) as exc:
            return ResultadoConsulta(identificacion, nombre, False, error=str(exc)[:200])
        if not datos.get("success"):
            return ResultadoConsulta(identificacion, nombre, False, error=str(datos.get("message"))[:200])
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(datos, ensure_ascii=False))
    contenido = datos.get("data") or {}
    obras = [
        {k: o.get(k) for k in ("DESCRIPCION", "CIUDAD", "GRUPO", "CLASE_OBRA", "ROL", "DECISION_ADMIN", "COD_OBRA", "COD_ENTIDAD")}
        for o in contenido.get("projects") or []
    ]
    return ResultadoConsulta(identificacion, nombre, True, obras=obras)
