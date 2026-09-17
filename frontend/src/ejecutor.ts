/** Ejecuta la evaluación de los proponentes de una evaluación fuera de React,
 * para que siga avanzando mientras el usuario navega por otras páginas de la
 * app. Cada resultado se guarda en el servidor apenas termina. */
import type { ResultadoRequisito } from './api'
import { evaluarProponente } from './evaluaciones'
import { MENSAJE_SISTEMA } from './http'

// Pocas en paralelo: cada proponente puede ocupar cientos de MB en el servidor.
const CONCURRENCIA = 2

export interface EstadoEjecucion {
  evaluando: boolean
  inicio: number | null
  completados: number
  total: number
}

type AlResultado = (proponenteId: string, resultados: ResultadoRequisito[] | null, error: string | null) => void

interface Ejecucion {
  estado: EstadoEjecucion
  controlador: AbortController
  oyentes: Set<() => void>
  alResultado: Set<AlResultado>
}

const ejecuciones = new Map<string, Ejecucion>()
const REPOSO: EstadoEjecucion = { evaluando: false, inicio: null, completados: 0, total: 0 }

function obtener(id: string): Ejecucion {
  let e = ejecuciones.get(id)
  if (!e) {
    e = { estado: REPOSO, controlador: new AbortController(), oyentes: new Set(), alResultado: new Set() }
    ejecuciones.set(id, e)
  }
  return e
}

function actualizar(e: Ejecucion, cambios: Partial<EstadoEjecucion>) {
  e.estado = { ...e.estado, ...cambios }
  e.oyentes.forEach((f) => f())
}

export function estadoEjecucion(id: string): EstadoEjecucion {
  return ejecuciones.get(id)?.estado ?? REPOSO
}

export function suscribir(id: string, oyente: () => void, alResultado: AlResultado): () => void {
  const e = obtener(id)
  e.oyentes.add(oyente)
  e.alResultado.add(alResultado)
  return () => {
    e.oyentes.delete(oyente)
    e.alResultado.delete(alResultado)
  }
}

export async function iniciar(id: string, proponenteIds: string[]): Promise<void> {
  const e = obtener(id)
  if (e.estado.evaluando || proponenteIds.length === 0) return
  e.controlador = new AbortController()
  const { signal } = e.controlador
  actualizar(e, { evaluando: true, inicio: Date.now(), completados: 0, total: proponenteIds.length })

  const cola = [...proponenteIds]
  async function trabajador() {
    while (cola.length && !signal.aborted) {
      const pid = cola.shift()!
      try {
        const resultados = await evaluarProponente(id, pid, signal)
        e.alResultado.forEach((f) => f(pid, resultados, null))
      } catch (err) {
        if (signal.aborted) return
        e.alResultado.forEach((f) => f(pid, null, err instanceof Error ? err.message : MENSAJE_SISTEMA))
      }
      actualizar(e, { completados: e.estado.completados + 1 })
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCIA }, trabajador))
  actualizar(e, { evaluando: false })
}

export function detener(id: string) {
  const e = ejecuciones.get(id)
  if (!e) return
  e.controlador.abort()
  actualizar(e, { evaluando: false })
}

export function hayEjecucionesActivas(): boolean {
  return [...ejecuciones.values()].some((e) => e.estado.evaluando)
}
