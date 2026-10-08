"""Idoneidad y experiencia de un contratista frente al perfil del estudio previo.

Junta lo leído (títulos y periodos) con el perfil y la tabla de honorarios de
la entidad, y deja lo que necesita el certificado de idoneidad: la experiencia
en línea, su total, la franja en la que cae y si los honorarios pactados caben
en el tope. Lo que no se pudo establecer queda en `revisiones`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from motor.ops.experiencia import ExperienciaLineal, Periodo, Tramo, ajustar_a_franja, poner_en_linea
from motor.ops.honorarios import SIN_POSGRADO, FranjaProfesional, TablaHonorarios, posgrado_mayor
from motor.ops.relacion import obligaciones_iguales
from motor.ops.tiempo import DIAS_ANIO, texto_duracion
from motor.ops.titulos import Titulo, fecha_de_grado


@dataclass
class Perfil:
    """Lo que pide el estudio previo."""

    anios_minimos: float
    anios_maximos: float | None
    posgrado: str = SIN_POSGRADO
    honorarios_mensuales: int = 0
    # Obligaciones específicas del contratista, para reconocer la experiencia relacionada.
    obligaciones: list[str] = field(default_factory=list)
    # Experiencia específica (calificada) que además exige el perfil, en años.
    # Con ella la tabla de honorarios reconoce un valor adicional.
    especifica_minima: float = 0
    especifica_maxima: float | None = None
    # La frase del estudio previo que define el perfil, tal como está escrita.
    descripcion: str = ""


@dataclass
class Reglas:
    # La experiencia profesional cuenta desde el grado; en False cuenta toda.
    desde_el_grado: bool = True
    # Contar el día de inicio y el de terminación de cada periodo.
    ambos_extremos: bool = True


@dataclass
class Idoneidad:
    lineal: ExperienciaLineal
    # Tramos que sobran para quedar dentro de la franja del perfil.
    retirar: list[Tramo]
    grado: date | None
    posgrado: str
    dias_relacionada: int
    franja: FranjaProfesional | None
    tope: int | None
    revisiones: list[str] = field(default_factory=list)

    @property
    def dias(self) -> int:
        """Experiencia que queda después de retirar lo que sobra."""
        return self.lineal.dias - sum(t.dias for t in self.retirar)


def evaluar_idoneidad(
    periodos: list[Periodo], titulos: list[Titulo], perfil: Perfil, tabla: TablaHonorarios | None = None,
    reglas: Reglas | None = None, avisos: list[str] | None = None,
) -> Idoneidad:
    reglas = reglas or Reglas()
    revisiones = list(avisos or [])
    grado = fecha_de_grado(titulos)
    if reglas.desde_el_grado and grado is None:
        revisiones.append("No se leyó la fecha de grado: la experiencia se contó completa y hay que confirmar desde cuándo cuenta.")

    for periodo in periodos:
        if perfil.obligaciones and periodo.texto and not periodo.relacionada:
            periodo.obligaciones_iguales = obligaciones_iguales(perfil.obligaciones, periodo.texto)
            periodo.relacionada = bool(periodo.obligaciones_iguales)

    desde = grado if reglas.desde_el_grado else None
    lineal = poner_en_linea(periodos, desde, reglas.ambos_extremos)
    retirar = ajustar_a_franja(lineal, perfil.anios_minimos, perfil.anios_maximos)
    relacionada = poner_en_linea([p for p in periodos if p.relacionada], desde, reglas.ambos_extremos).dias
    posgrado = posgrado_mayor([t.nivel for t in titulos])

    resultado = Idoneidad(lineal, retirar, grado, posgrado, relacionada, None, None, revisiones)
    for tramo in lineal.tramos:
        if tramo.periodo.abierto:
            revisiones.append(
                f"{tramo.periodo.referencia or tramo.periodo.entidad or 'Una certificación'} no trae fecha de terminación: "
                f"se contó hasta el {tramo.fin:%d/%m/%Y}, cuando se expidió."
            )
    if resultado.dias < perfil.anios_minimos * DIAS_ANIO:
        revisiones.append(
            f"La experiencia acreditada ({texto_duracion(resultado.dias)}) no llega a los {perfil.anios_minimos:g} años del perfil."
        )
    elif perfil.anios_maximos is not None and resultado.dias > perfil.anios_maximos * DIAS_ANIO:
        revisiones.append(
            f"La experiencia acreditada ({texto_duracion(resultado.dias)}) pasa de los {perfil.anios_maximos:g} años del perfil "
            "con los periodos que se conservan."
        )
    pide_especifica = perfil.especifica_minima > 0 or perfil.especifica_maxima is not None
    if pide_especifica and relacionada < perfil.especifica_minima * DIAS_ANIO:
        revisiones.append(
            f"El perfil pide {perfil.especifica_minima:g} años de experiencia específica y hay {texto_duracion(relacionada)} marcados como "
            "relacionados: marque los periodos que la acreditan."
        )
    if tabla:
        resultado.franja = tabla.franja(resultado.dias)
        if resultado.franja:
            # El reconocimiento por experiencia específica solo aplica si el
            # perfil la pide, y hasta la franja que pide.
            reconocida = relacionada if pide_especifica else 0
            if perfil.especifica_maxima is not None:
                reconocida = min(reconocida, int(perfil.especifica_maxima * DIAS_ANIO) - 1)
            resultado.tope = resultado.franja.tope(posgrado) + tabla.valor_reconocimiento(reconocida)
            if perfil.honorarios_mensuales > resultado.tope:
                revisiones.append(
                    f"Los honorarios (${perfil.honorarios_mensuales:,}) superan el tope de la franja {resultado.franja.nombre} "
                    f"(${resultado.tope:,}).".replace(",", ".")
                )
    return resultado
