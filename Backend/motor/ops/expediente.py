"""Lectura completa del expediente de una prestación de servicios: los
documentos de la entidad (estudio previo y CDP) y los del contratista.

No decide nada: deja lo leído para que `idoneidad` lo evalúe con las reglas
y las correcciones de la persona.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from motor.ops import documentos as motor_documentos
from motor.ops.certificaciones import leer_periodos
from motor.ops.estudio_previo import EstudioPrevio, leer_estudio_previo, problema_con_el_cdp, valor_del_cdp
from motor.ops.experiencia import Periodo
from motor.ops.hoja_de_vida import ExperienciaDeclarada, estudios_declarados, experiencia_declarada
from motor.ops.honorarios import ESPECIALIZACION, MAESTRIA
from motor.ops.identidad import libreta_exigible
from motor.ops.matricula import Matricula, leer_matricula
from motor.ops.titulos import PROFESIONAL, Titulo, leer_titulos
from motor.procesamiento.pdf_utils import paginas_de_texto
from motor.tecnica.rup import normalizar

_ESTUDIO_PREVIO_RE = re.compile(r"ESTUDIOS?\s+PREVIOS?")
_CDP_RE = re.compile(r"DISPONIBILIDAD\s+PRESUPUESTAL")
NIVELES_SUPERIORES = (PROFESIONAL, ESPECIALIZACION, MAESTRIA)
NO_ES_DE_LA_PERSONA = "No se leyó en la certificación el nombre ni la cédula de la persona: confirme que es suya."


@dataclass
class Expediente:
    estudio: EstudioPrevio | None = None
    estudio_archivo: str | None = None
    cdp: int | None = None
    cdp_archivo: str | None = None
    documentos: list[motor_documentos.ResultadoDocumento] = field(default_factory=list)
    periodos: list[Periodo] = field(default_factory=list)
    titulos: list[Titulo] = field(default_factory=list)
    matricula: Matricula | None = None
    # Experiencia que la persona relacionó en su hoja de vida del SIGEP (None: no aportó la hoja de vida).
    sigep: ExperienciaDeclarada | None = None
    # Archivos del contratista que no correspondieron a ningún documento exigido.
    sin_reconocer: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def leer_expediente(
    de_la_entidad: dict[str, bytes], del_contratista: dict[str, bytes], nombre: str, cedula: str | None,
    fecha_referencia: date | None = None, exige_libreta: bool | None = None,
) -> Expediente:
    exp = Expediente()
    for archivo, contenido in de_la_entidad.items():
        try:
            texto = "\n".join(paginas_de_texto(contenido))
        except Exception:  # noqa: BLE001
            exp.avisos.append(f"No se pudo leer «{archivo}».")
            continue
        cabecera = normalizar(texto[:3000])
        if exp.cdp is None and _CDP_RE.search(cabecera) and (valor := valor_del_cdp(texto)) is not None:
            exp.cdp, exp.cdp_archivo = valor, archivo
        elif exp.estudio is None and _ESTUDIO_PREVIO_RE.search(cabecera):
            leido = leer_estudio_previo(texto)
            if leido.perfil or leido.objeto:
                exp.estudio, exp.estudio_archivo = leido, archivo
    if exp.estudio is None:
        exp.avisos.append("No se encontró el estudio previo entre los documentos de la entidad: registre el perfil a mano.")
    else:
        exp.avisos.extend(exp.estudio.avisos)
        if problema := problema_con_el_cdp(exp.estudio, exp.cdp):
            exp.avisos.append(problema)

    textos = motor_documentos.leer_textos(del_contratista)
    motivo_libreta = ""
    if exige_libreta is None:
        exige_libreta, motivo_libreta = libreta_exigible(cedula, textos, fecha_referencia)
    exp.documentos, clasificacion = motor_documentos.verificar_documentos(
        del_contratista, nombre, cedula, fecha_referencia, exige_libreta, textos=textos
    )
    # Lo deducido (de la cédula o de la hoja de vida) no basta para dar la
    # libreta por «no aplica»: se propone y lo confirma quien revisa. Solo lo
    # que se indicó al crear la contratación es definitivo.
    if motivo_libreta:
        for r in exp.documentos:
            if r.clave == "libreta_militar" and r.estado == motor_documentos.NO_APLICA:
                r.estado, r.motivo = motor_documentos.REVISION, motivo_libreta
    exp.sin_reconocer = clasificacion.sin_reconocer
    de = {r.clave: [a for a in (r.archivo, *r.adicionales) if a] for r in exp.documentos}
    if archivo := next(iter(de.get("vigencia_matricula", [])), None):
        try:
            exp.matricula = leer_matricula("\n".join(paginas_de_texto(del_contratista[archivo], 2)))
        except Exception:  # noqa: BLE001
            pass
    # Las certificaciones y los títulos pueden venir en varios archivos: además
    # de los reconocidos, se leen los que no correspondieron a otro documento.
    certificaciones, titulos = de.get("certificaciones_laborales", []), de.get("titulos", [])
    for archivo in dict.fromkeys([*certificaciones, *titulos, *exp.sin_reconocer]):
        try:
            paginas = paginas_de_texto(del_contratista[archivo])
        except Exception:  # noqa: BLE001
            exp.avisos.append(f"No se pudo leer «{archivo}».")
            continue
        if archivo not in titulos:
            lectura = leer_periodos(paginas, archivo, fecha_referencia)
            exp.periodos.extend(lectura.periodos)
            if archivo in certificaciones or lectura.periodos:
                exp.avisos.extend(lectura.avisos)
        if archivo not in certificaciones:
            exp.titulos.extend(leer_titulos(paginas, archivo))
    # Una certificación de otra persona metida en el paquete no puede sumar:
    # la suya debe traer su cédula o su nombre.
    for periodo in exp.periodos:
        if not motor_documentos._es_de_la_persona(periodo.contexto, nombre, cedula):
            periodo.nota = (periodo.nota + " " if periodo.nota else "") + NO_ES_DE_LA_PERSONA
    _completar_con_la_hoja_de_vida(exp, del_contratista, next(iter(de.get("hoja_de_vida_sigep", [])), None))
    exp.periodos.sort(key=lambda p: (p.inicio, p.fin))
    return exp


def _completar_con_la_hoja_de_vida(exp: Expediente, del_contratista: dict[str, bytes], archivo: str | None) -> None:
    """Lo que no se pudo leer de los diplomas (fecha de grado, posgrado) se
    toma de la hoja de vida de la función pública, marcado como declarado."""
    if archivo is None:
        return
    try:
        texto = "\n".join(paginas_de_texto(del_contratista[archivo]))
    except Exception:  # noqa: BLE001
        return
    exp.sigep = experiencia_declarada(texto)
    declarados = estudios_declarados(texto, archivo)
    leidos = [t for t in exp.titulos if t.nivel in NIVELES_SUPERIORES]
    falta_grado = not any(t.nivel == PROFESIONAL and t.fecha for t in leidos)
    posgrados_leidos = {t.nivel for t in leidos if t.nivel in (ESPECIALIZACION, MAESTRIA)}
    tomados = [
        t for t in declarados
        if (t.nivel == PROFESIONAL and falta_grado) or (t.nivel in (ESPECIALIZACION, MAESTRIA) and t.nivel not in posgrados_leidos)
    ]
    if tomados:
        exp.titulos.extend(tomados)
        que = " y ".join(dict.fromkeys("la fecha de grado" if t.nivel == PROFESIONAL else "el posgrado" for t in tomados))
        exp.avisos.append(f"No se pudo leer en los diplomas {que}: se tomó de la hoja de vida de la función pública. Confírmelo contra el diploma.")
