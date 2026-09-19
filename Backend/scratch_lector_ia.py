"""Prueba del lector del pliego con IA sobre un pliego real. Solo mide."""
import json, sys, time
sys.path.insert(0, ".")
from motor.pliego import analisis, lectura, lector_ia
from motor.pliego.catalogo import config_desde_pliego, parametros_de

pdf = sys.argv[1]
paginas = lectura.leer_paginas(open(pdf, "rb").read())
ex = analisis.extraer(paginas)
ambitos = {s.numero: s.ambito for s in ex.secciones}
t0 = time.time()
reqs = lector_ia.leer(lectura.secciones(paginas), ambitos, paginas, progreso=lambda n, t: print(f"  {n}/{t}", end="\r", flush=True))
print(f"\n{len(reqs)} requisitos en {time.time()-t0:.0f}s")
for r in reqs:
    extra = parametros_de(r) if r.verificacion else ("config" if config_desde_pliego(r) else "revisión")
    print(f"p{r.pagina:<3} {(r.verificacion or '— nuevo').replace('juridica.', ''):20s} {r.requisito[:70]:70s} | {r.aplica_a} | {r.vigencia_dias or r.vigencia_meses or ''} | {extra}")
json.dump([r.model_dump() for r in reqs], open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
