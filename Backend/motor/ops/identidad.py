"""Nombre y cédula del contratista, leídos de sus propios certificados de
antecedentes (Procuraduría, Policía y medidas correctivas traen los dos
datos). Sirve para no pedirlos a mano y para avisar si no coinciden con lo
que escribió la persona."""
from __future__ import annotations

import re
from collections import Counter
from datetime import date

from motor.evaluacion import antecedentes
from motor.evaluacion.formato1 import _norm
from motor.ops.tiempo import FECHA, fecha_de

_CON_NOMBRE = (antecedentes.CONFIG_PROCURADURIA, antecedentes.CONFIG_POLICIA, antecedentes.CONFIG_RNMC)


# Numeración histórica de la Registraduría: las cédulas de 20 a 69 millones
# se asignaron a mujeres; por debajo y de 70 a 99 millones, a hombres. Las de
# diez dígitos (NUIP) no dicen nada.
_NACIMIENTO_RE = re.compile(rf"FECHA\s+DE\s+NACIMIENTO\W{{0,8}}({FECHA})")
# Formato único de hoja de vida: «GENERO … F X M NB» (la X va junto a lo que marcó).
_GENERO_RE = re.compile(r"\bF\s*(X?)\s*M\s*(X?)\s*NB\b")
EDAD_LIBRETA = 50


def libreta_exigible(cedula: str | None, textos: dict[str, str], fecha_referencia: date | None) -> tuple[bool | None, str]:
    """Si a la persona se le exige libreta militar (hombre menor de 50 años),
    cuando se puede saber por su cédula o por lo que marcó en la hoja de vida
    de la función pública; None si no. Con el motivo, para que quien revise
    sepa de dónde salió y lo corrija si no es así."""
    try:
        numero = int(re.sub(r"\D", "", cedula or ""))
    except ValueError:
        return None, ""
    corregir = " Si no es así, corríjalo en los datos del contratista."
    if 20_000_000 <= numero <= 69_999_999:
        return False, "Por la numeración de su cédula no se le exige." + corregir
    hombre = numero < 20_000_000 or 70_000_000 <= numero <= 99_999_999
    if not hombre:
        marca = next((m for t in textos.values() for m in [_GENERO_RE.search(t)] if m and bool(m.group(1)) != bool(m.group(2))), None)
        if marca is None:
            return None, ""
        if marca.group(1):
            return False, "En su hoja de vida marcó género femenino: no se le exige." + corregir
    if fecha_referencia is None:
        return None, ""
    nacimiento = next((f for t in textos.values() for m in [_NACIMIENTO_RE.search(t)] if m and (f := fecha_de(m.group(1)))), None)
    if nacimiento is None:
        return None, ""
    edad = fecha_referencia.year - nacimiento.year - ((fecha_referencia.month, fecha_referencia.day) < (nacimiento.month, nacimiento.day))
    if edad >= EDAD_LIBRETA:
        return False, f"Tiene {edad} años según su cédula: solo se exige a menores de {EDAD_LIBRETA}."
    return True, ""


def identificar(pdfs: dict[str, bytes]) -> tuple[str | None, str | None]:
    """(nombre, cédula) en los que coinciden más certificados; None si no se leen."""
    nombres: Counter[str] = Counter()
    cedulas: Counter[str] = Counter()
    for certificado in antecedentes.leer_certificados(pdfs):
        texto = _norm(certificado.texto)
        for config in _CON_NOMBRE:
            if config.requisito not in certificado.requisitos:
                continue
            nombre, cedula = config.extraer_identidad(texto)
            if nombre and len(nombre.split()) >= 2:
                nombres[" ".join(sorted(nombre.split()))] += 1
                nombres[f"={nombre}"] += 0
            if cedula and (digitos := re.sub(r"\D", "", cedula)):
                cedulas[digitos] += 1
    cedula = cedulas.most_common(1)[0][0] if cedulas else None
    if not nombres:
        return None, cedula
    # Cada entidad escribe el nombre en un orden (apellidos primero o al
    # final): se cuentan iguales y se devuelve una de las formas leídas.
    clave = max((k for k in nombres if not k.startswith("=")), key=lambda k: nombres[k])
    forma = next(k[1:] for k in nombres if k.startswith("=") and " ".join(sorted(k[1:].split())) == clave)
    return forma, cedula
