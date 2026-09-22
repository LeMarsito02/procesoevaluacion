"""Parámetros de la evaluación financiera que salen del pliego.

- Presupuesto, plazo y anticipo de cada lote (1.1 y 8.3).
- Capital de trabajo demandado por lote (3.7): con plazo menor a 12 meses,
  (POE − anticipo) × 33 %; si no, (POE − anticipo) / plazo × meses de
  apalancamiento según la tabla del pliego. Nunca más que el presupuesto.
- Capacidad residual del proceso por lote (3.11.1): POE − anticipo con plazo
  hasta 12 meses; si no, (POE − anticipo) / plazo × 12.
- Patrimonio (3.8): solo si el presupuesto es de al menos 40.000 SMMLV y el
  plazo de al menos 24 meses.
- Umbrales de los indicadores (Matriz 2 – Indicadores financieros y
  organizacionales): la matriz es un anexo aparte del pliego; si no está, los
  indicadores se calculan pero su cumplimiento va a revisión hasta que una
  persona registre los umbrales del proceso.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from motor.tecnica.rup import normalizar, numero

# Meses de apalancamiento del capital de trabajo según el plazo (3.7).
_APALANCAMIENTO = [(12, 24, 4), (24, 36, 8), (36, 48, 12), (48, 60, 16), (60, 72, 20), (72, 84, 24),
                   (84, 96, 28), (96, 108, 32), (108, 120, 36), (120, 10_000, 40)]


@dataclass
class LoteFinanciero:
    nombre: str
    presupuesto: float | None
    plazo_meses: float | None = None
    anticipo: float | None = None  # fracción del valor del contrato (0,20)

    @property
    def valor_anticipo(self) -> float | None:
        if self.presupuesto is None or self.anticipo is None:
            return None
        return self.presupuesto * self.anticipo

    @property
    def capital_de_trabajo_demandado(self) -> float | None:
        if self.presupuesto is None or self.anticipo is None or self.plazo_meses is None:
            return None
        base = self.presupuesto - self.valor_anticipo
        if self.plazo_meses < 12:
            return min(base * 0.33, self.presupuesto)
        meses = next(n for desde, hasta, n in _APALANCAMIENTO if desde <= self.plazo_meses < hasta)
        return min(base / self.plazo_meses * meses, self.presupuesto)

    @property
    def capacidad_residual_del_proceso(self) -> float | None:
        if self.presupuesto is None or self.anticipo is None or self.plazo_meses is None:
            return None
        base = self.presupuesto - self.valor_anticipo
        return base if self.plazo_meses <= 12 else base / self.plazo_meses * 12


@dataclass
class Umbrales:
    """Matriz 2: mínimos y máximos de los indicadores."""
    liquidez_min: float | None = None
    endeudamiento_max: float | None = None
    cobertura_min: float | None = None
    roa_min: float | None = None
    roe_min: float | None = None
    fuente: str = ""

    @property
    def completos(self) -> bool:
        return None not in (self.liquidez_min, self.endeudamiento_max, self.cobertura_min, self.roa_min, self.roe_min)


@dataclass
class ParametrosFinancieros:
    smmlv: float
    lotes: list[LoteFinanciero] = field(default_factory=list)
    umbrales: Umbrales = field(default_factory=Umbrales)
    patrimonio_aplica: bool = False
    avisos: list[str] = field(default_factory=list)


_ANTICIPO_RE = re.compile(r"ANTICIPO\s+Y/O\s+PAGO\s+ANTICIPADO(.{0,1200})", re.S)
_PORCENTAJE_RE = re.compile(r"\(\s*(\d{1,3}(?:[.,]\d+)?)\s*%\s*\)")
_SIN_ANTICIPO_RE = re.compile(r"NO\s+(?:SE\s+)?(?:ENTREGARA|OTORGARA|HABRA|CONTEMPLA)\s+(?:NINGUN\s+)?ANTICIPO|NO\s+APLICA")
# "(4) MESES", aunque la tabla parta el texto: "(4) MILLONES ... MESES".
_PLAZO_RE = re.compile(r"\(\s*(\d{1,3})\s*\)(?=[^()$]{0,80}?\bMESES\b)")
_SECCION_11_RE = re.compile(r"OBJETO, PRESUPUESTO OFICIAL, PLAZO Y UBICACION(.{0,6000}?)\n\s*1\.2\.?\s", re.S)
_UMBRAL_RE = {
    "liquidez_min": r"LIQUIDEZ[^\n\d]{0,60}?(?:>=|≥|MAYOR\s+O\s+IGUAL\s+A)\s*(\d+(?:[.,]\d+)?)",
    "endeudamiento_max": r"ENDEUDAMIENTO[^\n\d]{0,60}?(?:<=|≤|MENOR\s+O\s+IGUAL\s+A)\s*(\d+(?:[.,]\d+)?)",
    "cobertura_min": r"COBERTURA\s+DE\s+INTERESES[^\n\d]{0,60}?(?:>=|≥|MAYOR\s+O\s+IGUAL\s+A)\s*(\d+(?:[.,]\d+)?)",
    "roa_min": r"RENTABILIDAD\s+(?:DEL|SOBRE\s+EL)\s+ACTIVO[^\n\d]{0,60}?(?:>=|≥|MAYOR\s+O\s+IGUAL\s+A)\s*(\d+(?:[.,]\d+)?)",
    "roe_min": r"RENTABILIDAD\s+(?:DEL|SOBRE\s+EL)\s+PATRIMONIO[^\n\d]{0,60}?(?:>=|≥|MAYOR\s+O\s+IGUAL\s+A)\s*(\d+(?:[.,]\d+)?)",
}


def _anticipo(texto_norm: str) -> float | None:
    """Fracción del anticipo (8.3): la última sección con ese título (la
    primera es el índice)."""
    secciones = list(_ANTICIPO_RE.finditer(texto_norm))
    if not secciones:
        return None
    cuerpo = secciones[-1].group(1)
    if _SIN_ANTICIPO_RE.search(cuerpo[:400]):
        return 0.0
    m = _PORCENTAJE_RE.search(cuerpo)
    return float(m.group(1).replace(",", ".")) / 100 if m else None


def _plazos(texto_norm: str, lotes: int) -> list[float | None]:
    secciones = list(_SECCION_11_RE.finditer(texto_norm))
    if not secciones:
        return [None] * lotes
    plazos = [float(p) for p in _PLAZO_RE.findall(secciones[-1].group(1))]
    if len(plazos) == lotes:
        return plazos
    if len(plazos) == 1:
        return plazos * lotes
    return [None] * lotes


def umbrales_del_texto(texto_norm: str, fuente: str) -> Umbrales:
    """Umbrales escritos en el pliego o en la Matriz 2 ("LIQUIDEZ >= 1,2")."""
    u = Umbrales(fuente=fuente)
    for campo, patron in _UMBRAL_RE.items():
        if m := re.search(patron, texto_norm):
            setattr(u, campo, numero(m.group(1)))
    return u


def leer_parametros(contenido_pliego: bytes, lotes: list[tuple[str, float | None]], smmlv: float,
                    matriz2: bytes | None = None) -> ParametrosFinancieros:
    """`lotes`: [(nombre, presupuesto)] como los leyó el análisis técnico del
    pliego (ya separa los lotes cuando el presupuesto viene en letras)."""
    from motor.procesamiento.pdf_utils import abrir_pdf

    with abrir_pdf(contenido_pliego) as pdf:
        texto_norm = normalizar("\n".join(page.extract_text() or "" for page in pdf.pages))
    parametros = ParametrosFinancieros(smmlv=smmlv)
    anticipo = _anticipo(texto_norm)
    if anticipo is None:
        parametros.avisos.append("no se leyó el porcentaje de anticipo en el pliego (8.3)")
    plazos = _plazos(texto_norm, len(lotes))
    for (nombre, presupuesto), plazo in zip(lotes, plazos):
        parametros.lotes.append(LoteFinanciero(nombre, presupuesto, plazo, anticipo))
    if any(p is None for p in plazos):
        parametros.avisos.append("no se leyó el plazo de cada lote en el pliego (1.1)")
    total = sum(l.presupuesto or 0 for l in parametros.lotes)
    plazo_max = max((p for p in plazos if p), default=0)
    parametros.patrimonio_aplica = total / smmlv >= 40_000 and plazo_max >= 24
    parametros.umbrales = umbrales_del_texto(texto_norm, "pliego")
    if matriz2 is not None and not parametros.umbrales.completos:
        with abrir_pdf(matriz2) as pdf:
            texto_matriz = normalizar("\n".join(page.extract_text() or "" for page in pdf.pages))
        parametros.umbrales = umbrales_del_texto(texto_matriz, "Matriz 2")
    return parametros
