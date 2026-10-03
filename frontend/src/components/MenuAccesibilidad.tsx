import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { CLAVE, INICIALES, TAMANOS, ZOOMS, aplicarAccesibilidad, leer, type Preferencias } from '../accesibilidad'
import Icono from './Icono'

/** Menú de accesibilidad, como la barra de accesibilidad de los sitios GOV.CO
 * (MinTIC, Res. 1519 de 2020): cada persona ajusta la interfaz a su necesidad
 * y la preferencia queda guardada en su navegador.
 *
 * - Tamaño del texto (solo las letras) y ampliar la página (todo): baja visión.
 * - Alto contraste: baja visión, daltonismo, pantallas con reflejo.
 * - Resaltar enlaces y botones: baja visión, discapacidad cognitiva.
 * - Espaciado y letra fácil de leer: dislexia, discapacidad cognitiva.
 * - Guía de lectura: dificultades de atención o de seguimiento visual.
 * - Pausar animaciones: sensibilidad al movimiento, epilepsia fotosensible.
 * - Centro de Relevo: personas sordas (servicio del Estado colombiano). */

export default function MenuAccesibilidad() {
  const [abierto, setAbierto] = useState(false)
  const [p, setP] = useState<Preferencias>(leer)
  const [guiaY, setGuiaY] = useState<number | null>(null)
  const panel = useRef<HTMLDivElement>(null)
  const boton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    aplicarAccesibilidad(p)
    try {
      localStorage.setItem(CLAVE, JSON.stringify(p))
    } catch {
      // Sin almacenamiento (navegación privada): se aplica igual en esta visita.
    }
  }, [p])

  // La guía de lectura sigue al puntero.
  useEffect(() => {
    if (!p.guia) return
    const mover = (e: MouseEvent) => setGuiaY(e.clientY)
    window.addEventListener('mousemove', mover)
    return () => window.removeEventListener('mousemove', mover)
  }, [p.guia])

  // Escape cierra y devuelve el foco al botón; al abrir, el foco entra al panel.
  useEffect(() => {
    if (!abierto) return
    panel.current?.querySelector<HTMLElement>('button')?.focus()
    const tecla = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setAbierto(false)
        boton.current?.focus()
      }
    }
    const fuera = (e: MouseEvent) => {
      if (!panel.current?.contains(e.target as Node) && !boton.current?.contains(e.target as Node)) setAbierto(false)
    }
    window.addEventListener('keydown', tecla)
    window.addEventListener('mousedown', fuera)
    return () => {
      window.removeEventListener('keydown', tecla)
      window.removeEventListener('mousedown', fuera)
    }
  }, [abierto])

  const cambiar = (c: Partial<Preferencias>) => setP((prev) => ({ ...prev, ...c }))
  const indice = TAMANOS.indexOf(p.texto)
  const indiceZoom = ZOOMS.indexOf(p.zoom)
  const opciones: { clave: keyof Preferencias; nombre: string; ayuda: string }[] = [
    { clave: 'contraste', nombre: 'Alto contraste', ayuda: 'Negro sobre blanco, bordes marcados' },
    { clave: 'enlaces', nombre: 'Resaltar enlaces y botones', ayuda: 'Subraya enlaces y enmarca botones' },
    { clave: 'espaciado', nombre: 'Más espacio entre letras y líneas', ayuda: 'Ayuda con la dislexia' },
    { clave: 'letraLegible', nombre: 'Letra fácil de leer', ayuda: 'Cambia a una letra más clara' },
    { clave: 'guia', nombre: 'Guía de lectura', ayuda: 'Una franja que sigue al puntero' },
    { clave: 'sinAnimaciones', nombre: 'Pausar animaciones', ayuda: 'Quita movimientos y transiciones' },
  ]
  const cambios = JSON.stringify(p) !== JSON.stringify(INICIALES)

  // Fuera de #root: así el menú no se amplía con el tamaño del texto (se
  // saldría de la pantalla) y siempre queda al alcance.
  return createPortal(
    <>
      {p.guia && guiaY !== null && <div className="a11y-guia" style={{ top: guiaY - 22 }} aria-hidden="true" />}
      <button
        ref={boton}
        type="button"
        className="a11y-boton"
        aria-label="Opciones de accesibilidad"
        aria-expanded={abierto}
        aria-controls="menu-accesibilidad"
        title="Accesibilidad"
        data-activo={cambios}
        onClick={() => setAbierto((a) => !a)}
      >
        <Icono nombre="accesibilidad" tam={24} />
      </button>
      {abierto && (
        <div ref={panel} id="menu-accesibilidad" className="a11y-panel" role="dialog" aria-label="Opciones de accesibilidad">
          <div className="a11y-cabecera">
            <strong>Accesibilidad</strong>
            <button type="button" className="btn btn-ghost btn-icon" aria-label="Cerrar opciones de accesibilidad" onClick={() => setAbierto(false)}>
              <Icono nombre="x" tam={18} />
            </button>
          </div>

          <div className="a11y-grupo" role="group" aria-label="Tamaño del texto">
            <span>Tamaño del texto</span>
            <div className="a11y-tamano">
              <button type="button" aria-label="Reducir el texto" disabled={indice <= 0} onClick={() => cambiar({ texto: TAMANOS[indice - 1] })}>
                A−
              </button>
              <output aria-live="polite">{p.texto} %</output>
              <button
                type="button"
                aria-label="Aumentar el texto"
                disabled={indice >= TAMANOS.length - 1}
                onClick={() => cambiar({ texto: TAMANOS[indice + 1] })}
              >
                A+
              </button>
            </div>
          </div>

          <div className="a11y-grupo" role="group" aria-label="Ampliar la página">
            <span>Ampliar la página</span>
            <div className="a11y-tamano">
              <button type="button" aria-label="Reducir la página" disabled={indiceZoom <= 0} onClick={() => cambiar({ zoom: ZOOMS[indiceZoom - 1] })}>
                −
              </button>
              <output aria-live="polite">{p.zoom} %</output>
              <button
                type="button"
                aria-label="Ampliar la página"
                disabled={indiceZoom >= ZOOMS.length - 1}
                onClick={() => cambiar({ zoom: ZOOMS[indiceZoom + 1] })}
              >
                +
              </button>
            </div>
          </div>

          {opciones.map((o) => (
            <button key={o.clave} type="button" className="a11y-opcion" aria-pressed={Boolean(p[o.clave])} onClick={() => cambiar({ [o.clave]: !p[o.clave] })}>
              <span className="a11y-interruptor" aria-hidden="true" />
              <span>
                <strong>{o.nombre}</strong>
                <span className="small">{o.ayuda}</span>
              </span>
            </button>
          ))}

          <a className="a11y-relevo" href="https://centroderelevo.gov.co" target="_blank" rel="noopener noreferrer">
            Centro de Relevo: comunicación para personas sordas
          </a>
          <button type="button" className="btn btn-secondary btn-sm" disabled={!cambios} onClick={() => setP(INICIALES)}>
            <Icono nombre="deshacer" tam={15} /> Restablecer
          </button>
        </div>
      )}
    </>,
    document.body,
  )
}
