"""A qué integrante de un proponente plural pertenece cada documento
financiero (estados financieros, Formato 5). Un documento de un consorcio
suele nombrar a todos sus integrantes, así que manda el NIT; sin NIT, el
nombre completo y seguido, y el de ningún otro integrante."""
from __future__ import annotations

import re

from motor.tecnica.experiencia import IntegranteTecnico
from motor.tecnica.rup import normalizar


def _nit_escrito(integrante: IntegranteTecnico, texto: str) -> bool:
    nit = re.sub(r"\D", "", integrante.nit or (integrante.rup.nit if integrante.rup else ""))
    # Con o sin dígito de verificación; el de una persona natural es su
    # cédula (6 a 10 dígitos), agrupada de a tres desde la derecha.
    return any(re.search(r"(?<![\d.])" + _agrupado(c) + r"(?!\d)", texto) for c in {nit, nit[:-1]} if len(c) >= 6)


_SIGLAS_SOCIEDAD_RE = re.compile(r"(?:S\.?\s*A\.?\s*S\.?|S\.?\s*A\.?|LTDA\.?|E\.?\s*U\.?)\s*$")


def _nombre_escrito(integrante: IntegranteTecnico, compacto: str) -> bool:
    """El nombre, sin la sigla de la sociedad, escrito seguido (sin
    espacios) en el texto compactado."""
    nombre = _SIGLAS_SOCIEDAD_RE.sub("", normalizar(integrante.nombre).strip())
    nombre = re.sub(r"[^A-Z0-9&]", "", nombre)
    return len(nombre) >= 4 and nombre in re.sub(r"[^A-Z0-9&]", "", compacto)


def _del_integrante(integrante: IntegranteTecnico, texto: str, integrantes: list[IntegranteTecnico]) -> bool:
    """El documento es de este integrante: trae su NIT (o su cédula), o, si
    no trae el de ningún integrante, su nombre y el de ningún otro (los
    documentos de un consorcio suelen nombrar a todos sus integrantes)."""
    if len(integrantes) <= 1:
        return True
    if _nit_escrito(integrante, texto):
        return True
    otros = [i for i in integrantes if i is not integrante]
    if any(_nit_escrito(o, texto) for o in otros):
        return False
    compacto = re.sub(r"\s+", "", texto)
    return _nombre_escrito(integrante, compacto) and not any(_nombre_escrito(o, compacto) for o in otros)


def _agrupado(digitos: str) -> str:
    grupos = []
    while digitos:
        grupos.insert(0, digitos[-3:])
        digitos = digitos[:-3]
    return r"[.,\s]?".join(grupos)


def estados_del_integrante(integrante: IntegranteTecnico, estados: dict[str, str], integrantes: list[IntegranteTecnico],
                           completos: dict[str, str] | None = None) -> dict[str, str]:
    """Los estados financieros del integrante. Una página suelta de un PDF
    ("archivo (pág. 3)") es de quien sea dueño del PDF completo si este trae
    el NIT de un solo integrante; si no (PDF combinado), se decide por la
    página."""
    suyos = {}
    for clave, texto in estados.items():
        base = clave.split(" (pág. ")[0]
        completo = (completos or {}).get(base)
        if base != clave and completo is not None and len(integrantes) > 1:
            duenos = [i for i in integrantes if _nit_escrito(i, completo)]
            if len(duenos) == 1:
                if duenos[0] is integrante:
                    suyos[clave] = texto
                continue
        if _del_integrante(integrante, texto, integrantes):
            suyos[clave] = texto
    return suyos


# El propio formato dice de quién es: "PROPONENTE O INTEGRANTE: X",
# "INTEGRANTES (SI ES OFERENTE PLURAL): X".
_TITULAR_RE = re.compile(
    r"(?:NOMBRE\s+DEL\s+)?(?:PROPONENTRE|PROPONENTE|OFERENTE)\s*(?:O\s*(?:INTEGRANTE|MIEMBRO))?\s*:\s*(.{3,90})"
    r"|INTEGRANTES?\s*(?:\(SI\s+ES\s+OFERENTE\s+PLURAL\))?\s*:\s*(.{3,90})"
)
_FIN_TITULAR_RE = re.compile(r"\b(?:FECHA|NIT|C\.?C\.?|PROC|PROCESO|CON\s+EL\s+FIN|SENORES?|NUMERO)\b")
_PALABRAS_TITULAR = {"CONSORCIO", "UNION", "TEMPORAL", "SAS", "SA", "LTDA", "EU", "BIC", "DEL", "DE", "LA", "Y", "O"}


def titulares_del_documento(texto: str) -> list[str]:
    """Nombres que el formato declara como suyos (el del proponente plural y
    el del integrante)."""
    nombres = []
    for m in _TITULAR_RE.finditer(normalizar(texto)):
        bruto = m.group(1) or m.group(2) or ""
        corte = _FIN_TITULAR_RE.search(bruto)
        nombre = " ".join(bruto[: corte.start() if corte else len(bruto)].split()).strip(" .,:-_")
        if len(nombre) >= 4:
            nombres.append(nombre)
    return nombres


def _tokens(nombre: str) -> set[str]:
    return {p for p in re.findall(r"[A-Z0-9&]{2,}", normalizar(nombre).replace(".", "").replace(" & ", "&"))
            if p not in _PALABRAS_TITULAR}


def integrante_del_titular(titulares: list[str], integrantes: list[IntegranteTecnico]) -> IntegranteTecnico | None:
    """El integrante al que se refiere el formato: el que comparte más
    palabras con alguno de los títulos y gana con claridad."""
    puntajes = []
    for integrante in integrantes:
        propias = _tokens(integrante.nombre)
        mejor = max((len(propias & _tokens(t)) for t in titulares), default=0)
        puntajes.append((mejor, integrante))
    puntajes.sort(key=lambda x: -x[0])
    if not puntajes or puntajes[0][0] < 1:
        return None
    if len(puntajes) > 1 and puntajes[1][0] >= puntajes[0][0]:
        return None
    if puntajes[0][0] == 1:
        # Una sola palabra en común: vale si es distintiva ("KONKON") y de
        # nadie más.
        comunes = {p for t in titulares for p in _tokens(t)} & _tokens(puntajes[0][1].nombre)
        if not any(len(p) >= 5 for p in comunes):
            return None
    return puntajes[0][1]
