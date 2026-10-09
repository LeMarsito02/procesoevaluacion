"""Reúne de cada oferta del proceso lo que sirve para cruzarlas (RF-14) y
guarda el resultado. Ver motor/coincidencias.py."""
from __future__ import annotations

import hashlib
import logging

from evaluaciones.models import AnalisisCoincidencias, PersonaVerificada, Proceso, Resultado
from motor import coincidencias as motor
from motor.integrations.drive import download_file_bytes
from motor.procesamiento.pdf_utils import paginas_de_texto
from motor.procesamiento.zip_utils import extraer_pdfs

log = logging.getLogger("mievaluador.coincidencias")
NOMBRES_TIPO = {"documento": "Documento idéntico", "persona": "Misma persona", "empresa": "Misma empresa integrante",
                "profesional": "Mismo profesional", "correo": "Mismo correo", "telefono": "Mismo teléfono", "direccion": "Misma dirección"}


def clave(c: dict) -> str:
    return hashlib.sha256(f"{c['tipo']}|{c['valor']}|{'|'.join(c['ofertas'])}".encode()).hexdigest()[:16]


def calcular(proceso: Proceso, usuario) -> AnalisisCoincidencias:
    proponentes = list(proceso.proponentes.all())
    resultados = list(Resultado.objects.filter(evaluacion__proceso=proceso).values("proponente_id", "requisito", "datos"))
    personas = list(PersonaVerificada.objects.filter(evaluacion__proceso=proceso).values("proponente_id", "nombre", "documento", "rol", "tipo"))
    avisos: list[str] = []
    ofertas: list[motor.DatosOferta] = []
    for p in proponentes:
        o = motor.DatosOferta(clave=str(p.id), nombre=p.nombre)
        pdfs: dict[str, bytes] = {}
        if proceso.documentos_eliminados_en:
            if not avisos:
                avisos.append("Los documentos del proceso ya se eliminaron por la retención: no se compararon los archivos.")
        else:
            try:
                pdfs = extraer_pdfs(download_file_bytes(p.drive_file_id))
            except Exception:  # noqa: BLE001
                avisos.append(f"No se pudo descargar la oferta de {p.nombre}: sus archivos no se compararon.")
        o.archivos = pdfs
        for x in personas:
            if x["proponente_id"] != p.id:
                continue
            if x["tipo"] == "juridica":
                o.empresas.append((x["nombre"], x["documento"] or ""))
            else:
                o.personas.append((x["nombre"], x["documento"], x["rol"]))
        for r in resultados:
            if r["proponente_id"] != p.id:
                continue
            d = r["datos"] or {}
            for a in d.get("personas_antecedente") or []:
                (o.empresas if a.get("tipo") == "juridica" else o.personas).append(
                    (a.get("nombre", ""), a.get("documento"), a.get("rol", "")) if a.get("tipo") != "juridica" else (a.get("nombre", ""), a.get("documento") or "")
                )
            if d.get("matricula_profesional"):
                o.matriculas.append((d.get("profesion_certificada") or "", d["matricula_profesional"]))
            if r["requisito"] == 1 and d.get("archivo_evaluado") in pdfs:
                try:
                    o.texto_contacto = "\n".join(paginas_de_texto(pdfs[d["archivo_evaluado"]], 2))
                except Exception:  # noqa: BLE001
                    pass
        ofertas.append(o)
    hallado = motor.buscar(ofertas)
    nombres = {str(p.id): f"{p.hoja} · {p.nombre}" for p in proponentes}

    def a_dict(c: motor.Coincidencia) -> dict:
        d = {"tipo": c.tipo, "tipo_nombre": NOMBRES_TIPO[c.tipo], "valor": c.valor, "detalle": c.detalle, "ofertas": c.ofertas,
             "proponentes": [nombres[k] for k in c.ofertas]}
        d["clave"] = clave(d)
        return d

    analisis, _ = AnalisisCoincidencias.objects.update_or_create(
        proceso=proceso,
        defaults={"entidad_id": proceso.entidad_id, "calculado_por": usuario, "resultado": {
            "coincidencias": [a_dict(c) for c in hallado.coincidencias], "comunes": [a_dict(c) for c in hallado.comunes],
            "avisos": avisos, "ofertas": len(proponentes),
        }},
    )
    return analisis
