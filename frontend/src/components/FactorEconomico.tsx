import { useCallback, useEffect, useState } from 'react'
import { formatPesos } from '../format'
import { mensajeDe } from '../http'
import {
  calificarFactor,
  decidirOferta,
  guardarParametros,
  registrarOferta,
  verEconomica,
  type Economica,
  type Factor,
  type OfertaEconomica,
} from '../economica'
import Icono from './Icono'

const pesos = (v: string | number | null | undefined) => (v == null || v === '' ? '—' : formatPesos(Number(v)))

/** Factor económico de cada lote: ofertas, verificación aritmética, alerta de precios
 * artificialmente bajos y calificación según la TRM (RF-11 y RF-13). */
export default function FactorEconomico({ procesoId }: { procesoId: string }) {
  const [e, setE] = useState<Economica | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)

  useEffect(() => {
    verEconomica(procesoId)
      .then(setE)
      .catch((x: unknown) => setError(mensajeDe(x)))
  }, [procesoId])

  const hacer = useCallback(async (accion: () => Promise<Economica>) => {
    setOcupado(true)
    setError(null)
    try {
      setE(await accion())
      return true
    } catch (x) {
      setError(mensajeDe(x))
      return false
    } finally {
      setOcupado(false)
    }
  }, [])

  if (!e) return error ? <div className="callout callout-bad">{error}</div> : null
  return (
    <section className="card ops-tarjeta">
      <div className="card-head">
        <div>
          <h2>Factor económico</h2>
          <p className="small muted">
            Se califica el valor total corregido de las ofertas válidas con el método que escoge la TRM, según el pliego. Nada se califica mientras quede algo
            sin confirmar.
          </p>
        </div>
      </div>
      {error && (
        <div className="callout callout-bad" role="alert" style={{ marginBottom: 12 }}>
          <Icono nombre="alerta" />
          <div>{error}</div>
        </div>
      )}
      {e.factores.map((f) => (
        <Lote key={f.id} f={f} e={e} procesoId={procesoId} ocupado={ocupado} hacer={hacer} />
      ))}
    </section>
  )
}

