"""Analítica de rendimiento del programa contra evaluaciones reales.

Cada "prueba" es un proceso real ya evaluado por la entidad: se compara, requisito
por requisito y proponente por proponente, lo que decidió el programa solo con lo
que decidió el evaluador (abogado o técnico) en su informe.

Definiciones (las mismas en todo el tablero):
- Decisión automática: el programa resolvió el requisito sin una persona (aprobó
  o lo marcó como "no aplica").
- Aprobación indebida: decisión automática que el evaluador rechazó. Es el único
  error que pasa sin que nadie lo vea; lo demás lo revisa una persona.
- Revisión justificada: lo que el programa mandó a revisión y el evaluador
  también rechazó.
- Techo del error: cota superior exacta (binomial, una cola, 95 % de confianza)
  de la tasa de aprobaciones indebidas. Con 0 errores en n decisiones es
  1 − 0,05^(1/n): "con 95 % de confianza, el error está por debajo de X".
"""
from __future__ import annotations

import json
import math
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

CONFIANZA = 0.95
APROBADO = {"SI", "N.A."}


def techo_del_error(errores: int, n: int, confianza: float = CONFIANZA) -> float | None:
    """Cota superior de Clopper-Pearson (una cola) de la tasa de error."""
    if n <= 0:
        return None
    if errores >= n:
        return 1.0
    alfa = 1 - confianza
    if errores == 0:
        return 1 - alfa ** (1 / n)

    def cola(p: float) -> float:  # P(X <= errores) con X ~ Binomial(n, p)
        return sum(math.comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(errores + 1))

    bajo, alto = errores / n, 1.0
    for _ in range(80):
        medio = (bajo + alto) / 2
        if cola(medio) > alfa:
            bajo = medio
        else:
            alto = medio
    return alto


@dataclass
class Fila:
    proponente: str
    requisito: str
    nuestro: str  # SI | N.A. | NO | ERROR
    referencia: str  # SI | N.A. | NO


@dataclass
class Prueba:
    clave: str
    area: str  # juridica | tecnica
    nombre: str  # nombre comercial, sin datos de la entidad
    filas: list[Fila] = field(default_factory=list)
    tiempos: dict[str, float] = field(default_factory=dict)  # segundos por proponente
    minutos_proceso: float | None = None  # reloj del proceso completo
    a_ciegas: bool = True
    nota: str = ""


def _estadisticas(filas: list[Fila]) -> dict:
    n = len(filas)
    automaticas = [f for f in filas if f.nuestro in APROBADO]
    indebidas = [f for f in automaticas if f.referencia == "NO"]
    revision = [f for f in filas if f.nuestro not in APROBADO]
    justificadas = [f for f in revision if f.referencia == "NO"]
    return {
        "decisiones": n,
        "automaticas": len(automaticas),
        "automatizacion": len(automaticas) / n if n else None,
        "indebidas": len(indebidas),
        "precision": 1 - len(indebidas) / len(automaticas) if automaticas else None,
        "techo_error": techo_del_error(len(indebidas), len(automaticas)),
        "revision": len(revision),
        "revision_justificada": len(justificadas),
    }


def resumir(prueba: Prueba, titulos: dict[str, str] | None = None) -> dict:
    por_proponente: dict[str, list[Fila]] = defaultdict(list)
    por_requisito: dict[str, list[Fila]] = defaultdict(list)
    for f in prueba.filas:
        por_proponente[f.proponente].append(f)
        por_requisito[f.requisito].append(f)
    # Proponente resuelto solo: todos sus requisitos, sin una persona.
    completos = [fs for fs in por_proponente.values() if all(f.nuestro in APROBADO for f in fs)]
    completos_mal = [fs for fs in completos if any(f.referencia == "NO" for f in fs)]
    tiempos = sorted(prueba.tiempos.values())
    return {
        "clave": prueba.clave,
        "area": prueba.area,
        "nombre": prueba.nombre,
        "a_ciegas": prueba.a_ciegas,
        "nota": prueba.nota,
        "proponentes": len(por_proponente),
        **_estadisticas(prueba.filas),
        "proponentes_resueltos_solos": len(completos),
        "proponentes_resueltos_solos_mal": len(completos_mal),
        "segundos_por_proponente": statistics.mean(tiempos) if tiempos else None,
        "segundos_mediana": statistics.median(tiempos) if tiempos else None,
        "minutos_proceso": prueba.minutos_proceso,
        "por_requisito": [
            {"requisito": r, "titulo": (titulos or {}).get(r, r), **_estadisticas(fs)}
            for r, fs in sorted(por_requisito.items(), key=lambda x: _orden(x[0]))
        ],
    }


