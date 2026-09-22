"""Evaluación técnica de un proponente: reúne los documentos (RUP de cada
integrante, Formato 2 y Formato 3) y evalúa la experiencia de cada lote."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from motor.evaluacion.camara_comercio import PISTAS_RUP, TITULO_RUP_RE, encontrar_documentos
from motor.evaluacion.personalizado import esta_firmado
from motor.evaluacion.proponente_plural import datos_formato2, integrantes_formato2
from motor.procesamiento.pdf_utils import buscar_pagina
from motor.tecnica.experiencia import IntegranteTecnico, ResultadoLote, evaluar_experiencia
from motor.tecnica.formato3 import Formato3, leer_excel, leer_pdf
from motor.tecnica.longitud import area_del_contrato, longitud_del_contrato
from motor.tecnica.puntaje import Factor, discapacidad, emprendimiento_mujeres, factor_calidad, industria_nacional, mipyme
from motor.tecnica.parametros import ParametrosTecnicos
from motor.tecnica.rup import Rup, leer_rups as leer_rups_del_texto, normalizar, texto_del_pdf

_TITULO_FORMATO3_RE = re.compile(r"FORMATO\s*3\b.{0,40}EXPERIENCIA", re.S)
_PLURAL_RE = re.compile(r"^\s*(?:CONSORCIO|CONSROCIO|COSORCIO|CONSORCIP|UNION TEMPORAL|U\.?\s?T\.?\b)")
_PISTA_FORMATO3_RE = re.compile(r"FORMAT\w*\s*(?:NO\.?\s*)?3\b|EXPERIENCIA")


@dataclass
class ResultadoTecnico:
    lotes: list[ResultadoLote] = field(default_factory=list)
    integrantes: list[IntegranteTecnico] = field(default_factory=list)
    formato3: str | None = None
    rups: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    puntaje: list[Factor] = field(default_factory=list)


def _digitos(texto: str | None) -> str:
    return re.sub(r"\D", "", texto or "")[:9]


def _mismo_nombre(a: str, b: str) -> bool:
    quitar = r"\b(S\.?A\.?S\.?|SAS|S\.?A\.?|LTDA|LIMITADA|E\.?U\.?|Y|DE|LA|EL)\b|[^A-Z0-9 ]"
    pa = set(re.sub(quitar, " ", normalizar(a)).split())
    pb = set(re.sub(quitar, " ", normalizar(b)).split())
    if not pa or not pb:
        return False
    return len(pa & pb) / min(len(pa), len(pb)) >= 0.6


def leer_rups(pdfs: dict[str, bytes]) -> list[tuple[str, Rup]]:
    rups = []
    for archivo in encontrar_documentos(pdfs, TITULO_RUP_RE, PISTAS_RUP):
        try:
            leidos = leer_rups_del_texto(texto_del_pdf(pdfs[archivo]))
        except Exception:  # noqa: BLE001
            continue
        rups.extend((archivo, rup) for rup in leidos if rup.experiencias or rup.nit)
    # Un RUP por NIT: el de más contratos (copias parciales dentro de otros formatos).
    por_nit: dict[str, tuple[str, Rup]] = {}
    for archivo, rup in rups:
        clave = _digitos(rup.nit) or archivo
        if clave not in por_nit or len(rup.experiencias) > len(por_nit[clave][1].experiencias):
            por_nit[clave] = (archivo, rup)
    return list(por_nit.values())


def encontrar_formato3(pdfs: dict[str, bytes], excels: dict[str, bytes]) -> Formato3 | None:
    """Primero el Excel (se pide "preferiblemente en Excel" y se lee exacto);
    si no, la tabla del PDF."""
    for archivo in sorted(excels, key=lambda a: not _PISTA_FORMATO3_RE.search(normalizar(a))):
        if (formato := leer_excel(excels[archivo], archivo)) is not None:
            return formato
    candidatos = sorted(pdfs, key=lambda a: not _PISTA_FORMATO3_RE.search(normalizar(a)))
    for archivo in candidatos:
        try:
            texto = buscar_pagina(pdfs[archivo], lambda t: bool(_TITULO_FORMATO3_RE.search(normalizar(t))), max_paginas=2)
        except Exception:  # noqa: BLE001
            continue
        if texto is not None and (formato := leer_pdf(pdfs[archivo], archivo)) is not None:
            return formato
    return None


_COMPOSICION_RE = re.compile(
    r"COMPOSICION\s+ACCIONARIA|CERTIFICACION\s+ACCIONARIA|CERTIFICAD[OA]\s+DE\s+(?:LOS\s+)?SOCIOS|SOCIOS\s+Y/?O\s+ACCIONISTAS|CONFORMACION\s+(?:ACCIONARIA|DE\s+LA\s+(?:PERSONA|SOCIEDAD))"
    r"|LIBRO\s+(?:OFICIAL\s+)?DE\s+(?:REGISTRO\s+DE\s+)?(?:ACCIONISTAS|SOCIOS)"
)


def verificador_de_socios(
    pdfs: dict[str, bytes], integrantes: list[IntegranteTecnico], fecha_cierre: date,
):
    """3.5.2 E: la experiencia de socios vale si la sociedad tiene menos de
    tres años y aporta el documento de su conformación firmado por el
    representante legal y el revisor fiscal o contador; pasados los tres
    años la sociedad la conserva tal como quedó en el RUP."""
    memoria: dict[str, tuple[bool | None, str]] = {}

    def verificar(nombre: str) -> tuple[bool | None, str]:
        if nombre in memoria:
            return memoria[nombre]
        integrante = next((i for i in integrantes if i.nombre == nombre), None)
        constitucion = integrante.rup.fecha_constitucion if integrante and integrante.rup else None
        if constitucion is None:
            memoria[nombre] = (None, "no se leyó su fecha de constitución en el RUP")
            return memoria[nombre]
        try:
            tres_anos = constitucion.replace(year=constitucion.year + 3)
        except ValueError:  # 29 de febrero
            tres_anos = constitucion.replace(year=constitucion.year + 3, day=28)
        if tres_anos <= fecha_cierre:
            memoria[nombre] = (True, f"constituida el {constitucion:%d/%m/%Y}, tiene más de tres años y conserva la experiencia registrada en su RUP")
            return memoria[nombre]
        nit = _digitos(integrante.nit or integrante.rup.nit)
        for archivo, contenido in pdfs.items():
            try:
                texto = buscar_pagina(contenido, lambda t: bool(_COMPOSICION_RE.search(normalizar(t))), max_paginas=2)
            except Exception:  # noqa: BLE001
                continue
            if texto is None:
                continue
            texto = normalizar(texto)
            de_la_sociedad = (nit and nit in re.sub(r"\D", "", texto)) or _mismo_nombre(nombre, texto[:3000]) or normalizar(nombre)[:20] in texto
            firmas = "REPRESENTANTE LEGAL" in texto and re.search(r"REVISOR\s+FISCAL|CONTADOR", texto)
            if de_la_sociedad and firmas and esta_firmado(contenido):
                memoria[nombre] = (True, f"constituida el {constitucion:%d/%m/%Y} (menos de tres años); aporta la certificación de su composición: {archivo}")
                return memoria[nombre]
        memoria[nombre] = (
            None,
            f"constituida el {constitucion:%d/%m/%Y} (menos de tres años): no se encontró el documento de su conformación "
            "firmado por el representante legal y el revisor fiscal o contador",
        )
        return memoria[nombre]

    return verificar


_PALABRAS_COMUNES = {
    "SAS", "S.A.S", "LTDA", "SA", "CONSORCIO", "UNION", "TEMPORAL", "INGENIERIA", "INGENIEROS", "CONSTRUCCIONES",
    "CONSTRUCTORA", "OBRAS", "CIVILES", "PROYECTOS", "SERVICIOS", "INVERSIONES", "GRUPO", "GROUP", "SOCIEDAD", "COLOMBIA",
    "ASOCIADOS", "INFRAESTRUCTURA", "CONSULTORES", "CONSULTORIA",
}


def _sigla_en(nombre: str, rup: Rup) -> bool:
    """El nombre del Formato 2 es la sigla que el RUP trae junto a la razón
    social ("KONSTRUCCIONES Y KONSULTORIAS S.A.S. - KONKON S.A.S."): todas sus
    palabras propias están en el encabezado del RUP."""
    palabras = [p for p in normalizar(nombre).replace(".", " ").split() if p not in _PALABRAS_COMUNES and len(p) >= 3]
    return bool(palabras) and all(re.search(rf"\b{re.escape(p)}\b", rup.encabezado) for p in palabras)


def integrantes_del_proponente(
    pdfs: dict[str, bytes], rups: list[tuple[str, Rup]], plural: bool, codigo_proceso: str | None,
) -> tuple[list[IntegranteTecnico], list[str]]:
    avisos: list[str] = []
    if not plural:
        if len(rups) == 1:
            rup = rups[0][1]
            return [IntegranteTecnico(nombre=rup.nombre, nit=rup.nit, participacion=1.0, rup=rup)], avisos
        if not rups:
            avisos.append("no se encontró el RUP del proponente")
            return [], avisos
        avisos.append(f"se encontraron {len(rups)} RUP de un proponente individual; se usan todos")
        return [IntegranteTecnico(nombre=r.nombre, nit=r.nit, participacion=None, rup=r) for _, r in rups], avisos

    del_formato2 = integrantes_formato2(pdfs, codigo_proceso)
    datos = datos_formato2(pdfs, codigo_proceso)
    porcentajes = datos[1].porcentajes if datos else []
    if del_formato2 and len(porcentajes) != len(del_formato2):
        avisos.append("no se pudo asociar el porcentaje de participación de cada integrante en el Formato 2")
        porcentajes = []
    integrantes: list[IntegranteTecnico] = []
    sin_usar = list(rups)
    # De lo más seguro a lo menos: NIT, nombre, sigla.
    pruebas = (
        lambda persona, rup: bool(_digitos(persona.identificacion)) and _digitos(persona.identificacion) == _digitos(rup.nit),
        lambda persona, rup: _mismo_nombre(persona.nombre, rup.nombre),
        lambda persona, rup: _sigla_en(persona.nombre, rup),
    )
    asignados: dict[int, tuple[str, Rup]] = {}
    for prueba in pruebas:
        for i, persona in enumerate(del_formato2):
            if i in asignados:
                continue
            rup = next((r for r in sin_usar if prueba(persona, r[1])), None)
            if rup is not None:
                asignados[i] = rup
                sin_usar.remove(rup)
    for i, persona in enumerate(del_formato2):
        rup = asignados.get(i)
        integrantes.append(IntegranteTecnico(
            nombre=persona.nombre, nit=persona.identificacion,
            participacion=porcentajes[i] / 100 if porcentajes else None,
            rup=rup[1] if rup else None,
        ))
    sin_rup = [i for i in integrantes if i.rup is None]
    if len(sin_rup) == 1 and len(sin_usar) == 1:
        # Un integrante y un RUP sin pareja: el RUP está a nombre de la razón
        # social completa y el Formato 2 usa otra forma del nombre.
        sin_rup[0].rup = sin_usar[0][1]
        avisos.append(f"el RUP de {sin_rup[0].nombre} está a nombre de {sin_usar[0][1].nombre}; verifica que sea el mismo")
    else:
        for integrante in sin_rup:
            avisos.append(f"no se encontró el RUP de {integrante.nombre}")
    if not del_formato2:
        avisos.append("no se leyeron los integrantes del Formato 2; se toman los RUP aportados")
        integrantes = [IntegranteTecnico(nombre=r.nombre, nit=r.nit, participacion=None, rup=r) for _, r in rups]
    return integrantes, avisos


def aplicar_puntajes_del_pliego(factores: list[Factor], puntajes: dict[str, float | None]) -> list[Factor]:
    """El puntaje de cada factor sale del pliego (capítulo IV). "NO APLICA":
    no se evalúa. Si no se pudo leer, se deja a revisión con el valor del
    documento tipo como referencia."""
    for f in factores:
        if f.clave in puntajes and puntajes[f.clave] is None:
            f.puntaje_maximo, f.puntaje, f.no_aplica = 0, 0, True
            f.motivos = ["N.A. — el pliego dice que este factor NO APLICA"]
        elif f.clave in puntajes:
            f.puntaje_maximo = float(puntajes[f.clave])
            if f.puntaje is not None:
                f.puntaje = f.puntaje_maximo
        elif f.clave != "maquinaria":
            f.motivos.append(
                f"no se leyó en el pliego cuántos puntos da este factor; el documento tipo da {f.puntaje_maximo:g}: verifícalo"
            )
            f.puntaje = None
    return factores


def evaluar_proponente_tecnico(
    pdfs: dict[str, bytes], excels: dict[str, bytes], nombre_proponente: str, parametros: ParametrosTecnicos,
    fecha_cierre: date, codigo_proceso: str | None = None,
) -> ResultadoTecnico:
    resultado = ResultadoTecnico()
    rups = leer_rups(pdfs)
    resultado.rups = [a for a, _ in rups]
    plural = bool(_PLURAL_RE.match(normalizar(nombre_proponente))) or len(integrantes_formato2(pdfs, codigo_proceso)) >= 2
    integrantes, avisos = integrantes_del_proponente(pdfs, rups, plural, codigo_proceso)
    resultado.integrantes = integrantes
    resultado.avisos.extend(avisos)
    formato3 = encontrar_formato3(pdfs, excels)
    resultado.formato3 = formato3.archivo if formato3 else None
    textos: dict[str, str] = {}
    resultado.lotes = evaluar_experiencia(
        formato3, integrantes, parametros, fecha_cierre, plural,
        lambda c: longitud_del_contrato(pdfs, textos, c.numero_contrato, c.contratante),
        verificador_de_socios(pdfs, integrantes, fecha_cierre),
        lambda c: area_del_contrato(pdfs, textos, c.numero_contrato, c.contratante),
    )
    resultado.puntaje = aplicar_puntajes_del_pliego([
        *factor_calidad(pdfs, codigo_proceso),
        industria_nacional(pdfs, integrantes, codigo_proceso),
        discapacidad(pdfs, integrantes, resultado.lotes, plural, fecha_cierre),
        emprendimiento_mujeres(pdfs, integrantes, plural, fecha_cierre),
        mipyme(integrantes, plural),
        Factor("maquinaria", "4.2.2 Disponibilidad y condiciones funcionales de la maquinaria de obra", 0,
               motivos=["el programa no verifica este factor: revísalo a mano con lo que pide el pliego"]),
    ], parametros.puntajes)
    for lote in resultado.lotes:
        for aviso in avisos:
            lote.motivos.append(aviso)
            if lote.cumple:
                lote.cumple = False
    return resultado
