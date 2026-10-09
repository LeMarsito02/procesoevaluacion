import { useEffect, useRef, useState } from 'react'
import { eliminarCarga, verCarga } from '../api'
import { useDialogos } from '../dialogos'
import { huellaRapida } from '../huella'
import { mensajeDe } from '../http'
import Icono from './Icono'

interface Props {
  codigoProceso: string
  fechaCierre: string
  carpetaDrive: string
  archivo: File | null
  /** Ofertas en .zip subidas a mano, en vez de una carpeta compartida. */
  ofertas: File[]
  analizando: boolean
  /** Avance de la subida mientras se envían los archivos. */
  subida?: { cargado: number; total: number; inicio: number; ahora: number; reutilizadas?: string[] } | null
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

// Lo que acepta el servidor por carga (SUBIDA_MAXIMA_CARGA): hasta 10 GB por archivo, 20 GB en total.
const LIMITE_SUBIDA = 20 * 1024 ** 3

function tiempoLegible(segundos: number): string {
  if (segundos < 60) return `${Math.max(1, Math.round(segundos))} s`
  const m = Math.floor(segundos / 60)
  return m < 60 ? `${m} min ${String(Math.round(segundos % 60)).padStart(2, '0')} s` : `${Math.floor(m / 60)} h ${m % 60} min`
}

/** Barra de la subida con lo enviado, la velocidad y el tiempo que falta. */
function AvanceSubida({ cargado, total, inicio, ahora, reutilizadas = [] }: { cargado: number; total: number; inicio: number; ahora: number; reutilizadas?: string[] }) {
  const pct = total > 0 ? Math.min(100, (cargado / total) * 100) : 0
  const segundos = (ahora - inicio) / 1000
  const velocidad = segundos > 0.5 ? cargado / segundos : 0
  const falta = velocidad > 0 ? (total - cargado) / velocidad : null
  const terminada = cargado >= total && total > 0
  return (
    <div className="subida" role="status" aria-live="polite">
      <div className="leyendo-cabeza">
        <strong>{terminada ? 'Archivos subidos: guardándolos en el servidor…' : `Subiendo los archivos · ${Math.floor(pct)} %`}</strong>
        {!terminada && falta !== null && segundos > 1.5 && <span className="small muted">faltan unos {tiempoLegible(falta)}</span>}
      </div>
      <div className="barra-progreso" role="progressbar" aria-label="Avance de la subida" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.floor(pct)}>
        <span style={{ width: `${pct}%` }} />
      </div>
      {reutilizadas.length > 0 && (
        <span className="small" style={{ color: 'var(--ok)', fontWeight: 600 }}>
          Ya estaba en el servidor, no se vuelve a subir: {reutilizadas.join(', ')}
        </span>
      )}
      <span className="small muted">
        {tamanoLegible(cargado)} de {tamanoLegible(total)}
        {velocidad > 0 && !terminada ? ` · ${tamanoLegible(velocidad)}/s` : ''} · Si se corta o recarga la página, vuelva a elegir los mismos archivos: sigue desde donde iba.
      </span>
    </div>
  )
}

function tamanoLegible(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}

