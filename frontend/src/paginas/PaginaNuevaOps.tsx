import { useEffect, useRef, useState } from 'react'
import Icono from '../components/Icono'
import { listarEntidades, type Entidad } from '../cuentas'
import { mensajeDe } from '../http'
import { crearOps } from '../ops'
import { navegar } from '../rutas'
import { useSesion } from '../sesion'

const hoy = () => new Date().toLocaleDateString('en-CA')

function tamanoLegible(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const esAdmitido = (f: File) => /\.(pdf|zip)$/i.test(f.name) || f.type === 'application/pdf'

/** Nueva prestación de servicios: los datos del contratista y sus documentos.
 * El perfil, el valor y las obligaciones salen del estudio previo. */
export default function PaginaNuevaOps() {
  const { usuario } = useSesion()!
  const esSuper = usuario.rol === 'superadmin'
  const [nombre, setNombre] = useState('')
  const [cedula, setCedula] = useState('')
  const [referencia, setReferencia] = useState('')
  const [fecha, setFecha] = useState(hoy())
  const [libreta, setLibreta] = useState<'' | 'si' | 'no'>('')
  const [deEntidad, setDeEntidad] = useState<File[]>([])
  const [deContratista, setDeContratista] = useState<File[]>([])
  const [entidades, setEntidades] = useState<Entidad[]>([])
  const [entidadId, setEntidadId] = useState<string | null>(esSuper ? null : (usuario.entidad?.id ?? null))
  const [creando, setCreando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    document.title = 'Nueva OPS · MiEvaluador'
    if (esSuper) listarEntidades().then((l) => setEntidades(l.filter((e) => e.activa && e.modulo_ops))).catch(() => undefined)
  }, [esSuper])

  const falta = [
    esSuper && !entidadId && 'la entidad',
    // Nombre y cédula van los dos o ninguno: vacíos, se leen de los antecedentes.
    (nombre.trim() || cedula.trim()) && nombre.trim().length < 5 && 'el nombre completo del contratista',
    (nombre.trim() || cedula.trim()) && cedula.replace(/\D/g, '').length < 5 && 'su cédula',
    deContratista.length === 0 && 'los documentos del contratista',
  ].filter(Boolean) as string[]

  async function crear() {
    setCreando(true)
    setError(null)
    try {
      const creada = await crearOps({
        nombre, cedula, referencia, fechaReferencia: fecha, exigeLibreta: libreta, entidadId: esSuper ? entidadId : null,
        documentosEntidad: deEntidad, documentosContratista: deContratista,
      })
      navegar(`/ops/${creada.id}`, true)
    } catch (e) {
      setError(mensajeDe(e, 'No se pudo crear la contratación.'))
      setCreando(false)
    }
  }

  return (
    <main className="page page-narrow">
      <div className="page-head">
        <div>
          <div className="eyebrow">Nueva OPS</div>
          <h1>Prestación de servicios</h1>
          <p>
            Cargue los documentos del contratista y de la entidad. El sistema lee el perfil del estudio previo, pone la
            experiencia en línea sin traslapes y revisa cada documento.
          </p>
        </div>
      </div>

      <form
        className="card"
        onSubmit={(e) => {
          e.preventDefault()
          if (falta.length === 0 && !creando) void crear()
        }}
      >
        {esSuper && (
          <div className="field" style={{ marginBottom: 20 }}>
            <label htmlFor="ops-entidad">Entidad</label>
            <select id="ops-entidad" className="input" value={entidadId ?? ''} onChange={(e) => setEntidadId(e.target.value || null)}>
              <option value="">Elija la entidad…</option>
              {entidades.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.nombre}
                </option>
              ))}
            </select>
            <span className="hint">Solo aparecen las entidades con el módulo de prestación de servicios.</span>
          </div>
        )}

        <h2 className="ops-seccion">1. El contratista</h2>
        <div className="grid-2" style={{ marginBottom: 20 }}>
          <div className="field">
            <label htmlFor="ops-nombre">Nombre completo</label>
            <input id="ops-nombre" className="input" value={nombre} onChange={(e) => setNombre(e.target.value)} autoComplete="off" />
            <span className="hint">Puede dejar el nombre y la cédula vacíos: se leen de sus certificados de antecedentes.</span>
          </div>
          <div className="field">
            <label htmlFor="ops-cedula">Cédula</label>
            <div className="input-group">
              <Icono nombre="hash" tam={16} />
              <input id="ops-cedula" className="input" inputMode="numeric" value={cedula} onChange={(e) => setCedula(e.target.value)} autoComplete="off" />
            </div>
          </div>
          <div className="field">
            <label htmlFor="ops-referencia">Número del proceso o contrato (opcional)</label>
            <input id="ops-referencia" className="input" placeholder="CPS-208-2026" value={referencia} onChange={(e) => setReferencia(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="ops-fecha">Fecha del estudio previo</label>
            <div className="input-group">
              <Icono nombre="calendario" tam={16} />
              <input id="ops-fecha" className="input" type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} required />
            </div>
            <span className="hint">Contra esta fecha se mide la vigencia de los antecedentes.</span>
          </div>
        </div>
        <div className="field" style={{ marginBottom: 24 }}>
          <label htmlFor="ops-libreta">¿Es hombre menor de 50 años?</label>
          <select id="ops-libreta" className="input" value={libreta} onChange={(e) => setLibreta(e.target.value as '' | 'si' | 'no')}>
            <option value="">No lo sé todavía</option>
            <option value="si">Sí: se le exige libreta militar</option>
            <option value="no">No: la libreta militar no aplica</option>
          </select>
        </div>

        <h2 className="ops-seccion">2. Los documentos</h2>
        <div className="grid-2" style={{ marginBottom: 8 }}>
          <ZonaArchivos
            titulo="De la entidad"
            ayuda="Estudio previo y CDP. De ahí salen el perfil, el valor y las obligaciones."
            archivos={deEntidad}
            onCambiar={setDeEntidad}
          />
          <ZonaArchivos
            titulo="Del contratista"
            ayuda="Certificaciones, títulos, antecedentes, cédula, RUT y los demás. En PDF o en un .zip."
            archivos={deContratista}
            onCambiar={setDeContratista}
          />
        </div>
        <p className="hint" style={{ marginBottom: 20 }}>
          No hace falta ordenarlos ni nombrarlos: cada documento se reconoce por lo que dice.
        </p>

        {error && (
          <div className="callout callout-bad" role="alert" style={{ marginBottom: 16 }}>
            <Icono nombre="alerta" />
            <div>{error}</div>
          </div>
        )}
        <div className="acciones-form">
          <button type="button" className="btn btn-ghost" onClick={() => navegar('/procesos/nuevo')} disabled={creando}>
            Cancelar
          </button>
          <span className="small muted" style={{ marginLeft: 'auto' }}>
            {falta.length > 0 && `Falta ${falta.join(', ')}.`}
          </span>
          <button type="submit" className="btn btn-primary btn-lg" disabled={falta.length > 0 || creando}>
            {creando ? <span className="spinner" /> : <Icono nombre="chispa" />} {creando ? 'Subiendo documentos…' : 'Analizar documentos'}
          </button>
        </div>
      </form>
    </main>
  )
}

