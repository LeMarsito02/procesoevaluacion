import { useEffect, useState } from 'react'
import { calcularCoincidencias, revisarCoincidencia, verCoincidencias, type Coincidencias } from '../economica'
import { mensajeDe } from '../http'
import Icono from './Icono'

/** Coincidencias entre las ofertas del proceso (RF-14): un insumo para el comité, no una decisión. */
export default function CoincidenciasOfertas({ procesoId }: { procesoId: string }) {
  const [c, setC] = useState<Coincidencias | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [notas, setNotas] = useState<Record<string, string>>({})

  useEffect(() => {
    verCoincidencias(procesoId)
      .then(setC)
      .catch((x: unknown) => setError(mensajeDe(x)))
  }, [procesoId])

  async function hacer(accion: () => Promise<Coincidencias>) {
    setOcupado(true)
    setError(null)
    try {
      setC(await accion())
    } catch (x) {
      setError(mensajeDe(x))
    } finally {
      setOcupado(false)
    }
  }

  if (!c) return error ? <div className="callout callout-bad">{error}</div> : null
  const lista = c.coincidencias ?? []
  return (
    <section className="card ops-tarjeta">
      <div className="card-head">
        <div>
          <h2>Coincidencias entre ofertas</h2>
          <p className="small muted">
            Documentos idénticos, mismas personas, empresas, profesionales, correos, teléfonos o direcciones en ofertas distintas. Es un insumo para prevenir
            prácticas colusorias: el comité revisa cada una y deja su conclusión.
          </p>
        </div>
        {c.puede_registrar && (
          <button type="button" className="btn btn-secondary btn-sm" disabled={ocupado} onClick={() => void hacer(() => calcularCoincidencias(procesoId))}>
            {ocupado ? <span className="spinner oscuro" /> : <Icono nombre="buscar" tam={15} />} {c.calculado ? 'Buscar de nuevo' : 'Buscar coincidencias'}
          </button>
        )}
      </div>
      {error && <div className="callout callout-bad">{error}</div>}
      {!c.calculado ? (
        <p className="small muted">Aún no se han buscado.</p>
      ) : (
        <>
          {(c.avisos ?? []).map((a) => (
            <p key={a} className="small ops-motivo">
              {a}
            </p>
          ))}
          {lista.length === 0 ? (
            <div className="callout callout-ok">
              <Icono nombre="check" />
              <div>No se encontraron coincidencias entre las {c.ofertas ?? ''} ofertas.</div>
            </div>
          ) : (
            <div className="tabla-wrap">
              <table className="tabla ops-tabla">
                <thead>
                  <tr>
                    <th>Coincidencia</th>
                    <th>Ofertas</th>
                    <th>Conclusión del comité</th>
                  </tr>
                </thead>
                <tbody>
                  {lista.map((x) => {
                    const revision = c.revisiones?.[x.clave]
                    return (
                      <tr key={x.clave}>
                        <td style={{ maxWidth: 320 }}>
                          <strong>{x.tipo_nombre}</strong>
                          <div className="small">{x.tipo === 'documento' ? x.detalle : x.valor}</div>
                          {x.tipo !== 'documento' && x.detalle && <div className="small muted">{x.detalle}</div>}
                        </td>
                        <td className="small">
                          {x.proponentes.map((p) => (
                            <div key={p}>{p}</div>
                          ))}
                        </td>
                        <td className="small" style={{ maxWidth: 320 }}>
                          {revision ? (
                            <>
                              {revision.nota}
                              <div className="muted">{revision.por}</div>
                            </>
                          ) : c.puede_registrar ? (
                            <div className="tramite-fila">
                              <input className="input" aria-label="Conclusión del comité" value={notas[x.clave] ?? ''} onChange={(e) => setNotas({ ...notas, [x.clave]: e.target.value })} />
                              <button type="button" className="btn btn-sm btn-secondary" disabled={ocupado || !(notas[x.clave] ?? '').trim()} onClick={() => void hacer(() => revisarCoincidencia(procesoId, x.clave, notas[x.clave]))}>
                                Guardar
                              </button>
                            </div>
                          ) : (
                            <span className="muted">Sin revisar</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          {(c.comunes ?? []).length > 0 && (
            <p className="small muted" style={{ marginTop: 8 }}>
              {(c.comunes ?? []).length} documentos aparecen en casi todas las ofertas (formatos en blanco del pliego): no se cuentan como coincidencia.
            </p>
          )}
        </>
      )}
    </section>
  )
}
