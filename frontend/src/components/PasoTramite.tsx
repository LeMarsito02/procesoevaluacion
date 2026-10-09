import { useCallback, useEffect, useState } from 'react'
import { formatFechaCorta } from '../format'
import { mensajeDe } from '../http'
import {
  crearObservacion,
  fijarTraslado,
  NOMBRE_DECISION,
  responderObservacion,
  urlMatriz,
  verTramite,
  type DecisionObservacion,
  type Observacion,
  type Tramite,
} from '../tramite'
import Icono from './Icono'

const hoy = () => new Date().toLocaleDateString('en-CA')
const TONO_DECISION: Record<DecisionObservacion, string> = { pendiente: 'revisar', acoge: 'cumple', acoge_parcial: 'cumple', no_acoge: 'no_aplica' }

/** Traslado del informe: el término y la matriz de observaciones (RF-16). */
export default function PasoTramite({ evaluacionId }: { evaluacionId: string }) {
  const [t, setT] = useState<Tramite | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)

  useEffect(() => {
    verTramite(evaluacionId)
      .then(setT)
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [evaluacionId])

  const hacer = useCallback(async (accion: () => Promise<Tramite>) => {
    setOcupado(true)
    setError(null)
    try {
      setT(await accion())
      return true
    } catch (e) {
      setError(mensajeDe(e))
      return false
    } finally {
      setOcupado(false)
    }
  }, [])

  if (!t) return <main className="page">{error ? <div className="callout callout-bad">{error}</div> : <div className="vacio"><span className="spinner oscuro" /></div>}</main>
  const editable = t.puede_registrar

  return (
    <main className="page tramite">
      <div className="page-head">
        <div>
          <div className="eyebrow">Traslado del informe</div>
          <h1>Observaciones al informe</h1>
          <p>El término del traslado y las observaciones al informe con su respuesta. Todo queda con quién y cuándo.</p>
        </div>
        <div className="page-head-acciones">
          <a className="btn btn-secondary" href={urlMatriz(evaluacionId)}>
            <Icono nombre="descargar" /> Matriz en Excel
          </a>
        </div>
      </div>
      {error && (
        <div className="callout callout-bad" role="alert" style={{ marginBottom: 16 }}>
          <Icono nombre="alerta" />
          <div>{error}</div>
        </div>
      )}
      <TrasladoCard t={t} editable={editable} ocupado={ocupado} onGuardar={(f, d) => hacer(() => fijarTraslado(evaluacionId, f, d))} />
      <Observaciones t={t} editable={editable} ocupado={ocupado} id={evaluacionId} hacer={hacer} />
    </main>
  )
}

function TrasladoCard({ t, editable, ocupado, onGuardar }: { t: Tramite; editable: boolean; ocupado: boolean; onGuardar: (f: string, d: number) => Promise<boolean> }) {
  const [fecha, setFecha] = useState(t.traslado?.publicado_en ?? hoy())
  const [dias, setDias] = useState(String(t.traslado?.dias_habiles ?? 3))
  const tr = t.traslado
  return (
    <section className="card ops-tarjeta">
      <div className="card-head">
        <div>
          <h2>Término del traslado</h2>
          <p className="small muted">Se cuenta en días hábiles desde el día siguiente a la publicación del informe, sin fines de semana ni festivos.</p>
        </div>
        {tr && (
          <span className="pill" data-estado={tr.vencido ? 'error' : 'revisar'}>
            {tr.vencido ? `Venció el ${formatFechaCorta(tr.vence_en)}` : `Vence el ${formatFechaCorta(tr.vence_en)} · faltan ${tr.dias_habiles_restantes} días hábiles`}
          </span>
        )}
      </div>
      {editable && (
        <div className="tramite-fila">
          <div className="field">
            <label htmlFor="tr-fecha">Publicación del informe</label>
            <input id="tr-fecha" className="input" type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="tr-dias">Días hábiles de traslado</label>
            <input id="tr-dias" className="input" type="number" min={1} max={30} value={dias} onChange={(e) => setDias(e.target.value)} />
          </div>
          <button type="button" className="btn btn-primary" disabled={ocupado || !fecha || !Number(dias)} onClick={() => void onGuardar(fecha, Number(dias))}>
            {tr ? 'Actualizar' : 'Registrar traslado'}
          </button>
        </div>
      )}
    </section>
  )
}

