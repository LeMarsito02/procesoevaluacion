import { detalleError, pedir } from './http'

export interface Lote {
  numero: string
  objeto: string
  plazo_meses: number
  valor_presupuesto: number
  lugar_ejecucion: string | null
}

export interface GarantiaSeriedad {
  vigencia_meses: number
  porcentaje: number
  base_calculo: 'lote_mayor_valor' | 'presupuesto_total'
  lote_base: string | null
  valor_base: number
  valor_asegurado: number
  fecha_cierre: string
  fecha_vencimiento: string
}

export interface ProcesoDocumentoBase {
  codigo_proceso: string
  fecha_cierre: string
  objeto_general: string
  lotes: Lote[]
  lote_mayor_valor: string
  presupuesto_total: number
  garantia_seriedad: GarantiaSeriedad
  advertencias: string[]
}

export interface Proponente {
  numero_orden: number
  hoja: string
  nombre_proponente: string
  nombre_archivo: string
  drive_file_id: string
  advertencia: string | null
}

export interface AnalisisResponse {
  documento_base: ProcesoDocumentoBase
  proponentes: Proponente[]
  proponentes_no_reconocidos: string[]
  drive_error: string | null
  pliego: AnalisisPliego | null
  pliego_error: string | null
}

export type TipoHallazgo =
  | 'ajuste_parametro'
  | 'requisito_nuevo'
  | 'requisito_no_exigido'
  | 'aclaracion'
  | 'informativo'
  | 'fuera_de_alcance'
  | 'obligacion'

/** Algo que dice el pliego frente a la forma de evaluar de la entidad, con su prueba literal. */
export interface HallazgoPliego {
  id: string
  tipo: TipoHallazgo
  titulo: string
  detalle: string
  seccion: string
  pagina: number
  cita: string
  verificacion: string | null
  parametro: string | null
  valor_plantilla: string | number | string[] | null
  valor_pliego: string | number | string[] | null
  valor_pliego_texto: string | null
  requiere_decision: boolean
}

export interface SeccionPliego {
  numero: string
  titulo: string
  pagina: number
  ambito: string
  verificaciones: string[]
}

/** Lectura profunda del pliego con la IA local (corre en el trabajador). */
export interface LecturaIA {
  estado: 'pendiente' | 'leyendo' | 'listo' | 'error' | 'no_disponible'
  progreso: number
  modelo: string
  requisitos: number
  error: string
}

/** Un requisito jurídico que exige el pliego y cómo se verificará. */
export interface RequisitoDelPliego {
  id: string
  requisito: string
  documento: string | null
  expide: string | null
  aplica_a: string[]
  vigencia_dias: number | null
  vigencia_meses: number | null
  condiciones: string[]
  cita: string
  seccion: string
  pagina: number
  verificacion: string | null
  como: string
  estado: 'motor' | 'motor_nuevo' | 'documento' | 'revision' | 'condicional' | 'extranjeros'
  parametros: Record<string, number>
}

export interface AnalisisPliego {
  id: string
  nombre_archivo: string
  paginas: number
  documento_tipo: string
  reutilizado: boolean
  hallazgos: HallazgoPliego[]
  secciones: SeccionPliego[]
  lectura_ia: LecturaIA
  requisitos: RequisitoDelPliego[]
}

export interface DecisionPliego {
  decision: 'aceptado' | 'rechazado'
  nota: string
}

/** Una persona o empresa a la que un requisito de antecedentes le exige certificado. */
export interface PersonaAntecedente {
  nombre: string
  documento: string | null
  tipo: 'natural' | 'juridica'
  rol: 'representante_legal' | 'suplente' | 'integrante' | 'proponente'
  estado: 'cumple' | 'falta' | 'con_novedad' | 'vencido'
  archivo: string | null
}

export interface ResultadoRequisito {
  hoja: string
  numero_orden: number
  nombre_proponente: string
  requisito: number
  cumple: boolean | null
  motivo: string | null
  archivo_evaluado: string | null
  lotes_encontrados: string[]
  numero_proceso_encontrado: boolean
  objeto_relacionado: boolean | null
  tipo_proponente: 'persona_natural' | 'persona_juridica' | 'consorcio' | 'union_temporal' | 'otro' | null
  firma_detectada: boolean
  representante_legal: string | null
  firma_nombre_certificado: string | null
  firma_confirmada: boolean | null
  matricula_profesional: string | null
  profesion_certificada: string | null
  copnia_vigente: boolean | null
  copnia_sin_antecedentes: boolean | null
  copnia_fecha_expedicion: string | null
  error: string | null
  archivos_disponibles: string[]
  /** A quién se le exigió el certificado en este requisito y cómo le fue. */
  personas_antecedente: PersonaAntecedente[]
  /** Evaluación técnica: contratos del lote o puntaje del factor. */
  detalle?: DetalleTecnico | null
}

