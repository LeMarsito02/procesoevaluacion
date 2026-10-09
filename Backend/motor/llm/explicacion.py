"""Explicación en palabras llanas de lo que el motor ya decidió.

Quien revisa es abogado, y el detalle del motor está escrito en la jerga del
pliego: "CRP sin calcular", "CO (mayor ingreso operacional)", "SCE sin leer".
Esto no reemplaza ese detalle —sigue ahí, porque es lo que se puede verificar
contra el documento— sino que lo acompaña con un párrafo que dice lo mismo en
español corriente.

Reglas, las mismas que para el resto de la IA local del proyecto:

- El modelo **no decide**. Recibe lo que el motor ya calculó y solo lo redacta.
  Ninguna respuesta cambia un cumple, un no cumple ni un punto por revisar.
- El modelo **no aporta datos**. Si en la explicación aparece una cifra que no
  venía en lo que se le pasó, la respuesta se descarta entera: preferimos no
  explicar nada antes que explicar un número inventado.
- Si el modelo no está, tarda o responde cualquier cosa, se devuelve None y la
  pantalla se queda con el detalle técnico de siempre.
- Nada sale del servidor: el modelo corre en local.
"""
from __future__ import annotations

import re

from motor.llm.cliente import consultar_json, respuesta_guardada

# Las siglas se le dan resueltas: si el modelo las define de memoria se
# equivoca (llamó a la capacidad residual "la capacidad financiera del
# candidato"), y una definición torcida confunde a quien revisa más que la
# jerga original.
_GLOSARIO = (
    "CRP: capacidad residual del proponente, el margen de contratación que le queda después de descontar lo que ya "
    "tiene en ejecución; el pliego exige un mínimo.\n"
    "CO: capacidad de organización, el mayor ingreso operacional de los años que pide el pliego.\n"
    "E: el factor de experiencia dentro de la fórmula de la capacidad residual, que da puntos.\n"
    "CT: capacidad técnica, el número de profesionales de planta del proponente, que da puntos.\n"
    "CF: capacidad financiera, que se mide con el índice de liquidez y da puntos.\n"
    "SCE: saldo de los contratos que el proponente tiene en ejecución, que se resta de su capacidad.\n"
    "SMMLV: salarios mínimos mensuales legales vigentes, la unidad en que el pliego mide la experiencia.\n"
    "RUP: Registro Único de Proponentes, el certificado de la cámara de comercio donde están inscritos los contratos "
    "que el proponente ya ejecutó.\n"
    "UNSPSC: el clasificador con que se codifican los contratos; el pliego exige unos códigos determinados.\n"
    "Formato 3: el formato donde el proponente lista los contratos con que acredita su experiencia.\n"
    "Formato 5C: el formato donde declara los contratos que tiene en ejecución.\n"
    "Acta o certificación del contrato: el documento con que el contratante prueba que el contrato se ejecutó."
)

_INSTRUCCION = (
    "Eres quien le explica a un abogado, en español claro, el resultado de una evaluación de un proceso de "
    "contratación pública colombiano. Te paso el resultado que ya calculó el programa.\n"
    "Escribe una explicación de dos a cuatro frases que diga, en palabras corrientes: qué se estaba verificando, "
    "qué se encontró y, si falta algo, qué tendría que mirar la persona que revisa.\n"
    "Reglas: no decidas nada (no digas si cumple o no cumple más allá de lo que ya dice el resultado); no agregues "
    "cifras, fechas ni nombres que no estén en el texto que te paso; no repitas la jerga, tradúcela; no uses "
    "viñetas; usa solo las definiciones de este glosario y no inventes otras.\n"
    "No enuncies la regla del pliego ni lo que el pliego exige si no aparece en el texto que te paso: no sabes qué "
    "dice ese pliego y equivocarte en el sentido de la regla es peor que no explicarla. Cuenta solo lo que el "
    "programa encontró y, si falta algo, qué documento habría que mirar.\n"
    f"Glosario:\n{_GLOSARIO}\n"
    'Responde solo con JSON: {"explicacion": "..."}'
)

# Cifras de tres dígitos o más: las que de verdad importan (valores, SMMLV,
# NIT, años). Las de uno o dos dígitos aparecen en cualquier frase ("dos
# contratos", "el 60%") y compararlas daría falsos positivos.
_CIFRA_RE = re.compile(r"\d[\d.,]{2,}")


def _cifras(texto: str) -> set[str]:
    return {re.sub(r"[.,]", "", c).lstrip("0") or "0" for c in _CIFRA_RE.findall(texto)}


def _inventa_cifras(explicacion: str, fuente: str) -> bool:
    """La explicación trae una cifra que no estaba en lo que se le pasó."""
    return bool(_cifras(explicacion) - _cifras(fuente))


def explicar(titulo: str, motivo: str, datos: str = "", por_revisar: list[str] | None = None,
             solo_guardada: bool = False) -> str | None:
    """El párrafo en palabras llanas, o None si no se pudo generar.
    `solo_guardada`: la que ya se redactó para este mismo resultado, sin llamar
    al modelo (para mostrarla al volver a abrir el requisito).

    `titulo` es el requisito ("Capacidad residual"), `motivo` lo que el motor
    concluyó, `datos` el detalle técnico tal como se le muestra a quien revisa y
    `por_revisar` los puntos que quedan pendientes en esa oferta."""
    partes = [f"Requisito: {titulo}"]
    if motivo:
        partes.append(f"Resultado del programa: {motivo}")
    if datos:
        partes.append(f"Detalle: {datos}")
    for punto in por_revisar or []:
        partes.append(f"Por revisar: {punto}")
    fuente = "\n".join(partes)
    if len(fuente) < 20:
        return None

    respuesta = respuesta_guardada(_INSTRUCCION, fuente) if solo_guardada else consultar_json(_INSTRUCCION, fuente)
    if not respuesta:
        return None
    explicacion = str(respuesta.get("explicacion") or "").strip()
    if len(explicacion) < 30 or len(explicacion) > 1200:
        return None
    if _inventa_cifras(explicacion, fuente):
        return None
    return explicacion