interface PropsSeccion {
  t: Tramite
  id: string
  editable: boolean
  ocupado: boolean
  hacer: (accion: () => Promise<Tramite>) => Promise<boolean>
}

function Observaciones({ t, id, editable, ocupado, hacer }: PropsSeccion) {
  const [nueva, setNueva] = useState(false)
  const [observante, setObservante] = useState('')
  const [recibida, setRecibida] = useState(hoy())
  const [texto, setTexto] = useState('')
  const [proponente, setProponente] = useState('')
  const [requisito, setRequisito] = useState('')
  const [abierta, setAbierta] = useState<string | null>(null)

  async function crear() {
    const ok = await hacer(() =>
      crearObservacion(id, { observante, recibida_en: recibida, texto, proponente_id: proponente || null, requisito: requisito ? Number(requisito) : null }),
    )
    if (ok) {
      setNueva(false)
      setObservante('')
      setTexto('')
      setRequisito('')
    }
  }

  return (
    <section className="card ops-tarjeta">
      <div className="card-head">
        <div>
          <h2>Matriz de observaciones ({t.resumen.observaciones})</h2>
          <p className="small muted">{t.resumen.sin_responder ? `${t.resumen.sin_responder} sin responder.` : 'Todas respondidas.'} Si se cambia una respuesta, la anterior queda en la auditoría.</p>
        </div>
        {editable && !nueva && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setNueva(true)}>
            <Icono nombre="mas" tam={15} /> Registrar observación
          </button>
        )}
      </div>
      {nueva && (
        <div className="ops-form ops-form-periodo" style={{ marginBottom: 14 }}>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="ob-quien">Quién la presenta</label>
              <input id="ob-quien" className="input" value={observante} onChange={(e) => setObservante(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="ob-fecha">Recibida el</label>
              <input id="ob-fecha" className="input" type="date" value={recibida} onChange={(e) => setRecibida(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="ob-prop">Sobre el proponente (opcional)</label>
              <select id="ob-prop" className="input" value={proponente} onChange={(e) => setProponente(e.target.value)}>
                <option value="">General</option>
                {t.proponentes.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.hoja} · {p.nombre}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="ob-req">Requisito (opcional)</label>
              <input id="ob-req" className="input" inputMode="numeric" value={requisito} onChange={(e) => setRequisito(e.target.value.replace(/\D/g, ''))} />
            </div>
          </div>
          <div className="field" style={{ marginTop: 12 }}>
            <label htmlFor="ob-texto">Observación</label>
            <textarea id="ob-texto" className="input" rows={3} value={texto} onChange={(e) => setTexto(e.target.value)} />
          </div>
          <div className="dialogo-pie">
            <button type="button" className="btn btn-ghost" onClick={() => setNueva(false)}>
              Cancelar
            </button>
            <button type="button" className="btn btn-primary" disabled={ocupado || !observante.trim() || !texto.trim()} onClick={() => void crear()}>
              Registrar
            </button>
          </div>
        </div>
      )}
      {t.observaciones.length === 0 ? (
        <div className="vacio">No hay observaciones al informe.</div>
      ) : (
        <div className="tabla-wrap">
          <table className="tabla ops-tabla">
            <thead>
              <tr>
                <th>N.º</th>
                <th>Observación</th>
                <th>Respuesta</th>
                <th>Decisión</th>
                {editable && <th aria-label="Acciones" />}
              </tr>
            </thead>
            <tbody>
              {t.observaciones.map((o) =>
                abierta === o.id ? (
                  <tr key={o.id}>
                    <td colSpan={editable ? 5 : 4}>
                      <RespuestaObservacion o={o} ocupado={ocupado} onCancelar={() => setAbierta(null)} onGuardar={async (d) => (await hacer(() => responderObservacion(id, o.id, d))) && setAbierta(null)} />
                    </td>
                  </tr>
                ) : (
                  <tr key={o.id}>
                    <td className="num">{o.consecutivo}</td>
                    <td style={{ maxWidth: 380 }}>
                      <strong>{o.observante}</strong>
                      <span className="small muted">
                        {' '}
                        · {formatFechaCorta(o.recibida_en)}
                        {o.proponente && ` · sobre ${o.proponente}`}
                        {o.requisito && ` · requisito ${o.requisito}`}
                      </span>
                      {o.extemporanea && <div className="small ops-motivo">Presentada después del traslado</div>}
                      <div className="small">{o.texto}</div>
                    </td>
                    <td className="small" style={{ maxWidth: 360 }}>
                      {o.respuesta || <span className="muted">Sin responder</span>}
                      {o.respondida_por && (
                        <div className="muted">
                          {o.respondida_por} · {formatFechaCorta((o.respondida_en ?? '').slice(0, 10))}
                        </div>
                      )}
                    </td>
                    <td>
                      <span className="pill" data-estado={TONO_DECISION[o.decision]}>
                        {NOMBRE_DECISION[o.decision]}
                      </span>
                      {o.modifica_resultado && <div className="small ops-motivo">Cambia el resultado</div>}
                    </td>
                    {editable && (
                      <td>
                        <button type="button" className="enlace small" onClick={() => setAbierta(o.id)}>
                          {o.respuesta ? 'Cambiar respuesta' : 'Responder'}
                        </button>
                      </td>
                    )}
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function RespuestaObservacion({
  o,
  ocupado,
  onCancelar,
  onGuardar,
}: {
  o: Observacion
  ocupado: boolean
  onCancelar: () => void
  onGuardar: (d: { respuesta: string; decision: DecisionObservacion; modifica_resultado: boolean }) => void
}) {
  const [respuesta, setRespuesta] = useState(o.respuesta)
  const [decision, setDecision] = useState<DecisionObservacion>(o.decision === 'pendiente' ? 'no_acoge' : o.decision)
  const [modifica, setModifica] = useState(o.modifica_resultado)
  return (
    <div className="ops-form ops-form-periodo">
      <p className="small">
        <strong>{o.observante}:</strong> {o.texto}
      </p>
      <div className="field" style={{ marginTop: 8 }}>
        <label htmlFor="ro-resp">Respuesta de la entidad</label>
        <textarea id="ro-resp" className="input" rows={3} value={respuesta} onChange={(e) => setRespuesta(e.target.value)} />
      </div>
      <div className="tramite-fila" style={{ marginTop: 12 }}>
        <div className="field">
          <label htmlFor="ro-dec">Decisión</label>
          <select id="ro-dec" className="input" value={decision} onChange={(e) => setDecision(e.target.value as DecisionObservacion)}>
            <option value="acoge">Se acoge</option>
            <option value="acoge_parcial">Se acoge parcialmente</option>
            <option value="no_acoge">No se acoge</option>
          </select>
        </div>
        <label className="ops-check">
          <input type="checkbox" checked={modifica} onChange={(e) => setModifica(e.target.checked)} /> Cambia el resultado de la evaluación
        </label>
      </div>
      <div className="dialogo-pie">
        <button type="button" className="btn btn-ghost" onClick={onCancelar}>
          Cancelar
        </button>
        <button type="button" className="btn btn-primary" disabled={ocupado || !respuesta.trim()} onClick={() => onGuardar({ respuesta, decision, modifica_resultado: modifica })}>
          Guardar respuesta
        </button>
      </div>
    </div>
  )
}
