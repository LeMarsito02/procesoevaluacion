import type { ResultadoRequisito } from './api'
import { REQUISITOS } from './requisitos'

/** Estado de un requisito tal como lo ve el abogado. */
export type Estado = 'cumple' | 'no_aplica' | 'revisar' | 'error' | 'revisado_cumple' | 'revisado_no_cumple'

export type Revisiones = Record<string, boolean>

export function claveRevision(hoja: string, requisito: number): string {
  return `${hoja}|${requisito}`
}

export function estadoDe(r: ResultadoRequisito, revisiones: Revisiones): Estado {
  const revision = revisiones[claveRevision(r.hoja, r.requisito)]
  if (revision === true) return 'revisado_cumple'
  if (revision === false) return 'revisado_no_cumple'
  if (r.error) return 'error'
  if ((r.motivo ?? '').startsWith('N.A.')) return 'no_aplica'
  if (r.cumple === true) return 'cumple'
  return 'revisar'
}

export const ETIQUETA_ESTADO: Record<Estado, string> = {
  cumple: 'Cumple',
  no_aplica: 'No aplica',
  revisar: 'Por revisar',
  error: 'No se pudo evaluar',
  revisado_cumple: 'Cumple · revisado',
  revisado_no_cumple: 'No cumple · revisado',
}

export function esPendiente(estado: Estado): boolean {
  return estado === 'revisar' || estado === 'error'
}

/** Resultado con la decisión del abogado aplicada, tal como va al Excel. */
export function aplicarRevision(r: ResultadoRequisito, revisiones: Revisiones): ResultadoRequisito {
  const revision = revisiones[claveRevision(r.hoja, r.requisito)]
  if (revision === undefined) return r
  if (revision) return { ...r, cumple: true, motivo: null, error: null }
  return {
    ...r,
    cumple: false,
    error: null,
    motivo: r.motivo || r.error || 'Revisado por el abogado: no cumple',
  }
}

export function usaIA(r: ResultadoRequisito): boolean {
  return (r.motivo ?? '').includes('IA local')
}

/** Conteos de un proponente sobre los requisitos visibles. */
export function resumenProponente(lista: ResultadoRequisito[] | undefined, revisiones: Revisiones) {
  const visibles = (lista ?? []).filter((r) => REQUISITOS.some((q) => q.numero === r.requisito))
  let pendientes = 0
  let revisados = 0
  let noCumple = 0
  for (const r of visibles) {
    const e = estadoDe(r, revisiones)
    if (esPendiente(e)) pendientes++
    if (e === 'revisado_cumple' || e === 'revisado_no_cumple') revisados++
    if (e === 'revisado_no_cumple') noCumple++
  }
  return { total: visibles.length, pendientes, revisados, noCumple }
}
