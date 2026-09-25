"""Qué entiende el programa de un Documento Base, y qué no.

Sirve para saber por qué un pliego sale con avisos sin tener que abrirlo a mano:
dice si el documento trae texto o es un escaneo, en qué página encontró la tabla
de objeto y presupuesto y el numeral de la garantía, y qué leyó de cada uno.

    manage.py revisar_pliego ruta/al/pliego.pdf
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Dice qué entiende el programa de un Documento Base y qué no pudo leer."

    def add_arguments(self, parser) -> None:
        parser.add_argument("pdf", help="ruta del Documento Base en PDF")
        parser.add_argument("--codigo", default="REVISION-000-2026")
        parser.add_argument("--cierre", default=str(date.today()), help="fecha de cierre (AAAA-MM-DD)")

    def handle(self, *args, **opciones) -> None:
        import pdfplumber

        from motor.parsers.documento_base import _es_escaneado, build_proceso

        ruta = Path(opciones["pdf"]).expanduser()
        if not ruta.exists():
            raise CommandError(f"No existe el archivo: {ruta}")
        contenido = ruta.read_bytes()
        self.stdout.write(f"{ruta.name} · {len(contenido) / 1e6:.1f} MB")

        with pdfplumber.open(ruta) as pdf:
            total = len(pdf.pages)
            escaneado = _es_escaneado(pdf)
            sin_texto = 0
            for page in pdf.pages:
                if len((page.extract_text() or "").strip()) < 300 and page.images:
                    sin_texto += 1
                page.flush_cache()
        self.stdout.write(f"{total} páginas · {sin_texto} son imagen (sin texto propio)")
        if sin_texto:
            self.stdout.write(self.style.WARNING(
                "  Ese pliego está escaneado en parte o del todo: esas páginas se leen con OCR, "
                "que tarda unos dos segundos cada una la primera vez y luego queda en caché."))
        if escaneado:
            self.stdout.write("  El principio del documento también es imagen: la búsqueda se acota para no "
                              "hacer OCR de más.")

        self.stdout.write("\nLeyendo… (la primera vez de un escaneado puede tardar minutos)")
        proceso = build_proceso(opciones["codigo"], date.fromisoformat(opciones["cierre"]), contenido)
        self.stdout.write(f"\nmodalidad: {getattr(proceso, 'modalidad', '') or '—'}")
        self.stdout.write(f"lotes: {len(proceso.lotes)}")
        for lote in proceso.lotes:
            self.stdout.write(f"  {lote.numero}: ${lote.valor_presupuesto:,.0f} · {lote.plazo_meses} meses "
                              f"· {lote.lugar_ejecucion or 'sin lugar'}")
            self.stdout.write(f"     objeto: {(lote.objeto or '—')[:160]}")
        g = proceso.garantia_seriedad
        self.stdout.write(f"garantía de seriedad: {g.vigencia_meses} meses · {g.porcentaje:.0%} "
                          f"· ${g.valor_asegurado:,.0f} · vence {g.fecha_vencimiento}")
        avisos = getattr(proceso, "advertencias", None) or []
        if avisos:
            self.stdout.write(self.style.WARNING(f"\n{len(avisos)} aviso(s):"))
            for a in avisos:
                self.stdout.write(f"  - {a}")
        else:
            self.stdout.write(self.style.SUCCESS("\nSin avisos: se leyó todo."))
