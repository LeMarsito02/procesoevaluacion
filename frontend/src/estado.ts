import type { AnalisisResponse, ProcesoDocumentoBase, Proponente, ResultadoRequisito } from './api'
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

// ---------------------------------------------------------------------------
// Guardado en el navegador: una evaluación de 81 proponentes toma tiempo y no
// debe perderse si se cierra la pestaña. Todo con try/catch: si el navegador
// no deja guardar, la aplicación sigue funcionando igual.
// ---------------------------------------------------------------------------

export interface SesionGuardada {
  version: 1
  guardadoEn: number
  codigoProceso: string
  fechaCierre: string
  carpetaDrive: string
  proceso: ProcesoDocumentoBase
  proponentes: Proponente[]
  noReconocidos: string[]
  driveError: string | null
  resultados: Record<string, ResultadoRequisito[]>
  revisiones: Revisiones
}

const CLAVE_SESION = 'evaluador-juridico:sesion'

export function guardarSesion(sesion: SesionGuardada): void {
  try {
    localStorage.setItem(CLAVE_SESION, JSON.stringify(sesion))
  } catch {
    try {
      // Si no cabe, se guarda sin las listas de archivos disponibles.
      const liviana = {
        ...sesion,
        resultados: Object.fromEntries(
          Object.entries(sesion.resultados).map(([h, lista]) => [
            h,
            lista.map((r) => ({ ...r, archivos_disponibles: [] })),
          ]),
        ),
      }
      localStorage.setItem(CLAVE_SESION, JSON.stringify(liviana))
    } catch {
      /* sin guardado: la app sigue funcionando */
    }
  }
}

export function leerSesion(): SesionGuardada | null {
  try {
    const crudo = localStorage.getItem(CLAVE_SESION)
    if (!crudo) return null
    const sesion = JSON.parse(crudo) as SesionGuardada
    return sesion.version === 1 ? sesion : null
  } catch {
    return null
  }
}

export function borrarSesion(): void {
  try {
    localStorage.removeItem(CLAVE_SESION)
  } catch {
    /* nada */
  }
}

export type { AnalisisResponse }
