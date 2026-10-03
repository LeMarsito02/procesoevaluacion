import { useEffect, useState } from 'react'
import {
  generarActaRevisionCruzada,
  urlActaRevisionCruzada,
  verActasRevisionCruzada,
  type ActasRevisionCruzada,
} from '../evaluaciones'
import { mensajeDe } from '../http'
import Icono from './Icono'

/** Acta de la revisión cruzada de las evaluaciones jurídica, técnica y
 * financiera antes de adjudicar. La genera el jefe de una dependencia del
 * proceso o el administrador; la firman los integrantes de los comités. */
export default function RevisionCruzada({ procesoId }: { procesoId: string }) {
  const [datos, setDatos] = useState<ActasRevisionCruzada | null>(null)
  const [generando, setGenerando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    verActasRevisionCruzada(procesoId)
      .then(setDatos)
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [procesoId])

  async function generar() {
    setGenerando(true)
    setError(null)
    try {
      setDatos(await generarActaRevisionCruzada(procesoId))
    } catch (e) {
      setError(mensajeDe(e))
    } finally {
      setGenerando(false)
    }
  }

  const ultima = datos?.actas[0]
  return (
    <section className="card revision-cruzada" style={{ marginTop: 16 }}>
      <div className="card-head">
        <div>
          <h2>Revisión cruzada de los comités</h2>
          <p>
            Antes de adjudicar, los comités jurídico, técnico y financiero revisan juntos las tres evaluaciones. El acta
            trae el estado de cada evaluación, el resultado consolidado por lote con el orden de elegibilidad entre los
            habilitados, los puntos de control (fórmulas del pliego, orden frente a la resolución, inhabilidades
            sobrevinientes) y las firmas de todos los integrantes.
          </p>
        </div>
        <Icono nombre="usuarios" tam={22} />
      </div>
      {error && (
        <div className="callout callout-bad" role="alert">
          {error}
        </div>
      )}
      {!datos ? (
        <span className="spinner oscuro" role="status" aria-label="Cargando actas" />
      ) : (
        <>
          {ultima && (!ultima.todas_aprobadas || ultima.pendientes > 0) && (
            <div className="callout callout-warn" role="status" style={{ marginBottom: 12 }}>
              <Icono nombre="alerta" />
              <div>
                La última acta se generó con evaluaciones sin aprobar o requisitos pendientes: su resultado es preliminar.
                Genérela de nuevo cuando las tres estén aprobadas.
              </div>
            </div>
          )}
          {datos.actas.length > 0 ? (
            <div className="tabla-wrap">
              <table className="tabla">
                <thead>
                  <tr>
                    <th scope="col">Consecutivo</th>
                    <th scope="col">Versión</th>
                    <th scope="col">Generó</th>
                    <th scope="col">Estado al generarla</th>
                    <th scope="col">Documento</th>
                  </tr>
                </thead>
                <tbody>
                  {datos.actas.map((a) => (
                    <tr key={a.id}>
                      <td>
                        <strong>{a.consecutivo}</strong>
                        <div className="small muted">{new Date(a.generada_en).toLocaleString('es-CO')}</div>
                      </td>
                      <td>v{a.version}</td>
                      <td className="small">{a.generada_por}</td>
                      <td>
                        {a.todas_aprobadas && a.pendientes === 0 ? (
                          <span className="pill pill-xs" data-estado="cumple">Evaluaciones aprobadas</span>
                        ) : (
                          <span className="pill pill-xs" data-estado="revisar">Preliminar</span>
                        )}
                      </td>
                      <td>
                        <a className="btn btn-ghost btn-sm" href={urlActaRevisionCruzada(procesoId, a.id)} title={`Huella SHA-256: ${a.sha256}`}>
                          <Icono nombre="descargar" tam={15} /> Word
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="small muted">Todavía no se ha generado el acta de este proceso.</p>
          )}
          {datos.puede_generar ? (
            <div className="acciones" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" type="button" disabled={generando} onClick={generar}>
                {generando ? <span className="spinner" /> : <Icono nombre="documento" tam={16} />}
                {datos.actas.length ? 'Generar nueva versión del acta' : 'Generar acta de revisión cruzada'}
              </button>
            </div>
          ) : (
            <p className="small muted" style={{ marginTop: 8 }}>
              La genera el jefe de una de las dependencias del proceso o el administrador.
            </p>
          )}
        </>
      )}
    </section>
  )
}
