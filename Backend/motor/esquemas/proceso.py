from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class Lote(BaseModel):
    numero: str = Field(..., description='Identificador del lote, ej. "LOTE 1"')
    objeto: str = Field(..., description="Descripción del objeto del lote o segmento")
    plazo_meses: int = Field(..., description="Plazo de ejecución del contrato, en meses")
    valor_presupuesto: float = Field(..., description="Valor del Presupuesto Oficial del lote, en pesos")
    lugar_ejecucion: str | None = Field(default=None, description="Lugar(es) de ejecución del contrato")


class GarantiaSeriedad(BaseModel):
    vigencia_meses: int = Field(..., description="Meses de vigencia contados desde la fecha de cierre")
    porcentaje: float = Field(..., description="Porcentaje del valor asegurado, ej. 0.10 para 10%")
    base_calculo: str = Field(
        ..., description='"lote_mayor_valor" si aplica sobre el lote de mayor valor, "presupuesto_total" si aplica sobre la suma de todos los lotes'
    )
    lote_base: str | None = Field(default=None, description="Lote sobre el que se calculó la garantía, cuando aplica")
    valor_base: float = Field(..., description="Valor en pesos sobre el que se calculó el porcentaje")
    valor_asegurado: float = Field(..., description="Valor asegurado resultante (valor_base * porcentaje)")
    fecha_cierre: date
    fecha_vencimiento: date = Field(..., description="fecha_cierre + vigencia_meses")


class Proponente(BaseModel):
    numero_orden: int = Field(..., description="Número p1, p2, p3... con el que llegó el proponente en Drive")
    hoja: str = Field(..., description='Hoja del Excel que le corresponde, ej. "P-01"')
    nombre_proponente: str = Field(..., description="Nombre del proponente extraído del nombre del archivo")
    nombre_archivo: str = Field(..., description="Nombre original del archivo/carpeta en Drive")
    drive_file_id: str
    advertencia: str | None = Field(default=None, description="Ej. nombre de archivo que no se pudo interpretar")


class ProcesoDocumentoBase(BaseModel):
    codigo_proceso: str
    fecha_cierre: date
    objeto_general: str
    lotes: list[Lote]
    lote_mayor_valor: str
    presupuesto_total: float
    garantia_seriedad: GarantiaSeriedad
    advertencias: list[str] = Field(
        default_factory=list,
        description="Mensajes sobre datos que no se pudieron extraer con certeza y deben revisarse manualmente",
    )
    # Definición de evaluación de la entidad (motor.criterios.DefinicionEvaluacion
    # serializada). None = evaluación jurídica base del sistema.
    criterios: dict | None = Field(default=None, exclude=True)


class AnalisisResponse(BaseModel):
    documento_base: ProcesoDocumentoBase
    proponentes: list[Proponente] = Field(default_factory=list)
    proponentes_no_reconocidos: list[str] = Field(
        default_factory=list, description="Archivos de la carpeta de Drive cuyo nombre no siguió el patrón pN <nombre>"
    )
    drive_error: str | None = Field(default=None, description="Motivo por el que no se pudo leer la carpeta de Drive")


class ResultadoRequisito(BaseModel):
    hoja: str
    numero_orden: int
    nombre_proponente: str
    requisito: int = Field(default=1, description="Número del requisito jurídico evaluado (por ahora solo el 1)")
    cumple: bool | None = Field(default=None, description="None si no se pudo evaluar (ej. error al descargar el zip)")
    motivo: str | None = Field(default=None, description="Explicación de por qué no cumple, cuando aplica")
    archivo_evaluado: str | None = Field(default=None, description="Ruta dentro del zip del archivo que se evaluó")
    lotes_encontrados: list[str] = Field(default_factory=list)
    numero_proceso_encontrado: bool = False
    objeto_relacionado: bool | None = Field(
        default=None,
        description="El objeto descrito en la carta comparte suficientes palabras clave con el objeto del "
        "Documento Base (evita cartas recicladas de otro proceso)",
    )
    tipo_proponente: str | None = Field(
        default=None,
        description='Uno de "persona_natural", "persona_juridica", "consorcio", "union_temporal", "otro", según '
        'la casilla "El Proponente es:" del Formato 1. Lo usan otros requisitos (4, 5, 6, 12, 14-17) para saber '
        "si aplican como individuo o como plural.",
    )
    firma_detectada: bool = Field(
        default=False, description="Hay una firma (imagen escaneada o firma digital con certificado) en el documento"
    )
    representante_legal: str | None = Field(
        default=None, description="Nombre del representante legal declarado en el texto del Formato 1"
    )
    firma_nombre_certificado: str | None = Field(
        default=None,
        description="Nombre real extraído del certificado de firma digital, cuando la plataforma de firma lo incluye "
        "(muchas usan un ID genérico en vez del nombre, en cuyo caso queda en None)",
    )
    firma_confirmada: bool | None = Field(
        default=None,
        description="True si el nombre del certificado coincide con el representante legal declarado, False si "
        "coincide con otra persona, None si no se pudo verificar automáticamente (firma escaneada o certificado sin "
        "nombre real) y requiere revisión humana",
    )
    # --- Específicos del Requisito 2 (COPNIA: aval de ingeniero/arquitecto) ---
    matricula_profesional: str | None = Field(default=None, description="Número de matrícula profesional del COPNIA")
    profesion_certificada: str | None = Field(default=None, description="Profesión certificada en el COPNIA")
    copnia_vigente: bool | None = Field(default=None, description="El COPNIA indica que la matrícula está vigente")
    copnia_sin_antecedentes: bool | None = Field(
        default=None, description="El COPNIA indica que el profesional no tiene antecedentes disciplinarios"
    )
    copnia_fecha_expedicion: date | None = Field(default=None, description="Fecha de expedición del COPNIA")

    error: str | None = Field(default=None, description="Error técnico (descarga, zip corrupto, archivo no encontrado)")
    archivos_disponibles: list[str] = Field(
        default_factory=list,
        description="Rutas de todos los PDF hallados en el zip del proponente, para revisión manual cuando no se identificó el Formato 1 automáticamente (ej. documentos escaneados con mal OCR)",
    )


class GenerarExcelRequest(BaseModel):
    documento_base: ProcesoDocumentoBase
    proponentes: list[Proponente] = Field(default_factory=list)
    resultados: list[ResultadoRequisito] = Field(
        default_factory=list,
        description="Resultados de todos los requisitos evaluados, de cualquier número — cada uno ya trae su "
        "propio campo 'requisito' para saber en qué fila de cada hoja va",
    )


class EvaluarRequisitosRequest(BaseModel):
    documento_base: ProcesoDocumentoBase
    proponentes: list[Proponente]


class EvaluarProponenteRequest(BaseModel):
    documento_base: ProcesoDocumentoBase
    proponente: Proponente


class VerDocumentoRequest(BaseModel):
    drive_file_id: str
    archivo_evaluado: str
