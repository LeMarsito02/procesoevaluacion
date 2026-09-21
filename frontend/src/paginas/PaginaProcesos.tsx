import { useEffect, useMemo, useState } from 'react'
import Icono from '../components/Icono'
import { eliminarProceso, listarProcesos, type ProcesoResumen } from '../evaluaciones'
import { formatFechaCorta } from '../format'
import { mensajeDe } from '../http'
import { navegar } from '../rutas'
import { puedeCrearProcesos, useSesion } from '../sesion'
import { porcentajeAvance, textoCierre } from './avance'
import { EstadoEvaluacionPill } from './TarjetaEvaluacion'

export default function PaginaProcesos() {
  const { usuario } = useSesion()!
  const [procesos, setProcesos] = useState<ProcesoResumen[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busqueda, setBusqueda] = useState('')
  // Proceso que se va a eliminar (se confirma escribiendo su código).
  const [aEliminar, setAEliminar] = useState<ProcesoResumen | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  useEffect(() => {
    listarProcesos()
      .then(setProcesos)
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [])

  const visibles = useMemo(() => {
    const q = busqueda.trim().toLowerCase()
    return (procesos ?? []).filter(
      (p) =>
        !q ||
        `${p.codigo} ${p.objeto} ${p.evaluaciones.map((e) => e.responsable?.nombre_completo ?? '').join(' ')}`.toLowerCase().includes(q),
    )
  }, [procesos, busqueda])

  const puedeCrear = puedeCrearProcesos(usuario)

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">{usuario.entidad?.nombre ?? 'Todas las entidades'}</div>
          <h1>Procesos</h1>
          <p>Todos los procesos de la entidad con el avance de cada evaluación.</p>
        </div>
        {puedeCrear && (
          <button className="btn btn-primary" type="button" onClick={() => navegar('/procesos/nuevo')}>
            <Icono nombre="mas" /> Nuevo proceso
          </button>
        )}
      </div>
      {aviso && (
        <div className="callout callout-ok" style={{ marginBottom: 16 }} role="status">
          <Icono nombre="check" />
          <div>{aviso}</div>
        </div>
      )}
      {error && (
        <div className="callout callout-bad" style={{ marginBottom: 16 }} role="alert">
          <Icono nombre="alerta" />
          <div>{error}</div>
        </div>
      )}
      <div className="toolbar">
        <div className="input-group search">
          <Icono nombre="buscar" tam={16} />
          <input className="input" placeholder="Buscar por código, objeto o responsable" value={busqueda} onChange={(e) => setBusqueda(e.target.value)} />
        </div>
        {procesos && <span className="small muted">{visibles.length} procesos</span>}
      </div>
      {procesos === null ? (
        <div className="vacio">
          <span className="spinner oscuro" />
        </div>
      ) : (
        <div className="tabla-wrap">
          <table className="tabla">
            <thead>
              <tr>
                <th>Proceso</th>
                <th>Cierre</th>
                <th>Proponentes</th>
                <th>Evaluaciones</th>
                <th>Creado</th>
              </tr>
            </thead>
            <tbody>
              {visibles.map((p) => (
                <tr key={p.id}>
                  <td style={{ maxWidth: 300 }}>
                    <strong>{p.codigo}</strong>
                    <div className="small muted recortar">{p.objeto}</div>
                  </td>
                  <td className="small nowrap">{textoCierre(p.fecha_cierre)}</td>
                  <td className="num">{p.proponentes}</td>
                  <td>
                    <div className="lista-ev">
                      {p.evaluaciones.map((e) => {
                        const pct = porcentajeAvance(e)
                        return (
                          <button key={e.id} type="button" className="fila-ev" onClick={() => navegar(`/evaluaciones/${e.id}`)}>
                            <span className="tag">{e.tipo_nombre}</span>
                            <EstadoEvaluacionPill e={e} />
                            <span className="barra fila-ev-barra">
                              <span style={{ width: `${pct}%` }} />
                            </span>
                            <span className="num small">{pct}%</span>
                            <span className="small muted recortar">{e.responsable?.nombre_completo ?? 'Sin asignar'}</span>
                          </button>
                        )
                      })}
                    </div>
                  </td>
                  <td className="small muted nowrap">
                    {formatFechaCorta(p.creado_en.slice(0, 10))}
                    <div>{p.creado_por.nombre_completo}</div>
                    {p.puede_eliminar && (
                      <button
                        type="button"
                        className="enlace"
                        style={{ color: 'var(--bad)', marginTop: 4 }}
                        title="Eliminar el proceso con todo lo suyo"
                        aria-label={`Eliminar el proceso ${p.codigo}`}
                        onClick={() => {
                          setAviso(null)
                          setAEliminar(p)
                        }}
                      >
                        Eliminar proceso
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {visibles.length === 0 && (
                <tr>
                  <td colSpan={5} className="vacio">
                    {procesos.length === 0 ? 'La entidad aún no tiene procesos.' : 'Ningún proceso coincide con la búsqueda.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {aEliminar && (
        <ConfirmarEliminacion
          proceso={aEliminar}
          onCancelar={() => setAEliminar(null)}
          onEliminado={() => {
            setProcesos((lista) => (lista ?? []).filter((x) => x.id !== aEliminar.id))
            setAviso(`Se eliminó el proceso ${aEliminar.codigo}.`)
            setAEliminar(null)
          }}
        />
      )}
    </main>
  )
}

/** Eliminar es irreversible: se explica qué se borra y se confirma
 * escribiendo el código del proceso. */
function ConfirmarEliminacion({
  proceso,
  onCancelar,
  onEliminado,
}: {
  proceso: ProcesoResumen
  onCancelar: () => void
  onEliminado: () => void
}) {
  const [escrito, setEscrito] = useState('')
  const [eliminando, setEliminando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const coincide = escrito.trim().toUpperCase() === proceso.codigo.trim().toUpperCase()

  async function eliminar() {
    setEliminando(true)
    setError(null)
    try {
      await eliminarProceso(proceso.id, escrito)
      onEliminado()
    } catch (e) {
      setError(mensajeDe(e))
      setEliminando(false)
    }
  }

  return (
    <>
      <div className="overlay" onClick={onCancelar} />
      <div className="dialogo" role="dialog" aria-modal="true" aria-labelledby="titulo-eliminar">
        <h2 id="titulo-eliminar">Eliminar el proceso {proceso.codigo}</h2>
        <p className="small">
          Se borran para siempre {proceso.evaluaciones.length === 1 ? 'su evaluación' : `sus ${proceso.evaluaciones.length} evaluaciones`},{' '}
          {proceso.proponentes === 1 ? 'el proponente' : `los ${proceso.proponentes} proponentes`} con sus resultados y
          revisiones, los certificados aportados y los expedientes generados. <strong>No se puede deshacer.</strong>
        </p>
        <label className="small muted" style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 12 }}>
          Para confirmar, escriba el código del proceso: <strong style={{ color: 'var(--ink)' }}>{proceso.codigo}</strong>
          <input
            className="input"
            autoFocus
            value={escrito}
            onChange={(e) => setEscrito(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && coincide && !eliminando && void eliminar()}
          />
        </label>
        {error && (
          <p className="small" role="alert" style={{ color: 'var(--bad)', marginTop: 8 }}>
            {error}
          </p>
        )}
        <div className="dialogo-pie">
          <button type="button" className="btn btn-ghost" onClick={onCancelar}>
            Cancelar
          </button>
          <button type="button" className="btn btn-bad" disabled={!coincide || eliminando} onClick={() => void eliminar()}>
            {eliminando && <span className="spinner" />} Eliminar para siempre
          </button>
        </div>
      </div>
    </>
  )
}