/** Zona para soltar varios PDF (o un .zip). Se pueden ir sumando archivos. */
export function ZonaArchivos({
  titulo,
  ayuda,
  archivos,
  onCambiar,
}: {
  titulo: string
  ayuda: string
  archivos: File[]
  onCambiar: (archivos: File[]) => void
}) {
  const entrada = useRef<HTMLInputElement>(null)
  const [arrastrando, setArrastrando] = useState(false)

  function agregar(nuevos: FileList | null) {
    if (!nuevos) return
    const ya = new Set(archivos.map((a) => `${a.name}:${a.size}`))
    onCambiar([...archivos, ...Array.from(nuevos).filter((f) => esAdmitido(f) && !ya.has(`${f.name}:${f.size}`))])
  }

  return (
    <div className="field">
      <label>{titulo}</label>
      <div
        className="dropzone zona-archivos"
        role="button"
        tabIndex={0}
        data-over={arrastrando}
        data-filled={archivos.length > 0}
        onClick={() => entrada.current?.click()}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && entrada.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setArrastrando(true)
        }}
        onDragLeave={() => setArrastrando(false)}
        onDrop={(e) => {
          e.preventDefault()
          setArrastrando(false)
          agregar(e.dataTransfer.files)
        }}
      >
        <div className="dropzone-icon">
          <Icono nombre={archivos.length ? 'documento' : 'subir'} tam={22} />
        </div>
        <div style={{ minWidth: 0 }}>
          {archivos.length ? (
            <>
              <strong>
                {archivos.length} {archivos.length === 1 ? 'archivo' : 'archivos'}
              </strong>
              <span className="small muted">{tamanoLegible(archivos.reduce((s, a) => s + a.size, 0))} · clic para sumar más</span>
            </>
          ) : (
            <>
              <strong>Arrastre aquí los PDF</strong>
              <span className="small muted">o haga clic para buscarlos</span>
            </>
          )}
        </div>
      </div>
      <input
        ref={entrada}
        type="file"
        accept="application/pdf,.pdf,.zip,application/zip"
        multiple
        hidden
        onChange={(e) => {
          agregar(e.target.files)
          e.target.value = ''
        }}
      />
      <span className="hint">{ayuda}</span>
      {archivos.length > 0 && (
        <ul className="zona-lista">
          {archivos.map((a, i) => (
            <li key={`${a.name}:${a.size}`}>
              <span className="recortar">{a.name}</span>
              <button type="button" className="btn btn-ghost btn-sm btn-icon" aria-label={`Quitar ${a.name}`} onClick={() => onCambiar(archivos.filter((_, j) => j !== i))}>
                <Icono nombre="x" tam={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
