"""Enlace del motor financiero con la plataforma.

La evaluación financiera de un proponente se calcula una sola vez (RUP de
cada integrante, estados financieros, certificados de la Junta Central de
Contadores, Formato 5) y cada requisito de la definición toma su parte.
Números internos:

- 201: capacidad financiera (liquidez, endeudamiento, cobertura).
- 202: capacidad organizacional (rentabilidad del activo y del patrimonio).
- 203: validez de los documentos de la capacidad de organización.
- 204: patrimonio (solo si el pliego lo exige).
- 211, 212, …: capital de trabajo de cada lote.
- 221, 222, …: capacidad residual de cada lote.

Un requisito de un lote al que el proponente no se presenta queda "N.A.".
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from motor.esquemas.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito
from motor.financiera.capacidad import Revision
from motor.financiera.parametros import LoteFinanciero, ParametrosFinancieros, Umbrales
from motor.financiera.proponente import ResultadoFinanciero, evaluar_proponente_financiero
from motor.integrations.drive import download_file_bytes, get_file_metadata
from motor.procesamiento.zip_utils import extraer_hojas_de_calculo, pdfs_con_aportados

NUMEROS: dict[str, int] = {
    "indicadores": 201,
    "organizacional": 202,
    "validez": 203,
    "patrimonio": 204,
    "capital_trabajo": 211,
    "residual": 221,
}

# Último proponente calculado en este worker: los requisitos del mismo
# proponente lo comparten.
_ULTIMO: tuple[str, ResultadoFinanciero] | None = None


def parametros_a_dict(parametros: ParametrosFinancieros) -> dict:
    return asdict(parametros)


def parametros_de_dict(datos: dict) -> ParametrosFinancieros:
    datos = dict(datos)
    lotes = [LoteFinanciero(**l) for l in datos.pop("lotes", [])]
    umbrales = Umbrales(**datos.pop("umbrales", {}))
    return ParametrosFinancieros(**datos, lotes=lotes, umbrales=umbrales)


def _base(proponente: Proponente, numero: int) -> dict:
    return {
        "hoja": proponente.hoja,
        "numero_orden": proponente.numero_orden,
        "nombre_proponente": proponente.nombre_proponente,
        "requisito": numero,
    }


def resultado_financiero(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoFinanciero:
    global _ULTIMO
    if not proceso.parametros_financieros:
        raise ValueError("El proceso no tiene los parámetros financieros del pliego (presupuesto, plazo y anticipo por lote).")
    try:
        md5 = (get_file_metadata(proponente.drive_file_id) or {}).get("md5Checksum")
    except Exception:  # noqa: BLE001
        md5 = None
    aportados = hashlib.md5(b"".join(c for _, c in proponente.documentos_aportados)).hexdigest()
    parametros_json = json.dumps(proceso.parametros_financieros, sort_keys=True, default=str)
    clave = f"{proponente.drive_file_id}|{md5}|{aportados}|{hashlib.md5(parametros_json.encode()).hexdigest()}"
    if _ULTIMO is not None and _ULTIMO[0] == clave:
        return _ULTIMO[1]
    _ULTIMO = None
    zip_bytes = download_file_bytes(proponente.drive_file_id)
    pdfs = pdfs_con_aportados(zip_bytes, proponente)
    resultado = evaluar_proponente_financiero(
        pdfs, extraer_hojas_de_calculo(zip_bytes), proponente.nombre_proponente,
        parametros_de_dict(proceso.parametros_financieros), proceso.fecha_cierre, proceso.codigo_proceso,
    )
    _ULTIMO = (clave, resultado)
    return resultado


def _integrantes(resultado: ResultadoFinanciero) -> list[dict]:
    filas = []
    for i in resultado.integrantes:
        f = i.rup.financiera if i.rup else None
        filas.append({
            "nombre": i.nombre, "nit": i.nit, "participacion": i.participacion,
            "rup": i.rup.nombre if i.rup else None,
            "financiera": None if f is None else {
                "fecha_corte": str(f.fecha_corte) if f.fecha_corte else None, "activo_corriente": f.activo_corriente, "activo_total": f.activo_total,
                "pasivo_corriente": f.pasivo_corriente, "pasivo_total": f.pasivo_total, "patrimonio": f.patrimonio,
                "utilidad_operacional": f.utilidad_operacional, "gastos_intereses": f.gastos_intereses,
            },
        })
    return filas


def _resultado(proponente: Proponente, numero: int, revision: Revision | None, resultado: ResultadoFinanciero,
               extra: dict | None = None) -> ResultadoRequisito:
    if revision is None:
        return ResultadoRequisito(**_base(proponente, numero), error="No se calculó esta verificación.")
    motivos = list(dict.fromkeys(revision.motivos))
    # Lo que impide decidir con seguridad (integrantes, lotes) va primero.
    avisos = [a for a in resultado.avisos if a not in motivos]
    cumple = revision.cumple and not avisos
    return ResultadoRequisito(
        **_base(proponente, numero),
        cumple=cumple,
        motivo="; ".join(avisos + motivos) or None,
        detalle={"financiera": {**(revision.detalle or {}), **(extra or {})}, "integrantes_financieros": _integrantes(resultado)},
    )


def evaluar(proponente: Proponente, proceso: ProcesoDocumentoBase, clave: str, numero: int,
            lote: int | None = None) -> ResultadoRequisito:
    resultado = resultado_financiero(proponente, proceso)
    if clave == "indicadores":
        return _resultado(proponente, numero, resultado.financiera, resultado)
    if clave == "organizacional":
        return _resultado(proponente, numero, resultado.organizacional, resultado)
    if clave == "validez":
        return _resultado(proponente, numero, resultado.validez, resultado)
    if clave == "patrimonio":
        return _patrimonio(proponente, proceso, numero, resultado)
    lotes = parametros_de_dict(proceso.parametros_financieros).lotes
    indice = lote or 0
    if indice >= len(lotes):
        return ResultadoRequisito(**_base(proponente, numero), error="El pliego no tiene ese lote.")
    nombre = lotes[indice].nombre
    if nombre not in resultado.lotes_presentados:
        return ResultadoRequisito(
            **_base(proponente, numero), cumple=True,
            motivo=f"N.A. — el proponente no se presenta al {nombre.lower()}",
            detalle={"financiera": {"no_aplica": True, "lote": nombre}},
        )
    if clave == "capital_trabajo":
        return _resultado(proponente, numero, resultado.capital_por_lote.get(nombre), resultado, {"lote": nombre})
    if clave == "residual":
        residual = resultado.residual
        if residual is not None and not residual.cumple and nombre in (residual.detalle or {}).get("lotes_cubiertos", []):
            # No alcanza para todos los lotes pero sí para este (el de mayor
            # valor): se habilita en él (pliego 3.11).
            residual = Revision(True, [*residual.motivos, f"se habilita en el {nombre.lower()}, el de mayor valor que alcanza a cubrir"],
                                residual.detalle)
        return _resultado(proponente, numero, residual, resultado, {"lote": nombre})
    return ResultadoRequisito(**_base(proponente, numero), error=f"Verificación financiera desconocida: {clave}")


def _patrimonio(proponente: Proponente, proceso: ProcesoDocumentoBase, numero: int,
                resultado: ResultadoFinanciero) -> ResultadoRequisito:
    parametros = parametros_de_dict(proceso.parametros_financieros)
    if parametros.patrimonio_aplica is None:
        # No se leyó el plazo o el presupuesto del proceso: no se sabe si el
        # pliego lo exige, así que no se puede dar por no aplicable.
        return ResultadoRequisito(
            **_base(proponente, numero), cumple=False,
            motivo=("No se pudo determinar si el pliego exige patrimonio mínimo: falta el plazo o el presupuesto del "
                    "proceso (3.8). Revísalo en el pliego."),
            detalle={"financiera": {"patrimonio": None}},
        )
    if not parametros.patrimonio_aplica:
        return ResultadoRequisito(
            **_base(proponente, numero), cumple=True,
            motivo="N.A. — el pliego solo lo exige con presupuesto de 40.000 SMMLV o más y plazo de 24 meses o más",
            detalle={"financiera": {"no_aplica": True}},
        )
    patrimonio = resultado.indicadores.patrimonio if resultado.indicadores else None
    return ResultadoRequisito(
        **_base(proponente, numero), cumple=False,
        motivo=(f"Patrimonio del proponente (RUP) ${patrimonio:,.0f}: compáralo con el exigido en el pliego (3.8)."
                if patrimonio is not None else "No se leyó el patrimonio del RUP de todos los integrantes."),
        detalle={"financiera": {"patrimonio": patrimonio}, "integrantes_financieros": _integrantes(resultado)},
    )
