import { useState } from 'react'
import type { Lote, Proponente } from '../api'
import { formatFechaCorta, formatPesos } from '../format'
import Icono from './Icono'

export type BaseCalculo = 'lote_mayor_valor' | 'presupuesto_total'

interface Props {
  codigoProceso: string
  fechaCierre: string
  objetoGeneral: string
  lotes: Lote[]
  vigenciaMeses: number
  porcentajePct: number
  baseCalculo: BaseCalculo
  advertencias: string[]
  derivados: { presupuestoTotal: number; loteMayorNumero: string; valorBase: number; valorAsegurado: number; fechaVencimiento: string }
  proponentes: Proponente[]
  noReconocidos: string[]
  driveError: string | null
  hayResultados: boolean
  /** Deshabilita la edición (sin permiso o evaluación aprobada). */
  soloLectura?: boolean
  /** Texto del botón principal; por defecto "Evaluar N proponentes". */
  textoAccion?: string
  ocupado?: boolean
  deshabilitado?: boolean
  /** Contenido extra antes de los botones (p. ej. quién evalúa). */
  antesDeAcciones?: React.ReactNode
  onCambiarObjeto: (v: string) => void
  onCambiarLote: (indice: number, cambios: Partial<Lote>) => void
  onCambiarGarantia: (cambios: { vigenciaMeses?: number; porcentajePct?: number; baseCalculo?: BaseCalculo }) => void
  onVolver: (() => void) | null
  onEvaluar: () => void
}

/** Minutos aproximados en frío, medidos en la prueba real (85 min / 81 proponentes). */
function estimacionMinutos(n: number): number {
  return Math.max(1, Math.round(n * 1.05))
}

