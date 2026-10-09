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
  /** Compromiso de uso (expediente LEG-004, 6.4): falta aceptarlo antes de decidir. */
  compromiso_pendiente?: boolean
  compromiso_version?: string
  compromiso_texto?: string
  version_sistema?: string
}

export interface Miembro extends Usuario {
  activo: boolean
  ultimo_ingreso: string | null
  debe_cambiar_clave: boolean
  compromiso_aceptado_en?: string | null
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
  /** Identificador del directorio de Microsoft (Entra ID) de la entidad; vacío = sin acceso con Microsoft. */
  microsoft_directorio: string
  /** Sus usuarios solo entran con Microsoft, no con contraseña. */
  exigir_microsoft: boolean
  /** Quien entra por primera vez con una cuenta del directorio recibe un usuario de consulta, sin acceso a evaluaciones. */
  microsoft_crear_usuarios: boolean
  /** Tiene la licencia del módulo de prestación de servicios (OPS). */
  modulo_ops: boolean
  /** Cuándo se comprobó que su administrador de Microsoft 365 aprobó la lectura de su OneDrive. */
  onedrive_autorizado_en: string | null
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
  { id: 'consulta', nombre: 'Consulta', descripcion: 'Entra al sistema pero no ve evaluaciones: son reservadas al comité designado.' },
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

export const opcionesDeAcceso = () => pedirJson<{ microsoft: boolean }>('/api/auth/opciones')
/** Lleva a la página de Microsoft; al volver, la pantalla de acceso lee `?microsoft=`. */
export const URL_MICROSOFT = '/api/auth/microsoft/iniciar'
export const obtenerYo = () => pedirJson<Usuario>('/api/auth/yo')
export const iniciarSesion = (email: string, password: string, recaptcha: string | null) =>
  conCsrf(enviarJson<LoginOut>('/api/auth/login', 'POST', { email, password, recaptcha }))
export const configurar2fa = () => enviarJson<{ otpauth_uri: string; secreto: string }>('/api/auth/2fa/configurar', 'POST')
export const verificar2fa = (codigo: string) => conCsrf(enviarJson<LoginOut>('/api/auth/2fa/verificar', 'POST', { codigo }))
export const cerrarSesion = () => enviarJson<{ ok: boolean }>('/api/auth/logout', 'POST')
export const cambiarClave = (actual: string, nueva: string) =>
  enviarJson<{ ok: boolean }>('/api/auth/cambiar-clave', 'POST', { actual, nueva })
export const solicitarRecuperacion = (email: string, recaptcha: string | null) =>
  enviarJson<{ ok: boolean }>('/api/auth/recuperar', 'POST', { email, recaptcha })
export const restablecerClave = (uid: string, token: string, password: string) =>
  enviarJson<{ ok: boolean }>('/api/auth/restablecer', 'POST', { uid, token, password })
export const aceptarCompromiso = (version: string) =>
  enviarJson<Usuario>('/api/auth/compromiso', 'POST', { version, acepto: true })
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
export const cambiarModuloOps = (id: string, modulo_ops: boolean) =>
  enviarJson<Entidad>(`/api/plataforma/entidades/${id}`, 'PATCH', { modulo_ops })
export const configurarMicrosoft = (
  id: string,
  datos: { microsoft_directorio: string; exigir_microsoft: boolean; microsoft_crear_usuarios: boolean },
) => enviarJson<Entidad>(`/api/plataforma/entidades/${id}`, 'PATCH', datos)

/** Enlace que se le envía al administrador de Microsoft 365 de la entidad para
 * que apruebe, una vez, que MiEvaluador lea (solo lectura) las carpetas de ofertas. */
export const enlaceAutorizacionOneDrive = (id: string) =>
  pedirJson<{ url: string; redirect_uri: string; autorizado_en: string | null }>(`/api/plataforma/entidades/${id}/onedrive`)
export const probarOneDrive = (id: string) => enviarJson<Entidad>(`/api/plataforma/entidades/${id}/onedrive/probar`, 'POST')

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
