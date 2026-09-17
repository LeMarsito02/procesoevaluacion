import { useEffect, useMemo, useState } from 'react'
import Icono from '../components/Icono'
import { listarProcesos, type ProcesoResumen } from '../evaluaciones'
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
    </main>
  )
}
