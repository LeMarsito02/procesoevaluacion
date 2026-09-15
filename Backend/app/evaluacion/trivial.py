from __future__ import annotations

from app.models.proceso import ProcesoDocumentoBase, Proponente, ResultadoRequisito


def evaluar_proponente_requisito13(proponente: Proponente, proceso: ProcesoDocumentoBase) -> ResultadoRequisito:
    """Requisito 13: Registro Único Tributario - RUT. El abogado confirmó que
    actualmente no se exige/valida este requisito en ningún proceso — siempre
    se marca N.A., sin necesidad de descargar ni revisar documentos."""
    del proceso  # no aplica, se deja explícito por claridad
    return ResultadoRequisito(
        hoja=proponente.hoja,
        numero_orden=proponente.numero_orden,
        nombre_proponente=proponente.nombre_proponente,
        requisito=13,
        cumple=True,
        motivo="N.A. — el RUT no se exige actualmente en esta evaluación",
    )
