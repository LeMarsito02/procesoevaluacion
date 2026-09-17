/** Cliente HTTP de la API: sesión por cookie, token CSRF, sesión vencida y
 * mensajes de error comprensibles (nunca errores técnicos del navegador). */

const API_URL = import.meta.env.VITE_API_URL ?? ''

let csrf: string | null = null

export const MENSAJE_SIN_CONEXION =
  'No pudimos comunicarnos con MiEvaluador. Revise su conexión a internet e inténtelo de nuevo.'
export const MENSAJE_SISTEMA =
  'El sistema no está disponible en este momento. Inténtelo de nuevo en unos minutos; si continúa, avise a soporte de LeMarTek.'

export class ErrorApi extends Error {
  /** 0 = no hubo respuesta del servidor. */
  status: number
  constructor(status: number, mensaje: string) {
    super(mensaje)
    this.status = status
  }

  /** Falla del sistema o de la conexión (no del usuario ni de sus datos). */
  get esDelSistema(): boolean {
    return this.status === 0 || this.status >= 500 || this.status === 404
  }
}

function mensajePorEstado(status: number): string {
  if (status === 0) return MENSAJE_SIN_CONEXION
  if (status === 401) return 'Su sesión terminó. Inicie sesión de nuevo.'
  if (status === 403) return 'No tiene permiso para esta acción.'
  if (status === 413) return 'El archivo es demasiado grande.'
  if (status === 429) return 'Demasiados intentos. Espere unos minutos e inténtelo de nuevo.'
  if (status === 400 || status === 422) return 'Revise los datos ingresados e inténtelo de nuevo.'
  return MENSAJE_SISTEMA
}

export function fijarCsrf(token: string | null | undefined) {
  if (token) csrf = token
}

async function fetchSeguro(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, { ...init, credentials: 'same-origin' })
  } catch (err) {
    if (init.signal?.aborted) throw err
    throw new ErrorApi(0, MENSAJE_SIN_CONEXION)
  }
}

function esJson(res: Response): boolean {
  return (res.headers.get('Content-Type') ?? '').includes('application/json')
}

async function obtenerCsrf(): Promise<string> {
  const res = await fetchSeguro(`${API_URL}/api/auth/csrf`, {})
  if (!res.ok || !esJson(res)) throw new ErrorApi(res.ok ? 502 : res.status, mensajePorEstado(res.ok ? 502 : res.status))
  const datos = await res.json()
  csrf = datos.csrf as string
  return csrf
}

/** Mensaje para mostrar al usuario a partir de una respuesta con error. */
export async function detalleError(res: Response): Promise<string> {
  // Respuestas que no son de la API (proxy caído, página HTML, servidor reiniciando).
  if (!esJson(res)) return mensajePorEstado(res.status)
  try {
    const data = await res.json()
    if (typeof data?.detail === 'string' && data.detail.trim()) {
      if (/CSRF/i.test(data.detail)) return 'La página estuvo inactiva mucho tiempo. Recárguela e inténtelo de nuevo.'
      return data.detail
    }
  } catch {
    // Cuerpo ilegible: se usa el mensaje genérico.
  }
  return mensajePorEstado(res.status)
}

/** fetch con credenciales y CSRF. Si la sesión vence, avisa a la app con el
 * evento `sesion-vencida` (salvo en las rutas de autenticación). Lanza
 * `ErrorApi` con un mensaje comprensible si no hay conexión. */
export async function pedir(ruta: string, init: RequestInit = {}, reintento = true): Promise<Response> {
  const metodo = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (metodo !== 'GET' && metodo !== 'HEAD') {
    headers.set('X-CSRFToken', csrf ?? (await obtenerCsrf()))
  }
  const res = await fetchSeguro(`${API_URL}${ruta}`, { ...init, headers })

  if (res.status === 403 && reintento && metodo !== 'GET' && esJson(res)) {
    // El token CSRF pudo rotar (inicio de sesión en otra pestaña): se renueva una vez.
    const datos = await res.clone().json().catch(() => null)
    if (typeof datos?.detail === 'string' && /CSRF/i.test(datos.detail)) {
      await obtenerCsrf()
      return pedir(ruta, init, false)
    }
  }
  if (res.status === 401 && !ruta.startsWith('/api/auth/')) {
    window.dispatchEvent(new Event('sesion-vencida'))
  }
  return res
}

export async function pedirJson<T>(ruta: string, init: RequestInit = {}): Promise<T> {
  const res = await pedir(ruta, init)
  if (!res.ok) throw new ErrorApi(res.status, await detalleError(res))
  if (res.status === 204) return undefined as T
  if (!esJson(res)) throw new ErrorApi(502, MENSAJE_SISTEMA)
  return res.json() as Promise<T>
}

export function enviarJson<T>(ruta: string, metodo: string, cuerpo?: unknown): Promise<T> {
  return pedirJson<T>(ruta, {
    method: metodo,
    headers: { 'Content-Type': 'application/json' },
    body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
  })
}

/** Texto para mostrar de cualquier error capturado. */
export function mensajeDe(err: unknown, porDefecto = MENSAJE_SISTEMA): string {
  if (err instanceof ErrorApi) return err.message
  return porDefecto
}
