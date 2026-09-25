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
    def datos_creibles(self) -> bool:
        """El presupuesto, el plazo y el anticipo tienen sentido. Con un plazo
        negativo o un anticipo fuera de rango el capital de trabajo exigido
        sale inventado, y un anticipo del 100 % lo dejaría en cero, con lo que
        cualquiera pasaría."""
        if self.presupuesto is not None and self.presupuesto <= 0:
            return False
        if self.plazo_meses is not None and not 0 < self.plazo_meses <= 120:
            return False
        return not (self.anticipo is not None and not 0 <= self.anticipo <= 0.9)

    @property
    def valor_anticipo(self) -> float | None:
        if self.presupuesto is None or self.anticipo is None or not self.datos_creibles:
            return None
        return self.presupuesto * self.anticipo

    @property
    def capital_de_trabajo_demandado(self) -> float | None:
        if self.presupuesto is None or self.anticipo is None or self.plazo_meses is None:
            return None
        if not self.datos_creibles:
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
    # True aplica, False no aplica, None no se pudo saber (falta el plazo o el
    # presupuesto): entonces el requisito va a revisión, no a "no aplica".
    patrimonio_aplica: bool | None = False
    avisos: list[str] = field(default_factory=list)
    # Parámetros que solo leyó la IA del pliego, o en los que la IA y las
    # reglas no coinciden. Entran en `avisos` (y por tanto ningún lote se
    # aprueba solo) hasta que una persona los confirme: ver
    # motor/pliego/fusion.py.
    sin_confirmar: list[str] = field(default_factory=list)
    # Requisitos que el pliego exige y el motor no sabe verificar: mientras
    # haya alguno, el lote va a revisión (motor/pliego/catalogo_tecnico.py).
    requisitos_sin_verificar: list[str] = field(default_factory=list)
    # Los indicadores que la Matriz 2 reserva a los proponentes que acrediten
    # ser Mipyme. Son más laxos, así que no se aplican por defecto: solo a quien
    # lo acredite con su RUP (motor/financiera/proponente.py).
    umbrales_mipyme: Umbrales | None = None
    # Lo que el pliego PERMITE y el motor no sabe aprovechar (acreditar algo con
    # un documento alterno, por ejemplo). No frena ninguna aprobación —ignorarlo
    # no aprueba a nadie de más—, pero sí puede hacer que se rechace a quien
    # cumplía: por eso se dice cuando el resultado no es un cumple.
    permisos_del_pliego: list[str] = field(default_factory=list)


# El título de la sección cambia entre documentos tipo: "ANTICIPO Y/O PAGO
# ANTICIPADO" (licitación) y "ANTICIPO O PAGO ANTICIPADO" (menor cuantía).
_ANTICIPO_RE = re.compile(r"ANTICIPO\s+(?:Y\s*/\s*O|O)\s+PAGO\s+ANTICIPADO(.{0,1200})", re.S)
# Con el número de sección delante es la sección de verdad y no una
# mención de paso ("se incluye la forma de pago, anticipo o pago anticipado").
_ANTICIPO_NUMERADO_RE = re.compile(r"8\.3\.?\s*ANTICIPO\s+(?:Y\s*/\s*O|O)\s+PAGO\s+ANTICIPADO(.{0,1200})", re.S)
# El porcentaje del anticipo viene de tres formas: "(20%)", "[30%]" (el
# documento tipo deja los corchetes de la plantilla sin reemplazar) y sin
# nada: "un valor equivalente al 25% del valor básico del contrato". Dentro
# de la sección del anticipo, el primero que aparece es el suyo.
_PORCENTAJE_RE = re.compile(r"[(\[]\s*(\d{1,3}(?:[.,]\d+)?)\s*%\s*[)\]]|(\d{1,3}(?:[.,]\d+)?)\s*%")
# "No se entregará anticipo"; un "NO APLICA" suelto no basta: puede ser el de
# otra fila de la tabla y dejaría el anticipo en cero (inflando el capital de
# trabajo y la capacidad residual exigidos).
_SIN_ANTICIPO_RE = re.compile(
    r"NO\s+(?:SE\s+)?(?:ENTREGARA|OTORGARA|HABRA|CONTEMPLA|APLICA)\s+(?:NINGUN\s+)?(?:ANTICIPO|PAGO\s+ANTICIPADO)"
    r"|ANTICIPO[^\n]{0,40}NO\s+APLICA"
)
# "(4) MESES", aunque la tabla parta el texto: "(4) MILLONES ... MESES".
_PLAZO_RE = re.compile(r"\(\s*(\d{1,3})\s*\)(?=[^()$]{0,80}?\bMESES\b)")
_SECCION_11_RE = re.compile(
    r"OBJETO, PRESUPUESTO OFICIAL, PLAZO Y UBICACION(.{0,6000}?)"
    r"(?:\n\s*1\.2\.?\s|\n\s*DOCUMENTOS DEL PROCESO|\n\s*COMUNICACIONES Y OBSERVACIONES|\Z)", re.S)
