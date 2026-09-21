/** reCAPTCHA Enterprise en los formularios públicos (entrar, recuperar clave).
 *
 * El script de Google se carga solo en la pantalla de acceso, no en toda la
 * aplicación. Si no carga (sin conexión a Google, bloqueador), el formulario se
 * envía sin token y el servidor decide: en desarrollo no se verifica. */

export const CLAVE_SITIO: string = import.meta.env.VITE_RECAPTCHA_SITE_KEY ?? '6Lecm8ctAAAAAGBlk3npIJqs-cnWZwIdGg3cO3Pm'

interface GrecaptchaEnterprise {
  ready: (f: () => void) => void
  execute: (clave: string, opciones: { action: string }) => Promise<string>
}

declare global {
  interface Window {
    grecaptcha?: { enterprise?: GrecaptchaEnterprise }
  }
}

let cargando: Promise<GrecaptchaEnterprise | null> | null = null

/** Carga el script de reCAPTCHA una sola vez. */
export function cargarRecaptcha(): Promise<GrecaptchaEnterprise | null> {
  if (!CLAVE_SITIO) return Promise.resolve(null)
  cargando ??= new Promise((resolver) => {
    const listo = () => {
      const g = window.grecaptcha?.enterprise
      if (g) g.ready(() => resolver(g))
      else resolver(null)
    }
    if (window.grecaptcha?.enterprise) return listo()
    const script = document.createElement('script')
    script.src = `https://www.google.com/recaptcha/enterprise.js?render=${encodeURIComponent(CLAVE_SITIO)}`
    script.async = true
    script.onload = listo
    script.onerror = () => {
      cargando = null // se reintenta en el próximo envío
      resolver(null)
    }
    document.head.appendChild(script)
  })
  return cargando
}

/** Token para la acción (vence a los dos minutos: se pide justo antes de enviar). */
export async function tokenRecaptcha(accion: 'LOGIN' | 'RECUPERAR_CLAVE'): Promise<string | null> {
  const g = await Promise.race([cargarRecaptcha(), new Promise<null>((r) => setTimeout(() => r(null), 8000))])
  if (!g) return null
  try {
    return await g.execute(CLAVE_SITIO, { action: accion })
  } catch {
    return null
  }
}
