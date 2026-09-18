/** API de cuentas: sesión, 2FA, credenciales, equipo y entidades. */
import { enviarJson, fijarCsrf, pedirJson } from './http'

export type Rol = 'superadmin' | 'admin_entidad' | 'jefe_area' | 'evaluador' | 'consulta' | 'soporte'
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
  acceso_soporte_hasta: string | null
}

export interface Miembro extends Usuario {
  activo: boolean
  ultimo_ingreso: string | null
  debe_cambiar_clave: boolean
}

/** Solo llega una vez, al crear la cuenta o al reiniciar la contraseña. */
export interface Credenciales {
  usuario: Miembro
  password_temporal: string
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

export type EstadoLogin = 'ok' | 'cambiar_clave' | 'verificar_2fa' | 'configurar_2fa'

interface LoginOut {
  estado: EstadoLogin
  csrf: string
  usuario: Usuario | null
}

export const ROLES: { id: Exclude<Rol, 'superadmin' | 'soporte'>; nombre: string; descripcion: string }[] = [
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
export const fijarClaveInicial = (nueva: string) => conCsrf(enviarJson<LoginOut>('/api/auth/clave-inicial', 'POST', { nueva }))

const q = (entidadId?: string | null) => (entidadId ? `?entidad_id=${entidadId}` : '')
export const listarUsuarios = (entidadId?: string | null) => pedirJson<Miembro[]>(`/api/equipo/usuarios${q(entidadId)}`)
export const actualizarUsuario = (id: string, cambios: { rol?: Rol; areas?: TipoArea[]; activo?: boolean }) =>
  enviarJson<Miembro>(`/api/equipo/usuarios/${id}`, 'PATCH', cambios)
export const crearUsuario = (datos: { nombre_completo: string; email: string; rol: Rol; areas: TipoArea[] }, entidadId?: string | null) =>
  enviarJson<Credenciales>(`/api/equipo/usuarios${q(entidadId)}`, 'POST', datos)
export const reiniciarClave = (id: string) => enviarJson<Credenciales>(`/api/equipo/usuarios/${id}/clave`, 'POST')
export const listarAuditoria = (entidadId?: string | null) => pedirJson<EventoAuditoria[]>(`/api/equipo/auditoria${q(entidadId)}`)

export const listarEntidades = () => pedirJson<Entidad[]>('/api/plataforma/entidades')
export const crearEntidad = (datos: {
  nombre: string
  nit: string
  email_admin: string
  nombre_admin: string
  sigla: string
  base: 'sistema' | 'copiar'
  copiar_de: string | null
}) => enviarJson<{ entidad: Entidad; credenciales: Credenciales }>('/api/plataforma/entidades', 'POST', datos)
export const cambiarEstadoEntidad = (id: string, activa: boolean) =>
  enviarJson<Entidad>(`/api/plataforma/entidades/${id}`, 'PATCH', { activa })

// --- Soporte de LeMarTek ---
export interface PersonaSoporte {
  id: string
  nombre_completo: string
  email: string
}

export interface AccesoSoporte {
  id: string
  soporte: PersonaSoporte
  otorgado_por: string | null
  motivo: string
  creado_en: string
  expira_en: string
  revocado_en: string | null
  vigente: boolean
}

export const accesosDisponibles = () =>
  pedirJson<{ entidad: { id: string; nombre: string }; expira_en: string; motivo: string }[]>('/api/auth/soporte/accesos')
export const entrarComoSoporte = (entidadId: string) => enviarJson<Usuario>('/api/auth/soporte/entrar', 'POST', { entidad_id: entidadId })
export const salirDeEntidad = () => enviarJson<Usuario>('/api/auth/soporte/salir', 'POST')
export const soporteDeLaEntidad = (entidadId?: string | null) =>
  pedirJson<{ accesos: AccesoSoporte[]; personal: PersonaSoporte[] }>(`/api/equipo/soporte${q(entidadId)}`)
export const otorgarSoporte = (datos: { soporte_id: string; horas: number; motivo: string }, entidadId?: string | null) =>
  enviarJson<AccesoSoporte>(`/api/equipo/soporte${q(entidadId)}`, 'POST', datos)
export const revocarSoporte = (id: string) => enviarJson<void>(`/api/equipo/soporte/${id}`, 'DELETE')
export const personalDeSoporte = () => pedirJson<PersonaSoporte[]>('/api/plataforma/soporte')
export const crearCuentaSoporte = (email: string, nombre_completo: string) =>
  enviarJson<{ soporte: PersonaSoporte; password_temporal: string }>('/api/plataforma/soporte', 'POST', { email, nombre_completo })

// --- Salario mínimo por año (plataforma) ---
export interface SalarioMinimo {
  ano: number
  valor: number
  norma: string
  actualizado_por: string | null
  actualizado_en: string
}

export const listarSalariosMinimos = () => pedirJson<SalarioMinimo[]>('/api/plataforma/salarios-minimos')
export const guardarSalarioMinimo = (ano: number, valor: number, norma: string) =>
  enviarJson<SalarioMinimo>(`/api/plataforma/salarios-minimos/${ano}`, 'PUT', { valor, norma })