function Lote({ f, e, procesoId, ocupado, hacer }: { f: Factor; e: Economica; procesoId: string; ocupado: boolean; hacer: (a: () => Promise<Economica>) => Promise<boolean> }) {
  const editable = e.puede_registrar
  const [puntaje, setPuntaje] = useState(f.puntaje_maximo ?? '')
  const [presupuesto, setPresupuesto] = useState(f.presupuesto_oficial ?? '')
  const [costo, setCosto] = useState(f.costo_estimado ?? '')
  const [tabla, setTabla] = useState(f.tabla_metodos)
  const [trm, setTrm] = useState(f.trm ?? '')
  const [fechaTrm, setFechaTrm] = useState(f.fecha_trm ?? '')
  const [proponente, setProponente] = useState(e.proponentes[0]?.id ?? '')
  const [valor, setValor] = useState('')
  const [archivo, setArchivo] = useState<File | null>(null)

  const guardar = () =>
    hacer(() =>
      guardarParametros(procesoId, f.id, {
        puntaje_maximo: puntaje || null,
        presupuesto_oficial: presupuesto || null,
        costo_estimado: costo || null,
        tabla_metodos: tabla,
        trm: trm || null,
        fecha_trm: fechaTrm || null,
      }),
    )

  return (
    <div className="economica-lote">
      <h3 className="ops-seccion">{f.lote === 'Único' ? 'Oferta económica' : f.lote}</h3>
      {editable && (
        <div className="economica-parametros">
          <Campo id={`pm-${f.id}`} etiqueta="Puntaje máximo" valor={puntaje} onCambio={setPuntaje} />
          <Campo id={`po-${f.id}`} etiqueta="Presupuesto oficial" valor={presupuesto} onCambio={setPresupuesto} />
          <Campo id={`ce-${f.id}`} etiqueta="Costo estimado (estudio del sector)" valor={costo} onCambio={setCosto} />
          <div className="field">
            <label htmlFor={`tb-${f.id}`}>Métodos del pliego</label>
            <select id={`tb-${f.id}`} className="input" value={tabla} onChange={(x) => setTabla(x.target.value as 'vigentes' | 'anteriores')}>
              <option value="vigentes">Documentos Tipo vigentes (mediana, geométrica, aritmética baja, menor valor)</option>
              <option value="anteriores">Documentos Tipo anteriores (aritmética, aritmética alta, geométrica con PO, menor valor)</option>
            </select>
          </div>
          <Campo id={`trm-${f.id}`} etiqueta="TRM" valor={trm} onCambio={setTrm} />
          <div className="field">
            <label htmlFor={`ft-${f.id}`}>Fecha de la TRM</label>
            <input id={`ft-${f.id}`} className="input" type="date" value={fechaTrm} onChange={(x) => setFechaTrm(x.target.value)} />
          </div>
          <button type="button" className="btn btn-secondary" disabled={ocupado} onClick={() => void guardar()}>
            Guardar parámetros
          </button>
        </div>
      )}
      <p className="small muted">
        {f.metodo ? (
          <>
            Método por la TRM{f.orden > 1 ? ` (lote ${f.orden}: el siguiente de la tabla)` : ''}: <strong>{f.metodo_nombre}</strong>.{' '}
          </>
        ) : (
          f.error_metodo || 'Sin TRM todavía. '
        )}
        Rangos: {f.rangos.map((r) => `${r.desde}–${r.hasta} ${r.metodo.toLowerCase()}`).join(' · ')}.
      </p>
      {f.bajas && <p className="small muted">Ofertas artificialmente bajas (guía de Colombia Compra): {f.bajas.explicacion}</p>}

      <div className="tabla-wrap" style={{ marginTop: 8 }}>
        <table className="tabla ops-tabla">
          <thead>
            <tr>
              <th>Proponente</th>
              <th>Ofertado</th>
              <th>Verificación aritmética</th>
              <th>Valor corregido</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {f.ofertas.map((o) => (
              <FilaOferta key={o.id} o={o} editable={editable} ocupado={ocupado} procesoId={procesoId} hacer={hacer} />
            ))}
            {f.ofertas.length === 0 && (
              <tr>
                <td colSpan={5} className="vacio">
                  Sin ofertas económicas registradas.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {editable && (
        <div className="economica-parametros" style={{ marginTop: 12 }}>
          <div className="field">
            <label htmlFor={`op-${f.id}`}>Proponente</label>
            <select id={`op-${f.id}`} className="input" value={proponente} onChange={(x) => setProponente(x.target.value)}>
              {e.proponentes.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.hoja} · {p.nombre}
                </option>
              ))}
            </select>
          </div>
          <Campo id={`ov-${f.id}`} etiqueta="Valor total ofertado" valor={valor} onCambio={setValor} />
          <div className="field">
            <label htmlFor={`oa-${f.id}`}>Formulario de la oferta (Excel, opcional)</label>
            <input id={`oa-${f.id}`} className="input" type="file" accept=".xlsx,.xlsm,.pdf" onChange={(x) => setArchivo(x.target.files?.[0] ?? null)} />
          </div>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={ocupado || !valor || !proponente}
            onClick={() => void hacer(() => registrarOferta(procesoId, f.id, proponente, valor, archivo)).then((ok) => ok && setValor(''))}
          >
            Registrar oferta
          </button>
        </div>
      )}

      {f.por_confirmar.length > 0 ? (
        <div className="callout callout-warn" style={{ marginTop: 12 }}>
          <Icono nombre="alerta" />
          <div>
            <strong>Falta antes de calificar</strong>
            <ul>
              {f.por_confirmar.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : (
        editable &&
        !f.calificacion && (
          <button type="button" className="btn btn-primary" style={{ marginTop: 12 }} disabled={ocupado} onClick={() => void hacer(() => calificarFactor(procesoId, f.id))}>
            Calificar con {f.metodo_nombre.toLowerCase()}
          </button>
        )
      )}
      {f.calificacion && (
        <div className="callout callout-ok" style={{ marginTop: 12 }}>
          <Icono nombre="check" />
          <div>
            <strong>
              {f.calificacion.metodo_nombre} · TRM {f.calificacion.trm} ({f.calificacion.centavos_trm} centavos) del {f.calificacion.fecha_trm}
            </strong>
            {f.calificacion.referencia != null && <div className="small">Valor de referencia: {pesos(f.calificacion.referencia)}</div>}
            {f.calificacion.explicacion && <div className="small">{f.calificacion.explicacion}</div>}
            <ol className="small" style={{ marginTop: 6 }}>
              {f.calificacion.puntajes.map((p) => (
                <li key={p.hoja}>
                  {p.hoja} · {p.proponente}: {pesos(p.valor)} → <strong>{p.puntaje.toLocaleString('es-CO', { maximumFractionDigits: 7 })}</strong> puntos
                </li>
              ))}
            </ol>
            <div className="small muted">Confirmada por {f.confirmada_por}. Si cambia un dato, la calificación queda sin efecto.</div>
          </div>
        </div>
      )}
    </div>
  )
}

function Campo({ id, etiqueta, valor, onCambio }: { id: string; etiqueta: string; valor: string; onCambio: (v: string) => void }) {
  return (
    <div className="field">
      <label htmlFor={id}>{etiqueta}</label>
      <input id={id} className="input" inputMode="decimal" value={valor} onChange={(x) => onCambio(x.target.value.replace(/[^\d.]/g, ''))} />
    </div>
  )
}

function FilaOferta({ o, editable, ocupado, procesoId, hacer }: { o: OfertaEconomica; editable: boolean; ocupado: boolean; procesoId: string; hacer: (a: () => Promise<Economica>) => Promise<boolean> }) {
  const [corregido, setCorregido] = useState(o.valor_corregido ?? o.revision.propuesto ?? o.valor_ofertado)
  const [motivo, setMotivo] = useState<string | null>(null)
  const r = o.revision
  return (
    <tr>
      <td>
        <strong>{o.hoja}</strong> · {o.proponente}
        {o.nombre_archivo && <div className="small muted">{o.nombre_archivo}</div>}
        <div className="small">
          {o.habilitacion === 'habilitado' ? (
            <span className="muted">Habilitado</span>
          ) : o.habilitacion === 'no_habilitado' ? (
            <span className="ops-motivo">No quedó habilitado</span>
          ) : (
            <span className="muted">Habilitantes sin terminar</span>
          )}
        </div>
      </td>
      <td className="small nowrap">{pesos(o.valor_ofertado)}</td>
      <td className="small" style={{ maxWidth: 320 }}>
        {(r.diferencias ?? []).map((d) => (
          <div key={d} className="ops-motivo">
            {d}
          </div>
        ))}
        {(r.sin_verificar ?? []).map((d) => (
          <div key={d} className="muted">
            {d}
          </div>
        ))}
        {!r.diferencias?.length && !r.sin_verificar?.length && <span className="muted">Sin errores ({r.items} ítems)</span>}
        {r.propuesto && <div>Propuesto: {pesos(r.propuesto)}</div>}
      </td>
      <td className="small">
        {o.valor_corregido ? (
          <>
            {pesos(o.valor_corregido)}
            <div className="muted">Confirmó {o.corregido_por}</div>
          </>
        ) : editable ? (
          <div className="tramite-fila">
            <input className="input" style={{ minWidth: 130 }} inputMode="decimal" aria-label="Valor corregido" value={corregido} onChange={(x) => setCorregido(x.target.value.replace(/[^\d.]/g, ''))} />
            <button type="button" className="btn btn-sm btn-ok" disabled={ocupado || !corregido} onClick={() => void hacer(() => decidirOferta(procesoId, o.id, { confirmar_corregido: true, valor_corregido: corregido }))}>
              Confirmar
            </button>
          </div>
        ) : (
          <span className="muted">Sin confirmar</span>
        )}
      </td>
      <td className="small">
        <span className="pill" data-estado={o.estado === 'valida' ? (o.alerta_baja ? 'revisar' : 'cumple') : 'error'}>
          {o.estado === 'valida' ? 'Válida' : 'Rechazada'}
        </span>
        {o.motivo_rechazo && <div className="ops-motivo">{o.motivo_rechazo}</div>}
        {editable && o.estado === 'valida' && motivo === null && (
          <div style={{ marginTop: 4 }}>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setMotivo(o.habilitacion === 'no_habilitado' ? 'No quedó habilitado en los requisitos habilitantes.' : '')}>
              Rechazar oferta
            </button>
          </div>
        )}
        {editable && o.estado === 'valida' && motivo !== null && (
          <div className="tramite-fila" style={{ marginTop: 4 }}>
            <input className="input" aria-label="Motivo del rechazo" value={motivo} onChange={(x) => setMotivo(x.target.value)} />
            <button
              type="button"
              className="btn btn-sm btn-bad"
              disabled={ocupado || !motivo.trim()}
              onClick={() => void hacer(() => decidirOferta(procesoId, o.id, { estado: 'rechazada', motivo_rechazo: motivo })).then((ok) => ok && setMotivo(null))}
            >
              Rechazar
            </button>
          </div>
        )}
        {editable && o.estado === 'rechazada' && (
          <div style={{ marginTop: 4 }}>
            <button type="button" className="btn btn-sm btn-ghost" disabled={ocupado} onClick={() => void hacer(() => decidirOferta(procesoId, o.id, { estado: 'valida' }))}>
              Volver a válida
            </button>
          </div>
        )}
        {o.alerta_baja && o.estado === 'valida' && (
          <div style={{ marginTop: 4 }}>
            <div className="ops-motivo">Puede ser artificialmente baja: {o.alerta_baja}</div>
            {o.justificacion === 'aceptada' ? (
              <div className="muted">Justificación aceptada</div>
            ) : (
              editable && (
                <div className="ops-decidir" style={{ marginTop: 4 }}>
                  {o.justificacion !== 'solicitada' && (
                    <button type="button" className="btn btn-sm btn-ghost" disabled={ocupado} onClick={() => void hacer(() => decidirOferta(procesoId, o.id, { justificacion: 'solicitada' }))}>
                      Pedir justificación
                    </button>
                  )}
                  <button type="button" className="btn btn-sm btn-ok" disabled={ocupado} onClick={() => void hacer(() => decidirOferta(procesoId, o.id, { justificacion: 'aceptada' }))}>
                    Aceptar justificación
                  </button>
                  <button type="button" className="btn btn-sm btn-bad" disabled={ocupado} onClick={() => void hacer(() => decidirOferta(procesoId, o.id, { justificacion: 'no_aceptada' }))}>
                    Rechazar
                  </button>
                </div>
              )
            )}
            {o.justificacion === 'solicitada' && <div className="muted">Justificación solicitada</div>}
          </div>
        )}
      </td>
    </tr>
  )
}
