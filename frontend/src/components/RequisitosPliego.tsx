import { useEffect, useState } from 'react'
import { asumirRequisitosPliego, requisitosPliego, type RequisitoPliego } from '../evaluaciones'
import { mensajeDe } from '../http'
import Icono from './Icono'

/** Lo que el pliego exige y el programa no sabe verificar. Cada uno frena la
 * aprobación automática de TODOS los proponentes, y eso es a propósito: nada
 * que no se haya mirado se da por cumplido. Pero mirarlo una vez basta —el
 * pliego es el mismo para todos—, así que aquí se revisan de una sola vez
 * para el proceso completo y queda registrado quién lo hizo. */
export default function RequisitosPliego({ evaluacionId, soloLectura }: { evaluacionId: string; soloLectura: boolean }) {
  const [datos, setDatos] = useState<RequisitoPliego[] | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)
  const [marcados, setMarcados] = useState<Record<string, boolean>>({})

  function cargar() {
    requisitosPliego(evaluacionId)
      .then(setDatos)
      .catch((e) => setError(mensajeDe(e, 'No se pudieron leer los requisitos del pliego.')))
  }
  useEffect(cargar, [evaluacionId])

  if (datos === undefined && !error) return null
  if (datos && datos.length === 0) return null
  const pendientes = (datos ?? []).filter((r) => !r.asumido)
  const elegidos = pendientes.filter((r) => marcados[r.clave])

  async function asumir() {
    setGuardando(true)
    setAviso(null)
    try {
      const r = await asumirRequisitosPliego(evaluacionId, elegidos.map((e) => e.clave))
      setAviso(
        `Se marcaron ${r.asumidos} requisito(s) como revisados por ti.` +
          (r.reevaluados ? ` Se volverán a evaluar ${r.reevaluados} proponente(s).` : ''),
      )
      setMarcados({})
      cargar()
    } catch (e) {
      setError(mensajeDe(e, 'No se pudieron marcar los requisitos.'))
    } finally {
      setGuardando(false)
    }
  }

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <div>
          <h2>Requisitos del pliego que el programa no verifica</h2>
          <p>
            Estos salen del pliego de este proceso y el programa no sabe comprobarlos, así que no los da por
            cumplidos: mientras estén pendientes, ningún lote se aprueba solo. Revísalos una vez —el pliego es el
            mismo para todos los proponentes— y márcalos aquí.
          </p>
        </div>
      </div>
      {error && <div className="callout callout-bad" style={{ marginBottom: 12 }}>{error}</div>}
      {aviso && <div className="callout callout-ok" style={{ marginBottom: 12 }}>{aviso}</div>}
      {pendientes.length > 0 && (
        <div className="callout callout-warn" style={{ marginBottom: 12 }}>
          <Icono nombre="alerta" />
          <div>
            {pendientes.length} requisito(s) sin revisar. Marcar uno no lo aprueba: dice que lo miraste tú, y por eso
            queda registrado a tu nombre.
          </div>
        </div>
      )}
      <div className="tabla-wrap">
        <table className="tabla">
          <thead>
            <tr>
              {!soloLectura && <th style={{ width: 36 }} />}
              <th>Requisito</th>
              <th>Lo que dice el pliego</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {(datos ?? []).map((r) => (
              <tr key={r.clave}>
                {!soloLectura && (
                  <td>
                    {r.asumido ? (
                      <span className="small muted">—</span>
                    ) : (
                      <input
                        type="checkbox"
                        checked={marcados[r.clave] ?? false}
                        onChange={(e) => setMarcados({ ...marcados, [r.clave]: e.target.checked })}
                        aria-label={`Marcar como revisado: ${r.requisito}`}
                      />
                    )}
                  </td>
                )}
                <td>{r.requisito}</td>
                <td className="small muted">{r.cita ? `«${r.cita}»` : '—'}</td>
                <td className="small">{r.asumido ? 'revisado por una persona' : 'sin revisar'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!soloLectura && pendientes.length > 0 && (
        <div className="acciones" style={{ marginTop: 12 }}>
          <button type="button" className="btn btn-primary btn-sm" disabled={guardando || elegidos.length === 0} onClick={asumir}>
            {guardando ? 'Guardando…' : `Marcar ${elegidos.length || ''} como revisados por mí`.replace('  ', ' ')}
          </button>
          <p className="small muted" style={{ margin: 0 }}>
            Al marcarlos, los proponentes ya evaluados vuelven a la fila para que el cambio cuente.
          </p>
        </div>
      )}
    </section>
  )
}
