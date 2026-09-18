"""Cuántos Formatos 2 se leen por tabla (sin modelo). Solo mide."""
import os, sys, time
sys.path.insert(0, ".")
os.environ.setdefault("DRIVE_SOLO_CACHE", "1")
from dotenv import load_dotenv
load_dotenv(".env")
from motor.evaluacion import proponente_plural as pp
from motor.evaluacion.formato1 import obtener_tipo_proponente
from motor.integrations.drive import download_file_bytes, list_proponentes
from motor.procesamiento.zip_utils import extraer_pdfs
ok = total = 0
for p in list_proponentes(os.environ["MEDICION_DRIVE_FOLDER"]).proponentes:
    pdfs = extraer_pdfs(download_file_bytes(p.drive_file_id))
    if obtener_tipo_proponente(pdfs) in ("consorcio", "union_temporal"):
        total += 1
        enc = pp.encontrar_formato2(pdfs)
        t0 = time.time()
        r = pp._integrantes_de_tabla(pdfs[enc[0]]) if enc else []
        ok += bool(r)
        print(f"{p.hoja}: {time.time()-t0:.1f}s {[(i.nombre, i.identificacion, 'N' if i.persona_natural else 'J') for i in r] or 'SIN TABLA'}", flush=True)
    del pdfs
print(f"\nleídos por tabla: {ok} de {total}")
