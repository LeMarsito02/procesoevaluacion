import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'
import { useDialogo } from './dialogo'
import Icono from './components/Icono'

/** Confirmaciones y preguntas de la aplicación.
 *
 * Antes se usaba `window.confirm` y `window.prompt`, que el navegador pinta a
 * su manera: un cuadro gris con "localhost:5173 says" encima del texto. Aparte
 * de feo, no puede explicar nada —ni dar contexto, ni validar lo que se
 * escribe, ni distinguir una acción peligrosa de una corriente— y en algunos
 * navegadores se puede bloquear.
 *
 * Uso:
 *   const { confirmar, pedirTexto } = useDialogos()
 *   if (!(await confirmar({ titulo: '¿Archivar el proceso?' }))) return
 *   const nota = await pedirTexto({ titulo: '¿Qué consultó?', minimo: 15 })
 *   if (nota === null) return   // canceló
 */

interface Confirmacion {
  titulo: string
  mensaje?: ReactNode
  aceptar?: string
  cancelar?: string
  /** Acción destructiva o irreversible: el botón va en rojo. */
  peligro?: boolean
}

interface Pregunta extends Confirmacion {
  etiqueta?: string
  ayuda?: string
  /** Caracteres mínimos; hasta llegar, el botón está deshabilitado y se dice por qué. */
  minimo?: number
  placeholder?: string
  /** Varias líneas (una justificación) en vez de una sola. */
  largo?: boolean
}

interface Contexto {
  confirmar: (c: Confirmacion) => Promise<boolean>
  pedirTexto: (p: Pregunta) => Promise<string | null>
}

const ContextoDialogos = createContext<Contexto | null>(null)

export function useDialogos(): Contexto {
  const ctx = useContext(ContextoDialogos)
  if (!ctx) throw new Error('useDialogos necesita <ProveedorDialogos> arriba en el árbol')
  return ctx
}

type Abierto =
  | { tipo: 'confirmar'; datos: Confirmacion; resolver: (v: boolean) => void }
  | { tipo: 'texto'; datos: Pregunta; resolver: (v: string | null) => void }

export function ProveedorDialogos({ children }: { children: ReactNode }) {
  const [abierto, setAbierto] = useState<Abierto | null>(null)

  const confirmar = useCallback(
    (datos: Confirmacion) => new Promise<boolean>((resolver) => setAbierto({ tipo: 'confirmar', datos, resolver })),
    [],
  )
  const pedirTexto = useCallback(
    (datos: Pregunta) => new Promise<string | null>((resolver) => setAbierto({ tipo: 'texto', datos, resolver })),
    [],
  )

  return (
    <ContextoDialogos.Provider value={{ confirmar, pedirTexto }}>
      {children}
      {abierto && (
        <Dialogo
          key={abierto.datos.titulo}
          abierto={abierto}
          onCerrar={(valor) => {
            if (abierto.tipo === 'confirmar') abierto.resolver(valor === null ? false : true)
            else abierto.resolver(valor)
            setAbierto(null)
          }}
        />
      )}
    </ContextoDialogos.Provider>
  )
}

function Dialogo({ abierto, onCerrar }: { abierto: Abierto; onCerrar: (valor: string | null) => void }) {
  const caja = useRef<HTMLDivElement>(null)
  useDialogo(caja)
  const [texto, setTexto] = useState('')
  const datos = abierto.datos
  const pregunta = abierto.tipo === 'texto' ? (datos as Pregunta) : null
  const minimo = pregunta?.minimo ?? 0
  const faltan = Math.max(0, minimo - texto.trim().length)
  const listo = abierto.tipo !== 'texto' || faltan === 0

  function aceptar() {
    if (!listo) return
    onCerrar(abierto.tipo === 'texto' ? texto.trim() : '')
  }

  return (
    <>
      <div className="overlay" style={{ zIndex: 60 }} onClick={() => onCerrar(null)} />
      <div
        ref={caja}
        className="dialogo"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="dialogo-titulo"
        tabIndex={-1}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onCerrar(null)
          if (e.key === 'Enter' && (abierto.tipo === 'confirmar' || !pregunta?.largo)) aceptar()
        }}
      >
        <div className="dialogo-cabeza">
          <span className="dialogo-icono" data-peligro={!!datos.peligro}>
            <Icono nombre={datos.peligro ? 'alerta' : pregunta ? 'lapiz' : 'info'} tam={20} />
          </span>
          <h2 id="dialogo-titulo">{datos.titulo}</h2>
        </div>

        {datos.mensaje && <div className="dialogo-cuerpo">{datos.mensaje}</div>}

        {pregunta && (
          <div className="field">
            {pregunta.etiqueta && <label htmlFor="dialogo-campo">{pregunta.etiqueta}</label>}
            {pregunta.largo ? (
              <textarea
                id="dialogo-campo"
                className="textarea"
                rows={3}
                autoFocus
                placeholder={pregunta.placeholder}
                value={texto}
                onChange={(e) => setTexto(e.target.value)}
              />
            ) : (
              <input
                id="dialogo-campo"
                className="input"
                autoFocus
                placeholder={pregunta.placeholder}
                value={texto}
                onChange={(e) => setTexto(e.target.value)}
              />
            )}
            {pregunta.ayuda && <span className="hint">{pregunta.ayuda}</span>}
            {faltan > 0 && (
              <span className="hint" style={{ color: 'var(--warn)' }}>
                Faltan {faltan} caracteres.
              </span>
            )}
          </div>
        )}

        <div className="dialogo-pie">
          <button type="button" className="btn btn-ghost" onClick={() => onCerrar(null)}>
            {datos.cancelar ?? 'Cancelar'}
          </button>
          <button
            type="button"
            className={datos.peligro ? 'btn btn-bad' : 'btn btn-primary'}
            disabled={!listo}
            onClick={aceptar}
          >
            {datos.aceptar ?? 'Aceptar'}
          </button>
        </div>
      </div>
    </>
  )
}
