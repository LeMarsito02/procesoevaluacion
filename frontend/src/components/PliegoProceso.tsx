import { useState } from 'react'
import type { PliegoProceso as Pliego } from '../evaluaciones'
import { archivoPliego } from '../historico'
import { mensajeDe } from '../http'
import Icono from './Icono'

/** El pliego con el que se creó el proceso: qué se ajustó de la evaluación,
 * qué no y por qué, y lo que hay que tener presente al revisar. */
export default function PliegoProceso({ evaluacionId, pliego }: { evaluacionId: string; pliego: Pliego | null }) {
  const [abriendo, setAbriendo] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!pliego) {
    return (
      <section className="card" style={{ marginTop: 16 }}>
        <div className="callout callout-warn">
          <Icono nombre="alerta" />
          <div>Este proceso se creó sin analizar el pliego: la evaluación aplica la plantilla de la entidad sin ajustes.</div>
        </div>
      </section>
    )
  }

  async function abrir() {
    setAbriendo(true)
    setError(null)
    try {
      const { blob } = await archivoPliego(evaluacionId)
      window.open(URL.createObjectURL(blob), '_blank', 'noopener')
    } catch (e) {
      setError(mensajeDe(e, 'No se pudo abrir el pliego.'))
    } finally {
      setAbriendo(false)
    }
  }

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <div>
          <h2>Lo que exige el pliego</h2>
          <p>
            {pliego.nombre_archivo} · {pliego.paginas} páginas{pliego.documento_tipo && ` · documento tipo ${pliego.documento_tipo}`}
          </p>
        </div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={abrir} disabled={abriendo}>
          {abriendo ? <span className="spinner oscuro" /> : <Icono nombre="documento" tam={15} />} Abrir pliego
        </button>
      </div>
      {error && <div className="callout callout-bad" style={{ marginBottom: 12 }}>{error}</div>}
      {pliego.ajustes.length === 0 ? (
        <p className="small muted">El pliego no exigió ajustes a la evaluación de la entidad.</p>
      ) : (
        <div className="hallazgos">
          {pliego.ajustes.map((a) => (
            <div key={a.id} className="hallazgo" data-decision={a.decision}>
              <div className="hallazgo-cabeza">
                <span className="tag">{a.decision === 'aceptado' ? 'Aplicado' : 'No aplicado'}</span>
                <strong>{a.hallazgo.titulo}</strong>
              </div>
              {a.decision === 'rechazado' && <p className="small">Razón: {a.nota}</p>}
              <blockquote className="cita-pliego">
                «{a.hallazgo.cita}»
                <footer>
                  {a.hallazgo.seccion} · pág. {a.hallazgo.pagina} · decidió {a.por}
                </footer>
              </blockquote>
            </div>
          ))}
        </div>
      )}
      {pliego.obligaciones.length > 0 && (
        <details style={{ marginTop: 16 }}>
          <summary className="plegable">Otras obligaciones del pliego sin verificación automática ({pliego.obligaciones.length})</summary>
          <div className="hallazgos" style={{ marginTop: 10 }}>
            {pliego.obligaciones.map((h) => (
              <blockquote key={h.id} className="cita-pliego">
                «{h.cita}»
                <footer>
                  {h.seccion} · pág. {h.pagina}
                </footer>
              </blockquote>
            ))}
          </div>
        </details>
      )}
      {pliego.aclaraciones.length > 0 && (
        <>
          <h3 style={{ marginTop: 16, fontSize: 15 }}>Para tener en cuenta al revisar</h3>
          <ul className="lista-simple small">
            {pliego.aclaraciones.map((h) => (
              <li key={h.id}>
                <strong>{h.titulo}.</strong> {h.detalle} <span className="muted">(pág. {h.pagina})</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
