/** Asistente de consulta: conversaciones guardadas y respuesta transmitida en vivo. */
import { detalleError, enviarJson, ErrorApi, pedir, pedirJson } from './http'

export interface Fuente {
  evaluacion_id: string
  etiqueta: string
}

export interface Conversacion {
  id: string
  titulo: string
  actualizada_en: string
  /** Evaluación sobre la que se conversa; null = todas las de la persona. */
  evaluacion_id: string | null
}

export interface Mensaje {
  /** Negativo: aún no está guardado (se está escribiendo). */
  id: number
  rol: 'usuario' | 'asistente'
  contenido: string
  fuentes: Fuente[]
}

export interface OpcionEvaluacion {
  id: string
  etiqueta: string
  objeto: string
}

export interface EstadoAsistente {
  habilitado: boolean
  aviso: string
  conversaciones: Conversacion[]
  evaluaciones: OpcionEvaluacion[]
}

export type EventoAsistente =
  | { tipo: 'texto'; texto: string }
  | { tipo: 'consulta'; nombre: string }
  | { tipo: 'fuentes'; fuentes: Fuente[] }
  /** Hay otras respuestas generándose: esta espera turno. */
  | { tipo: 'espera' }
  | { tipo: 'error'; texto: string }
  | { tipo: 'fin' }

/** Con `evaluacionId`, solo las conversaciones sobre esa evaluación. */
export const estadoAsistente = (evaluacionId?: string) =>
  pedirJson<EstadoAsistente>(`/api/asistente${evaluacionId ? `?evaluacion_id=${evaluacionId}` : ''}`)
export const nuevaConversacion = (evaluacionId: string | null) =>
  enviarJson<Conversacion>('/api/asistente/conversaciones', 'POST', { evaluacion_id: evaluacionId })
export const verConversacion = (id: string) => pedirJson<Conversacion & { mensajes: Mensaje[] }>(`/api/asistente/conversaciones/${id}`)

/** Lo que el asistente está consultando, dicho para la persona. */
export const CONSULTAS: Record<string, string> = {
  mis_evaluaciones: 'Consultando sus evaluaciones',
  resumen_evaluacion: 'Revisando el estado de los proponentes',
  detalle_proponente: 'Revisando los requisitos del proponente',
  requisitos: 'Consultando los requisitos de la evaluación',
  pendientes: 'Buscando lo que falta por revisar',
}

/** Envía la pregunta y entrega cada evento de la respuesta en cuanto llega.
 * `evaluacionId` fija sobre qué evaluación se conversa (null = todas). */
export async function preguntar(
  conversacionId: string,
  texto: string,
  evaluacionId: string | null,
  alLlegar: (e: EventoAsistente) => void,
  senal?: AbortSignal,
) {
  const res = await pedir(`/api/asistente/conversaciones/${conversacionId}/mensajes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ texto, evaluacion_id: evaluacionId, cambiar_evaluacion: true }),
    signal: senal,
  })
  if (!res.ok || !res.body) throw new ErrorApi(res.status, await detalleError(res))
  const lector = res.body.getReader()
  const decodificador = new TextDecoder()
  let resto = ''
  for (;;) {
    const { done, value } = await lector.read()
    resto += decodificador.decode(value ?? new Uint8Array(), { stream: !done })
    const lineas = resto.split('\n')
    resto = lineas.pop() ?? ''
    for (const linea of lineas) {
      if (linea.trim()) alLlegar(JSON.parse(linea) as EventoAsistente)
    }
    if (done) break
  }
}
