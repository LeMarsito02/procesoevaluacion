"""Prototipo: leer el representante legal (principal) de cada certificado de
existencia, para exigirle antecedentes al de cada empresa integrante de un
consorcio. Se prueba aquí, contra los certificados reales, antes de llevarlo
al motor. Solo mide."""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, ".")
os.environ.setdefault("DRIVE_SOLO_CACHE", "1")

from dotenv import load_dotenv

load_dotenv(".env")

from motor.evaluacion import camara_comercio as cc
from motor.evaluacion.formato1 import obtener_tipo_proponente
from motor.integrations.drive import download_file_bytes, list_proponentes
from motor.procesamiento.zip_utils import extraer_pdfs

# Encabezado que la Cámara repite en cada página y que parte la tabla.
ENCABEZADO_PAGINA_RE = re.compile(
    r"PAGINA \d+ DE \d+ .{0,200}?CODIGO DE VERIFICACION:?\s*[A-Z0-9]+"
    r"(?:\s*VERIFIQUE EL CONTENIDO.{0,300}?(?:GENERADA AL MOMENTO DE SU EXPEDICION|ELECTRONICOS[^.]*\.))?",
    re.DOTALL,
)
SECCION_REPRESENTANTES_RE = re.compile(r"REPRESENTANTES? LEGAL(?:ES)?")
TABLA_RE = re.compile(r"CARGO\s+NOMBRE\s+(?:DE\s+)?IDENTIFICACION")
# Una fila: cargo, nombre, documento. En la Cámara de Bogotá el cargo sale
# partido ("REPRESENTANTE <nombre> C.C. NO. 123 LEGAL"), por eso "LEGAL" y
# "SUPLENTE" pueden venir después del número.
FILA_RE = re.compile(
    r"(GERENTE(?:\s+GENERAL)?|REPRESENTANTE(?:\s+LEGAL)?(?:\s+PRINCIPAL)?|PRESIDENTE|DIRECTOR[A]?\s+EJECUTIV[OA])"
    r"\s+([A-ZÑ][A-ZÑ ]{5,60}?)\s+(?:C\.?\s*[CE]\.?|CEDULA DE (?:CIUDADANIA|EXTRANJERIA))\s*(?:NO\.?|N[°º]\.?)?\s*(\d[\d.]{4,})"
    r"(\s+\S+(?:\s+\S+)?)?"
)


def representante(texto_norm: str) -> tuple[str, str] | None:
    """Representante legal principal: la primera fila de la tabla de
    nombramientos de representantes legales que no sea de un suplente."""
    limpio = ENCABEZADO_PAGINA_RE.sub(" ", texto_norm)
    for seccion in SECCION_REPRESENTANTES_RE.finditer(limpio):
        tabla = TABLA_RE.search(limpio, seccion.end(), seccion.end() + 1500)
        if not tabla:
            continue
        for fila in FILA_RE.finditer(limpio, tabla.end(), tabla.end() + 1500):
            cargo, cola = fila.group(1), fila.group(4) or ""
            if "SUPLENTE" in cargo or "SUPLENTE" in cola or "SUPLENTE" in fila.group(2):
                continue
            nombre = re.sub(r"\s+", " ", fila.group(2)).strip()
            return nombre, re.sub(r"\D", "", fila.group(3)).lstrip("0")
    return None


def main() -> None:
    props = list_proponentes(os.environ["MEDICION_DRIVE_FOLDER"]).proponentes
    total = leidos = 0
    for p in props[: int(os.environ.get("LIMITE", "83"))]:
        pdfs = extraer_pdfs(download_file_bytes(p.drive_file_id))
        tipo = obtener_tipo_proponente(pdfs)
        if tipo not in ("consorcio", "union_temporal"):
            del pdfs
            continue
        for nombre in cc.encontrar_documentos(pdfs, cc.TITULO_EXISTENCIA_RE, cc.PISTAS_EXISTENCIA):
            total += 1
            r = representante(cc._norm(cc._texto_completo(pdfs, nombre)))
            leidos += r is not None
            print(f"{p.hoja} {nombre.rsplit('/', 1)[-1][:34]:34s} → {r}", flush=True)
        del pdfs
    print(f"\nrepresentante leído en {leidos} de {total} certificados de integrantes")


if __name__ == "__main__":
    main()
