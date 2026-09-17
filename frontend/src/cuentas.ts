/** API de cuentas: sesión, 2FA, invitaciones, equipo y entidades. */
import { enviarJson, fijarCsrf, pedirJson } from './http'

export type Rol = 'superadmin' | 'admin_entidad' | 'jefe_area' | 'evaluador' | 'consulta'
export type TipoArea = 'juridica' | 'tecnica' | 'financiera'

export interface Area {
  id: string
  tipo: TipoArea
  nombre: string
}

export interface Usuario {
  id: string
  email: string
  nombre_completo: string
  rol: Rol
  rol_nombre: string
  entidad: { id: string; nombre: string } | null
  areas: Area[]
}

export interface Miembro extends Usuario {
  activo: boolean
  ultimo_ingreso: string | null
}

export interface Invitacion {
  id: string
  email: string
  rol: Rol
  rol_nombre: string
  areas: TipoArea[]
  creada_en: string
  expira_en: string
  vigente: boolean
}

export interface Entidad {
  id: string
  nombre: string
  nit: string
  activa: boolean
  usuarios: number
  creada_en: string
}

export interface EventoAuditoria {
  fecha: string
  usuario: string | null
  accion: string
  objeto_tipo: string
  objeto_id: string
  detalles: Record<string, unknown>
  ip: string | null
}

export type EstadoLogin = 'ok' | 'verificar_2fa' | 'configurar_2fa'

interface LoginOut {
  estado: EstadoLogin
  csrf: string
  usuario: Usuario | null
}

export const ROLES: { id: Exclude<Rol, 'superadmin'>; nombre: string; descripcion: string }[] = [
  { id: 'admin_entidad', nombre: 'Administrador de entidad', descripcion: 'Gestiona usuarios, áreas y criterios de la entidad.' },
  { id: 'jefe_area', nombre: 'Jefe de área', descripcion: 'Crea procesos y asigna evaluaciones a su equipo.' },
  { id: 'evaluador', nombre: 'Evaluador', descripcion: 'Evalúa y revisa los procesos que le asignan.' },
  { id: 'consulta', nombre: 'Consulta', descripcion: 'Solo puede ver procesos e informes.' },
]

export const AREAS: { id: TipoArea; nombre: string }[] = [
  { id: 'juridica', nombre: 'Jurídica' },
  { id: 'tecnica', nombre: 'Técnica' },
  { id: 'financiera', nombre: 'Financiera' },
]

async function conCsrf(promesa: Promise<LoginOut>): Promise<LoginOut> {
  const r = await promesa
  fijarCsrf(r.csrf)
  return r
}

export const obtenerYo = () => pedirJson<Usuario>('/api/auth/yo')
export const iniciarSesion = (email: string, password: string) =>
  conCsrf(enviarJson<LoginOut>('/api/auth/login', 'POST', { email, password }))
export const configurar2fa = () => enviarJson<{ otpauth_uri: string; secreto: string }>('/api/auth/2fa/configurar', 'POST')
export const verificar2fa = (codigo: string) => conCsrf(enviarJson<LoginOut>('/api/auth/2fa/verificar', 'POST', { codigo }))
export const cerrarSesion = () => enviarJson<{ ok: boolean }>('/api/auth/logout', 'POST')
export const cambiarClave = (actual: string, nueva: string) =>
  enviarJson<{ ok: boolean }>('/api/auth/cambiar-clave', 'POST', { actual, nueva })
export const solicitarRecuperacion = (email: string) => enviarJson<{ ok: boolean }>('/api/auth/recuperar', 'POST', { email })
export const restablecerClave = (uid: string, token: string, password: string) =>
  enviarJson<{ ok: boolean }>('/api/auth/restablecer', 'POST', { uid, token, password })
export const verInvitacion = (token: string) =>
  pedirJson<{ email: string; entidad: string; rol_nombre: string }>(`/api/auth/invitaciones/${encodeURIComponent(token)}`)
export const aceptarInvitacion = (token: string, nombre_completo: string, password: string) =>
  conCsrf(enviarJson<LoginOut>(`/api/auth/invitaciones/${encodeURIComponent(token)}/aceptar`, 'POST', { nombre_completo, password }))

const q = (entidadId?: string | null) => (entidadId ? `?entidad_id=${entidadId}` : '')
export const listarUsuarios = (entidadId?: string | null) => pedirJson<Miembro[]>(`/api/equipo/usuarios${q(entidadId)}`)
export const actualizarUsuario = (id: string, cambios: { rol?: Rol; areas?: TipoArea[]; activo?: boolean }) =>
  enviarJson<Miembro>(`/api/equipo/usuarios/${id}`, 'PATCH', cambios)
export const listarInvitaciones = (entidadId?: string | null) => pedirJson<Invitacion[]>(`/api/equipo/invitaciones${q(entidadId)}`)
export const invitar = (datos: { email: string; rol: Rol; areas: TipoArea[] }, entidadId?: string | null) =>
  enviarJson<Invitacion>(`/api/equipo/invitaciones${q(entidadId)}`, 'POST', datos)
export const revocarInvitacion = (id: string) => enviarJson<void>(`/api/equipo/invitaciones/${id}`, 'DELETE')
export const listarAuditoria = (entidadId?: string | null) => pedirJson<EventoAuditoria[]>(`/api/equipo/auditoria${q(entidadId)}`)

export const listarEntidades = () => pedirJson<Entidad[]>('/api/plataforma/entidades')
export const crearEntidad = (datos: { nombre: string; nit: string; email_admin: string }) =>
  enviarJson<Entidad>('/api/plataforma/entidades', 'POST', datos)
export const cambiarEstadoEntidad = (id: string, activa: boolean) =>
  enviarJson<Entidad>(`/api/plataforma/entidades/${id}`, 'PATCH', { activa })
