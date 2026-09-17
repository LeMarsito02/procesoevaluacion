"""Multas, sanciones y declaratorias de incumplimiento reportadas en el RUP.

Dos reglas distintas, según el criterio del abogado:

1. **Artículo 58 de la Ley 2195 de 2022** (reducción de puntaje): aplica a las
   multas o cláusulas penales impuestas durante el **último año** contado hacia
   atrás desde la fecha de cierre. Si la multa quedó fuera de ese año, el
   requisito se aprueba; si está dentro, se rechaza.

2. **Artículo 90 de la Ley 1474 de 2011** (inhabilidad por incumplimiento
   reiterado): dentro de una **misma vigencia fiscal** (año), el proponente
   incurrió en 5 o más multas, o 2 o más declaratorias de incumplimiento en al
   menos 2 contratos, o 2 multas más 1 declaratoria de incumplimiento.

Cuando una sanción no se puede interpretar (sin fecha legible, por ejemplo) el
requisito queda para revisión con el dato exacto que se leyó: nunca se aprueba
con información dudosa.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from dateutil.relativedelta import relativedelta

from motor import criterios

# Cada sanción empieza con la entidad que la reportó. Los tres formatos reales
# revisados (Barranquilla, Medellín y Bogotá) usan esta misma línea.
INICIO_RE = re.compile(r"ENTIDAD QUE REPORTO LA (SANCION|MULTA|INHABILIDAD|DECLARATORIA DE INCUMPLIMIENTO)\s*:?")
FECHA_RE = re.compile(r"\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b|\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
CAMPO_ACTO_RE = re.compile(r"QUE LA IMPUSO\s*:?(.{0,160})", re.S)
CAMPO_EJECUTORIA_RE = re.compile(r"EJECUTORIA\s*:?(.{0,160})", re.S)
CAMPO_CONTRATO_RE = re.compile(r"CONTRATO AFECTADO\s*:?\s*(.{0,80}?)(?:DESCRIPCION|VALOR|FECHA|NUMERO DE REGISTRO|ENTIDAD|$)", re.S)
CAMPO_DESCRIPCION_RE = re.compile(r"DESCRIPCION DE LA (?:SANCION|MULTA)\s*:?\s*(.{0,400}?)(?:LA SANCION ES|FECHA DE|NUMERO DE REGISTRO|ENTIDAD QUE|$)", re.S)
CAMPO_INCUMPLIMIENTO_RE = re.compile(r"LA SANCION ES INCUMPLIMIENTO\s*\(?SI O NO\)?\s*:?\s*(SI|NO)")
CAMPO_VALOR_RE = re.compile(r"VALOR DE LA MULTA EN PESOS\s*:?\s*([\d.,]+)")
# El texto del RUP a veces llega con caracteres dañados ("CLÃÂ¡USULA PENAL").
CLAUSULA_PENAL_RE = re.compile(r"CL.{0,4}USULA PENAL")
MENCIONA_INCUMPLIMIENTO_RE = re.compile(r"INCUMPLIMIENTO|CADUCIDAD")
HAY_SANCIONES_RE = re.compile(r"ENTIDAD QUE REPORTO LA (?:SANCION|MULTA|INHABILIDAD|DECLARATORIA)|DESCRIPCION DE LA (?:SANCION|MULTA)")


@dataclass
class Sancion:
    tipo: str  # multa | declaratoria | sancion
    entidad: str
    contrato: str
    descripcion: str
    fecha: date | None  # ejecutoria o, si no hay, la del acto administrativo
    valor: str
    es_incumplimiento: bool
    clausula_penal: bool

    @property
    def cuenta_como_multa(self) -> bool:
        """Multas y cláusulas penales (art. 58 y el conteo de multas del art. 90)."""
        return self.tipo == "multa" or self.clausula_penal

    @property
    def cuenta_como_incumplimiento(self) -> bool:
        return self.tipo == "declaratoria" or self.es_incumplimiento

    @property
    def contradictoria(self) -> bool:
        """La descripción habla de incumplimiento pero la casilla dice que no."""
        return (
            self.tipo == "sancion"
            and not self.es_incumplimiento
            and bool(MENCIONA_INCUMPLIMIENTO_RE.search(self.descripcion))
        )


def _fecha(texto: str) -> date | None:
    m = FECHA_RE.search(texto)
    if not m:
        return None
    g = m.groups()
    try:
        return date(int(g[0]), int(g[1]), int(g[2])) if g[0] else date(int(g[5]), int(g[4]), int(g[3]))
    except (TypeError, ValueError):
        return None


def _limpiar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip(" :.-")[:200]


def extraer_sanciones(texto_norm: str) -> list[Sancion]:
    """Lee la sección de multas/sanciones del RUP (texto ya normalizado)."""
    inicios = list(INICIO_RE.finditer(texto_norm))
    sanciones: list[Sancion] = []
    for i, inicio in enumerate(inicios):
        fin = inicios[i + 1].start() if i + 1 < len(inicios) else min(len(texto_norm), inicio.end() + 1200)
        bloque = texto_norm[inicio.end() : fin]
        etiqueta = inicio.group(1)
        descripcion = _limpiar(CAMPO_DESCRIPCION_RE.search(bloque).group(1)) if CAMPO_DESCRIPCION_RE.search(bloque) else ""
        incumplimiento = CAMPO_INCUMPLIMIENTO_RE.search(bloque)
        acto = CAMPO_ACTO_RE.search(bloque)
        ejecutoria = CAMPO_EJECUTORIA_RE.search(bloque)
        fecha = _fecha(ejecutoria.group(1)) if ejecutoria else None
        if fecha is None and acto:
            fecha = _fecha(acto.group(1))
        if fecha is None:
            fecha = _fecha(bloque)
        if etiqueta == "MULTA":
            tipo = "multa"
        elif etiqueta.startswith("DECLARATORIA"):
            tipo = "declaratoria"
        else:
            tipo = "sancion"
        sanciones.append(
            Sancion(
                tipo=tipo,
                entidad=_limpiar(bloque[:120].split("DOCUMENTO")[0]),
                contrato=_limpiar(CAMPO_CONTRATO_RE.search(bloque).group(1)) if CAMPO_CONTRATO_RE.search(bloque) else "",
                descripcion=descripcion,
                fecha=fecha,
                valor=CAMPO_VALOR_RE.search(bloque).group(1) if CAMPO_VALOR_RE.search(bloque) else "",
                es_incumplimiento=bool(incumplimiento and incumplimiento.group(1) == "SI"),
                clausula_penal=bool(CLAUSULA_PENAL_RE.search(descripcion or bloque)),
            )
        )
    return sanciones


def _texto(s: Sancion) -> str:
    partes = [{"multa": "multa", "declaratoria": "declaratoria de incumplimiento"}.get(s.tipo, "sanción")]
    if s.clausula_penal:
        partes.append("(cláusula penal)")
    if s.entidad:
        partes.append(f"de {s.entidad}")
    if s.contrato:
        partes.append(f"contrato {s.contrato}")
    if s.valor:
        partes.append(f"por ${s.valor}")
    partes.append(f"del {s.fecha:%d/%m/%Y}" if s.fecha else "sin fecha legible")
    return " ".join(partes)


def unificar(sanciones: list[Sancion]) -> list[Sancion]:
    """Un mismo hecho aparece dos veces en el RUP (en «SANCIONES» y otra vez en
    «DECLARATORIAS DE INCUMPLIMIENTO», con el mismo contrato y la misma fecha).
    Se cuenta una sola vez para no inventar un incumplimiento reiterado."""
    unicos: dict[tuple, Sancion] = {}
    for s in sanciones:
        clave = (s.entidad, s.contrato, s.fecha)
        previa = unicos.get(clave)
        if previa is None:
            unicos[clave] = s
            continue
        previa.es_incumplimiento = previa.es_incumplimiento or s.es_incumplimiento or s.tipo == "declaratoria"
        previa.clausula_penal = previa.clausula_penal or s.clausula_penal
        previa.valor = previa.valor or s.valor
        previa.descripcion = previa.descripcion or s.descripcion
        if previa.tipo == "sancion" and s.tipo == "multa":
            previa.tipo = "multa"
    return list(unicos.values())


def evaluar_sanciones(sanciones: list[Sancion], fecha_cierre: date) -> tuple[bool, str | None]:
    """Aplica las dos reglas. Devuelve (cumple, motivo)."""
    if not sanciones:
        return True, None
    sanciones = unificar(sanciones)

    meses = int(criterios.valor("sanciones_meses"))
    tope_multas = int(criterios.valor("inhabilidad_multas"))
    tope_incumplimientos = int(criterios.valor("inhabilidad_incumplimientos"))
    tope_mixto = int(criterios.valor("inhabilidad_multas_con_incumplimiento"))
    desde = fecha_cierre - relativedelta(months=meses)

    dudosas = [s for s in sanciones if s.contradictoria]
    if dudosas:
        return False, (
            "el RUP se contradice en "
            + "; ".join(f"{_texto(s)}: la describe como «{s.descripcion}» pero marca «INCUMPLIMIENTO: NO»" for s in dudosas)
            + " — revísalo con la entidad que la reportó"
        )

    sin_fecha = [s for s in sanciones if s.fecha is None]
    if sin_fecha:
        return False, (
            "el RUP reporta " + "; ".join(_texto(s) for s in sanciones)
            + f" — no se pudo leer la fecha de {len(sin_fecha)} de ellas, revísalas manualmente"
        )

    # Artículo 58 de la Ley 2195 de 2022: multas o cláusulas penales del último año.
    recientes = [s for s in sanciones if s.cuenta_como_multa and desde <= s.fecha <= fecha_cierre]
    # Artículo 90 de la Ley 1474 de 2011: incumplimiento reiterado en una vigencia fiscal.
    por_anio: dict[int, list[Sancion]] = defaultdict(list)
    for s in sanciones:
        por_anio[s.fecha.year].append(s)
    inhabilidades = []
    for anio, grupo in sorted(por_anio.items()):
        multas = [s for s in grupo if s.cuenta_como_multa]
        incumplimientos = [s for s in grupo if s.cuenta_como_incumplimiento]
        contratos = {s.contrato for s in incumplimientos if s.contrato}
        if len(multas) >= tope_multas:
            inhabilidades.append(f"{len(multas)} multas en {anio}")
        elif len(incumplimientos) >= tope_incumplimientos and len(contratos) >= 2:
            inhabilidades.append(f"{len(incumplimientos)} declaratorias de incumplimiento en {anio} ({len(contratos)} contratos)")
        elif len(multas) >= tope_mixto and incumplimientos:
            inhabilidades.append(f"{len(multas)} multas y {len(incumplimientos)} declaratoria(s) de incumplimiento en {anio}")

    detalle = "; ".join(_texto(s) for s in sanciones)
    if inhabilidades:
        return False, (
            f"posible inhabilidad por incumplimiento reiterado (art. 90 de la Ley 1474 de 2011): {', '.join(inhabilidades)}. "
            f"El RUP reporta: {detalle}"
        )
    if recientes:
        return False, (
            f"reporta {len(recientes)} multa(s) o cláusula(s) penal(es) impuestas en los últimos {meses} meses "
            f"antes del cierre ({desde:%d/%m/%Y} a {fecha_cierre:%d/%m/%Y}), lo que afecta la evaluación según el "
            f"art. 58 de la Ley 2195 de 2022: " + "; ".join(_texto(s) for s in recientes)
        )
    return True, (
        f"El RUP reporta sanciones anteriores al periodo evaluado ({desde:%d/%m/%Y} a {fecha_cierre:%d/%m/%Y}) y sin "
        f"incumplimiento reiterado: {detalle}"
    )
