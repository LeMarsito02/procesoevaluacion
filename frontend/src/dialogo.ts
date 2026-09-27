import { useEffect, type RefObject } from 'react'

const FOCALIZABLES =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** Comportamiento de ventana modal para el panel de un proponente y el visor
 * de documentos.
 *
 * Sin esto, el teclado sigue recorriendo la pantalla de atrás: quien revisa
 * con tabulador —o con lector de pantalla— sale del panel sin darse cuenta y
 * termina pulsando botones de la tabla que quedó debajo. Al abrirse, el foco
 * entra en el diálogo; mientras está abierto, el tabulador da la vuelta dentro;
 * al cerrarse, el foco vuelve donde estaba. */
export function useDialogo(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const anterior = document.activeElement as HTMLElement | null
    const nodo = ref.current
    if (!nodo) return
    if (!nodo.contains(document.activeElement)) {
      const primero = nodo.querySelector<HTMLElement>(FOCALIZABLES)
      ;(primero ?? nodo).focus({ preventScroll: true })
    }

    function alTabular(e: KeyboardEvent) {
      if (e.key !== 'Tab' || !nodo) return
      const focalizables = [...nodo.querySelectorAll<HTMLElement>(FOCALIZABLES)].filter(
        (el) => el.offsetParent !== null || el === document.activeElement,
      )
      if (focalizables.length === 0) return
      const primero = focalizables[0]
      const ultimo = focalizables[focalizables.length - 1]
      const actual = document.activeElement
      if (!e.shiftKey && (actual === ultimo || !nodo.contains(actual))) {
        e.preventDefault()
        primero.focus()
      } else if (e.shiftKey && (actual === primero || !nodo.contains(actual))) {
        e.preventDefault()
        ultimo.focus()
      }
    }

    document.addEventListener('keydown', alTabular)
    return () => {
      document.removeEventListener('keydown', alTabular)
      anterior?.focus?.({ preventScroll: true })
    }
  }, [ref])
}
