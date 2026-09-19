"""Comparación de modelos para entender el pliego: mismas secciones
jurídicas, en trozos, misma instrucción. Mide tiempo, respuestas en JSON
válido y requisitos extraídos; guarda todo para revisar la calidad a mano.
Uso: python scratch_comparar_ias.py <pliego.pdf> <modelo> [local|openrouter]"""
import json, os, re, sys, time
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
import requests
from motor.pliego import analisis, lectura

INSTRUCCION = (
    "Eres abogado experto en contratación estatal colombiana. Del fragmento de pliego que recibes, extrae los "
    "requisitos habilitantes JURÍDICOS (capacidad jurídica) que el proponente debe acreditar con su oferta. No incluyas "
    "requisitos técnicos, financieros ni de puntaje. Responde SOLO un objeto JSON, sin texto adicional: "
    '{"requisitos":[{"requisito":str,"documento":str,"aplica_a":str,"condiciones":[str],"cita":str}]} '
    '("cita" = frase literal corta del pliego). Si el fragmento no trae requisitos jurídicos: {"requisitos":[]}.'
)
TROZO = 3500


def trozos(pliego):
    paginas = lectura.leer_paginas(open(pliego, "rb").read())
    ex = analisis.extraer(paginas)
    juridicas = {s.numero for s in ex.secciones if s.ambito == "juridica"}
    for s in lectura.secciones(paginas):
        if s.numero not in juridicas:
            continue
        texto = f"{s.numero} {s.titulo}\n{s.texto}"
        for i in range(0, len(texto), TROZO):
            yield s.numero, texto[i : i + TROZO]


def local(modelo, texto):
    r = requests.post("http://localhost:11434/api/chat", timeout=900, json={
        "model": modelo, "stream": False, "format": "json", "think": False,
        "options": {"temperature": 0, "num_ctx": 4096},
        "messages": [{"role": "system", "content": INSTRUCCION}, {"role": "user", "content": texto}]})
    return r.json()["message"]["content"]


def openrouter(modelo, texto):
    for intento in range(3):
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", timeout=600, headers={
            "Authorization": f"Bearer {os.environ['openrouter_api_key']}"}, json={
            "model": modelo, "temperature": 0,
            "messages": [{"role": "system", "content": INSTRUCCION}, {"role": "user", "content": texto}]})
        d = r.json()
        if "choices" in d:
            return d["choices"][0]["message"]["content"] or ""
        time.sleep(20 * (intento + 1))  # límite de uso gratuito
    return json.dumps({"error": d.get("error")})


def main():
    pliego, modelo, via = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "local")
    llamar = local if via == "local" else openrouter
    salida, validos, total, inicio = [], 0, 0, time.time()
    lista = list(trozos(pliego))
    for n, (seccion, texto) in enumerate(lista, 1):
        t0 = time.time()
        crudo = llamar(modelo, texto)
        m = re.search(r"\{.*\}", crudo, re.S)
        try:
            reqs = json.loads(m.group(0))["requisitos"]
            validos += 1
        except Exception:
            reqs = None
        total += len(reqs or [])
        salida.append({"seccion": seccion, "segundos": round(time.time() - t0), "requisitos": reqs, "crudo": None if reqs is not None else crudo[:500]})
        print(f"[{n}/{len(lista)}] {seccion} {time.time()-t0:.0f}s {'JSON' if reqs is not None else 'NO JSON'} {len(reqs or [])} req.", flush=True)
    nombre = re.sub(r"\W+", "_", modelo)
    json.dump(salida, open(f".scratch/ia_{nombre}.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n{modelo}: {len(lista)} trozos, {validos} con JSON válido, {total} requisitos, {time.time()-inicio:.0f}s en total")


if __name__ == "__main__":
    main()