# El pliego a veces escribe el umbral en porcentaje ("endeudamiento <= 70 %"):
# se guarda siempre como razón.
_MAYOR = r"(?:>=|>|MAYOR\s+O\s+IGUAL\s+A|MAYOR\s+A|SUPERIOR\s+A|MINIMO(?:\s+DE)?)"
_MENOR = r"(?:<=|<|MENOR\s+O\s+IGUAL\s+A|MENOR\s+A|INFERIOR\s+A|MAXIMO(?:\s+DE)?)"
_VALOR = r"(\d+(?:[.,]\d+)?)\s*(%?)"
_UMBRAL_RE = {
    "liquidez_min": rf"LIQUIDEZ[^\n\d]{{0,60}}?{_MAYOR}\s*{_VALOR}",
    "endeudamiento_max": rf"ENDEUDAMIENTO[^\n\d]{{0,60}}?{_MENOR}\s*{_VALOR}",
    "cobertura_min": rf"COBERTURA\s+DE\s+INTERESES[^\n\d]{{0,60}}?{_MAYOR}\s*{_VALOR}",
    "roa_min": rf"RENTABILIDAD\s+(?:DEL|SOBRE\s+EL)\s+ACTIVO[^\n\d]{{0,60}}?{_MAYOR}\s*{_VALOR}",
    "roe_min": rf"RENTABILIDAD\s+(?:DEL|SOBRE\s+EL)\s+PATRIMONIO[^\n\d]{{0,60}}?{_MAYOR}\s*{_VALOR}",
}


def _anticipo(texto_norm: str) -> float | None:
    """Fracción del anticipo (8.3): la última sección con ese título (la
    primera es el índice)."""
    secciones = list(_ANTICIPO_NUMERADO_RE.finditer(texto_norm)) or list(_ANTICIPO_RE.finditer(texto_norm))
    if not secciones:
        return None
    cuerpo = secciones[-1].group(1)
    if _SIN_ANTICIPO_RE.search(cuerpo[:400]):
        return 0.0
    m = _PORCENTAJE_RE.search(cuerpo)
    if m is None:
        return None
    valor = float((m.group(1) or m.group(2)).replace(",", ".")) / 100
    return valor if 0 <= valor <= 1 else None


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
    """Umbrales escritos en el pliego o en la Matriz 2 ("LIQUIDEZ >= 1,2",
    "ENDEUDAMIENTO <= 70 %"). Siempre quedan como razón, no como porcentaje."""
    u = Umbrales(fuente=fuente)
    for campo, patron in _UMBRAL_RE.items():
        if m := re.search(patron, texto_norm):
            valor = numero(m.group(1))
            if valor is not None:
                setattr(u, campo, valor / 100 if m.group(2) else valor)
    return u


# Cada indicador de la Matriz 2: cómo se llama y con qué se compara.
_INDICADORES_MATRIZ = {
    "liquidez_min": (r"LIQUIDEZ", _MAYOR),
    "endeudamiento_max": (r"ENDEUDAMIENTO", _MENOR),
    "cobertura_min": (r"COBERTURA\s+DE\s+INTERESES", _MAYOR),
    "roa_min": (r"RENTABILIDAD\s+(?:DEL|SOBRE\s+EL)\s+ACTIVO", _MAYOR),
    "roe_min": (r"RENTABILIDAD\s+(?:DEL|SOBRE\s+EL)\s+PATRIMONIO", _MAYOR),
}
# Donde empieza otro indicador termina la fila del anterior.
_OTRO_INDICADOR_RE = (r"LIQUIDEZ|ENDEUDAMIENTO|COBERTURA|RENTABILIDAD|CAPITAL\s+DE\s+TRABAJO|PATRIMONIO\b"
                      r"|INDICADOR\b")
