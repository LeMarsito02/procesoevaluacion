"""¿Cuántos consorcios tienen integrantes que son personas naturales? Se
compara el número de integrantes del Formato 2 con el de empresas que
aportaron certificado de existencia. Solo mide."""
import os, sys
sys.path.insert(0, ".")
os.environ.setdefault("DRIVE_SOLO_CACHE", "1")
from dotenv import load_dotenv
load_dotenv(".env")
from motor.evaluacion import camara_comercio as cc
from motor.evaluacion.formato1 import obtener_tipo_proponente
from motor.evaluacion.proponente_plural import datos_formato2
from motor.integrations.drive import download_file_bytes, list_proponentes
from motor.procesamiento.zip_utils import extraer_pdfs

con_naturales = 0
plurales = 0
for p in list_proponentes(os.environ["MEDICION_DRIVE_FOLDER"]).proponentes:
    pdfs = extraer_pdfs(download_file_bytes(p.drive_file_id))
    tipo = obtener_tipo_proponente(pdfs)
    if tipo in ("consorcio", "union_temporal"):
        plurales += 1
        f2 = datos_formato2(pdfs)
        integrantes = len(f2[1].porcentajes) if f2 else 0
        empresas = len(cc.empresas_con_certificado(pdfs))
        marca = "  ← posibles personas naturales" if integrantes > empresas else ""
        con_naturales += bool(marca)
        print(f"{p.hoja}: {integrantes} integrantes · {empresas} empresas con certificado{marca}", flush=True)
    del pdfs
print(f"\n{con_naturales} de {plurales} consorcios/UT con más integrantes que empresas certificadas")
