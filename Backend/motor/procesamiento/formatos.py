"""Cómo se busca un formato del pliego entre los documentos de una oferta.

El número con que un pliego llama a sus formatos no identifica nada y cambia de
un proceso a otro:

    criterio                          obra   interventoría
    emprendimiento de mujeres           12        13
    vinculación de personas con
      discapacidad                       8         6
    criterios ambientales y sociales    14        12 (ahí se llama
                                                  "factor de sostenibilidad")

Lo que no cambia es el tema. Por eso los títulos se arman aquí: el tema es
obligatorio y el número es el que sea. Exigir un número fijo hacía que el
documento estuviera en la oferta y el motor dijera «no se encontró», con el
requisito entero a revisión en todas las ofertas del proceso.

Aflojar el número no afloja lo que se verifica después: si se abre el documento
equivocado, las comprobaciones de contenido fallan y el requisito va a revisión,
nunca a cumplido.

    TITULO_FORMATO3 = titulo_de_formato(r"EXPERIENCIA", separacion=40)

Los módulos que buscan **dentro** de un documento ya identificado (la capacidad
residual usa el 5.1 al 5.4 para separar sus secciones) y los que clasifican el
texto del pliego no usan esto: ahí el número sí distingue una parte de otra.
"""
from __future__ import annotations

import re

# Los formatos de un pliego van del 1 al 99; más dígitos serían otra cosa.
NUMERO = r"\d{1,2}"
# "FORMATO No. 3", "FORMATO N° 3", "FORMATO NO 3".
_ABREVIATURA = r"(?:N[O°º]\.?\s*)?"


def titulo_de_formato(tema: str, *, letra: str = "", separacion: int = 40) -> re.Pattern[str]:
    """El título de un formato del pliego, con el número que sea.

    `tema` es lo que identifica al formato ("CARTA\\s+DE\\s+PRESENTAC").
    `letra` exige la variante del formato (7A, 9B) cuando el pliego la
    distingue, y `separacion` cuántos caracteres caben entre el número y el
    tema (los guiones, la numeración de la entidad y los saltos de línea)."""
    # Sin `letra`, la variante se acepta igual ("FORMATO 2B - CONFORMACIÓN…"):
    # lo que la distingue es el tema, no la letra.
    variante = rf"\s*{letra}\b" if letra else r"\s*[A-D]?\b"
    return re.compile(
        rf"FORMATO\s*{_ABREVIATURA}{NUMERO}{variante}.{{0,{separacion}}}(?:{tema})",
        re.S,
    )
