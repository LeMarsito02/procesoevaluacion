/** Factor económico (RF-11), ofertas artificialmente bajas (RF-13) y coincidencias entre ofertas (RF-14). */
import { detalleError, enviarJson, ErrorApi, pedir, pedirJson } from './http'

export interface OfertaEconomica {
  id: string
  proponente_id: string
  proponente: string
  hoja: string
  valor_ofertado: string
  valor_corregido: string | null
  corregido_por: string | null
  revision: { diferencias?: string[]; sin_verificar?: string[]; propuesto?: string | null; items?: number; total_declarado?: string | null }
  nombre_archivo: string
  estado: 'valida' | 'rechazada'
  motivo_rechazo: string
  alerta_baja: string | null
  /** Si el proponente quedó habilitado en los requisitos habilitantes: solo se califica a los habilitados. */
  habilitacion: 'habilitado' | 'no_habilitado' | 'pendiente'
  justificacion: '' | 'solicitada' | 'aceptada' | 'no_aceptada'
  nota: string
}

export interface Factor {
  id: string
  lote: string
  orden: number
  puntaje_maximo: string | null
  presupuesto_oficial: string | null
  costo_estimado: string | null
  tabla_metodos: 'vigentes' | 'anteriores'
  trm: string | null
  fecha_trm: string | null
  metodo: string | null
  metodo_nombre: string
  error_metodo: string
  rangos: { desde: number; hasta: number; metodo: string }[]
  bajas: { metodo: 'relativa' | 'absoluta'; explicacion: string; valor_minimo_aceptable: number | null } | null
  ofertas: OfertaEconomica[]
  por_confirmar: string[]
  calificacion: {
    metodo_nombre: string
    referencia: number | null
    explicacion: string
    centavos_trm: number
    trm: string
    fecha_trm: string
    puntajes: { proponente: string; hoja: string; valor: string; puntaje: number }[]
  } | null
  confirmada_por: string | null
  confirmada_en: string | null
}

export interface Economica {
  puede_registrar: boolean
  proponentes: { id: string; nombre: string; hoja: string }[]
  factores: Factor[]
}

const base = (procesoId: string) => `/api/economica/procesos/${procesoId}`
export const verEconomica = (procesoId: string) => pedirJson<Economica>(base(procesoId))
export const guardarParametros = (procesoId: string, factorId: string, datos: Partial<Record<string, string | null>>) =>
  enviarJson<Economica>(`${base(procesoId)}/factores/${factorId}`, 'PUT', datos)
export const decidirOferta = (procesoId: string, ofertaId: string, datos: Record<string, unknown>) =>
  enviarJson<Economica>(`${base(procesoId)}/ofertas/${ofertaId}`, 'PUT', datos)
export const calificarFactor = (procesoId: string, factorId: string) => enviarJson<Economica>(`${base(procesoId)}/factores/${factorId}/calificar`, 'POST')

export async function registrarOferta(procesoId: string, factorId: string, proponenteId: string, valor: string, archivo: File | null): Promise<Economica> {
  const f = new FormData()
  f.append('proponente_id', proponenteId)
  f.append('valor_ofertado', valor)
  if (archivo) f.append('archivo', archivo)
  const res = await pedir(`${base(procesoId)}/factores/${factorId}/ofertas`, { method: 'POST', body: f })
  if (!res.ok) throw new ErrorApi(res.status, await detalleError(res))
  return res.json() as Promise<Economica>
}

export interface Coincidencia {
  clave: string
  tipo: string
  tipo_nombre: string
  valor: string
  detalle: string
  ofertas: string[]
  proponentes: string[]
}
export interface Coincidencias {
  puede_registrar: boolean
  calculado: boolean
  coincidencias?: Coincidencia[]
  comunes?: Coincidencia[]
  avisos?: string[]
  ofertas?: number
  revisiones?: Record<string, { nota: string; por: string; en: string }>
  calculado_en?: string
  calculado_por?: string | null
}
const baseC = (procesoId: string) => `/api/coincidencias/procesos/${procesoId}`
export const verCoincidencias = (procesoId: string) => pedirJson<Coincidencias>(baseC(procesoId))
export const calcularCoincidencias = (procesoId: string) => enviarJson<Coincidencias>(baseC(procesoId), 'POST')
export const revisarCoincidencia = (procesoId: string, clave: string, nota: string) =>
  enviarJson<Coincidencias>(`${baseC(procesoId)}/${clave}`, 'PUT', { nota })
