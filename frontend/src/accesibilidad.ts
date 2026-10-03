/** Preferencias de accesibilidad de cada persona (ver components/MenuAccesibilidad.tsx). */

export interface Preferencias {
  texto: number // porcentaje: solo el tamaño de las letras
  zoom: number // porcentaje: toda la página
  contraste: boolean
  enlaces: boolean
  espaciado: boolean
  letraLegible: boolean
  guia: boolean
  sinAnimaciones: boolean
}

export const INICIALES: Preferencias = {
  texto: 100,
  zoom: 100,
  contraste: false,
  enlaces: false,
  espaciado: false,
  letraLegible: false,
  guia: false,
  sinAnimaciones: false,
}
// WCAG 1.4.4 pide poder llevar el texto al 200 % sin perder contenido.
export const TAMANOS = [100, 125, 150, 175, 200]
export const ZOOMS = [100, 125, 150, 175, 200]
export const CLAVE = 'mievaluador.accesibilidad'

export function leer(): Preferencias {
  try {
    const guardadas = { ...INICIALES, ...JSON.parse(localStorage.getItem(CLAVE) ?? '{}') }
    // Valores fuera de la escala (de una versión anterior) vuelven al más cercano permitido.
    if (!TAMANOS.includes(guardadas.texto)) guardadas.texto = 100
    if (!ZOOMS.includes(guardadas.zoom)) guardadas.zoom = 100
    return guardadas
  } catch {
    return INICIALES
  }
}

/** Aplica las preferencias al documento. Se llama también antes de dibujar la
 * aplicación, para que no se vea un parpadeo con los valores por defecto. */
export function aplicarAccesibilidad(p: Preferencias = leer()) {
  const html = document.documentElement
  // El texto escala las letras (todos los tamaños dependen de --escala-texto);
  // el zoom amplía toda la página.
  html.style.setProperty('--escala-texto', String(p.texto / 100))
  html.style.setProperty('--a11y-zoom', String(p.zoom / 100))
  html.classList.toggle('a11y-zoom', p.zoom !== 100)
  html.classList.toggle('a11y-contraste', p.contraste)
  html.classList.toggle('a11y-enlaces', p.enlaces)
  html.classList.toggle('a11y-espaciado', p.espaciado)
  html.classList.toggle('a11y-letra', p.letraLegible)
  html.classList.toggle('a11y-sin-animaciones', p.sinAnimaciones)
}