# Cuál de los dos rangos aplica depende de la cuantía del proceso y la matriz
# no siempre lo dice: se toma el más exigente de cada indicador, que nunca
# aprueba a quien no debe, y se avisa para que una persona confirme el rango.
_MAS_EXIGENTE = {"liquidez_min": max, "endeudamiento_max": min, "cobertura_min": max,
                 "roa_min": max, "roe_min": max}


def umbrales_de_la_matriz(texto_norm: str) -> tuple[Umbrales, dict[str, list[float]]]:
    """(umbrales, opciones por indicador).

    La Matriz 2 pone una columna por rango de presupuesto ("RANGO 1: >0
    <4.000 SMMLV, RANGO 2: >= 4.000") y trae una tabla aparte para los
    proponentes MIPYME, así que de cada indicador salen varios valores. Cuál
    aplica es una decisión del proceso, no del programa: si todos los valores
    coinciden se usa ese; si no, el umbral se deja sin fijar y las opciones se
    devuelven para que una persona escoja en la plataforma.

    Adivinar sería peor de las dos maneras: con el valor menos exigente se
    aprobaría a quien no cumple, y con el más exigente se rechazaría a quien
    sí."""
    u = Umbrales(fuente="Matriz 2")
    opciones: dict[str, list[float]] = {}
    for campo, (nombre, comparador) in _INDICADORES_MATRIZ.items():
        valores: list[float] = []
        for m in re.finditer(nombre, texto_norm):
            # Hasta el siguiente indicador de la tabla (o 160 caracteres).
            resto = texto_norm[m.end(): m.end() + 160]
            corte = re.search(_OTRO_INDICADOR_RE, resto)
            ventana = resto[: corte.start()] if corte else resto
            for v in re.finditer(rf"(?:{comparador})?\s*{_VALOR}", ventana):
                valor = numero(v.group(1))
                if valor is not None and 0 < valor <= 100:
                    valores.append(valor / 100 if v.group(2) else valor)
        distintos = sorted(set(valores))
        if len(distintos) == 1:
            setattr(u, campo, distintos[0])
        elif distintos:
            opciones[campo] = distintos
    return u, opciones


def _texto_con_simbolos(texto: str) -> str:
    """normalizar() borra "≥" y "≤" al pasar a ASCII: se cambian antes."""
    return texto.replace("≥", ">=").replace("≤", "<=").replace("⩾", ">=").replace("⩽", "<=")


def _texto_por_filas(contenido_pliego: bytes, paginas: int = 12) -> str:
    """El pliego leído fila por fila, para recuperar lo que está en tablas.
    Solo las primeras páginas: ahí están el objeto, el presupuesto, el plazo
    y la ubicación de cada lote."""
    from motor.procesamiento.pdf_utils import abrir_pdf, texto_pagina_tabla

    partes = []
    with abrir_pdf(contenido_pliego) as pdf:
        for page in pdf.pages[:paginas]:
            partes.append(texto_pagina_tabla(page))
            page.flush_cache()
    return normalizar(_texto_con_simbolos("\n".join(partes)))


