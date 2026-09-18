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

export type TipoHallazgo = 'ajuste_parametro' | 'requisito_nuevo' | 'aclaracion' | 'informativo' | 'fuera_de_alcance'

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

export interface AnalisisPliego {
  id: string
  nombre_archivo: string
  paginas: number
  documento_tipo: string
  reutilizado: boolean
  hallazgos: HallazgoPliego[]
  secciones: SeccionPliego[]
}

export interface DecisionPliego {
  decision: 'aceptado' | 'rechazado'
  nota: string
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
}


export async function analizarDocumentoBase(
  codigoProceso: string,
  fechaCierre: string,
  archivo: File,
  carpetaDrive: string,
  entidadId?: string | null,
): Promise<AnalisisResponse> {
  const formData = new FormData()
  formData.append('codigo_proceso', codigoProceso)
  formData.append('fecha_cierre', fechaCierre)
  formData.append('archivo', archivo)
  if (carpetaDrive.trim()) {
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
export async function analizarPliego(archivo: File, entidadId: string | null): Promise<AnalisisPliego> {
  const formData = new FormData()
  formData.append('archivo', archivo)
  if (entidadId) formData.append('entidad_id', entidadId)
  const res = await pedir('/api/procesos/pliego', { method: 'POST', body: formData })
  if (!res.ok) throw new Error(await extractErrorDetail(res))
  return res.json()
}
