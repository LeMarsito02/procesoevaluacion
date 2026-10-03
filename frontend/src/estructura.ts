/** Estructura de evaluación de la entidad: dependencias por área. */
import { enviarJson, pedirJson } from './http'
import type { Persona } from './evaluaciones'

export interface Dependencia {
  id: string
  tipo: string
  tipo_nombre: string
  nombre: string
  palabras_clave: string
  activa: boolean
  orden: number
  jefes: Persona[]
  miembros: Persona[]
}

export interface DependenciaIn {
  tipo: string
  nombre: string
  palabras_clave: string
  jefes: string[]
  miembros: string[]
  activa: boolean
  orden: number
}

const conEntidad = (ruta: string, entidadId?: string | null) => (entidadId ? `${ruta}${ruta.includes('?') ? '&' : '?'}entidad_id=${entidadId}` : ruta)

export const listarDependencias = (entidadId?: string | null) => pedirJson<Dependencia[]>(conEntidad('/api/estructura/dependencias', entidadId))
export const crearDependencia = (d: DependenciaIn, entidadId?: string | null) =>
  enviarJson<Dependencia>(conEntidad('/api/estructura/dependencias', entidadId), 'POST', d)
export const editarDependencia = (id: string, d: DependenciaIn, entidadId?: string | null) =>
  enviarJson<Dependencia>(conEntidad(`/api/estructura/dependencias/${id}`, entidadId), 'PUT', d)
export const sugerirDependencia = (tipo: string, objeto: string, entidadId?: string | null) =>
  pedirJson<{ dependencia: { id: string; nombre: string } | null }>(
    conEntidad(`/api/estructura/sugerir?tipo=${tipo}&objeto=${encodeURIComponent(objeto)}`, entidadId),
  )
