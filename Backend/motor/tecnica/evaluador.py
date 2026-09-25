"""Enlace del motor técnico con la plataforma.

La evaluación técnica de un proponente se calcula una sola vez (RUP,
Formato 3, soportes, formatos de puntaje) y cada requisito de la
definición toma su parte: la experiencia de cada lote, cada factor de
puntaje. Números internos:

- 101, 102, …: experiencia habilitante de cada lote (101 = primer lote).
- 121 a 127: factores de puntaje.
- 130: obras civiles inconclusas (la consulta la hace la entidad).

Un requisito que "cumple" en un factor de puntaje significa que el puntaje
se otorga; si no se pudo verificar va a revisión, y quien revisa decide.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date

from motor.esquemas.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from motor.integrations.drive import download_file_bytes, get_file_metadata
from motor.procesamiento.zip_utils import extraer_hojas_de_calculo, pdfs_con_aportados
from motor.tecnica.experiencia import ResultadoLote
from motor.tecnica.parametros import LoteTecnico, ParametrosTecnicos
from motor.tecnica.proponente import ResultadoTecnico, evaluar_proponente_tecnico
from motor.tecnica.puntaje import Factor

NUMERO_EXPERIENCIA = 101
FACTORES: dict[str, int] = {
    "gerencia_proyectos": 121,
    "plan_calidad": 122,
    "criterios_ambientales": 123,
    "industria_nacional": 124,
    "discapacidad": 125,
    "mujeres": 126,
    "mipyme": 127,
    "maquinaria": 128,
}
OBRAS_INCONCLUSAS = 130

# Último proponente calculado en este worker: los requisitos del mismo
# proponente lo comparten.
_ULTIMO: tuple[str, ResultadoTecnico] | None = None


def parametros_a_dict(parametros: ParametrosTecnicos) -> dict:
    """Los parámetros como JSON: los conjuntos se guardan como listas
    ordenadas (un set no se puede serializar y rompe la API)."""
    datos = asdict(parametros)
    datos["clases_unspsc"] = sorted(parametros.clases_unspsc)
    datos["factores_nombrados"] = sorted(parametros.factores_nombrados)
    return datos


def parametros_de_dict(datos: dict) -> ParametrosTecnicos:
    datos = dict(datos)
    lotes = [LoteTecnico(**l) for l in datos.pop("lotes", [])]
    clases = set(datos.pop("clases_unspsc", []))
    nombrados = set(datos.pop("factores_nombrados", []))
    tabla = [tuple(f) for f in datos.pop("tabla_valor", [])]
    parametros = ParametrosTecnicos(**datos, lotes=lotes, clases_unspsc=clases, factores_nombrados=nombrados)
    if tabla:
        parametros.tabla_valor = tabla
    return parametros


def _base(proponente: Proponente, numero: int) -> dict:
    return {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
        "requisito": numero,
    }


def resultado_tecnico(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoTecnico:
    global _ULTIMO
    if not proceso.parametros_tecnicos:
        raise ValueError("El proceso no tiene los parámetros técnicos del pliego (presupuesto por lote, experiencia exigida).")
    try:
        md5 = (get_file_metadata(proponente.drive_file_id) or {}).get("md5Checksum")
    except Exception:  # noqa: BLE001
        md5 = None
    aportados = hashlib.md5(b"".join(c for _, c in proponente.documentos_aportados)).hexdigest()
    parametros_json = json.dumps(proceso.parametros_tecnicos, sort_keys=True, default=str)
    clave = f"{proponente.drive_file_id}|{md5}|{aportados}|{hashlib.md5(parametros_json.encode()).hexdigest()}"
    if _ULTIMO is not None and _ULTIMO[0] == clave:
        return _ULTIMO[1]
    _ULTIMO = None
    zip_bytes = download_file_bytes(proponente.drive_file_id)
    pdfs = pdfs_con_aportados(zip_bytes, proponente)
    resultado = evaluar_proponente_tecnico(
        pdfs, extraer_hojas_de_calculo(zip_bytes), proponente.nombre_proponente,
        parametros_de_dict(proceso.parametros_tecnicos), proceso.fecha_cierre, proceso.codigo_proceso,
    )
    _ULTIMO = (clave, resultado)
    return resultado


def _detalle_lote(lote: ResultadoLote, resultado: ResultadoTecnico) -> dict:
    return {
        "lote": lote.lote,
        "valor_a_certificar": lote.valor_a_certificar,
        "factor": lote.factor,
        "valor_certificado": lote.valor_certificado,
        "un_contrato_70": lote.un_contrato_70,
        "longitud": lote.longitud,
        "longitud_minima_km": lote.longitud_minima_km,
        "condiciones_plural": lote.condiciones_plural,
        "aporte_por_integrante": lote.aporte_por_integrante,
        # Lo que falta por mirar, separado por ámbito: lo del proceso sale del
        # pliego y se resuelve una vez para todos los proponentes; lo de la
        # oferta hay que mirarlo aquí.
        "experiencia_acreditada": lote.experiencia_acreditada,
        "revisiones": [
            {"clave": r.clave, "ambito": r.ambito, "que": r.que, "donde": r.donde}
            for r in lote.revisiones
        ],
        "contratos": [
            {
                "orden": c.orden,
                "consecutivos": c.consecutivos,
                "contratante": c.contratante,
                "numero_contrato": c.numero_contrato,
                "objeto": c.objeto,
                "valor_smmlv": c.valor_smmlv,
                "participacion": c.participacion,
                "valor_aportado": c.valor_aportado,
                "aportes": c.aportes,
                "unspsc": c.unspsc,
                "de_un_socio": c.de_un_socio,
                "longitud_km": c.longitud_km,
                "soporte_longitud": c.soporte_longitud,
                "cita_longitud": c.cita_longitud,
                "area_m2": c.area_m2,
                "soporte_area": c.soporte_area,
                "soporte": c.soporte,
                "problemas": c.problemas,
            }
            for c in lote.contratos
        ],
        "integrantes": [
            {"nombre": i.nombre, "nit": i.nit, "participacion": i.participacion, "rup": i.rup.nombre if i.rup else None,
             "tamano": i.rup.tamano_empresa if i.rup else None}
            for i in resultado.integrantes
        ],
        "formato3": resultado.formato3,
        "rups": resultado.rups,
    }


def evaluar_experiencia_lote(proponente: Proponente, proceso: ProcesoDocumentoBase, indice: int, numero: int) -> ResultadoRequisito:
    resultado = resultado_tecnico(proponente, proceso)
    if indice >= len(resultado.lotes):
        return ResultadoRequisito(**_base(proponente, numero), error="El pliego no tiene ese lote.")
    lote = resultado.lotes[indice]
    motivo = "; ".join(dict.fromkeys(lote.motivos)) or None
    if lote.valor_a_certificar is not None and (lote.cumple or lote.experiencia_acreditada):
        certifica = (
            f"Certifica {lote.valor_certificado:,.2f} SMMLV con {len([c for c in lote.contratos if c.valido])} contrato(s); "
            f"se requieren {lote.valor_a_certificar:,.2f}."
        )
        if lote.cumple:
            motivo = certifica + (f" {motivo}" if motivo else "")
        else:
            # La experiencia del proponente quedó acreditada y lo que falta sale
            # del pliego, igual para todos: se dice así para que quien revisa no
            # vuelva a mirar los contratos de cada oferta.
            faltan = lote.revisiones_del_proceso
            motivo = (
                f"{certifica} La experiencia está acreditada con lo aportado. Falta resolver "
                f"{len(faltan)} punto(s) del pliego, iguales para todos los proponentes: "
                + "; ".join(r.que for r in faltan[:3])
                + (" …" if len(faltan) > 3 else "")
            )
    return ResultadoRequisito(
        **_base(proponente, numero),
        cumple=bool(lote.cumple),
        motivo=motivo,
        archivo_evaluado=resultado.formato3,
        detalle=_detalle_lote(lote, resultado),
    )


def evaluar_factor(proponente: Proponente, proceso: ProcesoDocumentoBase, clave: str, numero: int) -> ResultadoRequisito:
    resultado = resultado_tecnico(proponente, proceso)
    factor: Factor | None = next((f for f in resultado.puntaje if f.clave == clave), None)
    if factor is None:
        return ResultadoRequisito(**_base(proponente, numero), error=f"Factor desconocido: {clave}")
    detalle = {"factor_clave": factor.clave, "puntaje_maximo": factor.puntaje_maximo, "puntaje": factor.puntaje}
    if factor.no_aplica:
        return ResultadoRequisito(**_base(proponente, numero), cumple=True, motivo=factor.motivos[0], detalle=detalle)
    otorgado = factor.puntaje is not None and factor.puntaje > 0
    motivo = "; ".join(factor.motivos) or None
    return ResultadoRequisito(
        **_base(proponente, numero),
        cumple=otorgado,
        motivo=(f"Otorga {factor.puntaje:g} puntos. {motivo}" if otorgado and motivo else
                f"Otorga {factor.puntaje:g} puntos." if otorgado else motivo),
        archivo_evaluado=factor.archivo,
        detalle=detalle,
    )


def evaluar_obras_inconclusas(proponente: Proponente, proceso: ProcesoDocumentoBase, numero: int) -> ResultadoRequisito:
    """Consulta el Registro Nacional de Obras Civiles Inconclusas por cada
    integrante. Sin anotaciones de ninguno: no hay descuento. Con alguna, o si
    no se pudo consultar a todos: a revisión (quien revisa decide el
    descuento de un punto)."""
    from motor.consultas import obras_inconclusas as registro

    base = _base(proponente, numero)
    detalle = {"factor_clave": "obras_inconclusas", "puntaje_maximo": 0, "fuente": registro.PAGINA}
    if proceso.codigo_proceso.upper().startswith("DEMO-"):
        # Los procesos de demostración tienen personas ficticias: nunca se consultan.
        return ResultadoRequisito(**base, cumple=False, detalle=detalle,
                                  motivo="Proceso de demostración: el registro de obras inconclusas no se consulta con datos ficticios.")
    resultado = resultado_tecnico(proponente, proceso)
    consultas, sin_identificacion = [], []
    for integrante in resultado.integrantes:
        numero_id = registro.identificacion_para_consulta(integrante.nit or (integrante.rup.nit if integrante.rup else None))
        if numero_id is None:
            sin_identificacion.append(integrante.nombre)
            continue
        consultas.append(registro.consultar(numero_id, integrante.nombre))
    detalle["consultas"] = [
        {"nombre": c.nombre, "identificacion": c.identificacion, "consultado": c.consultado, "obras": c.obras, "error": c.error}
        for c in consultas
    ]
    motivos = []
    if not resultado.integrantes:
        motivos.append("no se identificaron los integrantes del proponente para consultarlos")
    if sin_identificacion:
        motivos.append(f"no se leyó el NIT o la cédula de: {', '.join(sin_identificacion)}; consúltalos a mano")
    for c in consultas:
        if not c.consultado:
            motivos.append(f"no se pudo consultar a {c.nombre} ({c.identificacion}): {c.error}")
        elif c.obras:
            obras = "; ".join(f"{o.get('GRUPO')} en {o.get('CIUDAD')} ({o.get('ROL')}): {str(o.get('DESCRIPCION'))[:120]}" for o in c.obras)
            motivos.append(f"{c.nombre} ({c.identificacion}) tiene {len(c.obras)} anotación(es) en el registro: {obras}")
    consultados = ", ".join(f"{c.nombre} ({c.identificacion})" for c in consultas if c.consultado)
    if motivos:
        return ResultadoRequisito(**base, cumple=False, detalle=detalle, motivo=(
            "; ".join(motivos) + ". Una anotación vigente descuenta un punto del factor de calidad (Ley 2020 de 2020)."
            + (f" Sin anotaciones: {consultados}." if consultados and not any(c.obras for c in consultas) else "")
        ))
    return ResultadoRequisito(**base, cumple=True, detalle=detalle, motivo=(
        f"Sin anotaciones en el Registro Nacional de Obras Civiles Inconclusas (consultado el {date.today():%d/%m/%Y}): {consultados}."
    ))