def _orden(requisito: str):
    m = re.match(r"(\d+)", requisito)
    return (int(m.group(1)) if m else 999, requisito)


def global_(resumenes: list[dict], minutos_manuales: dict[str, float]) -> dict:
    """Totales de todas las pruebas y horas de trabajo que se ahorran
    (decisiones automáticas × minutos que tarda una persona por requisito)."""
    automaticas = sum(r["automaticas"] for r in resumenes)
    indebidas = sum(r["indebidas"] for r in resumenes)
    decisiones = sum(r["decisiones"] for r in resumenes)
    minutos = sum(r["automaticas"] * minutos_manuales.get(r["area"], 0) for r in resumenes)
    return {
        "pruebas": len(resumenes),
        "proponentes": sum(r["proponentes"] for r in resumenes),
        "decisiones": decisiones,
        "automaticas": automaticas,
        "automatizacion": automaticas / decisiones if decisiones else None,
        "indebidas": indebidas,
        "techo_error": techo_del_error(indebidas, automaticas),
        "horas_ahorradas": minutos / 60,
        "minutos_manuales": minutos_manuales,
    }


# ---------------------------------------------------------------- fuentes

def prueba_juridica(clave: str, nombre: str, carpeta: Path, nota: str = "", a_ciegas: bool = False) -> Prueba | None:
    """Medición jurídica de scratch_medicion.py (comparación con el informe del abogado)."""
    comparacion = carpeta / "medicion_comparacion.json"
    if not comparacion.exists():
        return None
    prueba = Prueba(clave, "juridica", nombre, nota=nota, a_ciegas=a_ciegas)
    for f in json.loads(comparacion.read_text()):
        nuestro = f["nuestro"] if f["nuestro"] in ("SI", "NO", "N.A.") else "ERROR"
        prueba.filas.append(Fila(f["hoja"], str(f["requisito"]), nuestro, f["ground_truth"]))
    tiempos = carpeta / "medicion_tiempos.json"
    if tiempos.exists():
        prueba.tiempos = {k: float(v) for k, v in json.loads(tiempos.read_text()).items() if v}
    return prueba


_FACTORES_REFERENCIA = {
    "gerencia_proyectos": "calidad", "plan_calidad": "calidad", "criterios_ambientales": "calidad",
    "industria_nacional": "industria", "discapacidad": "discapacidad", "mujeres": "mujeres", "mipyme": "mipyme",
}


def prueba_tecnica(clave: str, nombre: str, mediciones: list[Path], referencia: Path, desde: int = 1,
                   hasta: int = 10_000, a_ciegas: bool = True, nota: str = "") -> Prueba | None:
    """Medición técnica de .scratch/tecnica/medir.py contra el informe del técnico.
    "NO APLICA" del informe (el proponente no se presentó a ese lote) no se cuenta."""
    ref = json.loads(referencia.read_text()) if referencia.exists() else None
    if ref is None:
        return None
    prueba = Prueba(clave, "tecnica", nombre, a_ciegas=a_ciegas, nota=nota)
    for archivo in mediciones:
        if not archivo.exists():
            continue
        for n, dato in json.loads(archivo.read_text()).items():
            if not (desde <= int(n) <= hasta) or "lotes" not in dato or n not in ref:
                continue
            hoja = f"P-{int(n):02d}"
            if dato.get("segundos"):
                prueba.tiempos[hoja] = float(dato["segundos"])
            for i, lote in enumerate(dato["lotes"], 1):
                esperado = ref[n].get(f"lote{i}", {}).get("experiencia")
                if esperado in (None, "NO APLICA"):
                    continue
                prueba.filas.append(Fila(hoja, f"Experiencia lote {i}", "SI" if lote["cumple"] else "NO",
                                         "SI" if esperado == "CUMPLE" else "NO"))
            for factor in dato.get("puntaje", []):
                clave_ref = _FACTORES_REFERENCIA.get(factor["clave"])
                if clave_ref is None:
                    continue
                otorgado = ref[n]["lote1"][clave_ref] > 0
                nuestro = "N.A." if factor.get("no_aplica") else ("SI" if factor["puntaje"] is not None else "NO")
                prueba.filas.append(Fila(hoja, factor["nombre"], nuestro, "SI" if otorgado else "NO"))
    return prueba if prueba.filas else None
