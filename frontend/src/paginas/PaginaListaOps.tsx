import { useEffect, useMemo, useState } from 'react'
import Icono from '../components/Icono'
import { formatFechaCorta } from '../format'
import { mensajeDe } from '../http'
import {
  guardarHonorarios,
  listarOps,
  fechaLocal,
  NOMBRE_ESTADO,
  verHonorarios,
  type FranjaProfesional,
  type FranjaReconocimiento,
  type ListaOps,
  type TablaHonorarios,
} from '../ops'
import { navegar } from '../rutas'
import { useSesion } from '../sesion'

/** Las prestaciones de servicios de la entidad y su tabla de honorarios. */
export default function PaginaListaOps() {
  const { usuario } = useSesion()!
  const [lista, setLista] = useState<ListaOps | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busqueda, setBusqueda] = useState('')
  const [tabla, setTabla] = useState(false)

  useEffect(() => {
    document.title = 'OPS · MiEvaluador'
    listarOps()
      .then(setLista)
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [])

  const visibles = useMemo(() => {
    const q = busqueda.trim().toLowerCase()
    return (lista?.contrataciones ?? []).filter(
      (c) => !q || `${c.contratista_nombre} ${c.contratista_cedula} ${c.referencia} ${c.objeto} ${c.creada_por}`.toLowerCase().includes(q),
    )
  }, [lista, busqueda])

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">{usuario.entidad?.nombre ?? 'Todas las entidades'}</div>
          <h1>Prestación de servicios</h1>
          <p>Las OPS que usted creó{lista?.puede_configurar ? ' y las de su entidad' : ''}: idoneidad, experiencia y documentos de cada contratista.</p>
        </div>
        <div className="page-head-acciones">
          {lista?.puede_configurar && usuario.entidad && (
            <button type="button" className="btn btn-secondary" onClick={() => setTabla(true)}>
              Tabla de honorarios
            </button>
          )}
          {lista?.puede_crear && lista.licenciado && (
            <button type="button" className="btn btn-primary" onClick={() => navegar('/ops/nueva')}>
              <Icono nombre="mas" /> Nueva OPS
            </button>
          )}
        </div>
      </div>
      {error && (
        <div className="callout callout-bad" role="alert" style={{ marginBottom: 16 }}>
          <Icono nombre="alerta" />
          <div>{error}</div>
        </div>
      )}
      {lista && !lista.licenciado && (
        <div className="callout callout-info" style={{ marginBottom: 16 }}>
          <Icono nombre="info" />
          <div>Su entidad no tiene el módulo de prestación de servicios. Tiene licencia aparte: pídalo a LeMarTek para activarlo.</div>
        </div>
      )}
      <div className="toolbar">
        <div className="input-group search">
          <Icono nombre="buscar" tam={16} />
          <input className="input" placeholder="Buscar por contratista, cédula u objeto" value={busqueda} onChange={(e) => setBusqueda(e.target.value)} />
        </div>
        {lista && <span className="small muted">{visibles.length} contrataciones</span>}
      </div>
      {lista === null ? (
        <div className="vacio">{!error && <span className="spinner oscuro" />}</div>
      ) : (
        <div className="tabla-wrap">
          <table className="tabla tabla-apilable">
            <thead>
              <tr>
                <th>Contratista</th>
                <th>Objeto</th>
                <th>Estado</th>
                <th>Creada</th>
              </tr>
            </thead>
            <tbody>
              {visibles.map((c) => (
                <tr key={c.id} className="fila-clic" onClick={() => navegar(`/ops/${c.id}`)}>
                  <td data-label="Contratista">
                    {/* El clic (o Enter) sube a la fila, que es la que abre la contratación. */}
                    <button type="button" className="enlace">
                      <strong>{c.contratista_nombre || 'Contratista por identificar'}</strong>
                    </button>
                    <div className="small muted">
                      {c.contratista_cedula ? `C.C. ${Number(c.contratista_cedula).toLocaleString('es-CO')}` : 'Leyendo sus datos'}
                      {c.referencia && ` · ${c.referencia}`}
                    </div>
                  </td>
                  <td data-label="Objeto" style={{ maxWidth: 420 }}>
                    <div className="small recortar">{c.objeto || '—'}</div>
                    {!usuario.entidad && <div className="small muted">{c.entidad}</div>}
                  </td>
                  <td data-label="Estado">
                    <span className="pill" data-estado-ops={c.estado}>
                      {NOMBRE_ESTADO[c.estado]}
                    </span>
                  </td>
                  <td data-label="Creada" className="small muted nowrap">
                    {formatFechaCorta(fechaLocal(c.creada_en))}
                    <div>{c.creada_por}</div>
                  </td>
                </tr>
              ))}
              {visibles.length === 0 && (
                <tr>
                  <td colSpan={4} className="vacio">
                    {lista.contrataciones.length === 0 ? 'Aún no hay prestaciones de servicios.' : 'Ninguna coincide con la búsqueda.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {tabla && <EditorHonorarios onCerrar={() => setTabla(false)} />}
    </main>
  )
}

const pesos = (v: string) => Number(v.replace(/\D/g, '')) || 0
const numero = (v: string) => (v.trim() === '' ? null : Number(v.replace(',', '.')))

/** La tabla de honorarios máximos que la entidad expide cada año. */
function EditorHonorarios({ onCerrar }: { onCerrar: () => void }) {
  const [vigencia, setVigencia] = useState(new Date().getFullYear())
  const [datos, setDatos] = useState<TablaHonorarios | null>(null)
  const [norma, setNorma] = useState('')
  const [profesional, setProfesional] = useState<string[][]>([])
  const [reconocimiento, setReconocimiento] = useState<string[][]>([])
  const [guardando, setGuardando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  useEffect(() => {
    verHonorarios(vigencia)
      .then((t) => {
        setDatos(t)
        setNorma(t.norma)
        setProfesional(t.profesional.map((f) => [String(f.desde), f.hasta == null ? '' : String(f.hasta), String(f.sin_especializacion), String(f.con_especializacion), String(f.con_maestria)]))
        setReconocimiento(t.reconocimiento.map((f) => [String(f.desde), f.hasta == null ? '' : String(f.hasta), String(f.valor)]))
      })
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [vigencia])

  async function guardar() {
    setGuardando(true)
    setError(null)
    setAviso(null)
    try {
      const filasProfesional: FranjaProfesional[] = profesional.map((f) => ({
        desde: numero(f[0]) ?? 0, hasta: numero(f[1]), sin_especializacion: pesos(f[2]), con_especializacion: pesos(f[3]), con_maestria: pesos(f[4]),
      }))
      const filasReconocimiento: FranjaReconocimiento[] = reconocimiento.map((f) => ({ desde: numero(f[0]) ?? 0, hasta: numero(f[1]), valor: pesos(f[2]) }))
      setDatos(await guardarHonorarios({ vigencia, norma, profesional: filasProfesional, reconocimiento: filasReconocimiento }))
      setAviso(`Tabla de ${vigencia} guardada.`)
    } catch (e) {
      setError(mensajeDe(e))
    } finally {
      setGuardando(false)
    }
  }

  const cambiar = (filas: string[][], poner: (f: string[][]) => void, i: number, j: number, valor: string) =>
    poner(filas.map((f, x) => (x === i ? f.map((c, y) => (y === j ? valor : c)) : f)))

  const cuadro = (titulo: string, encabezados: string[], filas: string[][], poner: (f: string[][]) => void) => (
    <>
      <h3 className="ops-seccion">{titulo}</h3>
      <div className="tabla-wrap">
        <table className="tabla tabla-honorarios">
          <thead>
            <tr>
              {encabezados.map((e) => (
                <th key={e}>{e}</th>
              ))}
              <th aria-label="Quitar" />
            </tr>
          </thead>
          <tbody>
            {filas.map((f, i) => (
              <tr key={i}>
                {f.map((c, j) => (
                  <td key={j}>
                    <input
                      className="input"
                      inputMode="numeric"
                      aria-label={`${encabezados[j]}, fila ${i + 1}`}
                      placeholder={j === 1 ? 'en adelante' : ''}
                      value={j >= 2 && c ? Number(c.replace(/\D/g, '') || 0).toLocaleString('es-CO') : c}
                      onChange={(e) => cambiar(filas, poner, i, j, j >= 2 ? e.target.value.replace(/\D/g, '') : e.target.value)}
                    />
                  </td>
                ))}
                <td>
                  <button type="button" className="btn btn-ghost btn-sm btn-icon" aria-label={`Quitar la fila ${i + 1}`} onClick={() => poner(filas.filter((_, x) => x !== i))}>
                    <Icono nombre="x" tam={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button type="button" className="enlace small" onClick={() => poner([...filas, encabezados.map(() => '')])}>
        + Agregar franja
      </button>
    </>
  )

  return (
    <>
      <div className="overlay" onClick={onCerrar} />
      <div className="dialogo dialogo-ancho" role="dialog" aria-modal="true" aria-labelledby="titulo-honorarios">
        <h2 id="titulo-honorarios">Tabla de honorarios máximos</h2>
        <p className="small muted">
          La que su entidad expide cada año para los contratos de prestación de servicios. Con ella se verifica que los honorarios no
          superen el tope de la franja de experiencia del contratista.
        </p>
        <div className="grid-2" style={{ margin: '14px 0' }}>
          <div className="field">
            <label htmlFor="hon-vigencia">Vigencia</label>
            <input id="hon-vigencia" className="input" type="number" min={2020} max={2100} value={vigencia} onChange={(e) => {
                const nueva = Number(e.target.value)
                if (!nueva || nueva === vigencia) return
                setDatos(null)
                setError(null)
                setAviso(null)
                setVigencia(nueva)
              }}
            />
            {datos && datos.vigencias.length > 0 && <span className="hint">Registradas: {[...datos.vigencias].sort().join(', ')}</span>}
          </div>
          <div className="field">
            <label htmlFor="hon-norma">Acto que la adopta</label>
            <input id="hon-norma" className="input" placeholder="Resolución 1750 de 2025" value={norma} onChange={(e) => setNorma(e.target.value)} />
          </div>
        </div>
        {datos === null && !error ? (
          <div className="vacio">
            <span className="spinner oscuro" />
          </div>
        ) : (
          <>
            {cuadro('Experiencia profesional (años)', ['Desde', 'Hasta', 'Sin especialización', 'Con especialización', 'Con maestría o más'], profesional, setProfesional)}
            {cuadro('Reconocimiento por experiencia específica (años)', ['Desde', 'Hasta', 'Valor que se suma'], reconocimiento, setReconocimiento)}
          </>
        )}
        {error && (
          <p className="small" role="alert" style={{ color: 'var(--bad)', marginTop: 10 }}>
            {error}
          </p>
        )}
        {aviso && (
          <p className="small" role="status" style={{ color: 'var(--ok)', marginTop: 10 }}>
            {aviso}
          </p>
        )}
        <div className="dialogo-pie">
          <button type="button" className="btn btn-ghost" onClick={onCerrar}>
            Cerrar
          </button>
          <button type="button" className="btn btn-primary" disabled={guardando || datos === null} onClick={() => void guardar()}>
            {guardando && <span className="spinner" />} Guardar
          </button>
        </div>
      </div>
    </>
  )
}
