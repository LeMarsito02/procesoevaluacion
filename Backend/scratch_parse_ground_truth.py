"""Script temporal: parsea el Segundo Informe (PDF, ground truth) para
extraer, por cada proponente y cada uno de los 18 requisitos, el veredicto
(SI/NO/N.A.) y la nota. SOLO se usa para comparar qué tan confiable es el
programa -- nunca para construir la lógica de evaluación."""
from __future__ import annotations

import json
import re
import sys

import pdfplumber

PATH = "/home/lemarsito/Documents/NICOLASPENA/ProcesoEvaluacion/SEGUNDO INFORME DE EVALUACION JURIDICA ICCU-CM-037 de 2026 (1).pdf"

REQUISITO_ANCLA = {
    1: "Carta de presentación de la propuesta",
    2: "Propuesta suscrita o avalada por un Ingeniero",
    3: "Antecedentes disciplinarios profesionales del Ingeniero",
    4: "Conformación de proponente plural",
    5: "REDAM",
    6: "Certificado de Existencia y Representación legal",
    7: "Objeto Social acorde",
    8: "Facultades Representante Legal",
    9: "Registro Único de Proponentes",
    10: "Sanciones",
    11: "Garantía de Seriedad de la Propuesta",
    12: "Pago de seguridad social",
    13: "Registro Único Tributario",
    14: "Boletín de Responsables de la Contraloría",
    15: "Certificado de Antecedentes Disciplinarios de la Procuraduría",
    16: "Antecedentes Judiciales Policía Nacional",
    17: "Imposición de multas",
    18: "Certificado de Revisor Fiscal",
}

VEREDICTO_RE = re.compile(r"\bN\.A\.|\bNO CUMPLE\b|\bSI\b|\bNO\b")


def _extraer_bloque_proponente(texto_completo: str) -> dict:
    resultado = {}

    match_nombre = re.search(r"Proponente:\s*(.+)", texto_completo)
    nombre = match_nombre.group(1).strip() if match_nombre else None
    resultado["nombre"] = nombre

    # localizar posiciones de cada ancla numerada, en orden
    posiciones = {}
    for num, texto_ancla in REQUISITO_ANCLA.items():
        patron = re.compile(rf"(?<!\d){num}{re.escape(texto_ancla[:35])}")
        m = patron.search(texto_completo)
        if m:
            posiciones[num] = m.start()

    numeros_ordenados = sorted(posiciones.keys())
    requisitos = {}
    for idx, num in enumerate(numeros_ordenados):
        inicio = posiciones[num]
        fin = posiciones[numeros_ordenados[idx + 1]] if idx + 1 < len(numeros_ordenados) else len(texto_completo)
        bloque = texto_completo[inicio:fin]
        # quitar el texto del ancla (el enunciado del requisito) para que el
        # primer SI/NO/N.A. que aparezca sea el veredicto, no una palabra
        # suelta del enunciado
        bloque_sin_ancla = bloque[len(str(num)) + len(REQUISITO_ANCLA[num][:35]):]
        vmatch = VEREDICTO_RE.search(bloque_sin_ancla)
        veredicto = vmatch.group(0) if vmatch else None
        nota = bloque_sin_ancla[vmatch.end():].strip() if vmatch else bloque_sin_ancla.strip()
        nota = re.sub(r"\s+", " ", nota)[:200]
        requisitos[num] = {"veredicto": veredicto, "nota": nota}

    resultado["requisitos"] = requisitos
    resultado["requisitos_encontrados"] = len(requisitos)
    return resultado


def main():
    modo_debug = "--debug" in sys.argv

    with pdfplumber.open(PATH) as pdf:
        paginas_texto = [page.extract_text() or "" for page in pdf.pages]

    texto_total = "\n".join(paginas_texto)
    bloques = re.split(r"PROPONENTE \d+\n", texto_total)[1:]  # el primero es antes del primer proponente

    resultados = []
    for bloque in bloques:
        r = _extraer_bloque_proponente(bloque)
        resultados.append(r)

    incompletos = [r for r in resultados if r["requisitos_encontrados"] < 18]
    print(f"Total proponentes encontrados: {len(resultados)}")
    print(f"Con los 18 requisitos completos: {len(resultados) - len(incompletos)}")
    print(f"Incompletos: {len(incompletos)}")
    for r in incompletos:
        faltantes = [n for n in range(1, 19) if n not in r["requisitos"]]
        print(f"  {r['nombre']}: faltan {faltantes}")

    with open(".scratch/ground_truth.json", "w") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=1)
    print("Guardado en .scratch/ground_truth.json")

    if modo_debug:
        for r in resultados[:3]:
            print(f"--- {r['nombre']} ---")
            for num in sorted(r["requisitos"].keys()):
                info = r["requisitos"][num]
                print(f"  {num}: {info['veredicto']!r}  nota={info['nota'][:60]!r}")


if __name__ == "__main__":
    main()
