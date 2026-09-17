import { useRef, useState } from 'react'
import Icono from './Icono'

interface Props {
  codigoProceso: string
  fechaCierre: string
  carpetaDrive: string
  archivo: File | null
  analizando: boolean
  error: string | null
  onCambiar: (campos: { codigoProceso?: string; fechaCierre?: string; carpetaDrive?: string; archivo?: File | null }) => void
  onAnalizar: () => void
  onCancelar: () => void
}

function tamanoLegible(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function PasoNuevo(props: Props) {
  const { codigoProceso, fechaCierre, carpetaDrive, archivo, analizando, error } = props
  const inputArchivo = useRef<HTMLInputElement>(null)
  const [arrastrando, setArrastrando] = useState(false)

  const listo = codigoProceso.trim() && fechaCierre && archivo && carpetaDrive.trim()

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
                placeholder="ICCU-CM-037-2026"
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

        <div className="field">
          <label htmlFor="drive">Carpeta de Google Drive con las ofertas</label>
          <div className="input-group">
            <Icono nombre="carpeta" tam={16} />
            <input
              id="drive"
              className="input"
              placeholder="https://drive.google.com/drive/folders/…"
              value={carpetaDrive}
              onChange={(e) => props.onCambiar({ carpetaDrive: e.target.value })}
              required
            />
          </div>
          <span className="hint">
            Cada proponente debe estar en un archivo .zip o .rar nombrado como “P1 Nombre del proponente”.
          </span>
        </div>

        {error && (
          <div className="callout callout-bad" style={{ marginTop: 20 }}>
            <Icono nombre="alerta" />
            <div>{error}</div>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 24 }}>
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
      </form>
    </main>
  )
}