export default function PasoDatos(p: Props) {
  const [editandoLotes, setEditandoLotes] = useState(false)
  const [editandoGarantia, setEditandoGarantia] = useState(false)
  const [verProponentes, setVerProponentes] = useState(false)
  const n = p.proponentes.length

  return (
    <main className="page">
      <fieldset className="fieldset-limpio" disabled={p.soloLectura}>
      <div className="page-head">
        <div>
          <div className="eyebrow">Evaluación jurídica</div>
          <h1>Verifique los datos del proceso</h1>
          <p>
            Esto es lo que se leyó del Documento Base. Si algo no coincide, corríjalo antes de evaluar: estos valores se
            usan para verificar a cada proponente.
          </p>
        </div>
      </div>

      <div className="facts" style={{ marginBottom: 20 }}>
        <div className="fact">
          <div className="fact-label">Proceso</div>
          <div className="fact-value big">{p.codigoProceso}</div>
        </div>
        <div className="fact">
          <div className="fact-label">Fecha de cierre</div>
          <div className="fact-value big">{formatFechaCorta(p.fechaCierre)}</div>
        </div>
        <div className="fact">
          <div className="fact-label">Proponentes encontrados</div>
          <div className="fact-value big">{n}</div>
        </div>
        <div className="fact">
          <div className="fact-label">Presupuesto oficial total</div>
          <div className="fact-value big">{formatPesos(p.derivados.presupuestoTotal)}</div>
        </div>
      </div>

      {p.driveError && (
        <div className="callout callout-bad" style={{ marginBottom: 16 }}>
          <Icono nombre="alerta" />
          <div>
            <strong>No se pudieron leer las ofertas de Drive.</strong> {p.driveError}
          </div>
        </div>
      )}
      {p.advertencias.length > 0 && (
        <div className="callout callout-warn" style={{ marginBottom: 16 }}>
          <Icono nombre="alerta" />
          <div>
            <strong>Revise estos puntos del Documento Base:</strong>
            <ul>
              {p.advertencias.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {p.noReconocidos.length > 0 && (
        <div className="callout callout-warn" style={{ marginBottom: 16 }}>
          <Icono nombre="info" />
          <div>
            <strong>
              {p.noReconocidos.length} archivo(s) de la carpeta no se reconocieron como oferta y no se evaluarán:
            </strong>
            <ul>
              {p.noReconocidos.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
            <span className="small">Para incluirlos, renómbrelos como “P12 Nombre del proponente” y vuelva a cargar.</span>
          </div>
        </div>
      )}

      <section className="card">
        <div className="card-head">
          <div>
            <h2>Objeto y lotes</h2>
            <p>Se usan para verificar la carta de presentación y el objeto social.</p>
          </div>
          <button className="btn btn-secondary btn-sm" type="button" onClick={() => setEditandoLotes((v) => !v)}>
            {editandoLotes ? (
              <>
                <Icono nombre="check" tam={15} /> Listo
              </>
            ) : (
              <>
                <Icono nombre="lapiz" tam={15} /> Corregir
              </>
            )}
          </button>
        </div>

        {editandoLotes ? (
          <>
            <div className="field" style={{ marginBottom: 16 }}>
              <label htmlFor="objeto">Objeto general</label>
              <textarea id="objeto" className="textarea" rows={3} value={p.objetoGeneral} onChange={(e) => p.onCambiarObjeto(e.target.value)} />
            </div>
            <table className="tabla-lotes">
              <thead>
                <tr>
                  <th style={{ width: 70 }}>Lote</th>
                  <th>Objeto</th>
                  <th style={{ width: 110 }}>Plazo (meses)</th>
                  <th style={{ width: 190 }}>Presupuesto oficial</th>
                  <th style={{ width: 200 }}>Lugar de ejecución</th>
                </tr>
              </thead>
              <tbody>
                {p.lotes.map((lote, i) => (
                  <tr key={i}>
                    <td style={{ paddingTop: 16, fontWeight: 600 }}>{lote.numero}</td>
                    <td>
                      <textarea className="textarea" rows={3} value={lote.objeto} onChange={(e) => p.onCambiarLote(i, { objeto: e.target.value })} />
                    </td>
                    <td>
                      <input className="input" type="number" min={0} value={lote.plazo_meses} onChange={(e) => p.onCambiarLote(i, { plazo_meses: Number(e.target.value) })} />
                    </td>
                    <td>
                      <input className="input" type="number" min={0} value={lote.valor_presupuesto} onChange={(e) => p.onCambiarLote(i, { valor_presupuesto: Number(e.target.value) })} />
                    </td>
                    <td>
                      <input className="input" value={lote.lugar_ejecucion ?? ''} onChange={(e) => p.onCambiarLote(i, { lugar_ejecucion: e.target.value })} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <>
            <p style={{ color: 'var(--ink-2)', marginBottom: 16 }}>{p.objetoGeneral || <span className="muted">Sin objeto general</span>}</p>
            <div style={{ display: 'grid', gap: 10 }}>
              {p.lotes.map((lote) => (
                <div key={lote.numero} style={{ display: 'flex', gap: 16, padding: '12px 14px', background: 'var(--surface-2)', borderRadius: 10, border: '1px solid var(--line)' }}>
                  <span className="tag" style={{ flex: 'none' }}>
                    {lote.numero}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14 }}>{lote.objeto}</div>
                    <div className="small muted" style={{ marginTop: 4 }}>
                      {lote.plazo_meses} meses{lote.lugar_ejecucion ? ` · ${lote.lugar_ejecucion}` : ''}
                    </div>
                  </div>
                  <div className="num" style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>
                    {formatPesos(lote.valor_presupuesto)}
                    {lote.numero === p.derivados.loteMayorNumero && p.lotes.length > 1 && (
                      <div className="small" style={{ color: 'var(--gold)', fontWeight: 600, textAlign: 'right' }}>
                        Mayor valor
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <div>
            <h2>Garantía de seriedad exigida</h2>
            <p>Cada póliza se compara contra el valor de los lotes a los que se presenta el proponente.</p>
          </div>
          <button className="btn btn-secondary btn-sm" type="button" onClick={() => setEditandoGarantia((v) => !v)}>
            {editandoGarantia ? (
              <>
                <Icono nombre="check" tam={15} /> Listo
              </>
            ) : (
              <>
                <Icono nombre="lapiz" tam={15} /> Corregir
              </>
            )}
          </button>
        </div>
        <div className="facts">
          {p.baseCalculo === 'lote_mayor_valor' && p.lotes.length > 1 ? (
            p.lotes.map((lote) => (
              <div className="fact" key={lote.numero}>
                <div className="fact-label">Valor asegurado mínimo · {lote.numero}</div>
                <div className="fact-value big">
                  {formatPesos(Math.round(lote.valor_presupuesto * p.porcentajePct) / 100)}
                </div>
              </div>
            ))
          ) : (
            <div className="fact">
              <div className="fact-label">Valor asegurado mínimo</div>
              <div className="fact-value big">{formatPesos(p.derivados.valorAsegurado)}</div>
            </div>
          )}
          <div className="fact">
            <div className="fact-label">Vigencia mínima hasta</div>
            <div className="fact-value big">{formatFechaCorta(p.derivados.fechaVencimiento)}</div>
          </div>
          <div className="fact">
            <div className="fact-label">Cálculo</div>
            <div className="fact-value">
              {p.baseCalculo === 'lote_mayor_valor'
                ? `${p.porcentajePct}% de cada lote; si se presenta a varios, el del más caro`
                : `${p.porcentajePct}% del presupuesto total`}
            </div>
          </div>
        </div>
        {editandoGarantia && (
          <div className="grid-3" style={{ marginTop: 18 }}>
            <div className="field">
              <label htmlFor="vig">Vigencia (meses desde el cierre)</label>
              <input id="vig" className="input" type="number" min={1} value={p.vigenciaMeses} onChange={(e) => p.onCambiarGarantia({ vigenciaMeses: Number(e.target.value) })} />
            </div>
            <div className="field">
              <label htmlFor="pct">Porcentaje asegurado (%)</label>
              <input id="pct" className="input" type="number" min={0} step={0.1} value={p.porcentajePct} onChange={(e) => p.onCambiarGarantia({ porcentajePct: Number(e.target.value) })} />
            </div>
            <div className="field">
              <label htmlFor="base">Base de cálculo</label>
              <select id="base" className="select" value={p.baseCalculo} onChange={(e) => p.onCambiarGarantia({ baseCalculo: e.target.value as BaseCalculo })}>
                <option value="lote_mayor_valor">Lote de mayor valor</option>
                <option value="presupuesto_total">Presupuesto oficial total</option>
              </select>
            </div>
          </div>
        )}
      </section>

      <section className="card">
        <div className="card-head" style={{ marginBottom: verProponentes ? 18 : 0 }}>
          <div>
            <h2>Proponentes ({n})</h2>
            <p>Leídos de la carpeta de Google Drive.</p>
          </div>
          <button className="btn btn-secondary btn-sm" type="button" onClick={() => setVerProponentes((v) => !v)} disabled={n === 0}>
            <Icono nombre="usuarios" tam={15} /> {verProponentes ? 'Ocultar lista' : 'Ver lista'}
          </button>
        </div>
        {verProponentes && (
          <div className="lista-props">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 70 }}>No.</th>
                  <th>Proponente</th>
                  <th>Archivo</th>
                </tr>
              </thead>
              <tbody>
                {p.proponentes.map((pr) => (
                  <tr key={pr.drive_file_id}>
                    <td className="num muted">{pr.hoja}</td>
                    <td style={{ fontWeight: 600 }}>{pr.nombre_proponente}</td>
                    <td className="muted small">{pr.nombre_archivo}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      </fieldset>

      {p.antesDeAcciones}

      <div className="acciones-pie">
        {p.onVolver ? (
          <button className="btn btn-ghost" type="button" onClick={p.onVolver}>
            <Icono nombre="atras" /> Cambiar documento o carpeta
          </button>
        ) : (
          <span />
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          {n > 0 && !p.hayResultados && (
            <span className="small muted" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <Icono nombre="reloj" tam={15} /> Hasta ~{estimacionMinutos(n)} min · puede revisar mientras avanza
            </span>
          )}
          <button className="btn btn-primary btn-lg" type="button" onClick={p.onEvaluar} disabled={n === 0 || p.ocupado || p.deshabilitado}>
            {p.ocupado && <span className="spinner" />}
            {p.textoAccion ?? (p.hayResultados ? 'Ver evaluación' : `Evaluar ${n} proponentes`)} <Icono nombre="flecha" />
          </button>
        </div>
      </div>
    </main>
  )
}
