"""Factor económico de los Documentos Tipo de Colombia Compra Eficiente (RF-11).

El método de ponderación lo escoge la TRM: sus centavos caen en uno de cuatro
rangos que fija el pliego. Las versiones vigentes de los Documentos Tipo
(p. ej. CCE-EICP-GI-01 v8, 2025) usan mediana con valor absoluto, media
geométrica, media aritmética baja y menor valor; las anteriores usaban media
aritmética, media aritmética alta, media geométrica con presupuesto oficial y
menor valor. Aquí están los siete: el pliego de cada proceso dice cuáles y en
qué rangos.

Reglas comunes (Documentos Tipo):
- Se califica el valor total corregido de las propuestas válidas (no
  rechazadas ni declaradas artificialmente bajas).
- El puntaje se toma hasta el séptimo decimal; un puntaje negativo es cero.
- En procesos por lotes, la TRM define el método del primer lote y los
  siguientes toman el método siguiente de la tabla, en orden y volviendo al
  primero al terminar.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal

MEDIANA_VALOR_ABSOLUTO = "mediana_valor_absoluto"
MEDIA_GEOMETRICA = "media_geometrica"
MEDIA_ARITMETICA_BAJA = "media_aritmetica_baja"
MENOR_VALOR = "menor_valor"
MEDIA_ARITMETICA = "media_aritmetica"
MEDIA_ARITMETICA_ALTA = "media_aritmetica_alta"
MEDIA_GEOMETRICA_PRESUPUESTO = "media_geometrica_presupuesto"

NOMBRES = {
    MEDIANA_VALOR_ABSOLUTO: "Mediana con valor absoluto",
    MEDIA_GEOMETRICA: "Media geométrica",
    MEDIA_ARITMETICA_BAJA: "Media aritmética baja",
    MENOR_VALOR: "Menor valor",
    MEDIA_ARITMETICA: "Media aritmética",
    MEDIA_ARITMETICA_ALTA: "Media aritmética alta",
    MEDIA_GEOMETRICA_PRESUPUESTO: "Media geométrica con presupuesto oficial",
}
# (desde, hasta) en centavos, inclusive, y el método de cada rango.
RANGOS_VIGENTES: list[tuple[int, int, str]] = [
    (0, 24, MEDIANA_VALOR_ABSOLUTO), (25, 49, MEDIA_GEOMETRICA), (50, 74, MEDIA_ARITMETICA_BAJA), (75, 99, MENOR_VALOR),
]
RANGOS_ANTERIORES: list[tuple[int, int, str]] = [
    (0, 24, MEDIA_ARITMETICA), (25, 49, MEDIA_ARITMETICA_ALTA), (50, 74, MEDIA_GEOMETRICA_PRESUPUESTO), (75, 99, MENOR_VALOR),
]
DECIMALES = Decimal("0.0000001")


class ErrorPonderacion(ValueError):
    pass


@dataclass
class Calificacion:
    metodo: str
    referencia: float | None  # mediana, media… contra la que se compara
    puntajes: dict[str, float] = field(default_factory=dict)
    explicacion: str = ""


def centavos(trm: Decimal | float | str) -> int:
    """Los centavos de la TRM (4.123,57 → 57)."""
    valor = Decimal(str(trm))
    return int((valor - valor.to_integral_value(rounding=ROUND_DOWN)) * 100)


def metodo_por_trm(trm, rangos: list[tuple[int, int, str]] | None = None, lote: int = 1) -> str:
    """El método del lote `lote` (1 = el primero que se adjudica)."""
    rangos = rangos or RANGOS_VIGENTES
    c = centavos(trm)
    indice = next((i for i, (a, b, _) in enumerate(rangos) if a <= c <= b), None)
    if indice is None:
        raise ErrorPonderacion(f"Los centavos de la TRM ({c}) no caen en ningún rango del pliego.")
    return rangos[(indice + lote - 1) % len(rangos)][2]


def _recortar(p: float) -> float:
    if p <= 0:
        return 0.0
    return float(Decimal(repr(p)).quantize(DECIMALES, rounding=ROUND_DOWN))


def _cercania(ref: float, v: float, maximo: float, castigo_superior: float = 1) -> float:
    """maximo × (1 − |ref − v| / ref); por encima de ref, la diferencia pesa `castigo_superior` veces."""
    factor = castigo_superior if v > ref else 1
    return maximo * (1 - factor * abs(ref - v) / ref)


def veces_presupuesto(n: int) -> int:
    """Cuántas veces entra el presupuesto oficial en la media geométrica según el
    número de ofertas válidas (1 a 3 ofertas: una vez; 4 a 6: dos; …)."""
    return max(1, math.ceil(n / 3))


def calificar(valores: dict[str, float], metodo: str, puntaje_maximo: float, presupuesto: float | None = None) -> Calificacion:
    """Puntaje de cada propuesta válida (clave → valor total corregido)."""
    if not valores:
        raise ErrorPonderacion("No hay propuestas válidas para calificar.")
    if any(v <= 0 for v in valores.values()):
        raise ErrorPonderacion("Hay propuestas con valor cero o negativo.")
    v = list(valores.values())
    maximo = puntaje_maximo
    puntajes: dict[str, float] = {}
    ref: float | None = None
    explicacion = ""
    if metodo == MEDIANA_VALOR_ABSOLUTO:
        ordenados = sorted(v)
        mediana = statistics.median(ordenados)
        if len(v) % 2 == 1:
            ref = mediana
            explicacion = "Número impar de propuestas: el máximo puntaje es para la que está en la mediana."
        else:
            ref = max(x for x in ordenados if x < mediana) if any(x < mediana for x in ordenados) else mediana
            explicacion = f"Número par de propuestas: mediana {mediana:,.2f}; el máximo es para la inmediatamente por debajo."
        for k, x in valores.items():
            puntajes[k] = maximo if x == ref else maximo * (1 - abs((ref - x) / ref))
    elif metodo == MEDIA_GEOMETRICA:
        ref = math.exp(sum(math.log(x) for x in v) / len(v))
        cercana = min(valores, key=lambda k: abs(valores[k] - ref))
        for k, x in valores.items():
            puntajes[k] = maximo if k == cercana else maximo * (1 - abs(ref - x) / ref)
        explicacion = "Máximo puntaje para la más cercana (por exceso o por defecto) a la media geométrica."
    elif metodo == MEDIA_ARITMETICA_BAJA:
        ref = (min(v) + statistics.mean(v)) / 2
        for k, x in valores.items():
            puntajes[k] = maximo * (1 - abs(ref - x) / ref)
    elif metodo == MENOR_VALOR:
        ref = min(v)
        for k, x in valores.items():
            puntajes[k] = maximo * ref / x
    elif metodo in (MEDIA_ARITMETICA, MEDIA_ARITMETICA_ALTA):
        media = statistics.mean(v)
        ref = media if metodo == MEDIA_ARITMETICA else (max(v) + media) / 2
        for k, x in valores.items():
            puntajes[k] = _cercania(ref, x, maximo, castigo_superior=2)
    elif metodo == MEDIA_GEOMETRICA_PRESUPUESTO:
        if not presupuesto:
            raise ErrorPonderacion("La media geométrica con presupuesto oficial necesita el presupuesto oficial.")
        nv = veces_presupuesto(len(v))
        ref = math.exp((nv * math.log(presupuesto) + sum(math.log(x) for x in v)) / (nv + len(v)))
        for k, x in valores.items():
            puntajes[k] = _cercania(ref, x, maximo, castigo_superior=2)
        explicacion = f"El presupuesto oficial entra {nv} veces en la media geométrica."
    else:
        raise ErrorPonderacion(f"Método desconocido: {metodo}.")
    return Calificacion(metodo, ref, {k: _recortar(p) for k, p in puntajes.items()}, explicacion)


# --- Ofertas artificialmente bajas (Guía CCE-EICP-GI-27, 2024) ---------------
OFERTAS_PARA_COMPARACION_RELATIVA = 5
UMBRAL_ABSOLUTO = 0.20


@dataclass
class AlertaBaja:
    clave: str
    valor: float
    motivo: str


@dataclass
class AnalisisBajas:
    metodo: str  # "relativa" o "absoluta"
    explicacion: str
    valor_minimo_aceptable: float | None
    alertas: list[AlertaBaja] = field(default_factory=list)


def ofertas_bajas(valores: dict[str, float], costo_estimado: float | None) -> AnalisisBajas:
    """Con 5 o más ofertas, comparación relativa: valor mínimo aceptable =
    mediana − desviación estándar poblacional. Con menos, comparación absoluta:
    ofertas 20 % o más por debajo del costo estimado por la entidad. Es una
    alerta para pedir justificación, no un rechazo."""
    if len(valores) >= OFERTAS_PARA_COMPARACION_RELATIVA:
        v = list(valores.values())
        mediana, desviacion = statistics.median(v), statistics.pstdev(v)
        minimo = mediana - desviacion
        alertas = [AlertaBaja(k, x, f"Está por debajo del valor mínimo aceptable ({minimo:,.0f})".replace(",", ".") + ".")
                   for k, x in valores.items() if x < minimo]
        return AnalisisBajas("relativa", f"{len(v)} ofertas: mediana {mediana:,.0f} menos desviación estándar {desviacion:,.0f}.".replace(",", "."),
                             minimo, alertas)
    if not costo_estimado:
        return AnalisisBajas("absoluta", "Menos de 5 ofertas y sin costo estimado: no se puede aplicar la guía.", None)
    alertas = []
    for k, x in valores.items():
        variacion = (costo_estimado - x) / costo_estimado
        if variacion >= UMBRAL_ABSOLUTO:
            alertas.append(AlertaBaja(k, x, f"Está {variacion * 100:.1f} % por debajo del costo estimado.".replace(".", ",", 1)))
    return AnalisisBajas(
        "absoluta", f"Menos de 5 ofertas: se compara con el costo estimado ({costo_estimado:,.0f}); alerta desde 20 % por debajo.".replace(",", "."),
        costo_estimado * (1 - UMBRAL_ABSOLUTO), alertas,
    )
