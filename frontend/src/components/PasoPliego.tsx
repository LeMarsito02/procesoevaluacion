import { useState } from 'react'
import type { AnalisisPliego, DecisionPliego, HallazgoPliego } from '../api'
import Icono from './Icono'

interface Props {
  pliego: AnalisisPliego | null
  cargando: boolean
  error: string | null
  decisiones: Record<string, DecisionPliego>
  onDecidir: (id: string, decision: DecisionPliego) => void
  onReintentar: () => void
  /** Sin análisis: la persona confirma que se evalúa solo con la plantilla. */
  sinPliegoConfirmado: boolean
  onConfirmarSinPliego: (v: boolean) => void
  ocupado: boolean
  textoAccion: string
  onVolver: () => void
  onCrear: () => void
}

const ETIQUETA: Record<string, string> = {
  ajuste_parametro: 'Cambia un valor',
  requisito_nuevo: 'Requisito que su plantilla no evalúa',
}

/** Qué exige el pliego frente a la forma de evaluar de la entidad. Nada se
 * aplica sin que alguien lo decida; cada decisión va al reporte. */
export default function PasoPliego(p: Props) {
  const [verCobertura, setVerCobertura] = useState(false)
  const [verFuera, setVerFuera] = useState(false)
  const [verObligaciones, setVerObligaciones] = useState(false)

  const hallazgos = p.pliego?.hallazgos ?? []
  const porDecidir = hallazgos.filter((h) => h.requiere_decision)
  const sinEstructura = hallazgos.find((h) => h.id === 'estructura_no_reconocida')
  const aTener = hallazgos.filter((h) => (h.tipo === 'aclaracion' || h.tipo === 'informativo') && h !== sinEstructura)
  const obligaciones = hallazgos.filter((h) => h.tipo === 'obligacion')
  const fuera = hallazgos.filter((h) => h.tipo === 'fuera_de_alcance')
  const listos = porDecidir.filter((h) => decisionCompleta(p.decisiones[h.id])).length
  const puedeCrear = p.pliego ? listos === porDecidir.length : p.sinPliegoConfirmado

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Pliego del proceso</div>
          <h1>Lo que exige el pliego</h1>
          <p>
            El pliego puede cambiar o agregar requisitos frente a la forma de evaluar de su entidad. Se leyó completo y se
            comparó con su plantilla: decida qué se aplica a este proceso. Cada decisión queda en el reporte con la cita del
            pliego y quién la tomó.
          </p>
        </div>
      </div>

      {p.cargando && (
        <div className="callout callout-info">
          <span className="spinner oscuro" />
          <div>Leyendo el pliego completo y comparándolo con su plantilla…</div>
        </div>
      )}

      {!p.cargando && !p.pliego && (
        <div className="callout callout-warn" role="alert">
          <Icono nombre="alerta" />
          <div style={{ flex: 1 }}>
            <strong>No se pudo analizar el pliego.</strong> {p.error}
            <label className="check-linea" style={{ marginTop: 10 }}>
              <input type="checkbox" checked={p.sinPliegoConfirmado} onChange={(e) => p.onConfirmarSinPliego(e.target.checked)} />
              Entiendo que la evaluación usará solo la plantilla de la entidad, sin ajustes del pliego.
            </label>
          </div>
          <button type="button" className="btn btn-secondary btn-sm" onClick={p.onReintentar}>
            Reintentar
          </button>
        </div>
      )}

      {p.pliego && (
        <>
          <div className="pliego-resumen">
            <Icono nombre="documento" tam={18} />
            <span>
              <strong>{p.pliego.nombre_archivo}</strong> · {p.pliego.paginas} páginas leídas
              {p.pliego.documento_tipo && <> · documento tipo {p.pliego.documento_tipo}</>}
            </span>
            {p.pliego.reutilizado && <span className="tag">Ya se había analizado: se reutilizó</span>}
          </div>

          {sinEstructura && (
            <div className="callout callout-bad" role="alert" style={{ marginTop: 16 }}>
              <Icono nombre="alerta" />
              <div>
                <strong>{sinEstructura.titulo}.</strong> {sinEstructura.detalle}
              </div>
            </div>
          )}

          <section className="card" style={{ marginTop: 16 }}>
            <div className="card-head">
              <div>
                <h2>Cambian la evaluación</h2>
                <p>{porDecidir.length ? `${listos} de ${porDecidir.length} decididos` : 'Nada que decidir'}</p>
              </div>
            </div>
            {porDecidir.length === 0 ? (
              <div className="callout callout-ok">
                <Icono nombre="check" />
                <div>El pliego no cambia la forma de evaluar de su entidad.</div>
              </div>
            ) : (
              <div className="hallazgos">
                {porDecidir.map((h) => (
                  <HallazgoDecidible key={h.id} h={h} decision={p.decisiones[h.id]} onDecidir={(d) => p.onDecidir(h.id, d)} />
                ))}
              </div>
            )}
          </section>

          {aTener.length > 0 && (
            <section className="card" style={{ marginTop: 16 }}>
              <div className="card-head">
                <div>
                  <h2>Para tener en cuenta al revisar</h2>
                  <p>No cambian la evaluación, pero el pliego lo dice y conviene tenerlo presente.</p>
                </div>
              </div>
              <div className="hallazgos">
                {aTener.map((h) => (
                  <div key={h.id} className="hallazgo">
                    <strong>{h.titulo}</strong>
                    <p className="small">{h.detalle}</p>
                    <Cita h={h} />
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="card" style={{ marginTop: 16 }}>
            <button type="button" className="plegable" onClick={() => setVerCobertura((v) => !v)} aria-expanded={verCobertura}>
              <Icono nombre={verCobertura ? 'menos' : 'mas'} tam={15} /> Secciones jurídicas del pliego y qué las verifica (
              {p.pliego.secciones.length})
            </button>
            {verCobertura && (
              <div className="tabla-wrap" style={{ marginTop: 12 }}>
              <table className="tabla">
                <thead>
                  <tr>
                    <th>Sección</th>
                    <th>Pág.</th>
                    <th>Lo verifica</th>
                  </tr>
                </thead>
                <tbody>
                  {p.pliego.secciones.map((s) => (
                    <tr key={`${s.numero}-${s.pagina}`}>
                      <td>
                        {s.numero} {s.titulo}
                      </td>
                      <td className="num">{s.pagina}</td>
                      <td className="small">
                        {s.verificaciones.length ? (
                          s.verificaciones.join(' · ')
                        ) : (
                          <span className="pill" data-estado="revisar">
                            <span className="dot" /> Sin verificación automática
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </section>

          {obligaciones.length > 0 && (
            <section className="card" style={{ marginTop: 16 }}>
              <button type="button" className="plegable" onClick={() => setVerObligaciones((v) => !v)} aria-expanded={verObligaciones}>
                <Icono nombre={verObligaciones ? 'menos' : 'mas'} tam={15} /> Otras obligaciones del pliego sin verificación automática (
                {obligaciones.length})
              </button>
              {verObligaciones && (
                <>
                  <p className="small muted" style={{ marginTop: 8 }}>
                    Oraciones que obligan al proponente y que ninguna verificación del programa cubre. Léalas: si alguna
                    exige algo que deba revisarse en este proceso, téngalo en cuenta al evaluar.
                  </p>
                  <div className="hallazgos">
                    {obligaciones.map((h) => (
                      <Cita key={h.id} h={h} />
                    ))}
                  </div>
                </>
              )}
            </section>
          )}

          {fuera.length > 0 && (
            <section className="card" style={{ marginTop: 16 }}>
              <button type="button" className="plegable" onClick={() => setVerFuera((v) => !v)} aria-expanded={verFuera}>
                <Icono nombre={verFuera ? 'menos' : 'mas'} tam={15} /> Leído, fuera de la evaluación jurídica ({fuera.length})
              </button>
              {verFuera && (
                <ul className="lista-simple small">
                  {fuera.map((h) => (
                    <li key={h.id}>
                      <strong>{h.titulo}</strong> — {h.detalle} <span className="muted">(pág. {h.pagina})</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </>
      )}

      <div className="acciones-pie">
        <button className="btn btn-ghost" type="button" onClick={p.onVolver}>
          <Icono nombre="atras" /> Volver a los datos
        </button>
        <button className="btn btn-primary btn-lg" type="button" onClick={p.onCrear} disabled={!puedeCrear || p.ocupado || p.cargando}>
          {p.ocupado && <span className="spinner" />}
          {p.textoAccion} <Icono nombre="flecha" />
        </button>
      </div>
    </main>
  )
}

function decisionCompleta(d: DecisionPliego | undefined): boolean {
  return !!d && (d.decision === 'aceptado' || d.nota.trim().length >= 5)
}

function Cita({ h }: { h: HallazgoPliego }) {
  return (
    <blockquote className="cita-pliego">
      «{h.cita}»
      <footer>
        {h.seccion} · pág. {h.pagina}
      </footer>
    </blockquote>
  )
}

function HallazgoDecidible({
  h,
  decision,
  onDecidir,
}: {
  h: HallazgoPliego
  decision: DecisionPliego | undefined
  onDecidir: (d: DecisionPliego) => void
}) {
  const valor = (v: HallazgoPliego['valor_plantilla']) => (Array.isArray(v) ? v.join(', ') : String(v ?? '—'))
  return (
    <div className="hallazgo" data-decision={decision?.decision ?? 'pendiente'}>
      <div className="hallazgo-cabeza">
        <span className="tag">{ETIQUETA[h.tipo] ?? h.tipo}</span>
        <strong>{h.titulo}</strong>
      </div>
      <p className="small">{h.detalle}</p>
      {h.tipo === 'ajuste_parametro' && (
        <p className="small">
          Su plantilla: <strong>{valor(h.valor_plantilla)}</strong> → según el pliego: <strong>{h.valor_pliego_texto ?? valor(h.valor_pliego)}</strong>
        </p>
      )}
      <Cita h={h} />
      <div className="decision-botones">
        <button
          type="button"
          className={`btn btn-sm ${decision?.decision === 'aceptado' ? 'btn-primary' : 'btn-secondary'}`}
          aria-pressed={decision?.decision === 'aceptado'}
          onClick={() => onDecidir({ decision: 'aceptado', nota: '' })}
        >
          <Icono nombre="check" tam={14} /> Aplicar en este proceso
        </button>
        <button
          type="button"
          className={`btn btn-sm ${decision?.decision === 'rechazado' ? 'btn-bad' : 'btn-ghost'}`}
          aria-pressed={decision?.decision === 'rechazado'}
          onClick={() => onDecidir({ decision: 'rechazado', nota: decision?.nota ?? '' })}
        >
          No aplicar
        </button>
      </div>
      {decision?.decision === 'rechazado' && (
        <div className="field" style={{ marginTop: 8 }}>
          <label htmlFor={`nota-${h.id}`}>¿Por qué no se aplica? (queda en el reporte)</label>
          <textarea
            id={`nota-${h.id}`}
            className="input"
            rows={2}
            value={decision.nota}
            onChange={(e) => onDecidir({ decision: 'rechazado', nota: e.target.value })}
          />
          {decision.nota.trim().length < 5 && <span className="hint">Escriba al menos una frase.</span>}
        </div>
      )}
    </div>
  )
}
