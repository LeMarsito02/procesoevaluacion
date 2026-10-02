/** Preferencias de accesibilidad de cada persona (ver components/MenuAccesibilidad.tsx). */

export interface Preferencias {
  texto: number // porcentaje
  contraste: boolean
  enlaces: boolean
  espaciado: boolean
  letraLegible: boolean
  guia: boolean
  sinAnimaciones: boolean
}

export const INICIALES: Preferencias = {
  texto: 100,
  contraste: false,
  enlaces: false,
  espaciado: false,
  letraLegible: false,
  guia: false,
  sinAnimaciones: false,
}
export const TAMANOS = [100, 115, 130, 150]
export const CLAVE = 'mievaluador.accesibilidad'

export function leer(): Preferencias {
  try {
    return { ...INICIALES, ...JSON.parse(localStorage.getItem(CLAVE) ?? '{}') }
  } catch {
    return INICIALES
  }
}

/** Aplica las preferencias al documento. Se llama también antes de dibujar la
 * aplicación, para que no se vea un parpadeo con los valores por defecto. */
export function aplicarAccesibilidad(p: Preferencias = leer()) {
  const html = document.documentElement
  html.style.setProperty('--a11y-zoom', String(p.texto / 100))
  html.classList.toggle('a11y-texto', p.texto !== 100)
  html.classList.toggle('a11y-contraste', p.contraste)
  html.classList.toggle('a11y-enlaces', p.enlaces)
  html.classList.toggle('a11y-espaciado', p.espaciado)
  html.classList.toggle('a11y-letra', p.letraLegible)
  html.classList.toggle('a11y-sin-animaciones', p.sinAnimaciones)
}