export default function PasoNuevo(props: Props) {
  const { codigoProceso, fechaCierre, carpetaDrive, archivo, ofertas, analizando, error } = props
  const inputOfertas = useRef<HTMLInputElement>(null)
  const inputArchivo = useRef<HTMLInputElement>(null)
  const [arrastrando, setArrastrando] = useState(false)
  // Las ofertas llegan de una de dos formas, y antes las dos casillas estaban
  // una debajo de la otra con una nota explicando cuál manda. Se elige primero
  // y solo se muestra la que corresponde.
  const { confirmar } = useDialogos()
  // Qué archivos elegidos ya están en el servidor (por su huella): esos no se suben.
  const [enServidor, setEnServidor] = useState<Record<string, { huella: string; ofertas: number } | null>>({})
  const [avisoCargas, setAvisoCargas] = useState<string | null>(null)
  const clave = (f: File) => `${f.name}|${f.size}|${f.lastModified}`
  useEffect(() => {
    let vivo = true
    for (const f of ofertas) {
      const k = clave(f)
      huellaRapida(f)
        .then(async (huella) => {
          const r = await verCarga(huella, f.size)
          if (vivo) setEnServidor((e) => ({ ...e, [k]: r.guardada ? { huella, ofertas: r.ofertas } : null }))
        })
        .catch(() => vivo && setEnServidor((e) => ({ ...e, [k]: null })))
    }
    return () => {
      vivo = false
    }
  }, [ofertas])

  async function eliminarDelServidor(huella: string, nombre: string) {
    if (
      !(await confirmar({
        titulo: `¿Eliminar «${nombre}» del servidor?`,
        mensaje: 'Se borran sus ofertas guardadas, salvo las que ya use algún proceso (esas se conservan). Si lo vuelve a elegir, se subirá completo.',
        aceptar: 'Eliminar del servidor',
        cancelar: 'Conservar',
        peligro: true,
      }))
    )
      return
    try {
      const r = await eliminarCarga(huella)
      setAvisoCargas(`«${nombre}» se eliminó del servidor (${r.ofertas_borradas} ofertas borradas).`)
      setEnServidor((e) => Object.fromEntries(Object.entries(e).map(([k, x]) => [k, x && x.huella === huella ? null : x])))
    } catch (err) {
      setAvisoCargas(mensajeDe(err, 'No se pudo eliminar.'))
    }
  }

  // Lo habitual es una carpeta compartida; subirlas desde el equipo es la excepción.
  const [origen, setOrigen] = useState<'archivos' | 'carpeta'>(ofertas.length > 0 ? 'archivos' : 'carpeta')
  // Se marcan los campos que faltan solo después de intentar continuar.
  const [intentado, setIntentado] = useState(false)

  // Lo que hace falta para continuar, a la vista y con su campo: las ofertas
  // pueden venir de una carpeta compartida o subidas a mano (una de las dos).
  const requisitos = [
    { id: 'codigo', texto: 'Código del proceso', hecho: !!codigoProceso.trim() },
    { id: 'fecha', texto: 'Fecha de cierre', hecho: !!fechaCierre },
    { id: 'documento', texto: 'PDF del Documento Base', hecho: !!archivo },
    {
      id: origen === 'archivos' ? 'ofertas' : 'drive',
      texto: origen === 'archivos' ? 'Los .zip de las ofertas' : 'Enlace de la carpeta con las ofertas',
      hecho: !!(carpetaDrive.trim() || ofertas.length > 0),
    },
  ]
  // El servidor acepta hasta 2 GB por carga (LIMITE_OFERTAS_SUBIDAS): se avisa
  // antes de subir, no después de una hora de subida.
  const pesoOfertas = ofertas.reduce((suma, o) => suma + o.size, 0)
  const demasiado = origen === 'archivos' && pesoOfertas > LIMITE_SUBIDA
  const listo = requisitos.every((x) => x.hecho) && !demasiado
  const falta = (id: string) => intentado && !requisitos.find((x) => x.id === id)?.hecho

  function continuar() {
    if (listo) {
      props.onAnalizar()
      return
    }
    setIntentado(true)
    const primero = requisitos.find((x) => !x.hecho)
    const campo = primero && document.getElementById(primero.id === 'documento' ? 'zona-documento' : primero.id)
    campo?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    campo?.focus()
  }

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
          continuar()
        }}
      >
        <div className="grid-2" style={{ marginBottom: 20 }}>
          <div className="field">
            <label htmlFor="codigo">Código del proceso</label>
            <div className="input-group">
              <Icono nombre="hash" tam={16} />
              <input
                id="codigo"
                aria-invalid={falta('codigo')}
                className="input"
                placeholder="ENT-CM-037-2026"
                value={codigoProceso}
                onChange={(e) => props.onCambiar({ codigoProceso: e.target.value.toUpperCase() })}
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
                aria-invalid={falta('fecha')}
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
            id="zona-documento"
            className="dropzone"
            data-falta={falta('documento')}
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
            <button type="button" id="ofertas" className="btn btn-secondary" data-falta={falta('ofertas')} onClick={() => inputOfertas.current?.click()}>
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
            aria-label="Elegir los .zip de las ofertas"
            type="file"
            multiple
            accept=".zip,.rar,.7z"
            hidden
            onChange={(e) => props.onCambiar({ ofertas: Array.from(e.target.files ?? []) })}
          />
          {ofertas.length > 0 && (
            <ul className="ofertas-elegidas">
              {ofertas.slice(0, 12).map((o) => {
                const estado = enServidor[clave(o)]
                return (
                  <li key={clave(o)}>
                    <span>
                      {o.name} · {tamanoLegible(o.size)}
                    </span>
                    {estado === undefined ? (
                      <span className="small muted">revisando si ya está en el servidor…</span>
                    ) : estado ? (
                      <span className="oferta-en-servidor">
                        <span>
                          <Icono nombre="check" tam={13} grosor={3} /> Ya está en el servidor ({estado.ofertas} ofertas): no se volverá a subir
                        </span>
                        <button type="button" className="enlace" onClick={() => void eliminarDelServidor(estado.huella, o.name)}>
                          Eliminar del servidor
                        </button>
                      </span>
                    ) : (
                      <span className="small muted">se subirá</span>
                    )}
                  </li>
                )
              })}
              {ofertas.length > 12 && <li className="small muted">y {ofertas.length - 12} más…</li>}
            </ul>
          )}
          {demasiado && (
            <div className="callout callout-bad" role="alert" style={{ marginTop: 10 }}>
              <Icono nombre="alerta" />
              <div>
                Las ofertas pesan {tamanoLegible(pesoOfertas)} y el máximo por carga es 20 GB. Para ofertas tan pesadas use{' '}
                <button type="button" className="enlace" onClick={() => setOrigen('carpeta')}>
                  una carpeta compartida
                </button>
                : el servidor las descarga directo, sin pasar por la red de este equipo, y es mucho más rápido.
              </div>
            </div>
          )}
          {avisoCargas && (
            <div className="callout callout-ok" role="status" style={{ marginTop: 8 }}>
              <div>{avisoCargas}</div>
            </div>
          )}
          <span className="hint">
            Un .zip por proponente, nombrado “P1 Nombre del proponente” o “1. Nombre”. También sirve un solo .zip que
            traiga todas las ofertas dentro, cada una en su propio .zip o en su carpeta. Si un nombre no dice el
            número, se numera por el orden en que lo elija y queda anotado. Hasta 10 GB por archivo; si las ofertas pesan mucho, una carpeta compartida es más rápida.
          </span>
        </div>

        <div className="field" hidden={origen !== 'carpeta'}>
          <label htmlFor="drive">Enlace de la carpeta con las ofertas</label>
          <div className="input-group">
            <Icono nombre="carpeta" tam={16} />
            <input
              id="drive"
              aria-invalid={falta('drive')}
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

        <div style={{ marginTop: 24, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {analizando && props.subida && <AvanceSubida {...props.subida} />}
          <div className="requisitos-continuar" data-listo={listo} aria-live="polite" hidden={analizando}>
            <strong>{listo ? 'Todo listo para continuar' : 'Para continuar complete:'}</strong>
            <ul>
              {requisitos.map((x) => (
                <li key={x.id} data-hecho={x.hecho} data-falta={intentado && !x.hecho}>
                  <span className="requisito-marca" aria-hidden="true">
                    {x.hecho ? <Icono nombre="check" tam={13} grosor={3} /> : null}
                  </span>
                  {x.texto}
                  <span className="sr-only">{x.hecho ? ' (listo)' : ' (falta)'}</span>
                </li>
              ))}
            </ul>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
            <button className="btn btn-ghost" type="button" onClick={props.onCancelar}>
              Cancelar
            </button>
            <button className="btn btn-primary btn-lg" type="submit" disabled={analizando}>
            {analizando ? (
              <>
                <span className="spinner" /> {props.subida && props.subida.total > 0 ? `Subiendo · ${Math.floor(Math.min(100, (props.subida.cargado / props.subida.total) * 100))} %` : 'Subiendo los archivos…'}
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
