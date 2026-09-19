import { Fragment, useState } from 'react'
import type { AnalisisPliego, DecisionPliego, HallazgoPliego, LecturaIA, RequisitoDelPliego } from '../api'
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
  requisito_no_exigido: 'Su plantilla lo evalúa, el pliego no lo pide',
}

// Cómo se verifica cada requisito del pliego (chip de la tabla).
const ESTADO_REQUISITO: Record<RequisitoDelPliego['estado'], { texto: string; pill: string }> = {
  motor: { texto: 'Automático', pill: 'cumple' },
  motor_nuevo: { texto: 'Automático al aplicarlo', pill: 'cumple' },
  documento: { texto: 'Se busca el documento', pill: 'revisar' },
  revision: { texto: 'Revisión de una persona', pill: 'error' },
  extranjeros: { texto: 'Solo extranjeros', pill: 'no_aplica' },
}

const PARA_QUIEN: Record<string, string> = {
  persona_natural: 'persona natural',
  persona_juridica: 'persona jurídica',
  plural: 'consorcio o unión temporal',
  extranjero: 'extranjero',
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
  const ia = p.pliego?.lectura_ia
  const iaLeyendo = !!ia && (ia.estado === 'pendiente' || ia.estado === 'leyendo')
  // Mientras la IA lee pueden aparecer requisitos nuevos: se espera a que termine.
  const puedeCrear = p.pliego ? !iaLeyendo && listos === porDecidir.length : p.sinPliegoConfirmado

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

          {ia && <AvisoLectura ia={ia} />}

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

          {p.pliego.requisitos.length > 0 && <TablaRequisitos requisitos={p.pliego.requisitos} />}

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
      {iaLeyendo && (
        <p className="small muted" style={{ textAlign: 'right', marginTop: 6 }}>
          Podrá crear el proceso cuando termine la lectura del pliego.
        </p>
      )}
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
          <Icono nombre="check" tam={14} /> {h.tipo === 'requisito_no_exigido' ? 'No evaluarlo en este proceso' : 'Aplicar en este proceso'}
        </button>
        <button
          type="button"
          className={`btn btn-sm ${decision?.decision === 'rechazado' ? 'btn-bad' : 'btn-ghost'}`}
          aria-pressed={decision?.decision === 'rechazado'}
          onClick={() => onDecidir({ decision: 'rechazado', nota: decision?.nota ?? '' })}
        >
          {h.tipo === 'requisito_no_exigido' ? 'Mantenerlo' : 'No aplicar'}
        </button>
      </div>
      {decision?.decision === 'rechazado' && (
        <div className="field" style={{ marginTop: 8 }}>
          <label htmlFor={`nota-${h.id}`}>
            {h.tipo === 'requisito_no_exigido' ? '¿Por qué se mantiene si el pliego no lo pide?' : '¿Por qué no se aplica?'} (queda en el reporte)
          </label>
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

/** Avance de la lectura completa del pliego con la IA local. */
function AvisoLectura({ ia }: { ia: LecturaIA }) {
  if (ia.estado === 'pendiente' || ia.estado === 'leyendo') {
    return (
      <div className="callout callout-info" style={{ marginTop: 16 }} aria-live="polite">
        <span className="spinner oscuro" />
        <div style={{ flex: 1 }}>
          <strong>La IA está leyendo el pliego completo</strong> para sacar cada requisito jurídico que exige, aunque no
          esté en su plantilla. {ia.estado === 'pendiente' ? 'En cola…' : `${ia.progreso} %`}
          <div className="barra" style={{ marginTop: 8 }}>
            <div style={{ width: `${Math.max(ia.progreso, 3)}%` }} data-animada="true" />
          </div>
          <span className="small muted">Puede revisar lo de abajo mientras tanto; al terminar se agregan los hallazgos nuevos.</span>
        </div>
      </div>
    )
  }
  if (ia.estado === 'listo') {
    return (
      <div className="callout callout-ok" style={{ marginTop: 16 }}>
        <Icono nombre="check" />
        <div>
          La IA leyó el pliego completo: encontró <strong>{ia.requisitos}</strong> requisitos jurídicos. Todos están abajo,
          con la cita y la página del pliego.
        </div>
      </div>
    )
  }
  return (
    <div className="callout callout-warn" role="alert" style={{ marginTop: 16 }}>
      <Icono nombre="alerta" />
      <div>
        <strong>No se pudo hacer la lectura profunda con IA</strong>
        {ia.estado === 'no_disponible' ? ' (el servicio de IA no está disponible)' : ia.error ? ` (${ia.error})` : ''}. Se
        compararon las reglas conocidas del pliego con su plantilla; lea el pliego por si exige algo más.
      </div>
    </div>
  )
}

/** Cada requisito jurídico que exige el pliego y cómo se verificará. */
function TablaRequisitos({ requisitos }: { requisitos: RequisitoDelPliego[] }) {
  const [ver, setVer] = useState(true)
  const [abierto, setAbierto] = useState<string | null>(null)
  const cuenta = (e: RequisitoDelPliego['estado']) => requisitos.filter((r) => r.estado === e).length
  const automaticos = cuenta('motor') + cuenta('motor_nuevo')
  return (
    <section className="card" style={{ marginTop: 16 }}>
      <button type="button" className="plegable" onClick={() => setVer((v) => !v)} aria-expanded={ver}>
        <Icono nombre={ver ? 'menos' : 'mas'} tam={15} /> Requisitos jurídicos que exige el pliego ({requisitos.length})
      </button>
      {ver && (
        <>
          <p className="small muted" style={{ marginTop: 8 }}>
            {automaticos} automáticos · {cuenta('documento')} con búsqueda del documento · {cuenta('revision')} para revisión
            {cuenta('extranjeros') > 0 && <> · {cuenta('extranjeros')} solo para extranjeros</>}. Haga clic en uno para ver la
            cita del pliego.
          </p>
          <div className="tabla-wrap" style={{ marginTop: 8 }}>
            <table className="tabla">
              <thead>
                <tr>
                  <th>Requisito</th>
                  <th>Documento</th>
                  <th>Vigencia</th>
                  <th>Pág.</th>
                  <th>Cómo se verifica</th>
                </tr>
              </thead>
              <tbody>
                {requisitos.map((r) => {
                  const estado = ESTADO_REQUISITO[r.estado]
                  const vigencia = r.vigencia_dias
                    ? `${r.vigencia_dias} días`
                    : r.vigencia_meses
                      ? `${r.vigencia_meses} ${r.vigencia_meses === 1 ? 'mes' : 'meses'}`
                      : '—'
                  const abiertoEste = abierto === r.id
                  return (
                    <Fragment key={r.id}>
                      <tr onClick={() => setAbierto(abiertoEste ? null : r.id)} style={{ cursor: 'pointer' }} aria-expanded={abiertoEste}>
                        <td>
                          {r.requisito}
                          {r.aplica_a.length > 0 && (
                            <div className="small muted">Aplica a: {r.aplica_a.map((a) => PARA_QUIEN[a] ?? a).join(', ')}</div>
                          )}
                        </td>
                        <td className="small">
                          {r.documento ?? '—'}
                          {r.expide && <div className="muted">Expide: {r.expide}</div>}
                        </td>
                        <td className="small">{vigencia}</td>
                        <td className="num">{r.pagina}</td>
                        <td className="small">
                          <span className="pill" data-estado={estado.pill} title={r.como}>
                            <span className="dot" /> {estado.texto}
                          </span>
                        </td>
                      </tr>
                      {abiertoEste && (
                        <tr>
                          <td colSpan={5}>
                            <p className="small">{r.como}.</p>
                            {r.condiciones.length > 0 && (
                              <ul className="lista-simple small">
                                {r.condiciones.map((c) => (
                                  <li key={c}>{c}</li>
                                ))}
                              </ul>
                            )}
                            <blockquote className="cita-pliego">
                              «{r.cita}»
                              <footer>
                                {r.seccion} · pág. {r.pagina}
                              </footer>
                            </blockquote>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
