"""Crea (o vuelve a crear) el proceso de demostración DEMO-CM-001-2026.

Todo es inventado (ver demo/documentos.py): la entidad, los cuatro
proponentes, sus personas y documentos. Las ofertas se dejan en la caché de
ofertas como si vinieran de una carpeta de Drive, y el proceso se evalúa con
el motor real, así que la demostración muestra lo que el programa hace de
verdad. Volver a correrlo borra la demostración anterior y la arma de nuevo.

En los procesos cuyo código empieza por DEMO- las consultas en línea (RNMC y
COPNIA) no llaman a las páginas oficiales: devuelven un certificado simulado.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from demo import documentos as d

PROCESO = d.CODIGO


def _personas():
    P = d.Persona
    laura = P("LAURA CAMILA MÉNDEZ RÍOS", "MÉNDEZ RÍOS", "LAURA CAMILA", "1999000001", date(2008, 4, 10), date(1990, 2, 11), matricula="99202-000001")
    jorge = P("JORGE ANDRÉS PAREDES LUNA", "PAREDES LUNA", "JORGE ANDRÉS", "1999000002", date(2005, 6, 21), date(1987, 3, 2))
    julian = P("JULIÁN ESTEBAN ROJAS PRADA", "ROJAS PRADA", "JULIÁN ESTEBAN", "1999000003", date(2003, 8, 14), date(1985, 1, 20))
    sofia = P("SOFÍA ALEJANDRA TORRES LARA", "TORRES LARA", "SOFÍA ALEJANDRA", "1999000004", date(2009, 11, 3), date(1991, 7, 9))
    # Su certificado de medidas correctivas (RNMC) es de mayo: vencido para el cierre.
    carlos = P("CARLOS ALBERTO VEGA SOTO", "VEGA SOTO", "CARLOS ALBERTO", "1999000005", date(2002, 2, 27), date(1983, 10, 5),
               matricula="99202-000005", rnmc=date(2026, 5, 10))
    paula = P("PAULA ANDREA CASTRO MEJÍA", "CASTRO MEJÍA", "PAULA ANDREA", "1999000006", date(2007, 9, 18), date(1989, 4, 30))
    ana = P("ANA MARÍA SUÁREZ GIL", "SUÁREZ GIL", "ANA MARÍA", "1999000007", date(2006, 5, 5), date(1988, 12, 1), matricula="99202-000007")
    luis = P("LUIS FERNANDO ORTIZ CANO", "ORTIZ CANO", "LUIS FERNANDO", "1999000008", date(2004, 1, 16), date(1986, 6, 22))
    maria = P("MARÍA JOSÉ RESTREPO DÍAZ", "RESTREPO DÍAZ", "MARÍA JOSÉ", "1999000009", date(2001, 3, 12), date(1982, 8, 17), matricula="99202-000009")
    andres = P("ANDRÉS FELIPE GÓMEZ RUIZ", "GÓMEZ RUIZ", "ANDRÉS FELIPE", "1999000011", date(2010, 10, 8), date(1992, 5, 14))
    return laura, jorge, julian, sofia, carlos, paula, ana, luis, maria, andres


def _proponentes() -> list[d.Proponente]:
    laura, jorge, julian, sofia, carlos, paula, ana, luis, maria, andres = _personas()
    E = d.Empresa
    andes = E("ANDES INGENIERIA DEMO S.A.S.", "999100001", "4", julian)
    valle = E("ESTRUCTURAS DEL VALLE DEMO S.A.S.", "999100002", "2", sofia)
    andina = E("INGENIERIA ANDINA DEMO S.A.S.", "999100003", "0", carlos, suplente=paula)
    puentes = E("PUENTES Y CAMINOS DEMO S.A.S.", "999100004", "9", ana)
    topo = E("TOPOGRAFIA NORTE DEMO S.A.S.", "999100005", "7", luis)
    llano = E("CONSTRUCCIONES DEL LLANO DEMO S.A.", "999100006", "5", maria, suplente=andres, anonima=True,
              revisor_fiscal="DIEGO MAURICIO LÓPEZ VARGAS", revisor_cedula="1.999.000.010")
    return [
        d.Proponente("P-01", "CONSORCIO VIAS DEL SUR DEMO", "consorcio", laura, jorge, integrantes=[(andes, 60), (valle, 40)]),
        d.Proponente("P-02", "INGENIERIA ANDINA DEMO S.A.S.", "persona_juridica", carlos, paula, empresa=andina),
        # La póliza no alcanza el 10 % del lote de mayor valor.
        d.Proponente("P-03", "UNION TEMPORAL PUENTES DEMO", "union_temporal", ana, luis,
                     integrantes=[(puentes, 50), (topo, 50)], valor_poliza=80_000_000.0),
        # Su COPNIA es de abril: más de tres meses antes del cierre.
        d.Proponente("P-04", "CONSTRUCCIONES DEL LLANO DEMO S.A.", "persona_juridica", maria, andres, empresa=llano,
                     copnia=date(2026, 4, 20)),
    ]


def _documentos(p: d.Proponente) -> dict[str, str]:
    """Nombre del archivo en la oferta → HTML."""
    expedido = date(2026, 9, 1)
    docs: dict[str, str] = {
        "1. Carta de presentacion de la oferta.pdf": d.carta(p),
        "3. COPNIA y tarjeta profesional.pdf": d.copnia(p.representante, p.copnia),
        "5. Poliza de seriedad de la oferta.pdf": d.poliza(p, date(2026, 9, 10), date(2026, 12, 20)),
    }
    empresas = [e for e, _ in p.integrantes] or [p.empresa]
    if p.integrantes:
        docs["2. Formato 2 - Conformacion de proponente plural.pdf"] = d.formato2(p)
    for e in empresas:
        corto = e.razon.split(" DEMO")[0].title()
        docs[f"4. Camara de comercio/Existencia {corto}.pdf"] = d.existencia(e, expedido)
        docs[f"4. Camara de comercio/RUP {corto}.pdf"] = d.rup(e, expedido)
        docs[f"6. Seguridad social/Formato 5 {corto}.pdf"] = d.seguridad_social(e)
        docs[f"7. Antecedentes/Contraloria {corto}.pdf"] = d.contraloria(e.razon, e.nit, "NIT", expedido)
        docs[f"7. Antecedentes/Procuraduria {corto}.pdf"] = d.procuraduria(e.razon, e.nit, "NIT", expedido)
        if e.anonima:
            docs[f"4. Camara de comercio/Certificacion revisor fiscal {corto}.pdf"] = d.revisor_abierta_cerrada(e)
    personas = [p.representante] + ([p.suplente] if p.suplente else [])
    for persona in personas:
        corto = persona.nombres.split()[0].title()
        docs[f"7. Antecedentes/Contraloria {corto}.pdf"] = d.contraloria(persona.nombre, persona.cedula, "Cédula de Ciudadanía", expedido)
        docs[f"7. Antecedentes/Procuraduria {corto}.pdf"] = d.procuraduria(persona.nombre, persona.cedula, "Cédula de ciudadanía", expedido)
        docs[f"7. Antecedentes/Policia {corto}.pdf"] = d.policia(persona, expedido)
        docs[f"7. Antecedentes/RNMC {corto}.pdf"] = d.rnmc(persona)
        docs[f"7. Antecedentes/REDAM {corto}.pdf"] = d.redam(persona, expedido)
        docs[f"8. Cedulas/Cedula {corto}.pdf"] = d.cedula(persona)
    return docs


def _pliego_html() -> str:
    lotes = "".join(f"<li>{n}: {o}. Presupuesto ${v:,.0f}. Plazo {m} meses.</li>" for n, o, v, m, _ in d.LOTES)
    return d.html(f"""
