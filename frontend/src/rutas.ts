/** Enrutador mínimo sobre la History API (la app tiene pocas páginas). */
import { useEffect, useState } from 'react'

// Páginas recorridas dentro de la app: con 0 se entró por un enlace directo y
// «volver» no debe sacar a la persona de la aplicación.
let recorridas = 0
window.addEventListener('popstate', () => {
  recorridas = Math.max(0, recorridas - 1)
})

/** Vuelve a la página anterior de la app o, si no la hay, al inicio. */
export function volver() {
  if (recorridas > 0) window.history.back()
  else navegar('/')
}

export function navegar(ruta: string, reemplazar = false) {
  if (ruta === window.location.pathname) return
  if (reemplazar) window.history.replaceState(null, '', ruta)
  else {
    window.history.pushState(null, '', ruta)
    recorridas += 1
  }
  window.dispatchEvent(new Event('cambio-ruta'))
  window.scrollTo(0, 0)
}

export function useRuta(): string {
  const [ruta, setRuta] = useState(window.location.pathname)
  useEffect(() => {
    const actualizar = () => setRuta(window.location.pathname)
    window.addEventListener('popstate', actualizar)
    window.addEventListener('cambio-ruta', actualizar)
    return () => {
      window.removeEventListener('popstate', actualizar)
      window.removeEventListener('cambio-ruta', actualizar)
    }
  }, [])
  return ruta
}

/** Devuelve los segmentos variables si `ruta` encaja con `patron` ("/restablecer/:uid/:token"). */
export function encajar(patron: string, ruta: string): Record<string, string> | null {
  const p = patron.split('/').filter(Boolean)
  const r = ruta.split('/').filter(Boolean)
  if (p.length !== r.length) return null
  const params: Record<string, string> = {}
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(':')) params[p[i].slice(1)] = decodeURIComponent(r[i])
    else if (p[i] !== r[i]) return null
  }
  return params
}
