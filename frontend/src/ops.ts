/** Prestación de servicios (OPS): contratación directa de una persona. Se
 * verifican sus documentos y su experiencia frente al perfil del estudio previo. */
import { detalleError, enviarJson, ErrorApi, pedir, pedirJson } from './http'

export type EstadoOps = 'pendiente' | 'analizando' | 'lista' | 'confirmada' | 'error'
export type Posgrado = 'ninguno' | 'especializacion' | 'maestria'
export type EstadoDocumento = 'cumple' | 'falta' | 'revision' | 'no_cumple' | 'no_aplica'

export const NOMBRE_ESTADO: Record<EstadoOps, string> = {
  pendiente: 'En fila',
  analizando: 'Leyendo documentos',
  lista: 'Para revisar',
  confirmada: 'Confirmada',
  error: 'Con error',
}
export const NOMBRE_POSGRADO: Record<Posgrado, string> = {
  ninguno: 'Sin posgrado',
  especializacion: 'Especialización',
  maestria: 'Maestría o más',
}
export const NOMBRE_NIVEL: Record<string, string> = {
  profesional: 'Profesional',
  tecnologo: 'Tecnólogo',
  tecnico: 'Técnico',
  ...NOMBRE_POSGRADO,
}

export interface ResumenOps {
  id: string
  referencia: string
  contratista_nombre: string
  contratista_cedula: string
  estado: EstadoOps
  creada_en: string
  creada_por: string
  entidad: string
  objeto: string
}

export interface ListaOps {
  /** La entidad tiene la licencia del módulo; sin ella la opción lleva candado. */
  licenciado: boolean
  puede_crear: boolean
  puede_configurar: boolean
  contrataciones: ResumenOps[]
}

export interface PerfilOps {
  anios_minimos: number
  anios_maximos: number | null
  posgrado: Posgrado
  honorarios_mensuales: number
  obligaciones: string[]
  /** Experiencia específica (calificada) que además pide el perfil, en años. */
  especifica_minima: number
  especifica_maxima: number | null
  /** La frase del estudio previo que define el perfil. */
  descripcion: string
  corregido: boolean
}

export interface MatriculaOps {
  profesion: string
  numero: string
  fecha: string | null
  sin_sanciones: boolean
}

export interface TituloOps {
  nivel: string
  nombre: string
  fecha: string | null
  documento_id: string | null
  pagina: number | null
  /** Lo declara la persona en su hoja de vida; el diploma no se pudo leer. */
  declarado?: boolean
}

export interface PeriodoOps {
  id: string
  entidad: string
  referencia: string
  inicio: string
  fin: string
  /** Sin fecha de terminación en la certificación: se contó hasta su expedición. */
  abierto: boolean
  /** Algo de la lectura que una persona debe confirmar. */
  nota: string
  /** Lo agregó una persona; no viene de un documento. */
  manual: boolean
  /** Una persona le corrigió fechas, entidad o contrato. */
  corregido: boolean
  documento_id: string | null
  pagina: number | null
  /** cuenta · sobra (se propone retirar) · descartado (traslape o anterior al grado) · retirado (por la persona) */
  estado: 'cuenta' | 'sobra' | 'descartado' | 'retirado'
  motivo: string
  dias: number
  duracion: string
  cuenta_desde?: string
  recortado?: boolean
  relacionada?: boolean
  obligaciones_iguales?: number[]
  fijo?: boolean
}

export interface DocumentoOps {
  clave: string
  nombre: string
  estado: EstadoDocumento
  estado_final: EstadoDocumento
  motivo: string
  documento_id: string | null
  archivo: string | null
  fecha: string | null
  /** Otros archivos que son este mismo documento. */
  adicionales: { documento_id: string | null; archivo: string }[]
  decision: { estado: EstadoDocumento; nota: string } | null
}

export interface DetalleOps {
  id: string
  referencia: string
  estado: EstadoOps
  error: string
  contratista_nombre: string
  contratista_cedula: string
  exige_libreta: boolean | null
  fecha_referencia: string
  creada_en: string
  creada_por: string
  analizada_en: string | null
  segundos: number | null
  confirmada_en: string | null
  confirmada_por: string | null
  archivos: { id: string; origen: 'entidad' | 'contratista'; nombre: string; tamano: number }[]
  // Lo siguiente llega cuando termina el análisis.
  estudio?: { documento_id: string; objeto: string; plazo_meses: number | null; valor: number | null } | null
  cdp?: { documento_id: string; valor: number } | null
  perfil?: PerfilOps | null
  titulos?: TituloOps[]
  matricula?: MatriculaOps | null
  grado?: string | null
  grado_corregido?: boolean
  posgrado?: Posgrado
  posgrado_corregido?: boolean
  experiencia?: PeriodoOps[]
  total_dias?: number
  total?: string
  total_leido?: string
  relacionada_dias?: number
  relacionada?: string
  franja?: string | null
  tope?: number | null
  tabla_honorarios?: string | null
  documentos?: DocumentoOps[]
  documentos_pendientes?: number
  sin_reconocer?: { documento_id: string | null; archivo: string }[]
  revisiones?: string[]
  /** null mientras quede algo por revisar. */
  cumple?: boolean | null
}

