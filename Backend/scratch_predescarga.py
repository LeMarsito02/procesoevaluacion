"""Descarga por adelantado las ofertas que faltan (varias a la vez, desde el
final), mientras la medición evalúa las que ya están en disco. Solo llena la
caché de Drive."""
import sys, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")
from dotenv import load_dotenv

load_dotenv(".env")
from motor.integrations import drive

props = drive.list_proponentes(sys.argv[1]).proponentes
faltan = [p for p in reversed(props) if not drive._cache_paths(p.drive_file_id)[0].exists()]
print(f"por descargar: {len(faltan)}", flush=True)
inicio = time.time()


def bajar(p):
    """Con reintentos: un corte de red (cambio de wifi a cable) no tumba el resto."""
    t0 = time.time()
    for intento in range(4):
        if drive._cache_paths(p.drive_file_id)[0].exists():
            return p.hoja, 0 if intento == 0 else -1, time.time() - t0
        try:
            datos = drive.download_file_bytes(p.drive_file_id)
            return p.hoja, len(datos), time.time() - t0
        except Exception as exc:  # noqa: BLE001
            print(f"  {p.hoja}: falló ({type(exc).__name__}), reintento {intento + 1}", flush=True)
            time.sleep(5)
    return p.hoja, 0, time.time() - t0


total = 0
with ThreadPoolExecutor(max_workers=int(sys.argv[2]) if len(sys.argv) > 2 else 3) as ex:
    for hoja, tam, seg in ex.map(bajar, faltan):
        total += tam
        print(f"  {hoja}: {tam/1e6:.0f} MB en {seg:.0f} s", flush=True)
seg = time.time() - inicio
print(f"listo: {total/1e6:.0f} MB en {seg/60:.1f} min → {total/1e6/max(seg,1):.2f} MB/s en total", flush=True)