def leer_parametros(contenido_pliego: bytes, lotes: list[tuple[str, float | None]], smmlv: float,
                    matriz2: bytes | None = None) -> ParametrosFinancieros:
    """`lotes`: [(nombre, presupuesto)] como los leyó el análisis técnico del
    pliego (ya separa los lotes cuando el presupuesto viene en letras)."""
    from motor.procesamiento.pdf_utils import abrir_pdf

    with abrir_pdf(contenido_pliego) as pdf:
        texto_norm = normalizar(_texto_con_simbolos("\n".join(page.extract_text() or "" for page in pdf.pages)))
    parametros = ParametrosFinancieros(smmlv=smmlv)
    anticipo = _anticipo(texto_norm)
    plazos = _plazos(texto_norm, len(lotes))
    if anticipo is None or any(p is None for p in plazos):
        # El plazo y el anticipo viven en tablas, y la lectura corrida las
        # desarma ("DOCE (12) MESES" queda partido entre columnas). Se vuelve
        # a leer el pliego fila por fila, que es como se leen los documentos
        # difíciles en el resto del motor. No es cuestión de una palabra
        # distinta: es recuperar la estructura de la tabla.
        texto_tabla = _texto_por_filas(contenido_pliego)
        anticipo = anticipo if anticipo is not None else _anticipo(texto_tabla)
        if any(p is None for p in plazos):
            otros = _plazos(texto_tabla, len(lotes))
            plazos = [p if p is not None else o for p, o in zip(plazos, otros)]
    if anticipo is None:
        parametros.avisos.append("no se leyó el porcentaje de anticipo en el pliego (8.3)")
    for (nombre, presupuesto), plazo in zip(lotes, plazos):
        parametros.lotes.append(LoteFinanciero(nombre, presupuesto, plazo, anticipo))
    if any(p is None for p in plazos):
        parametros.avisos.append("no se leyó el plazo de cada lote en el pliego (1.1)")
    total = sum(l.presupuesto or 0 for l in parametros.lotes)
    plazo_max = max((p for p in plazos if p), default=0)
    if not total or not plazo_max:
        # Sin presupuesto o sin plazo no se puede saber si el pliego lo exige.
        parametros.patrimonio_aplica = None
    else:
        parametros.patrimonio_aplica = total / smmlv >= 40_000 and plazo_max >= 24
    parametros.umbrales = umbrales_del_texto(texto_norm, "pliego")
    if matriz2 is not None and not parametros.umbrales.completos:
        from motor.procesamiento.documentos import texto_de_documento

        texto_matriz = normalizar(_texto_con_simbolos(texto_de_documento(matriz2)))
        # Primero se intenta entender la matriz como lo que es: dos tablas
        # (Mipyme y los demás) con una columna por rango de presupuesto. Si se
        # entiende, ella misma dice cuál aplica —el rango del presupuesto del
        # lote en SMMLV— y no hay nada que preguntar.
        elegidos = _de_la_matriz_por_rango(matriz2, parametros, smmlv)
        if elegidos is not None:
            return parametros
        # La Matriz 2 completa lo que el pliego no dijo; no borra lo ya leído.
        de_matriz, opciones = umbrales_de_la_matriz(texto_matriz)
        for campo, valores in opciones.items():
            como_se_llama = campo.replace("_min", "").replace("_max", "").replace("_", " ")
            parametros.sin_confirmar.append(
                f"la Matriz 2 da varios valores para {como_se_llama} según el rango de presupuesto y si el proponente "
                f"es MIPYME ({', '.join(f'{v:g}' for v in valores)}): escoge el que aplica a este proceso"
            )
        for campo in ("liquidez_min", "endeudamiento_max", "cobertura_min", "roa_min", "roe_min"):
            if getattr(parametros.umbrales, campo) is None and getattr(de_matriz, campo) is not None:
                setattr(parametros.umbrales, campo, getattr(de_matriz, campo))
        if parametros.umbrales.fuente == "pliego" and any(
            getattr(de_matriz, c) is not None for c in ("liquidez_min", "endeudamiento_max", "cobertura_min", "roa_min", "roe_min")
        ):
            parametros.umbrales.fuente = "pliego y Matriz 2"
    return parametros


def _de_la_matriz_por_rango(matriz2: bytes, parametros: ParametrosFinancieros, smmlv: float) -> Umbrales | None:
    """Los umbrales que la Matriz 2 misma señala para este proceso, o None si no
    se pudo entender (entonces se sigue preguntando a una persona).

    El rango sale del presupuesto del lote en SMMLV, que es el criterio que da
    la matriz. Entre sus dos tablas se toma la de los demás proponentes: la de
    Mipyme es más laxa y solo aplica a quien acredite esa condición, que es algo
    del proponente y no del proceso. Aplicarla a todos aprobaría a quien no
    cumple."""
    from motor.financiera.matriz2 import leer_matriz2
    from motor.procesamiento.documentos import texto_de_documento

    matriz = leer_matriz2(texto_de_documento(matriz2))
    if matriz is None:
        return None
    presupuestos = [l.presupuesto for l in parametros.lotes if l.presupuesto]
    if not presupuestos:
        return None
    # Con varios lotes, el más caro: es el que fija el rango más exigente de los
    # que puede tocarle a un proponente que se presente a uno solo.
    elegido = matriz.umbrales(max(presupuestos) / smmlv)
    if elegido is None:
        return None
    umbrales, fuente = elegido
    parametros.umbrales = umbrales
    de_mipyme = matriz.umbrales(max(presupuestos) / smmlv, mipyme=True)
    # Se guardan aparte para poder aplicarlos a quien acredite ser Mipyme con su
    # RUP. Aplicárselos a todos aprobaría a quien no cumple; no aplicárselos a
    # quien sí lo acredita rechazaría a quien sí cumplía, que es el otro riesgo.
    if de_mipyme is not None and de_mipyme[0] != umbrales:
        parametros.umbrales_mipyme = de_mipyme[0]
    return umbrales
