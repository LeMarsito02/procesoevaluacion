/** API de procesos y evaluaciones guardados en el servidor. */
import type { AnalisisResponse, DecisionPliego, HallazgoPliego, ProcesoDocumentoBase, Proponente, ResultadoRequisito } from './api'
import type { InfoRequisito } from './requisitos'
import { detalleError, enviarJson, ErrorApi, pedir, pedirJson } from './http'

export type EstadoEvaluacion = 'sin_asignar' | 'asignada' | 'evaluando' | 'en_revision' | 'aprobada'

export interface Persona {
  id: string
  nombre_completo: string
  email: string
}

export interface Avance {
  proponentes: number
  evaluados: number
  con_error: number
  pendientes: number
  revisados: number
  en_fila: number
  procesando: number
}

export interface Fila {
  en_fila: number
  procesando: number
  por_delante: number
  capacidad: number
  segundos_por_proponente: number
  eta_segundos: number | null
}

export interface EvaluacionResumen {
  id: string
  tipo: string
  tipo_nombre: string
  estado: EstadoEvaluacion
  estado_nombre: string
  responsable: Persona | null
  avance: Avance
  entidad_id: string
  entidad_nombre: string
  proceso_id: string
  proceso_codigo: string
  proceso_objeto: string
  fecha_cierre: string
  actualizada_en: string
  aprobada_en: string | null
  puede_trabajar: boolean
  puede_gestionar: boolean
  tipo_disponible: boolean
  plantilla_version: number | null
  plantilla_nombre: string
  plantilla_desactualizada: boolean
  fila: Fila | null
}

export interface ProcesoResumen {
  id: string
  codigo: string
  objeto: string
  fecha_cierre: string
  creado_en: string
  creado_por: Persona
  proponentes: number
  evaluaciones: EvaluacionResumen[]
}

export interface ProponenteGuardado extends Proponente {
  id: string
}

export interface RevisionGuardada {
  proponente_id: string
  hoja: string
  requisito: number
  cumple: boolean
  nota: string
  usuario: string
  fecha: string
}

export interface EvaluacionDetalle {
  evaluacion: EvaluacionResumen
  documento_base: ProcesoDocumentoBase
  carpeta_drive: string
  proponentes_no_reconocidos: string[]
  proponentes: ProponenteGuardado[]
  resultados: ResultadoRequisito[]
  revisiones: RevisionGuardada[]
  catalogo: InfoRequisito[]
  pliego: PliegoProceso | null
}

/** Decisión tomada al crear el proceso sobre un hallazgo del pliego. */
export interface AjustePliego {
  id: string
  decision: 'aceptado' | 'rechazado'
  nota: string
  por: string
  en: string
  hallazgo: HallazgoPliego
}

export interface PliegoProceso {
  nombre_archivo: string
  paginas: number
  documento_tipo: string
  ajustes: AjustePliego[]
  aclaraciones: HallazgoPliego[]
}

export const urlPliego = (evaluacionId: string) => `/api/evaluaciones/${evaluacionId}/pliego`

export interface MiembroCarga extends Persona {
  rol: string
  rol_nombre: string
  areas: string[]
  evaluaciones_activas: number
  pendientes: number
}

export const listarProcesos = () => pedirJson<ProcesoResumen[]>('/api/evaluaciones/procesos')
export const misEvaluaciones = () => pedirJson<EvaluacionResumen[]>('/api/evaluaciones/mias')
export const cargaEquipo = (entidadId?: string | null) =>
  pedirJson<MiembroCarga[]>(`/api/evaluaciones/equipo${entidadId ? `?entidad_id=${entidadId}` : ''}`)
export const obtenerEvaluacion = (id: string) => pedirJson<EvaluacionDetalle>(`/api/evaluaciones/${id}`)

