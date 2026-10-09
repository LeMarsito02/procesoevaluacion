"""Verificación de errores aritméticos de la oferta económica (RF-11).

Los Documentos Tipo solo admiten dos correcciones:
A. las operaciones aritméticas mal hechas (cantidad × precio unitario, sumas,
   porcentajes del AIU y el IVA);
B. el ajuste al peso de los precios unitarios y del IVA: desde 0,5 se sube al
   peso siguiente y por debajo se baja.

Se lee el formulario de la oferta en Excel (el Formulario 1 de presupuesto).
Se buscan la fila de títulos (cantidad, valor unitario, valor total) y los
renglones de costo directo, administración, imprevistos, utilidad, IVA y
total. Lo que no se reconozca no se corrige: se informa, y el valor corregido
queda sin proponer para que lo establezca una persona.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

# Diferencias menores a esto (en pesos) son redondeos de Excel, no errores.
TOLERANCIA = Decimal("1")


def _plano(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", t).strip()


def al_peso(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _numero(celda) -> Decimal | None:
    if isinstance(celda, bool) or celda is None:
        return None
    if isinstance(celda, (int, float)):
        return Decimal(str(celda))
    t = str(celda).strip().replace("$", "").replace(" ", "")
    if not t or not re.fullmatch(r"-?[\d.,]+%?", t):
        return None
    porcentaje = t.endswith("%")
    t = t.rstrip("%")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".") if len(t.split(",")[-1]) != 3 else t.replace(",", "")
    elif t.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        n = Decimal(t)
    except ArithmeticError:
        return None
    return n / 100 if porcentaje else n


@dataclass
class Diferencia:
    fila: int
    concepto: str
    declarado: Decimal
    correcto: Decimal

    @property
    def texto(self) -> str:
        return f"Fila {self.fila} · {self.concepto}: dice {self.declarado:,.0f} y da {self.correcto:,.0f}.".replace(",", ".")


@dataclass
class Revision:
    total_declarado: Decimal | None = None
    total_corregido: Decimal | None = None
    items: int = 0
    diferencias: list[Diferencia] = field(default_factory=list)
    # Lo que no se pudo leer o verificar: con algo aquí, no se propone valor corregido.
    sin_verificar: list[str] = field(default_factory=list)

    @property
    def completa(self) -> bool:
        return not self.sin_verificar and self.total_corregido is not None


_ENCABEZADO = {"cantidad": re.compile(r"\bCANT"), "unitario": re.compile(r"UNITARIO|V(?:R|ALOR)\.?\s*UNIT|P(?:RECIO)?\.?\s*UNIT"),
               "total": re.compile(r"(?:VALOR|VR\.?|PRECIO)?\s*(?:TOTAL|PARCIAL)")}
# El orden importa: «IVA sobre la utilidad» es IVA, no utilidad.
_RENGLON = {
    "iva": re.compile(r"\bIVA\b"),
    "costo_directo": re.compile(r"(?:TOTAL\s+)?COSTOS?\s+DIRECTOS?|SUBTOTAL"),
    "administracion": re.compile(r"\bADMINISTRACION\b"),
    "imprevistos": re.compile(r"\bIMPREVISTOS?\b"),
    "utilidad": re.compile(r"\bUTILIDAD\b"),
    "total": re.compile(r"^(?:VALOR\s+)?TOTAL(?:\s+(?:DE\s+LA\s+)?(?:OFERTA|PROPUESTA|GENERAL|COSTO))?\b(?!.*DIRECT)"),
}


def revisar_excel(contenido: bytes) -> Revision:
    import openpyxl

    revision = Revision()
    try:
        libro = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
    except Exception:  # noqa: BLE001
        revision.sin_verificar.append("No se pudo abrir el archivo como Excel.")
        return revision
    hoja = libro.worksheets[0]
    filas = [list(f) for f in hoja.iter_rows(values_only=True)]
    columnas: dict[str, int] = {}
    inicio = None
    for i, fila in enumerate(filas):
        textos = [_plano(c) for c in fila]
        encontradas = {k: next((j for j, t in enumerate(textos) if patron.search(t)), None) for k, patron in _ENCABEZADO.items()}
        if all(v is not None for v in encontradas.values()):
            columnas, inicio = encontradas, i + 1
            break
    if inicio is None:
        revision.sin_verificar.append("No se encontró la fila de títulos con cantidad, valor unitario y valor total.")
        return revision

    suma = Decimal(0)
    renglones: dict[str, tuple[int, Decimal | None, Decimal | None]] = {}  # concepto → (fila, porcentaje, valor)
    for i in range(inicio, len(filas)):
        fila = filas[i]
        celdas = lambda k: fila[columnas[k]] if columnas[k] < len(fila) else None  # noqa: E731
        etiqueta = " ".join(_plano(c) for c in fila if isinstance(c, str))
        cantidad, unitario, total = _numero(celdas("cantidad")), _numero(celdas("unitario")), _numero(celdas("total"))
        concepto = next((k for k, p in _RENGLON.items() if p.search(etiqueta)), None)
        if concepto:
            numeros = [n for n in (_numero(c) for c in fila) if n is not None]
            porcentaje = next((n for n in numeros if 0 < n < 1), None)
            valor = total if total is not None else (max(numeros) if numeros else None)
            renglones.setdefault(concepto, (i + 1, porcentaje, valor))
            continue
        if cantidad is None or unitario is None or total is None:
            continue
        revision.items += 1
        correcto = al_peso(cantidad * al_peso(unitario))
        if abs(correcto - total) > TOLERANCIA:
            revision.diferencias.append(Diferencia(i + 1, f"ítem «{etiqueta[:60]}»", total, correcto))
        suma += correcto

    if not revision.items:
        revision.sin_verificar.append("No se encontraron ítems con cantidad, valor unitario y valor total.")
        return revision
    total_declarado = renglones.get("total", (0, None, None))[2]
    revision.total_declarado = total_declarado
    if total_declarado is None:
        revision.sin_verificar.append("No se encontró el renglón del valor total de la oferta.")

    def comparar(concepto: str, correcto: Decimal) -> None:
        if concepto in renglones and renglones[concepto][2] is not None and abs(renglones[concepto][2] - correcto) > TOLERANCIA:
            revision.diferencias.append(Diferencia(renglones[concepto][0], concepto.replace("_", " "), renglones[concepto][2], correcto))

    comparar("costo_directo", suma)
    corregido = suma
    for concepto in ("administracion", "imprevistos", "utilidad"):
        if concepto not in renglones:
            continue
        fila, porcentaje, valor = renglones[concepto]
        if porcentaje is None:
            revision.sin_verificar.append(f"No se leyó el porcentaje de {concepto} (fila {fila}).")
            continue
        correcto = al_peso(suma * porcentaje)
        comparar(concepto, correcto)
        corregido += correcto
    if "iva" in renglones:
        fila, porcentaje, valor = renglones["iva"]
        if porcentaje is None:
            revision.sin_verificar.append(f"No se leyó el porcentaje del IVA (fila {fila}).")
        else:
            # En obra, el IVA va sobre la utilidad; si no hay utilidad, sobre el costo directo.
            base = al_peso(suma * renglones["utilidad"][1]) if "utilidad" in renglones and renglones["utilidad"][1] else suma
            correcto = al_peso(base * porcentaje)
            comparar("iva", correcto)
            corregido += correcto
    if total_declarado is not None and abs(total_declarado - corregido) > TOLERANCIA:
        revision.diferencias.append(Diferencia(renglones["total"][0], "valor total", total_declarado, corregido))
    revision.total_corregido = corregido
    return revision
