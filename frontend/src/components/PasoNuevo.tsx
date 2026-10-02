import { useRef, useState } from 'react'
import Icono from './Icono'

interface Props {
  codigoProceso: string
  fechaCierre: string
  carpetaDrive: string
  archivo: File | null
  /** Ofertas en .zip subidas a mano, en vez de una carpeta compartida. */
  ofertas: File[]
  analizando: boolean
  error: string | null
  onCambiar: (campos: {
    codigoProceso?: string
    fechaCierre?: string
    carpetaDrive?: string
    archivo?: File | null
    ofertas?: File[]
  }) => void
  onAnalizar: () => void
  onCancelar: () => void
}

function tamanoLegible(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function PasoNuevo(props: Props) {
  const { codigoProceso, fechaCierre, carpetaDrive, archivo, ofertas, analizando, error } = props
  const inputOfertas = useRef<HTMLInputElement>(null)
  const inputArchivo = useRef<HTMLInputElement>(null)
  const [arrastrando, setArrastrando] = useState(false)
  // Las ofertas llegan de una de dos formas, y antes las dos casillas estaban
  // una debajo de la otra con una nota explicando cuál manda. Se elige primero
  // y solo se muestra la que corresponde.
  const [origen, setOrigen] = useState<'archivos' | 'carpeta'>(carpetaDrive.trim() ? 'carpeta' : 'archivos')

  // Las ofertas pueden venir de una carpeta compartida o subidas a mano: hace
  // falta una de las dos, no las dos.
  const falta = [
    !codigoProceso.trim() && 'el código del proceso',
    !fechaCierre && 'la fecha de cierre',
    !archivo && 'el PDF del Documento Base',
    !(carpetaDrive.trim() || ofertas.length > 0) &&
      (origen === 'archivos' ? 'los .zip de las ofertas' : 'el enlace de la carpeta con las ofertas'),
  ].filter(Boolean) as string[]
  const listo = falta.length === 0

  function soltar(e: React.DragEvent) {
    e.preventDefault()
    setArrastrando(false)
    const f = e.dataTransfer.files?.[0]
    if (f && (f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'))) props.onCambiar({ archivo: f })
  }

  return (
    <main className="page page-narrow">
      <div className="page-head">
        <div>
          <div className="eyebrow">Nuevo proceso</div>
          <h1>Cree un proceso para evaluar</h1>
          <p>
            Cargue el Documento Base y la carpeta con las ofertas. El sistema revisa los documentos de cada proponente y
            le muestra qué cumple y qué necesita su revisión.
          </p>
        </div>
      </div>

      <form
        className="card"
        onSubmit={(e) => {
          e.preventDefault()
          if (listo) props.onAnalizar()
        }}
      >
        <div className="grid-2" style={{ marginBottom: 20 }}>
          <div className="field">
            <label htmlFor="codigo">Código del proceso</label>
            <div className="input-group">
              <Icono nombre="hash" tam={16} />
              <input
                id="codigo"
                className="input"
                placeholder="ENT-CM-037-2026"
                value={codigoProceso}
                onChange={(e) => props.onCambiar({ codigoProceso: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="field">
            <label htmlFor="fecha">Fecha de cierre</label>
            <div className="input-group">
              <Icono nombre="calendario" tam={16} />
              <input
                id="fecha"
                className="input"
                type="date"
                value={fechaCierre}
                onChange={(e) => props.onCambiar({ fechaCierre: e.target.value })}
                required
              />
            </div>
            <span className="hint">Se usa para calcular vigencias (certificados, COPNIA, póliza).</span>
          </div>
        </div>

        <div className="field" style={{ marginBottom: 20 }}>
          <label>Documento Base (PDF)</label>
          <div
            className="dropzone"
            role="button"
            tabIndex={0}
            data-over={arrastrando}
            data-filled={!!archivo}
            onClick={() => inputArchivo.current?.click()}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputArchivo.current?.click()}
            onDragOver={(e) => {
              e.preventDefault()
              setArrastrando(true)
            }}
            onDragLeave={() => setArrastrando(false)}
            onDrop={soltar}
          >
            <div className="dropzone-icon">
              <Icono nombre={archivo ? 'documento' : 'subir'} tam={22} />
            </div>
            <div style={{ minWidth: 0 }}>
              {archivo ? (
                <>
                  <strong style={{ overflowWrap: 'anywhere' }}>{archivo.name}</strong>
                  <span className="small muted">{tamanoLegible(archivo.size)} · clic para cambiarlo</span>
                </>
              ) : (
                <>
                  <strong>Arrastre aquí el PDF del Documento Base</strong>
                  <span className="small muted">o haga clic para buscarlo en su equipo</span>
                </>
              )}
            </div>
          </div>
          <input
            ref={inputArchivo}
            type="file"
            accept="application/pdf"
            hidden
            onChange={(e) => props.onCambiar({ archivo: e.target.files?.[0] ?? null })}
          />
        </div>

        <div className="field" style={{ marginBottom: 16 }}>
          <label>¿Dónde están las ofertas?</label>
          <div className="opciones-origen" role="radiogroup" aria-label="Dónde están las ofertas">
            <button
              type="button"
              role="radio"
              aria-checked={origen === 'archivos'}
              className="opcion-origen"
              data-activa={origen === 'archivos'}
              onClick={() => setOrigen('archivos')}
            >
              <Icono nombre="subir" tam={17} />
              <span>
                <strong>En mi equipo</strong>
                <span className="small muted">Un .zip por proponente</span>
              </span>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={origen === 'carpeta'}
              className="opcion-origen"
              data-activa={origen === 'carpeta'}
              onClick={() => setOrigen('carpeta')}
            >
              <Icono nombre="carpeta" tam={17} />
              <span>
                <strong>En una carpeta compartida</strong>
                <span className="small muted">Google Drive u OneDrive</span>
              </span>
            </button>
          </div>
        </div>

        <div className="field" hidden={origen !== 'archivos'}>
          <label htmlFor="ofertas">Los .zip de las ofertas</label>
          <div className="acciones">
            <button type="button" className="btn btn-secondary" onClick={() => inputOfertas.current?.click()}>
              <Icono nombre="carpeta" tam={15} /> Elegir los .zip de las ofertas
            </button>
            {ofertas.length > 0 && (
              <>
                <span className="small">
                  {ofertas.length} oferta(s) ·{' '}
                  {tamanoLegible(ofertas.reduce((suma, o) => suma + o.size, 0))}
                </span>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => props.onCambiar({ ofertas: [] })}>
                  Quitar
                </button>
              </>
            )}
          </div>
          <input
            ref={inputOfertas}
            id="ofertas"
            type="file"
            multiple
            accept=".zip,.rar,.7z"
            hidden
            onChange={(e) => props.onCambiar({ ofertas: Array.from(e.target.files ?? []) })}
          />
          {ofertas.length > 0 && (
            <ul className="hint" style={{ margin: '6px 0 0', paddingLeft: 18 }}>
              {ofertas.slice(0, 8).map((o) => (
                <li key={o.name}>
                  {o.name} · {tamanoLegible(o.size)}
                </li>
              ))}
              {ofertas.length > 8 && <li>y {ofertas.length - 8} más…</li>}
            </ul>
          )}
          <span className="hint">
            Un .zip por proponente, nombrado “P1 Nombre del proponente” o “1. Nombre”. También sirve un solo .zip que
            traiga todas las ofertas dentro, cada una en su propio .zip o en su carpeta. Si un nombre no dice el
            número, se numera por el orden en que lo elija y queda anotado. Súbalas por tandas si pesan mucho.
          </span>
        </div>

        <div className="field" hidden={origen !== 'carpeta'}>
          <label htmlFor="drive">Enlace de la carpeta con las ofertas</label>
          <div className="input-group">
            <Icono nombre="carpeta" tam={16} />
            <input
              id="drive"
              className="input"
              placeholder="https://drive.google.com/drive/folders/… o https://1drv.ms/f/…"
              value={carpetaDrive}
              onChange={(e) => props.onCambiar({ carpetaDrive: e.target.value })}
            />
          </div>
          <span className="hint">
            Cada proponente debe estar en un archivo .zip o .rar nombrado como “P1 Nombre del proponente” o “1. Nombre”.
            En OneDrive, comparta la carpeta con «Cualquier persona con el vínculo».
          </span>
        </div>

        {error && (
          <div className="callout callout-bad" style={{ marginTop: 20 }}>
            <Icono nombre="alerta" />
            <div>{error}</div>
          </div>
        )}

        <div style={{ marginTop: 24, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {falta.length > 0 && !analizando && (
            <span className="small muted" style={{ textAlign: 'right' }}>
              Falta {falta.length > 1 ? `${falta.slice(0, -1).join(', ')} y ${falta[falta.length - 1]}` : falta[0]}.
            </span>
          )}
          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
            <button className="btn btn-ghost" type="button" onClick={props.onCancelar}>
              Cancelar
            </button>
            <button className="btn btn-primary btn-lg" type="submit" disabled={!listo || analizando}>
            {analizando ? (
              <>
                <span className="spinner" /> Leyendo documento y buscando ofertas…
              </>
            ) : (
              <>
                Continuar <Icono nombre="flecha" />
              </>
            )}
            </button>
          </div>
        </div>
      </form>
    </main>
  )
}