export const crearProceso = (datos: {
  documento_base: ProcesoDocumentoBase
  carpeta_drive: string
  proponentes: Proponente[]
  proponentes_no_reconocidos: string[]
  tipos: string[]
  entidad_id?: string | null
  responsable_id?: string | null
  sin_responsable?: boolean
  responsables?: Record<string, string | null>
  analisis_pliego_id?: string | null
  decisiones_pliego?: Record<string, DecisionPliego>
}) => enviarJson<EvaluacionResumen[]>('/api/evaluaciones/procesos', 'POST', datos)

export const guardarDocumentoBase = (id: string, doc: ProcesoDocumentoBase) =>
  enviarJson<ProcesoDocumentoBase>(`/api/evaluaciones/${id}/documento-base`, 'PUT', doc)
export const asignarEvaluacion = (id: string, responsableId: string | null) =>
  enviarJson<EvaluacionResumen>(`/api/evaluaciones/${id}/asignar`, 'POST', { responsable_id: responsableId })
export const aprobarEvaluacion = (id: string) => enviarJson<EvaluacionResumen>(`/api/evaluaciones/${id}/aprobar`, 'POST')
export const reabrirEvaluacion = (id: string) => enviarJson<EvaluacionResumen>(`/api/evaluaciones/${id}/reabrir`, 'POST')
export const guardarRevision = (id: string, proponenteId: string, requisito: number, cumple: boolean | null, nota = '') =>
  enviarJson<RevisionGuardada | null>(`/api/evaluaciones/${id}/revisiones`, 'PUT', {
    proponente_id: proponenteId,
    requisito,
    cumple,
    nota,
  })

export const encolarEvaluacion = (id: string, proponenteIds?: string[]) =>
  enviarJson<EvaluacionResumen>(`/api/evaluaciones/${id}/evaluar`, 'POST', { proponente_ids: proponenteIds ?? null })
export const pausarEvaluacion = (id: string) => enviarJson<EvaluacionResumen>(`/api/evaluaciones/${id}/pausar`, 'POST')
export const novedadesEvaluacion = (id: string, desde: string | null) =>
  pedirJson<{ evaluacion: EvaluacionResumen; resultados: ResultadoRequisito[]; hasta: string }>(
    `/api/evaluaciones/${id}/novedades${desde ? `?desde=${encodeURIComponent(desde)}` : ''}`,
  )

async function descargarBlob(ruta: string): Promise<{ blob: Blob; nombre: string | null }> {
  const res = await pedir(ruta)
  if (!res.ok) throw new ErrorApi(res.status, await detalleError(res))
  const disposicion = res.headers.get('Content-Disposition') ?? ''
  const nombre = /filename="([^"]+)"/.exec(disposicion)?.[1] ?? null
  return { blob: await res.blob(), nombre }
}

export const descargarInforme = (id: string) => descargarBlob(`/api/evaluaciones/${id}/informe`)
export const verDocumentoProponente = (id: string, proponenteId: string, archivo: string) =>
  descargarBlob(`/api/evaluaciones/${id}/proponentes/${proponenteId}/documento?archivo=${encodeURIComponent(archivo)}`).then((r) => r.blob)

export type { AnalisisResponse }

export interface TrabajadorFila {
  id: string
  capacidad: number
  iniciado_en: string
  latido: string
  activo: boolean
}

export interface EstadoFilaGlobal {
  capacidad_activa: number
  segundos_por_proponente: number
  total_en_fila: number
  total_procesando: number
  trabajadores: TrabajadorFila[]
  evaluaciones: EvaluacionResumen[]
}

export const estadoDeLaFila = () => pedirJson<EstadoFilaGlobal>('/api/evaluaciones/fila/estado')

export interface TipoEvaluacion {
  clave: 'juridica' | 'tecnica' | 'financiera'
  nombre: string
  descripcion: string
  disponible: boolean
}

export const listarTipos = () => pedirJson<TipoEvaluacion[]>('/api/evaluaciones/tipos')

export const actualizarPlantillaEvaluacion = (id: string) =>
  enviarJson<EvaluacionResumen>(`/api/evaluaciones/${id}/actualizar-plantilla`, 'POST')
