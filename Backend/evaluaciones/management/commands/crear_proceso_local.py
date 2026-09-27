"""Crea un proceso a partir de un pliego y unas ofertas que están en el disco.

Sirve para montar procesos de prueba con material real bajado del SECOP, sin
tener que subir los zip uno por uno desde el navegador: el mismo camino que usa
la aplicación (las ofertas van a la caché con un identificador «local:», el
pliego se analiza y queda guardado), pero desde la terminal.

    manage.py crear_proceso_local ../datasetdepruebas/test/ICCU-LP-027-2026 \
        --cierre 2026-07-24 --tipos juridica,tecnica,financiera

La carpeta debe tener `pliego.pdf` y una subcarpeta `ofertas/` con un zip por
proponente. Con `--sin-evaluar` el proceso queda creado pero no entra en la
fila, para practicar el flujo completo desde la interfaz.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from cuentas.models import Entidad, Rol, Usuario
from evaluaciones import servicios
from evaluaciones.models import AnalisisPliego, EstadoEvaluacion, Evaluacion, Proceso, Proponente
from evaluaciones.tipos import TIPOS
from motor.integrations import ofertas_locales
from motor.parsers.documento_base import build_proceso
from motor.pliego import analisis, lector_ia, lectura


class Command(BaseCommand):
    help = "Crea un proceso con un pliego y unas ofertas del disco."

    def add_arguments(self, parser):
        parser.add_argument("carpeta", help="Carpeta con pliego.pdf y ofertas/")
        parser.add_argument("--codigo", help="Código del proceso (por defecto, el nombre de la carpeta)")
        parser.add_argument("--cierre", help="Fecha de cierre AAAA-MM-DD (por defecto, la que diga el pliego)")
        parser.add_argument("--tipos", default="juridica", help="Áreas a evaluar, separadas por coma")
        parser.add_argument("--maximo", type=int, help="Usar solo las primeras N ofertas")
        parser.add_argument("--correo", help="Responsable de las evaluaciones")
        parser.add_argument("--sin-evaluar", action="store_true", help="No poner el proceso en la fila")

    def handle(self, *args, **opciones):
        carpeta = Path(opciones["carpeta"]).resolve()
        pliego_pdf = carpeta / "pliego.pdf"
        if not pliego_pdf.exists():
            raise CommandError(f"No está {pliego_pdf}")
        archivos_oferta = sorted((carpeta / "ofertas").glob("*.*"))
        if opciones["maximo"]:
            archivos_oferta = archivos_oferta[: opciones["maximo"]]
        if not archivos_oferta:
            raise CommandError(f"No hay ofertas en {carpeta / 'ofertas'}")

        tipos = [t.strip() for t in opciones["tipos"].split(",") if t.strip()]
        desconocidos = [t for t in tipos if t not in TIPOS]
        if desconocidos:
            raise CommandError(f"Áreas que no existen: {', '.join(desconocidos)}")

        responsable = (
            Usuario.objects.filter(email=opciones["correo"]).first()
            if opciones.get("correo")
            else Usuario.objects.filter(rol=Rol.EVALUADOR, entidad__isnull=False).order_by("creado_en").first()
        )
        if responsable is None or responsable.entidad is None:
            raise CommandError("No hay un evaluador con entidad al que asignarle el proceso (use --correo).")
        entidad: Entidad = responsable.entidad

        codigo = opciones.get("codigo") or carpeta.name
        if Proceso.objects.filter(entidad=entidad, codigo=codigo).exists():
            raise CommandError(f"Ya existe el proceso {codigo} en {entidad.nombre}.")

        # 1) El pliego: lo mismo que hace la aplicación al subirlo. La fecha de
        # cierre se pide aparte porque no está en el pliego —la fija la entidad
        # y cambia con las adendas— y de ella dependen todas las vigencias.
        if not opciones.get("cierre"):
            raise CommandError("Indique la fecha de cierre del proceso con --cierre AAAA-MM-DD.")
        cierre = date.fromisoformat(opciones["cierre"])
        self.stdout.write(f"Leyendo el pliego de {codigo}…")
        pliego = pliego_pdf.read_bytes()
        documento = build_proceso(codigo, cierre, pliego)

        huella = hashlib.sha256(pliego).hexdigest()
        # El mismo pliego no se analiza dos veces en una entidad (hay una
        # restricción de unicidad): si ya está, se reutiliza.
        analizado = AnalisisPliego.objects.filter(entidad=entidad, sha256=huella).first()
        if analizado is not None:
            self.stdout.write("El pliego ya estaba analizado: se reutiliza.")
        else:
            analizado = self._analizar(entidad, codigo, pliego, huella)

        # 2) Las ofertas, a la caché, con el mismo lector de nombres que la interfaz.
        self.stdout.write(f"Guardando {len(archivos_oferta)} ofertas…")
        locales = ofertas_locales.desde_archivos([(a.name, a.read_bytes()) for a in archivos_oferta])
        if not locales.proponentes:
            raise CommandError("Ninguna oferta se pudo leer como zip de proponente.")
        self._crear(entidad, responsable, codigo, cierre, documento, analizado, locales, tipos, opciones)

    def _analizar(self, entidad, codigo, pliego, huella):
        paginas = lectura.leer_paginas(pliego)
        analizado = AnalisisPliego(
            entidad=entidad,
            sha256=huella,
            nombre_archivo=f"Pliego {codigo}.pdf",
            paginas=len(paginas),
            documento_tipo="",
            extraccion=analisis.extraer(paginas).model_dump(mode="json"),
            version=analisis.VERSION_ANALISIS,
            estado_ia="pendiente",
            progreso_ia=0,
            version_ia=lector_ia.VERSION,
        )
        analizado.archivo.save(f"pliego-{codigo}.pdf", ContentFile(pliego), save=False)
        analizado.save()
        return analizado

    def _crear(self, entidad, responsable, codigo, cierre, documento, analizado, locales, tipos, opciones):
        # 3) El proceso, sus proponentes y las evaluaciones.
        with transaction.atomic():
            proceso = Proceso.objects.create(
                entidad=entidad,
                codigo=codigo,
                fecha_cierre=cierre,
                objeto=documento.objeto_general,
                documento_base=documento.model_dump(mode="json"),
                carpeta_drive="",
                proponentes_no_reconocidos=locales.no_reconocidos,
                analisis_pliego=analizado,
                creado_por=responsable,
            )
            Proponente.objects.bulk_create(
                Proponente(
                    entidad=entidad,
                    proceso=proceso,
                    numero_orden=p.numero_orden,
                    hoja=p.hoja,
                    nombre=p.nombre_proponente,
                    nombre_archivo=p.nombre_archivo,
                    drive_file_id=p.drive_file_id,
                    advertencia=p.advertencia or "",
                )
                for p in locales.proponentes
            )
            evaluaciones = [
                Evaluacion.objects.create(
                    entidad=entidad,
                    proceso=proceso,
                    tipo=tipo,
                    plantilla=servicios.plantilla_activa(entidad.id, tipo),
                    responsable=responsable,
                    asignada_por=responsable,
                    asignada_en=timezone.now(),
                    estado=EstadoEvaluacion.ASIGNADA,
                )
                for tipo in tipos
            ]

        if not opciones["sin_evaluar"]:
            for evaluacion in evaluaciones:
                servicios.encolar(evaluacion, None, responsable)

        estado = "creado, sin evaluar" if opciones["sin_evaluar"] else "en la fila de evaluación"
        self.stdout.write(
            self.style.SUCCESS(
                f"{codigo}: {len(locales.proponentes)} proponentes · {', '.join(tipos)} · {estado}"
                + (f" · {len(locales.no_reconocidos)} archivos no reconocidos" if locales.no_reconocidos else "")
            )
        )
