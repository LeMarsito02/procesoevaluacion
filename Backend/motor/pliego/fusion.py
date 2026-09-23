"""Junta lo que el pliego dice según las reglas y según la IA local.

Las reglas (expresiones regulares) son exactas pero frágiles: aciertan con la
redacción del documento tipo y se quedan mudas con cualquier variante. La IA
lee como una persona pero se equivoca de vez en cuando. Aquí se juntan con
una regla de oro:

    ningún proponente se aprueba solo con un dato que solo vio la IA y que
    nadie confirmó.

Cada parámetro queda con su procedencia:

- "regla"      lo leyeron las reglas del motor           -> se evalúa como siempre
- "regla+ia"   lo leyeron las dos y coinciden            -> se evalúa como siempre
- "ia"         solo lo leyó la IA                        -> se usa, pero el lote va a revisión
- "conflicto"  las dos lo leyeron y no coinciden         -> manda la regla y el lote va a revisión
- "persona"    alguien lo confirmó o lo corrigió         -> se evalúa como siempre

Así un pliego nuevo se evalúa desde el primer día (la IA lo entiende) sin que
un error de lectura pueda aprobar a nadie: lo que la IA aportó se revisa una
vez, se confirma, y a partir de ahí el proceso corre solo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from motor.pliego.parametros_ia import Leido, ParametrosIA

# Procedencias que permiten aprobar sin que una persona mire.
EN_FIRME = ("regla", "regla+ia", "persona")


@dataclass
class Procedencia:
    """De dónde salió un parámetro y qué dice el pliego al respecto."""

    campo: str
    origen: str
    valor_regla: object = None
    valor_ia: object = None
    cita: str = ""
    seccion: str = ""

    @property
    def en_firme(self) -> bool:
        return self.origen in EN_FIRME

    def explicacion(self) -> str:
        nombre = self.campo.replace("_", " ")
        if self.origen == "ia":
            return f"«{nombre}» lo leyó la IA del pliego y nadie lo ha confirmado: {self.cita[:160]}"
        if self.origen == "conflicto":
            return (f"«{nombre}»: las reglas leyeron {self.valor_regla!r} y la IA {self.valor_ia!r}; "
                    f"se usó el de las reglas. Cita de la IA: {self.cita[:120]}")
        return f"«{nombre}» = {self.valor_regla!r} ({self.origen})"


@dataclass
class Fusion:
    """Resultado de juntar las dos lecturas."""

    procedencias: dict[str, Procedencia] = field(default_factory=dict)

    @property
    def sin_confirmar(self) -> list[Procedencia]:
        return [p for p in self.procedencias.values() if not p.en_firme]

    def avisos(self) -> list[str]:
        return [p.explicacion() for p in self.sin_confirmar]


def _igual(a, b) -> bool:
    """Dos lecturas dicen lo mismo: los números con tolerancia, los textos por
    sus palabras (la IA copia con otra puntuación o sin tildes)."""
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= max(0.005, abs(float(a)) * 0.02)
    if isinstance(a, (list, set, tuple)) or isinstance(b, (list, set, tuple)):
        return set(a or []) == set(b or [])
    pa, pb = _palabras(str(a)), _palabras(str(b))
    if not pa or not pb:
        return False
    return len(pa & pb) >= 0.8 * min(len(pa), len(pb))


def _palabras(texto: str) -> set[str]:
    import unicodedata

    t = unicodedata.normalize("NFKD", texto.upper())
    return set(re.findall(r"[A-Z0-9]{3,}", "".join(c for c in t if not unicodedata.combining(c))))


def fundir(campo: str, de_la_regla, de_la_ia: Leido | None, confirmados: dict[str, object] | None = None):
    """(valor, procedencia) de un parámetro. `confirmados` trae lo que una
    persona revisó en la plataforma, que manda sobre todo lo demás."""
    if confirmados and campo in confirmados:
        valor = confirmados[campo]
        return valor, Procedencia(campo, "persona", valor_regla=valor)
    valor_ia = de_la_ia.valor if de_la_ia is not None else None
    cita = de_la_ia.cita if de_la_ia is not None else ""
    seccion = de_la_ia.seccion if de_la_ia is not None else ""
    if de_la_regla is not None and valor_ia is not None:
        if _igual(de_la_regla, valor_ia):
            return de_la_regla, Procedencia(campo, "regla+ia", de_la_regla, valor_ia, cita, seccion)
        # Discrepan: manda la regla (es exacta cuando acierta) y se avisa.
        return de_la_regla, Procedencia(campo, "conflicto", de_la_regla, valor_ia, cita, seccion)
    if de_la_regla is not None:
        return de_la_regla, Procedencia(campo, "regla", de_la_regla)
    if valor_ia is not None:
        return valor_ia, Procedencia(campo, "ia", None, valor_ia, cita, seccion)
    return None, Procedencia(campo, "no leido")


def _del_lote(mapa: dict[str, Leido], lote: str, total_lotes: int) -> Leido | None:
    """El valor que la IA leyó para ese lote. Si el proceso tiene varios
    lotes y la IA no los distinguió (lo dejó todo en "ÚNICO"), no se usa: un
    parámetro del lote 1 aplicado al lote 2 evalúa mal."""
    if lote in mapa:
        return mapa[lote]
    if total_lotes == 1:
        return mapa.get("ÚNICO") or (next(iter(mapa.values())) if len(mapa) == 1 else None)
    return None


def sin_verificar(ia: ParametrosIA | None) -> list[str]:
    """Lo que el pliego le exige al proponente y el motor no sabe comprobar.
    Mientras haya algo aquí, ningún lote se aprueba solo: se evalúa lo que se
    puede y esto queda escrito para que lo mire una persona.

    Es lo que hace al programa compatible con cualquier pliego: no necesita
    conocer de antemano todos los requisitos posibles, necesita no dar por
    cumplido lo que no miró."""
    from motor.pliego.catalogo_tecnico import cobertura

    if ia is None or not ia.requisitos:
        return []
    _, faltantes = cobertura([(str(r.valor), r.cita) for r in ia.requisitos])
    return [f"{requisito} — pliego: «{cita[:140]}»" for requisito, cita in faltantes]


def aplicar_a_tecnicos(parametros, ia: ParametrosIA | None, confirmados: dict | None = None) -> Fusion:
    """Completa los parámetros técnicos con lo que leyó la IA y deja dicho de
    dónde salió cada cosa. No cambia nada que las reglas ya hayan leído."""
    fusion = Fusion()
    if ia is None:
        return fusion

    def poner(objeto, campo: str, valor_ia: Leido | None, etiqueta: str | None = None) -> None:
        clave = etiqueta or campo
        valor, procedencia = fundir(clave, getattr(objeto, campo, None) or None, valor_ia, confirmados)
        if valor is not None:
            setattr(objeto, campo, valor)
        if procedencia.origen != "no leido":
            fusion.procedencias[clave] = procedencia

    total = len(parametros.lotes)
    for lote in parametros.lotes:
        nombre = lote.nombre.upper()
        poner(lote, "experiencia_general", _del_lote(ia.experiencia_general, nombre, total), f"experiencia general {lote.nombre}")
        poner(lote, "experiencia_especifica", _del_lote(ia.experiencia_especifica, nombre, total), f"experiencia específica {lote.nombre}")
        poner(lote, "condicion_objeto", _del_lote(ia.condicion_objeto, nombre, total), f"condición de objeto {lote.nombre}")
        poner(lote, "fraccion_un_contrato", _del_lote(ia.fraccion_un_contrato, nombre, total), f"porcentaje de un contrato {lote.nombre}")
        poner(lote, "longitud_minima_km", _del_lote(ia.longitud_minima_km, nombre, total), f"longitud mínima {lote.nombre}")
    if ia.clases_unspsc is not None:
        valor, procedencia = fundir("códigos UNSPSC", sorted(parametros.clases_unspsc) or None, ia.clases_unspsc, confirmados)
        if valor:
            parametros.clases_unspsc = set(valor)
        fusion.procedencias["códigos UNSPSC"] = procedencia
    if ia.max_contratos is not None:
        valor, procedencia = fundir("máximo de contratos", parametros.max_contratos, ia.max_contratos, confirmados)
        if valor:
            parametros.max_contratos = int(valor)
        fusion.procedencias["máximo de contratos"] = procedencia
    for clave, leido in ia.puntajes.items():
        actual = parametros.puntajes.get(clave)
        # Un factor que el pliego declara "no aplica" vale 0 en las dos
        # lecturas: se comparan como números.
        valor, procedencia = fundir(f"puntaje {clave}", actual, leido, confirmados)
        if clave not in parametros.puntajes and valor is not None:
            parametros.puntajes[clave] = float(valor)
            parametros.factores_nombrados.add(clave)
        fusion.procedencias[f"puntaje {clave}"] = procedencia
    return fusion


def aplicar_a_financieros(parametros, ia: ParametrosIA | None, confirmados: dict | None = None) -> Fusion:
    """Igual que el anterior, para los parámetros financieros: umbrales,
    anticipo, plazo y porcentaje de capital de trabajo."""
    fusion = Fusion()
    if ia is None:
        return fusion
    for campo in ("liquidez_min", "endeudamiento_max", "cobertura_min", "roa_min", "roe_min"):
        valor, procedencia = fundir(campo, getattr(parametros.umbrales, campo, None), getattr(ia, campo), confirmados)
        if valor is not None:
            setattr(parametros.umbrales, campo, valor)
        if procedencia.origen != "no leido":
            fusion.procedencias[campo] = procedencia
    total = len(parametros.lotes)
    for lote in parametros.lotes:
        nombre = lote.nombre.upper()
        valor, procedencia = fundir(f"anticipo {lote.nombre}", lote.anticipo, ia.anticipo, confirmados)
        if valor is not None:
            lote.anticipo = valor
        if procedencia.origen != "no leido":
            fusion.procedencias[f"anticipo {lote.nombre}"] = procedencia
        valor, procedencia = fundir(f"plazo {lote.nombre}", lote.plazo_meses,
                                    _del_lote(ia.plazo_meses, nombre, total), confirmados)
        if valor is not None:
            lote.plazo_meses = valor
        if procedencia.origen != "no leido":
            fusion.procedencias[f"plazo {lote.nombre}"] = procedencia
    return fusion
