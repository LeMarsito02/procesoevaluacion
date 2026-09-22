"""Validez de los documentos de la capacidad de organización (pliego 3.11.2 A,
numerales I y II; los exige también la evaluación financiera):

I.  Estado de resultados del año de mayor ingreso operacional, firmado por el
    representante legal, el contador y el revisor fiscal (o contador
    independiente), con su dictamen.
II. Tarjeta profesional y certificado de antecedentes disciplinarios de la
    Junta Central de Contadores, vigentes al cierre, de quienes lo firmaron.

La vigencia la dice el propio certificado ("con vigencia de (3) meses
contados a partir de la fecha de su expedición"). Un certificado vencido fue
el motivo más común de "no cumple" en la evaluación financiera de referencia.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from motor.financiera.capacidad import Revision
from motor.financiera.integrantes import estados_del_integrante
from motor.tecnica.experiencia import IntegranteTecnico
from motor.tecnica.rup import normalizar

_MESES = {m: i for i, m in enumerate(
    "ENERO FEBRERO MARZO ABRIL MAYO JUNIO JULIO AGOSTO SEPTIEMBRE OCTUBRE NOVIEMBRE DICIEMBRE".split(), 1)}
_TP_JCC_RE = re.compile(r"TARJETAPROFESIONALN[O°º]?\.?(\d{3,7})-?T")
# Tolera lo que confunde el OCR: "25 DIIAS DEL MES", "CAN VIGENCIA".
_FECHA_JCC_RE = re.compile(r"DADOEN[A-Z.]{2,30}?ALOS(\d{1,2})D[A-Z]{1,3}SDELMESDE([A-Z]+)DE(?:L)?(\d{4})")
_VIGENCIA_JCC_RE = re.compile(r"C[A-Z]NVIGENCIADE\(?0?(\d{1,2})\)?MESES")
_NOMBRE_JCC_RE = re.compile(r"(?:CONTADOR\s+PUBLICO|REVISOR\s+FISCAL)\s+(.{5,80}?)\s+IDENTIFICAD")
_CEDULA_JCC_RE = re.compile(r"CEDULADECIUDADANIA(?:NO\.?)?(\d{5,11})")
_ESTADOS_RE = re.compile(r"ESTADOS?\s+DE\s+RESULTADOS?|ESTADO\s+DE\s+RESULTADO\s+INTEGRAL|ESTADOS?\s+DE\s+SITUACION\s+FINANCIERA|BALANCE\s+GENERAL|ESTADOS\s+FINANCIEROS")
_DICTAMEN_RE = re.compile(r"DICTAMEN|INFORME\s+DEL\s+REVISOR\s+FISCAL|OPINION\s+(?:SIN\s+SALVEDADES|FAVORABLE|LIMPIA)|HE\s+AUDITADO|HE\s+EXAMINADO")
_TP_FIRMA_RE = re.compile(r"(?:T\.?\s*P\.?|TARJETA\s+PROFESIONAL)\s*(?:N[O°º]\.?\s*)?:?\s*(\d{3,7})\s*-?\s*T\b")
_PISTA_FINANCIERA_RE = re.compile(r"FINANCIER|CONTADOR|REVISOR|BALANCE|ESTADO|EEFF|DICTAMEN|JCC|JUNTA|ANTECEDENTE|RESIDUAL|CAPACIDAD")
_RESULTADOS_RE = re.compile(r"ESTADOS?\s+DE\s+RESULTADOS?|RESULTADO\s+INTEGRAL|PERDIDAS\s+Y\s+GANANCIAS")
_NO_ES_EEFF_RE = re.compile(r"REGISTRO\s+(?:UNICO\s+)?DE\s+PROPONENTES|CERTIFICADO\s+DE\s+EXISTENCIA|FORMATO\s*[1-9]")


@dataclass
class CertificadoJCC:
    archivo: str
    tarjeta: str
    nombre: str = ""
    cedula: str = ""
    expedicion: date | None = None
    vigencia_meses: int | None = None

    def vigente(self, fecha: date) -> bool | None:
        if self.expedicion is None or self.vigencia_meses is None:
            return None
        from motor.tecnica.puntaje import _mas_meses

        vence = _mas_meses(self.expedicion, self.vigencia_meses)
        return self.expedicion <= fecha <= vence if vence else None


def leer_certificado_jcc(archivo: str, texto: str) -> CertificadoJCC | None:
    norm = normalizar(texto)
    compacto = re.sub(r"\s+", "", norm)
    # El certificado de antecedentes; no otro documento que nombre la Junta
    # (una certificación de composición accionaria firmada por el contador).
    if "JUNTACENTRALDECONTADORES" not in compacto or "CERTIFICA" not in compacto or "ANTECEDENTES" not in compacto:
        return None
    tp = _TP_JCC_RE.search(compacto)
    if tp is None:
        return None
    c = CertificadoJCC(archivo, tp.group(1).lstrip("0"))
    if m := _NOMBRE_JCC_RE.search(" ".join(norm.split())):
        c.nombre = m.group(1).strip()
    if m := _CEDULA_JCC_RE.search(compacto):
        c.cedula = m.group(1)
    if (m := _FECHA_JCC_RE.search(compacto)) and m.group(2) in _MESES:
        try:
            c.expedicion = date(int(m.group(3)), _MESES[m.group(2)], int(m.group(1)))
        except ValueError:
            pass
    if m := _VIGENCIA_JCC_RE.search(compacto):
        c.vigencia_meses = int(m.group(1))
    return c


@dataclass
class DocumentosFinancieros:
    certificados: list[CertificadoJCC] = field(default_factory=list)
    # archivo -> texto normalizado de los estados financieros y dictámenes
    estados: dict[str, str] = field(default_factory=dict)
    dictamenes: dict[str, str] = field(default_factory=dict)
    # Texto de cada PDF leído completo (para saber de quién es una página suelta).
    completos: dict[str, str] = field(default_factory=dict)


def _texto(page) -> str:
    """Texto de la página de un documento financiero, fila por fila si está
    escaneada (ver motor.procesamiento.pdf_utils.texto_pagina_tabla)."""
    from motor.procesamiento import pdf_utils

    return pdf_utils.texto_pagina_tabla(page)


def documentos_financieros(pdfs: dict[str, bytes]) -> DocumentosFinancieros:
    """Recorre la oferta una vez: certificados de la Junta Central de
    Contadores (pueden venir sueltos o dentro de otros formatos), estados
    financieros y dictámenes."""
    from motor.procesamiento.pdf_utils import abrir_pdf

    docs = DocumentosFinancieros()
    for archivo, contenido in pdfs.items():
        try:
            with abrir_pdf(contenido) as pdf:
                paginas = []
                total = len(pdf.pages)
                # Las primeras páginas y las últimas: los certificados de la Junta
                # van adjuntos al final de los estados financieros.
                # Hasta 80 páginas: hay ofertas que juntan en un solo PDF los
                # formatos, los RUP y los estados financieros de todos.
                indices = list(range(min(total, 80))) + [i for i in range(max(80, total - 8), total)]
                for n in indices:
                    if n == 2:
                        # Solo se sigue leyendo lo que parece financiero (leer con
                        # OCR las cien piezas de una oferta completas tarda mucho).
                        inicio = normalizar(" ".join(paginas))
                        if not (_PISTA_FINANCIERA_RE.search(normalizar(archivo)) or _ESTADOS_RE.search(inicio)
                                or _DICTAMEN_RE.search(inicio) or "JUNTA" in inicio.replace(" ", "")):
                            break
                    page = pdf.pages[n]
                    paginas.append(_texto(page))
                    page.flush_cache()
        except Exception:  # noqa: BLE001
            continue
        # Un mismo PDF puede traer varios certificados (uno por página).
        for pagina in paginas:
            if (cert := leer_certificado_jcc(archivo, pagina)) is not None:
                docs.certificados.append(cert)
        texto = normalizar(" ".join(" ".join(paginas).split()))
        docs.completos[archivo] = texto
        if len(paginas) > 4:
            # PDF combinado: cada estado de resultados por su página (y la
            # siguiente), para asignarlo al integrante que nombra.
            normas = [normalizar(" ".join(p.split())) for p in paginas]
            for i, pagina in enumerate(normas):
                if _RESULTADOS_RE.search(pagina[:600]) and re.search(r"INGRESOS?", pagina):
                    docs.estados[f"{archivo} (pág. {i + 1})"] = " ".join(normas[i:i + 2])
        if _NO_ES_EEFF_RE.search(texto[:400]):
            continue
        if _ESTADOS_RE.search(texto[:3000]):
            docs.estados[archivo] = texto
        if _DICTAMEN_RE.search(texto):
            docs.dictamenes[archivo] = texto
    return docs


def _parecidas(a: str, b: str) -> bool:
    """Un dígito distinto o dos contiguos invertidos (lo que confunde el OCR
    al leer la tarjeta profesional de una firma escaneada)."""
    if len(a) != len(b) or a == b:
        return False
    distintos = [i for i in range(len(a)) if a[i] != b[i]]
    if len(distintos) == 1:
        return True
    return len(distintos) == 2 and distintos[1] == distintos[0] + 1 and a[distintos[0]] == b[distintos[1]] and a[distintos[1]] == b[distintos[0]]


def _por_tarjeta_parecida(tp: str, certificados: list[CertificadoJCC], texto_estados: str) -> list[CertificadoJCC]:
    """Certificados de una tarjeta casi igual a la leída en la firma, solo si
    el nombre del contador del certificado está en los estados financieros
    (así no se toma el certificado de otra persona)."""
    compacto = re.sub(r"\s+", "", texto_estados)
    elegidos = []
    for c in certificados:
        palabras = [p for p in re.findall(r"[A-Z]{3,}", normalizar(c.nombre))]
        if _parecidas(tp, c.tarjeta) and len(palabras) >= 2 and all(p in compacto for p in palabras[:3]):
            elegidos.append(c)
    return elegidos


def validez_capacidad_organizacional(
    integrantes: list[IntegranteTecnico], docs: DocumentosFinancieros, fecha_cierre: date,
) -> Revision:
    """Por integrante: sus estados financieros, quiénes los firman (tarjeta
    profesional) y que cada firmante tenga el certificado de la Junta Central
    de Contadores vigente al cierre; si firma un revisor fiscal, su dictamen."""
    motivos, detalle, todo_bien = [], {}, True
    por_tarjeta: dict[str, list[CertificadoJCC]] = {}
    for c in docs.certificados:
        por_tarjeta.setdefault(c.tarjeta, []).append(c)
    for integrante in integrantes:
        estados = estados_del_integrante(integrante, docs.estados, integrantes, docs.completos)
        if not estados:
            motivos.append(f"{integrante.nombre}: no se encontraron sus estados financieros (estado de resultados firmado)")
            todo_bien = False
            continue
        tarjetas = sorted({t.lstrip("0") for texto in estados.values() for t in _TP_FIRMA_RE.findall(texto)})
        if not tarjetas:
            motivos.append(f"{integrante.nombre}: no se leyó la tarjeta profesional de quienes firman sus estados financieros")
            todo_bien = False
            continue
        revisor = any(re.search(r"REVISOR\s+FISCAL", t) for t in estados.values())
        if revisor and not estados_del_integrante(integrante, docs.dictamenes, integrantes, docs.completos):
            motivos.append(f"{integrante.nombre}: firma un revisor fiscal pero no se encontró su dictamen")
            todo_bien = False
        estado_tarjetas = {}
        texto_estados = " ".join(estados.values())
        for tp in tarjetas:
            certs = por_tarjeta.get(tp, []) or _por_tarjeta_parecida(tp, docs.certificados, texto_estados)
            vigentes = [c for c in certs if c.vigente(fecha_cierre)]
            if vigentes:
                estado_tarjetas[tp] = f"vigente ({vigentes[0].expedicion:%d/%m/%Y})"
                continue
            todo_bien = False
            if certs:
                c = max(certs, key=lambda x: x.expedicion or date.min)
                estado_tarjetas[tp] = "vencido"
                motivos.append(
                    f"{integrante.nombre}: el certificado de la Junta Central de Contadores de la T.P. {tp}"
                    f"{' (' + c.nombre + ')' if c.nombre else ''} se expidió el "
                    f"{c.expedicion:%d/%m/%Y} con vigencia de {c.vigencia_meses} meses: no está vigente al cierre"
                    if c.expedicion and c.vigencia_meses else
                    f"{integrante.nombre}: no se leyó la fecha o la vigencia del certificado de la T.P. {tp}"
                )
            else:
                estado_tarjetas[tp] = "sin certificado"
                motivos.append(f"{integrante.nombre}: no se encontró el certificado de la Junta Central de Contadores de la T.P. {tp}")
        detalle[integrante.nombre] = {"estados": sorted(estados), "tarjetas": estado_tarjetas}
        if all(v.startswith("vigente") for v in estado_tarjetas.values()) and integrante.nombre not in " ".join(motivos):
            motivos.append(
                f"{integrante.nombre}: estados financieros firmados por T.P. {', '.join(tarjetas)} con certificados vigentes al cierre"
            )
    return Revision(todo_bien, motivos, {"validez": detalle})
