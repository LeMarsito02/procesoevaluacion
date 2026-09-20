"""Expediente final permanente de una evaluación.

Contiene, por proponente, los documentos de la oferta con los que se verificó
cada requisito y los certificados que el evaluador aportó; además el informe
Excel, el reporte formal en Word y un registro con los resultados, decisiones y
huellas SHA-256 de cada archivo. Se genera al aprobar la evaluación y no lo
borra la retención de documentos.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import tempfile
import zipfile
from collections import defaultdict

from django.core.files import File
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from evaluaciones import servicios
from evaluaciones.models import (
    DocumentoAportado,
    EstadoExpediente,
    Evaluacion,
    Expediente,
    PersonaVerificada,
    Resultado,
    Revision,
)
from evaluaciones.reporte import generar_reporte, validacion
from motor.esquemas.proceso import ResultadoRequisito
from motor.integrations.drive import download_file_bytes
from motor.procesamiento.zip_utils import PREFIJO_APORTADOS, extraer_pdfs

log = logging.getLogger("mievaluador.expediente")


def _seguro(nombre: str, largo: int = 80) -> str:
    limpio = re.sub(r'[\\/:*?"<>|]+', " ", nombre)
    return re.sub(r"\s+", " ", limpio).strip()[:largo] or "archivo"


def solicitar(evaluacion: Evaluacion, usuario) -> Expediente:
    with transaction.atomic():
        ultima = Expediente.objects.filter(evaluacion=evaluacion).aggregate(m=Max("version"))["m"] or 0
        return Expediente.objects.create(
            entidad_id=evaluacion.entidad_id, evaluacion=evaluacion, version=ultima + 1, solicitado_por=usuario
        )


def reclamar_pendiente() -> Expediente | None:
    with transaction.atomic():
        exp = (
            Expediente.objects.select_for_update(skip_locked=True)
            .filter(estado=EstadoExpediente.PENDIENTE)
            .order_by("creado_en")
            .first()
        )
        if exp is None:
            return None
        exp.estado = EstadoExpediente.GENERANDO
        exp.save(update_fields=["estado"])
        return exp


def construir(expediente: Expediente) -> None:
    """Arma el .zip (en disco temporal para no cargarlo en memoria) y lo guarda."""
    evaluacion = Evaluacion.objects.select_related("proceso", "entidad", "responsable", "aprobada_por", "plantilla").get(
        pk=expediente.evaluacion_id
    )
    proceso = evaluacion.proceso
    catalogo = {c["numero"]: c for c in servicios.catalogo(servicios.definicion_de(evaluacion))}
    huellas: list[tuple[str, str, int]] = []
    avisos: list[str] = []

    with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:

            def agregar(ruta: str, contenido: bytes) -> None:
                z.writestr(ruta, contenido)
                huellas.append((ruta, hashlib.sha256(contenido).hexdigest(), len(contenido)))

            excel, nombre_excel = servicios.generar_informe_excel(evaluacion)
            agregar(f"informe/{nombre_excel}", excel)
            word, nombre_word = generar_reporte(evaluacion)
            agregar(f"informe/{nombre_word}", word)
            # El pliego rige la evaluación: se archiva con ella.
            analisis = proceso.analisis_pliego
            if analisis is not None:
                try:
                    with analisis.archivo.open("rb") as f:
                        agregar(f"pliego/{_seguro(analisis.nombre_archivo, 150)}", f.read())
                except OSError as exc:
                    avisos.append(f"No se pudo incluir el pliego ({exc}).")

            resultados = defaultdict(dict)
            for r in Resultado.objects.filter(evaluacion=evaluacion):
                resultados[r.proponente_id][r.requisito] = ResultadoRequisito.model_validate(r.datos)
            revisiones = {(r.proponente_id, r.requisito): r for r in Revision.objects.filter(evaluacion=evaluacion).select_related("usuario")}
            aportados = defaultdict(list)
            for d in DocumentoAportado.objects.filter(evaluacion=evaluacion).select_related("persona", "subido_por"):
                aportados[d.proponente_id].append(d)
            personas = defaultdict(list)
            for p in PersonaVerificada.objects.filter(evaluacion=evaluacion):
                personas[p.proponente_id].append(p)

            registro_proponentes = []
            for p in proceso.proponentes.all().order_by("numero_orden"):
                carpeta = f"proponentes/{p.hoja} {_seguro(p.nombre, 60)}"
                usados = sorted({r.archivo_evaluado for r in resultados[p.id].values() if r.archivo_evaluado})
                if usados:
                    try:
                        pdfs = extraer_pdfs(download_file_bytes(p.drive_file_id))
                    except Exception as exc:  # noqa: BLE001
                        pdfs = {}
                        avisos.append(f"{p.hoja}: no se pudo descargar la oferta ({exc}); se conserva el registro sin los documentos.")
                    for ruta in usados:
                        # Los certificados aportados se guardan aparte, más abajo.
                        if ruta.startswith(PREFIJO_APORTADOS):
                            continue
                        contenido = pdfs.get(ruta)
                        if contenido is None:
                            if pdfs:
                                avisos.append(f"{p.hoja}: el documento «{ruta}» ya no está en la oferta.")
                            continue
                        agregar(f"{carpeta}/documentos evaluados/{_seguro(ruta.replace('/', ' - '), 150)}", contenido)
                for d in aportados[p.id]:
                    persona = f" - {_seguro(d.persona.nombre, 50)}" if d.persona else ""
                    nombre = f"{carpeta}/antecedentes aportados/Req {d.requisito}{persona} - {d.fecha_expedicion:%Y-%m-%d}.pdf"
                    with d.archivo.open("rb") as f:
                        agregar(nombre, f.read())

                requisitos = []
                for numero, info in catalogo.items():
                    r = resultados[p.id].get(numero)
                    rev = revisiones.get((p.id, numero))
                    v = validacion(r, rev, info["verifica"]) if r else None
                    requisitos.append(
                        {
                            "numero": numero,
                            "requisito": info["titulo"],
                            "resultado": v.estado if v else "No evaluado",
                            "forma_de_validacion": v.forma if v else None,
                            "justificacion": v.detalle if v else None,
                            "documento_soporte": r.archivo_evaluado if r else None,
                            "validado_por": rev.usuario.email if rev and rev.usuario_id else None,
                            "validado_en": rev.fecha.isoformat() if rev else None,
                            "resultado_del_sistema": r.model_dump(mode="json", exclude={"archivos_disponibles"}) if r else None,
                        }
                    )
                registro_proponentes.append(
                    {
                        "hoja": p.hoja,
                        "nombre": p.nombre,
                        "archivo_en_drive": p.nombre_archivo,
                        "personas_verificadas": [
                            {
                                "rol": x.get_rol_display(),
                                "tipo": x.get_tipo_display(),
                                "nombre": x.nombre,
                                "documento": x.documento,
                                "fecha_expedicion_documento": x.fecha_expedicion_documento.isoformat() if x.fecha_expedicion_documento else None,
                                "de": x.de.nombre if x.de_id else None,
                            }
                            for x in personas[p.id]
                        ],
                        "antecedentes_aportados": [
                            {
                                "requisito": d.requisito,
                                "persona": d.persona.nombre if d.persona else None,
                                "fecha_expedicion": d.fecha_expedicion.isoformat(),
                                "subido_por": d.subido_por.email if d.subido_por else None,
                                "subido_en": d.subido_en.isoformat(),
                                "observacion": d.observacion,
                            }
                            for d in aportados[p.id]
                        ],
                        "requisitos": requisitos,
                    }
                )

            registro = {
                "generado_por": "MiEvaluador by LeMarTek",
                "generado_en": timezone.now().isoformat(),
                "version_expediente": expediente.version,
                "entidad": {"nombre": evaluacion.entidad.nombre, "nit": evaluacion.entidad.nit},
                "proceso": {"codigo": proceso.codigo, "objeto": proceso.objeto, "fecha_cierre": proceso.fecha_cierre.isoformat()},
                "evaluacion": {
                    "tipo": evaluacion.get_tipo_display(),
                    "estado": evaluacion.get_estado_display(),
                    "responsable": evaluacion.responsable.email if evaluacion.responsable else None,
                    "aprobada_por": evaluacion.aprobada_por.email if evaluacion.aprobada_por else None,
                    "aprobada_en": evaluacion.aprobada_en.isoformat() if evaluacion.aprobada_en else None,
                    "plantilla": (
                        {"nombre": evaluacion.plantilla.nombre, "version": evaluacion.plantilla.version} if evaluacion.plantilla_id else "base del sistema"
                    ),
                },
                "pliego": (
                    {
                        "archivo": analisis.nombre_archivo,
                        "sha256": analisis.sha256,
                        "paginas": analisis.paginas,
                        "documento_tipo": analisis.documento_tipo,
                        "ajustes": proceso.ajustes_pliego,
                    }
                    if analisis is not None
                    else None
                ),
                "avisos": avisos,
                "proponentes": registro_proponentes,
            }
            agregar("registro.json", json.dumps(registro, ensure_ascii=False, indent=2).encode("utf-8"))
            manifiesto = io.StringIO()
            manifiesto.write(f"Expediente {proceso.codigo} · evaluación {evaluacion.get_tipo_display().lower()} · versión {expediente.version}\n")
            manifiesto.write("SHA-256  tamaño  archivo\n")
            for ruta, huella, tam in huellas:
                manifiesto.write(f"{huella}  {tam}  {ruta}\n")
            z.writestr("MANIFIESTO.txt", manifiesto.getvalue())

        tmp.flush()
        tmp.seek(0)
        sha = hashlib.sha256()
        for bloque in iter(lambda: tmp.read(1024 * 1024), b""):
            sha.update(bloque)
        tamano = tmp.tell()
        tmp.seek(0)
        expediente.archivo.save(f"v{expediente.version}.zip", File(tmp), save=False)
    # update() y no save(): si el expediente se anuló mientras se armaba, no se revive.
    actualizados = Expediente.objects.filter(pk=expediente.pk, estado=EstadoExpediente.GENERANDO).update(
        archivo=expediente.archivo.name,
        sha256=sha.hexdigest(),
        tamano=tamano,
        estado=EstadoExpediente.LISTO,
        terminado_en=timezone.now(),
        error="\n".join(avisos),
    )
    if not actualizados:
        expediente.archivo.delete(save=False)
        log.warning("Expediente %s anulado mientras se generaba; se descarta el archivo.", expediente.pk)
        return
    log.info("Expediente %s v%d listo (%.1f MB)", proceso.codigo, expediente.version, tamano / 1e6)


def atender_pendientes() -> int:
    """Genera los expedientes pendientes (lo llama el trabajador de la fila)."""
    n = 0
    while (exp := reclamar_pendiente()) is not None:
        try:
            construir(exp)
        except Exception as exc:  # noqa: BLE001
            log.exception("Falló el expediente %s", exp.id)
            Expediente.objects.filter(pk=exp.pk, estado=EstadoExpediente.GENERANDO).update(
                estado=EstadoExpediente.ERROR, error=str(exc)[:2000], terminado_en=timezone.now()
            )
        n += 1
    return n
