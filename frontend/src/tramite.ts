/** Traslado del informe de evaluación: su término y las observaciones con su respuesta (RF-16). */
import { enviarJson, pedirJson } from './http'

export type DecisionObservacion = 'pendiente' | 'acoge' | 'acoge_parcial' | 'no_acoge'

export const NOMBRE_DECISION: Record<DecisionObservacion, string> = {
  pendiente: 'Pendiente',
  acoge: 'Se acoge',
  acoge_parcial: 'Se acoge parcialmente',
  no_acoge: 'No se acoge',
}

export interface Observacion {
  id: string
  consecutivo: number
  observante: string
  proponente_id: string | null
  proponente: string | null
  requisito: number | null
  recibida_en: string
  texto: string
  extemporanea: boolean
  respuesta: string
  decision: DecisionObservacion
  modifica_resultado: boolean
  respondida_por: string | null
  respondida_en: string | null
  registrada_por: string | null
}

export interface Tramite {
  puede_registrar: boolean
  traslado: { publicado_en: string; dias_habiles: number; vence_en: string; dias_habiles_restantes: number; vencido: boolean } | null
  proponentes: { id: string; nombre: string; hoja: string }[]
  observaciones: Observacion[]
  resumen: { observaciones: number; sin_responder: number }
}

const base = (id: string) => `/api/tramite/${id}`
export const verTramite = (id: string) => pedirJson<Tramite>(base(id))
export const fijarTraslado = (id: string, publicado_en: string, dias_habiles: number) =>
  enviarJson<Tramite>(`${base(id)}/traslado`, 'PUT', { publicado_en, dias_habiles })
export const crearObservacion = (
  id: string,
  datos: { observante: string; recibida_en: string; texto: string; proponente_id: string | null; requisito: number | null },
) => enviarJson<Tramite>(`${base(id)}/observaciones`, 'POST', datos)
export const responderObservacion = (id: string, oid: string, datos: { respuesta: string; decision: DecisionObservacion; modifica_resultado: boolean }) =>
  enviarJson<Tramite>(`${base(id)}/observaciones/${oid}`, 'PUT', datos)
export const urlMatriz = (id: string) => `${base(id)}/matriz`
