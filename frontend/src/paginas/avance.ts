import type { EvaluacionResumen } from '../evaluaciones'
import { formatFechaCorta } from '../format'

export function diasParaCierre(iso: string): number {
  const hoy = new Date()
  hoy.setHours(0, 0, 0, 0)
  return Math.round((new Date(`${iso}T00:00:00`).getTime() - hoy.getTime()) / 86400000)
}

export function textoCierre(iso: string): string {
  const d = diasParaCierre(iso)
  if (d === 0) return 'Cierra hoy'
  if (d === 1) return 'Cierra mañana'
  if (d > 1) return `Cierra en ${d} días`
  return `Cerró el ${formatFechaCorta(iso)}`
}

/** Porcentaje de trabajo hecho: evaluar cuenta la mitad y revisar la otra mitad. */
export function porcentajeAvance(e: EvaluacionResumen): number {
  const { proponentes, evaluados, pendientes, revisados } = e.avance
  if (e.estado === 'aprobada') return 100
  if (!proponentes) return 0
  const evaluacion = evaluados / proponentes
  const porRevisar = pendientes + revisados
  const revision = evaluados === proponentes ? (porRevisar ? revisados / porRevisar : 1) : 0
  return Math.round((evaluacion * 0.5 + revision * 0.5) * 100)
}