<h1>PLIEGO DE CONDICIONES</h1>
<p class='centro'>CONCURSO DE MÉRITOS ABIERTO {d.CODIGO}<br>{d.ENTIDAD}</p>
<h2>1. OBJETO</h2><p>{d.OBJETO}.</p><ul>{lotes}</ul>
<h2>3. REQUISITOS HABILITANTES</h2>
<h2>3.2 CAPACIDAD JURÍDICA</h2>
<p>Los Proponentes deben tener capacidad jurídica para la presentación de la oferta y no estar incursos en causales de inhabilidad o incompatibilidad.</p>
<h2>3.3.2 PERSONAS JURÍDICAS</h2>
<p>a) Fecha de expedición del certificado de existencia y representación legal no mayor a treinta (30) días calendario anteriores a la fecha de cierre del Proceso de Contratación.</p>
<p>b) Acreditar que su duración no será inferior a la del plazo del contrato y un año más.</p>
<p>c) Presentar fotocopia del documento de identificación del representante legal.</p>
<h2>7.1 GARANTÍA DE SERIEDAD DE LA OFERTA</h2>
<p>El proponente presentará una garantía de seriedad de la oferta por el diez por ciento (10 %) del presupuesto del lote de mayor valor, con vigencia de tres (3) meses contados desde la fecha de cierre.</p>
""", "Pliego")


def _ajustes(pagina_de) -> list[dict]:
    from motor.pliego.analisis import Hallazgo

    ahora = timezone.now().isoformat()
    hallazgos = [
        Hallazgo(id="vigencia_existencia", tipo="ajuste_parametro", titulo="Vigencia del certificado de existencia y representación legal",
                 detalle="El pliego exige una fecha de expedición no mayor a 30 días calendario antes del cierre; la evaluación de la entidad usa 1 mes.",
                 seccion="3.3.2 PERSONAS JURÍDICAS", pagina=pagina_de("TREINTA (30) DIAS"),
                 cita="a) Fecha de expedición del certificado de existencia y representación legal no mayor a treinta (30) días calendario anteriores a la fecha de cierre del Proceso de Contratación.",
                 verificacion="juridica.existencia", parametro="camara_dias", valor_plantilla="1 mes", valor_pliego=30,
                 valor_pliego_texto="30 días", requiere_decision=True),
        Hallazgo(id="duracion_sociedad", tipo="requisito_nuevo", titulo="Duración de la sociedad",
                 detalle="El certificado de existencia debe mostrar una duración no inferior al plazo del contrato y un año más.",
                 seccion="3.3.2 PERSONAS JURÍDICAS", pagina=pagina_de("DURACION NO SERA"),
                 cita="b) Acreditar que su duración no será inferior a la del plazo del contrato y un año más.",
                 verificacion="juridica.duracion", requiere_decision=True,
                 requisito_propuesto={"verificacion": "juridica.duracion", "titulo": "Duración de la sociedad", "corto": "Duración"}),
        Hallazgo(id="identidad_representante", tipo="requisito_nuevo", titulo="Documento de identidad del representante legal",
                 detalle="El pliego pide copia del documento de identidad del representante legal.",
                 seccion="3.3.2 PERSONAS JURÍDICAS", pagina=pagina_de("FOTOCOPIA DEL DOCUMENTO"),
                 cita="c) Presentar fotocopia del documento de identificación del representante legal.",
                 verificacion="juridica.identidad", requiere_decision=True,
                 requisito_propuesto={"verificacion": "juridica.identidad", "titulo": "Documento de identidad del representante legal", "corto": "Identidad"}),
    ]
    return [
        {"id": h.id, "decision": "aceptado", "nota": "", "por": "Presentador de la demostración", "por_id": "", "en": ahora,
         "hallazgo": h.model_dump(mode="json")}
        for h in hallazgos
    ]


class Command(BaseCommand):
    help = "Crea el proceso de demostración DEMO-CM-001-2026 con datos inventados y lo pone a evaluar."

    def add_arguments(self, parser):
        parser.add_argument("--correo", default="", help="Correo del usuario que queda como responsable (por defecto el superadministrador).")

    def handle(self, *args, **opciones):
        from cuentas.models import Entidad, Rol, Usuario
        from evaluaciones import servicios
        from evaluaciones.models import AnalisisPliego, EstadoEvaluacion, Evaluacion, PlantillaEvaluacion, Proceso, Proponente
        from motor import criterios
        from motor.integrations.drive import CACHE_DIR
        from motor.pliego import analisis, lector_ia, lectura

        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.entidad_id', '*', false)")
        entidad = Entidad.objects.filter(nombre__icontains="Pruebas").first() or Entidad.objects.first()
        responsable = (
            Usuario.objects.filter(email=opciones["correo"]).first() if opciones["correo"]
            else Usuario.objects.filter(rol=Rol.SUPERADMIN).first()
        )
        self.stdout.write(f"Entidad: {entidad.nombre} · responsable: {responsable.email}")

        # 1) Borrar la demostración anterior.
        for anterior in Proceso.objects.filter(entidad=entidad, codigo=PROCESO):
            servicios.eliminar_proceso(anterior)
            self.stdout.write("Se borró la demostración anterior.")

        # 2) Los PDF de las ofertas y del pliego.
        proponentes = _proponentes()
        paginas_html = {p.hoja: _documentos(p) for p in proponentes}
        paginas_html["pliego"] = {"pliego.pdf": _pliego_html()}
        pdfs = _renderizar(paginas_html)
        self.stdout.write(f"PDF generados: {sum(len(v) for v in pdfs.values())}")

        # 3) Cada oferta como un .zip en la caché, como si viniera de Drive.
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for p in proponentes:
            memoria = io.BytesIO()
            with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as z:
                for nombre, contenido in pdfs[p.hoja].items():
                    z.writestr(f"{p.hoja} {p.nombre}/{nombre}", contenido)
            contenido = memoria.getvalue()
            (CACHE_DIR / f"demo-{p.hoja.lower()}.zip").write_bytes(contenido)
            (CACHE_DIR / f"demo-{p.hoja.lower()}.meta.json").write_text(json.dumps({
                "name": f"{p.hoja[2:]}. {p.nombre}.zip", "md5Checksum": hashlib.md5(contenido).hexdigest(), "size": str(len(contenido)),
            }))

        # 4) La plantilla de la demostración (no toca la de la entidad).
        definicion = criterios.definicion_sistema("juridica")
        definicion = definicion.model_copy(update={"parametros": {
            **definicion.parametros, "prefijo_codigo": "DEMO",
            "beneficiario_claves": ["IIVD", "INFRAESTRUCTURA VIAL DEMO"],
        }})
        version = (PlantillaEvaluacion.objects.filter(entidad=entidad, tipo="juridica").order_by("-version").values_list("version", flat=True).first() or 0) + 1
        plantilla = PlantillaEvaluacion.objects.create(
            entidad=entidad, tipo="juridica", version=version, nombre="Plantilla de la demostración",
            definicion=definicion.model_dump(mode="json"), nota="Solo para el proceso DEMO-CM-001-2026", activa=False, creada_por=responsable,
        )

        # 5) El pliego inventado, ya analizado.
        pliego = pdfs["pliego"]["pliego.pdf"]
        paginas = lectura.leer_paginas(pliego)
        texto = {p.numero: analisis.norm(p.texto) for p in paginas}

        def pagina_de(frase: str) -> int:
            return next((n for n, t in texto.items() if frase in t), 1)

        analizado = AnalisisPliego(
            entidad=entidad, sha256=hashlib.sha256(pliego).hexdigest(), nombre_archivo="Pliego de condiciones DEMO-CM-001-2026.pdf",
            paginas=len(paginas), documento_tipo="", extraccion=analisis.extraer(paginas).model_dump(mode="json"),
            version=analisis.VERSION_ANALISIS, estado_ia="listo", progreso_ia=100, version_ia=lector_ia.VERSION,
        )
        analizado.archivo.save("pliego-demo.pdf", ContentFile(pliego), save=False)
        analizado.save()

        # 6) El proceso, sus proponentes y la evaluación jurídica.
        garantia = {"lote_base": "LOTE 1", "porcentaje": 0.1, "valor_base": d.LOTES[0][2], "base_calculo": "lote_mayor_valor",
                    "fecha_cierre": d.CIERRE.isoformat(), "vigencia_meses": 3, "valor_asegurado": d.LOTES[0][2] * 0.1,
                    "fecha_vencimiento": (d.CIERRE + timedelta(days=91)).isoformat()}
        documento_base = {
            "codigo_proceso": d.CODIGO, "fecha_cierre": d.CIERRE.isoformat(), "objeto_general": d.OBJETO + ".",
            "lotes": [{"numero": n, "objeto": o, "plazo_meses": m, "lugar_ejecucion": lugar, "valor_presupuesto": v}
                      for n, o, v, m, lugar in d.LOTES],
            "lote_mayor_valor": "LOTE 1", "presupuesto_total": sum(v for _, _, v, _, _ in d.LOTES),
            "garantia_seriedad": garantia, "modalidad": "interventoria_transporte", "tarjeta_suplible": False, "advertencias": [],
        }
        proceso = Proceso.objects.create(
            entidad=entidad, codigo=d.CODIGO, fecha_cierre=d.CIERRE, objeto=d.OBJETO + ".", documento_base=documento_base,
            carpeta_drive="https://drive.google.com/demostracion", analisis_pliego=analizado,
            ajustes_pliego=_ajustes(pagina_de), creado_por=responsable,
        )
        for i, p in enumerate(proponentes, 1):
            Proponente.objects.create(entidad=entidad, proceso=proceso, numero_orden=i, hoja=p.hoja, nombre=p.nombre,
                                      nombre_archivo=f"{i}. {p.nombre}.zip", drive_file_id=f"demo-{p.hoja.lower()}")
        evaluacion = Evaluacion.objects.create(
            entidad=entidad, proceso=proceso, tipo="juridica", plantilla=plantilla, responsable=responsable,
            asignada_por=responsable, asignada_en=timezone.now(), estado=EstadoEvaluacion.ASIGNADA,
        )
        servicios.encolar(evaluacion, None, responsable)
        self.stdout.write(self.style.SUCCESS(
            f"Listo: {d.CODIGO} con {len(proponentes)} proponentes, en la fila de evaluación. Evaluación {evaluacion.id}"
        ))


def _renderizar(grupos: dict[str, dict[str, str]]) -> dict[str, dict[str, bytes]]:
    from playwright.sync_api import sync_playwright

    salida: dict[str, dict[str, bytes]] = {}
    with sync_playwright() as play:
        navegador = play.chromium.launch()
        pagina = navegador.new_page()
        for grupo, documentos in grupos.items():
            salida[grupo] = {}
            for nombre, contenido in documentos.items():
                pagina.set_content(contenido, wait_until="load")
                salida[grupo][nombre] = pagina.pdf(
                    format="Letter", print_background=True, display_header_footer=True,
                    header_template="<span></span>", footer_template=d.PIE_PAGINA,
                    margin={"top": "20mm", "bottom": "22mm", "left": "20mm", "right": "20mm"},
                )
        navegador.close()
    return salida