export interface ContratoTecnico {
  orden: number
  consecutivos: string[]
  contratante: string
  numero_contrato: string
  objeto: string
  valor_smmlv: number | null
  participacion: number | null
  valor_aportado: number | null
  aportes: Record<string, number>
  unspsc: boolean | null
  de_un_socio: boolean
  longitud_km: number | null
  soporte_longitud: string | null
  area_m2?: number | null
  soporte_area?: string | null
  problemas: string[]
}

export interface IntegranteFinanciero {
  nombre: string
  nit: string | null
  participacion: number | null
  rup: string | null
  financiera: {
    fecha_corte: string | null
    activo_corriente: number | null
    activo_total: number | null
    pasivo_corriente: number | null
    pasivo_total: number | null
    patrimonio: number | null
    utilidad_operacional: number | null
    gastos_intereses: number | null
  } | null
}

export interface ResidualIntegrante {
  nombre: string
  co: number | null
  e: number | null
  puntos_e: number | null
  profesionales: number | null
  puntos_ct: number | null
  liquidez: number | null
  puntos_cf: number | null
  sce: number | null
  crp: number | null
}

export interface DetalleFinanciero {
  no_aplica?: boolean
  compartido?: boolean
  lote?: string
  liquidez?: number | null
  endeudamiento?: number | null
  cobertura?: number | null
  roa?: number | null
  roe?: number | null
  capital_de_trabajo?: number
  demandado?: number | null
  exigida?: number
  crp?: number
  lotes_cubiertos?: string[]
  integrantes?: ResidualIntegrante[]
  patrimonio?: number | null
  /** Validez: por integrante, sus estados financieros y el estado del certificado de cada tarjeta profesional. */
  validez?: Record<string, { estados: string[]; tarjetas: Record<string, string> }>
}

/** Una cosa concreta por revisar. El ámbito es lo que dice cuánto cuesta:
 * "proceso" sale del pliego y se resuelve una vez para todos los proponentes,
 * "oferta" hay que mirarlo en esta oferta. */
export interface PuntoDeRevision {
  clave: string
  ambito: 'proceso' | 'oferta'
  que: string
  donde: string
}

export interface DetalleTecnico {
  lote?: string
  valor_a_certificar?: number | null
  factor?: number | null
  valor_certificado?: number
  un_contrato_70?: boolean | null
  longitud?: boolean | null
  longitud_minima_km?: number | null
  condiciones_plural?: boolean | null
  aporte_por_integrante?: Record<string, number>
  contratos?: ContratoTecnico[]
  integrantes?: { nombre: string; nit: string | null; participacion: number | null; rup: string | null; tamano: string | null }[]
  formato3?: string | null
  /** Evaluación financiera: indicadores, capital de trabajo o capacidad residual. */
  financiera?: DetalleFinanciero
  integrantes_financieros?: IntegranteFinanciero[]
  factor_clave?: string
  puntaje_maximo?: number
  puntaje?: number | null
  /** Lo que falta por mirar, punto por punto. */
  revisiones?: PuntoDeRevision[]
  /** La experiencia quedó acreditada con lo aportado: si el lote aún no cumple,
   * lo que falta sale del pliego y se resuelve una vez, no oferta por oferta. */
  experiencia_acreditada?: boolean
}


export async function analizarDocumentoBase(
  codigoProceso: string,
  fechaCierre: string,
  archivo: File,
  carpetaDrive: string,
  entidadId?: string | null,
  /** Las ofertas subidas a mano, cuando no están en una carpeta compartida. */
  ofertas?: File[] | null,
): Promise<AnalisisResponse> {
  const formData = new FormData()
  formData.append('codigo_proceso', codigoProceso)
  formData.append('fecha_cierre', fechaCierre)
  formData.append('archivo', archivo)
  if (ofertas && ofertas.length > 0) {
    for (const oferta of ofertas) formData.append('ofertas', oferta)
  } else if (carpetaDrive.trim()) {
    formData.append('carpeta_drive', carpetaDrive.trim())
  }
  if (entidadId) formData.append('entidad_id', entidadId)

  const res = await pedir(`/api/procesos/analizar`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const detail = await extractErrorDetail(res)
    throw new Error(detail)
  }

  return res.json()
}

const extractErrorDetail = detalleError

/** Solo el pliego, cuando la entidad se elige después (superadministrador). */
/** El análisis del pliego con el avance de la lectura con IA. */
export async function consultarPliego(id: string, entidadId: string | null): Promise<AnalisisPliego> {
  const q = entidadId ? `?entidad_id=${encodeURIComponent(entidadId)}` : ''
  const res = await pedir(`/api/procesos/pliego/${id}${q}`)
  if (!res.ok) throw new Error(await extractErrorDetail(res))
  return res.json()
}

export async function analizarPliego(archivo: File, entidadId: string | null): Promise<AnalisisPliego> {
  const formData = new FormData()
  formData.append('archivo', archivo)
  if (entidadId) formData.append('entidad_id', entidadId)
  const res = await pedir('/api/procesos/pliego', { method: 'POST', body: formData })
  if (!res.ok) throw new Error(await extractErrorDetail(res))
  return res.json()
}