export interface PeriodoNuevo {
  inicio: string
  fin: string
  entidad: string
  referencia: string
  relacionada: boolean
}

export interface DecisionesOps {
  periodos?: Record<
    string,
    { incluir?: boolean | null; relacionada?: boolean | null; entidad?: string; referencia?: string; inicio?: string; fin?: string }
  >
  /** Un periodo que la persona agrega a mano, y el id de uno agregado que quita. */
  agregar?: PeriodoNuevo
  quitar?: string
  perfil?:
    | {
        anios_minimos: number
        anios_maximos: number | null
        posgrado: Posgrado
        honorarios_mensuales: number
        especifica_minima: number
        especifica_maxima: number | null
      }
    | Record<string, never>
  grado?: string | null
  /** Posgrado que acredita la persona, cuando el diploma no se leyó ('' = lo leído). */
  posgrado?: Posgrado | ''
  documentos?: Record<string, { estado: EstadoDocumento; nota: string } | null>
}

export interface FranjaProfesional {
  desde: number
  hasta: number | null
  sin_especializacion: number
  con_especializacion: number
  con_maestria: number
}
export interface FranjaReconocimiento {
  desde: number
  hasta: number | null
  valor: number
}
export interface TablaHonorarios {
  vigencia: number
  norma: string
  profesional: FranjaProfesional[]
  reconocimiento: FranjaReconocimiento[]
  vigencias: number[]
}

const conEntidad = (entidadId?: string | null) => (entidadId ? `?entidad_id=${entidadId}` : '')

export const listarOps = (entidadId?: string | null) => pedirJson<ListaOps>(`/api/ops${conEntidad(entidadId)}`)
export const verOps = (id: string) => pedirJson<DetalleOps>(`/api/ops/${id}`)
export const decidirOps = (id: string, decisiones: DecisionesOps) => enviarJson<DetalleOps>(`/api/ops/${id}/decisiones`, 'PUT', decisiones)
export const corregirDatosOps = (
  id: string,
  datos: { contratista_nombre?: string; contratista_cedula?: string; exige_libreta?: boolean | null; fecha_referencia?: string; referencia?: string },
) => enviarJson<DetalleOps>(`/api/ops/${id}/datos`, 'PUT', datos)
export const reanalizarOps = (id: string) => enviarJson<DetalleOps>(`/api/ops/${id}/reanalizar`, 'POST')
export const confirmarOps = (id: string) => enviarJson<DetalleOps>(`/api/ops/${id}/confirmar`, 'POST')
export const reabrirOps = (id: string) => enviarJson<DetalleOps>(`/api/ops/${id}/reabrir`, 'POST')
export const eliminarOps = (id: string) => pedirJson<void>(`/api/ops/${id}`, { method: 'DELETE' })
export const urlCertificado = (id: string) => `/api/ops/${id}/certificado`
export const urlDocumento = (id: string, documentoId: string, pagina?: number | null) =>
  `/api/ops/${id}/documentos/${documentoId}${pagina ? `#page=${pagina}` : ''}`

async function enviarFormulario<T>(ruta: string, formulario: FormData): Promise<T> {
  const res = await pedir(ruta, { method: 'POST', body: formulario })
  if (!res.ok) throw new ErrorApi(res.status, await detalleError(res))
  return res.json() as Promise<T>
}

export function crearOps(datos: {
  nombre: string
  cedula: string
  referencia: string
  fechaReferencia: string
  exigeLibreta: '' | 'si' | 'no'
  entidadId: string | null
  documentosEntidad: File[]
  documentosContratista: File[]
}): Promise<DetalleOps> {
  const f = new FormData()
  f.append('contratista_nombre', datos.nombre)
  f.append('contratista_cedula', datos.cedula)
  f.append('referencia', datos.referencia)
  if (datos.fechaReferencia) f.append('fecha_referencia', datos.fechaReferencia)
  f.append('exige_libreta', datos.exigeLibreta)
  if (datos.entidadId) f.append('entidad_id', datos.entidadId)
  for (const a of datos.documentosEntidad) f.append('documentos_entidad', a)
  for (const a of datos.documentosContratista) f.append('documentos_contratista', a)
  return enviarFormulario('/api/ops', f)
}

export function agregarDocumentosOps(id: string, origen: 'entidad' | 'contratista', archivos: File[]): Promise<DetalleOps> {
  const f = new FormData()
  f.append('origen', origen)
  for (const a of archivos) f.append('archivos', a)
  return enviarFormulario(`/api/ops/${id}/documentos`, f)
}

export const verHonorarios = (vigencia?: number, entidadId?: string | null) => {
  const q = new URLSearchParams()
  if (vigencia) q.set('vigencia', String(vigencia))
  if (entidadId) q.set('entidad_id', entidadId)
  return pedirJson<TablaHonorarios>(`/api/ops/honorarios${q.size ? `?${q}` : ''}`)
}
export const guardarHonorarios = (tabla: Omit<TablaHonorarios, 'vigencias'>, entidadId?: string | null) =>
  enviarJson<TablaHonorarios>('/api/ops/honorarios', 'PUT', { ...tabla, entidad_id: entidadId ?? null })
