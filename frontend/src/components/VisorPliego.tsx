import { useEffect } from 'react'
import Icono from './Icono'

interface Props {
  /** De dónde se sirve el PDF. */
  url: string
  nombre: string
  /** Página en la que se abre (desde 1). */
  pagina?: number | null
  /** Qué se vino a mirar, para no perder el hilo. */
  buscando?: string
  onCerrar: () => void
}

/** El pliego dentro de la plataforma, abierto en la página donde está el dato.
 *
 * Existe para que leer el pliego no sea trabajo manual: cuando el programa no
 * pudo leer algo —el plazo, el porcentaje de la garantía, un lote—, la persona
 * lo ve aquí en su página y lo corrige al lado, sin bajarse el PDF ni buscar en
 * noventa páginas. El visor es el del navegador, así que trae su propia búsqueda
 * y su propio zoom. */
export default function VisorPliego({ url, nombre, pagina, buscando, onCerrar }: Props) {
  useEffect(() => {
    function tecla(e: KeyboardEvent) {
      if (e.key === 'Escape') onCerrar()
    }
    window.addEventListener('keydown', tecla)
    return () => window.removeEventListener('keydown', tecla)
  }, [onCerrar])

  const destino = pagina ? `${url}#page=${pagina}` : url
  return (
    <div className="visor" role="dialog" aria-modal="true" aria-label={`Pliego ${nombre}`}>
      <div className="visor-doc">
        <div className="visor-doc-head">
          <Icono nombre="documento" tam={16} />
          <span>
            {nombre}
            {pagina ? ` · página ${pagina}` : ''}
          </span>
          <a className="btn btn-ghost btn-sm" href={url} target="_blank" rel="noreferrer">
            Abrir aparte
          </a>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onCerrar}>
            <Icono nombre="x" tam={15} /> Cerrar
          </button>
        </div>
        <iframe src={destino} title={`Pliego ${nombre}`} />
      </div>
      <div className="visor-lado">
        <h3 style={{ margin: 0 }}>{buscando ? 'Qué comprobar' : 'El pliego'}</h3>
        {buscando ? (
          <p className="small">{buscando}</p>
        ) : (
          <p className="small muted">
            Se abre en la página donde el programa encontró el dato. Si algo quedó mal leído, corríjalo en el formulario
            y quedará registrado que lo confirmó una persona.
          </p>
        )}
        <p className="small muted">
          El visor es el del navegador: con Ctrl+F busca dentro del pliego y con Ctrl+rueda acerca.
        </p>
      </div>
    </div>
  )
}
