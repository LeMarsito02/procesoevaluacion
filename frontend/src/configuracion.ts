/** API de configuración por entidad (plantillas de informe). */
import { detalleError, enviarJson, ErrorApi, pedir, pedirJson } from './http'

export interface MapeoPlantilla {
  prefijo_codigo: string
  titulo: string
  hoja_proponente_patron: string
  hoja_modelo: string | null
  celda_titulo: string | null
  celda_objeto: string | null
  celda_nombre_proponente: string | null
  columna_resultado: string
  columna_detalle: string
  filas_por_requisito: Record<string, number>
  hoja_resumen: string | null
  celda_resumen: string | null
  texto_cumple: string
  texto_no_cumple: string
  texto_revisar: string
  agregar_hoja_datos: boolean
}

export interface InspeccionPlantilla {
  valida: boolean
  problemas: string[]
  hojas: string[]
  hojas_proponente: number
  filas: Record<string, string>
}

export interface Plantilla {
  id: string
  tipo: string
  nombre_original: string
  subida_en: string
  subida_por: string | null
  activa: boolean
  mapeo: MapeoPlantilla
  inspeccion: InspeccionPlantilla
}

export interface PlantillasTipo {
  tipo: string
  tipo_nombre: string
  motor_disponible: boolean
  activa: Plantilla | null
  usa_plantilla_del_sistema: boolean
  historial: Plantilla[]
}

const q = (entidadId?: string | null) => (entidadId ? `?entidad_id=${entidadId}` : '')

export const listarPlantillas = (entidadId?: string | null) => pedirJson<PlantillasTipo[]>(`/api/configuracion/plantillas${q(entidadId)}`)

export async function subirPlantilla(tipo: string, archivo: File, entidadId?: string | null): Promise<Plantilla> {
  const datos = new FormData()
  datos.append('tipo', tipo)
  datos.append('archivo', archivo)
  const res = await pedir(`/api/configuracion/plantillas${q(entidadId)}`, { method: 'POST', body: datos })
  if (!res.ok) throw new ErrorApi(res.status, await detalleError(res))
  return res.json()
}

export const ajustarMapeo = (id: string, mapeo: MapeoPlantilla) =>
  enviarJson<Plantilla>(`/api/configuracion/plantillas/${id}/mapeo`, 'PUT', { mapeo })
export const activarPlantilla = (id: string) => enviarJson<Plantilla>(`/api/configuracion/plantillas/${id}/activar`, 'POST')
export const borrarPlantilla = (id: string) => enviarJson<void>(`/api/configuracion/plantillas/${id}`, 'DELETE')

export async function descargarPlantilla(p: Plantilla) {
  const res = await pedir(`/api/configuracion/plantillas/${p.id}/archivo`)
  if (!res.ok) throw new ErrorApi(res.status, await detalleError(res))
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = p.nombre_original
  a.click()
  URL.revokeObjectURL(url)
}

// --- Plantillas de evaluación ---
export type GrupoRequisito =
  | 'oferta'
  | 'camara'
  | 'antecedentes'
  | 'experiencia'
  | 'puntaje'
  | 'financiera'
  | 'residual'
  | 'adicionales'
export type TipoProponente = 'persona_natural' | 'persona_juridica' | 'consorcio' | 'union_temporal'

export interface Bloque {
  tipo: 'vigencia_maxima' | 'contiene' | 'no_contiene' | 'menciona_representante' | 'menciona_proponente'
  meses?: number | null
  frases?: string[]
}

export interface ConfigPersonalizado {
  frases_documento: string[]
  paginas: number
  bloques: Bloque[]
  aplica_a: TipoProponente[]
}

export interface RequisitoDefinicion {
  numero: number
  titulo: string
  corto: string
  grupo: GrupoRequisito
  verificacion: string
  verifica: string
  fila_excel: number | null
  config: ConfigPersonalizado | null
}

export interface DefinicionEvaluacion {
  parametros: Record<string, unknown>
  requisitos: RequisitoDefinicion[]
}

export interface Parametro {
  clave: string
  nombre: string
  descripcion: string
  defecto: unknown
  tipo: 'entero' | 'texto' | 'lista_texto'
  minimo: number | null
  maximo: number | null
  unidad: string
}

export interface VerificacionMotor {
  clave: string
  corto: string
  titulo: string
  verifica: string
  grupo: GrupoRequisito
}

export interface CatalogoMotor {
  grupos: Record<string, string>
  parametros: Parametro[]
  verificaciones: VerificacionMotor[]
  tipos_proponente: TipoProponente[]
}

export interface VersionPlantilla {
  id: string
  version: number
  nombre: string
  nota: string
  activa: boolean
  creada_en: string
  creada_por: string | null
  evaluaciones: number
}

export interface PlantillaEvaluacion {
  tipo: string
  tipo_nombre: string
  motor_disponible: boolean
  activa: VersionPlantilla | null
  definicion: DefinicionEvaluacion
  versiones: VersionPlantilla[]
}

export const catalogoMotor = (tipo: string) => pedirJson<CatalogoMotor>(`/api/configuracion/catalogo?tipo=${tipo}`)
export const listarPlantillasEvaluacion = (entidadId?: string | null) =>
  pedirJson<PlantillaEvaluacion[]>(`/api/configuracion/evaluaciones${q(entidadId)}`)
export const publicarPlantillaEvaluacion = (
  datos: { tipo: string; nombre: string; definicion: DefinicionEvaluacion; nota: string },
  entidadId?: string | null,
) => enviarJson<VersionPlantilla>(`/api/configuracion/evaluaciones${q(entidadId)}`, 'POST', datos)
export const activarVersionPlantilla = (id: string) => enviarJson<VersionPlantilla>(`/api/configuracion/evaluaciones/${id}/activar`, 'POST')
export const probarRequisito = (datos: {
  evaluacion_id: string
  requisito: RequisitoDefinicion
  parametros: Record<string, unknown>
  proponente_ids: string[]
}) => enviarJson<import('./api').ResultadoRequisito[]>('/api/configuracion/requisitos/probar', 'POST', datos)
export const proponerRequisito = (tipo: string, descripcion: string) =>
  enviarJson<RequisitoDefinicion>('/api/configuracion/requisitos/proponer', 'POST', { tipo, descripcion })
