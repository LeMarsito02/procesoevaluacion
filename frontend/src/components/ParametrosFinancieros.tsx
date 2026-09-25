import { useEffect, useState } from 'react'
import { parametrosFinancieros, registrarUmbrales, type ParametrosFinancieros as Parametros } from '../evaluaciones'
import { mensajeDe } from '../http'
import Icono from './Icono'

const pesos = (v: number | null | undefined) =>
  v == null ? '—' : `$${v.toLocaleString('es-CO', { maximumFractionDigits: 0 })}`

const CAMPOS = [
  { clave: 'liquidez_min', nombre: 'Liquidez', signo: '≥' },
  { clave: 'endeudamiento_max', nombre: 'Endeudamiento', signo: '≤' },
  { clave: 'cobertura_min', nombre: 'Cobertura de intereses', signo: '≥' },
  { clave: 'roa_min', nombre: 'Rentabilidad del activo', signo: '≥' },
  { clave: 'roe_min', nombre: 'Rentabilidad del patrimonio', signo: '≥' },
] as const
type Clave = (typeof CAMPOS)[number]['clave']

const texto = (v: number | null | undefined) => (v == null ? '' : String(v).replace('.', ','))

/** Lo que la evaluación financiera toma del pliego por lote y los umbrales
 * de la Matriz 2. La matriz es un anexo aparte del pliego: si no viene en
 * él, una persona registra los umbrales y los proponentes se vuelven a
 * evaluar; mientras tanto los indicadores se calculan pero van a revisión. */
export default function ParametrosFinancieros({ evaluacionId, soloLectura }: { evaluacionId: string; soloLectura: boolean }) {
  const [datos, setDatos] = useState<Parametros | null | undefined>(undefined)
  const [valores, setValores] = useState<Record<Clave, string>>({} as Record<Clave, string>)
  const [editando, setEditando] = useState(false)
  const [guardando, setGuardando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  function cargar(p: Parametros | null) {
    setDatos(p)
    if (p) setValores(Object.fromEntries(CAMPOS.map((c) => [c.clave, texto(p.umbrales[c.clave])])) as Record<Clave, string>)
  }

  useEffect(() => {
    parametrosFinancieros(evaluacionId)
      .then(cargar)
      .catch((e) => setError(mensajeDe(e, 'No se pudieron leer los parámetros financieros.')))
  }, [evaluacionId])

  async function guardar() {
    const numeros: Record<string, number> = {}
    for (const c of CAMPOS) {
      const v = Number((valores[c.clave] ?? '').trim().replace(',', '.'))
      if (!(valores[c.clave] ?? '').trim() || !Number.isFinite(v) || v < 0) {
        setError(`Escribe un número válido para ${c.nombre.toLowerCase()}.`)
        return
      }
      numeros[c.clave] = v
    }
    setGuardando(true)
    setError(null)
    try {
      const p = await registrarUmbrales(evaluacionId, numeros as Record<Clave, number>)
      cargar({ ...(datos as Parametros), ...p, umbrales_completos: true, lotes: (datos as Parametros).lotes })
      setEditando(false)
      setAviso('Umbrales registrados. Los proponentes ya evaluados se volvieron a poner en la fila.')
    } catch (e) {
      setError(mensajeDe(e, 'No se pudieron registrar los umbrales.'))
    } finally {
      setGuardando(false)
    }
  }

  if (datos === undefined && !error) return null
  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <div>
          <h2>Parámetros financieros</h2>
          <p>Del pliego: presupuesto, plazo y anticipo de cada lote; umbrales de los indicadores (Matriz 2).</p>
        </div>
        {datos && !soloLectura && !editando && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditando(true)}>
            <Icono nombre="lapiz" tam={15} /> {datos.umbrales_completos ? 'Cambiar umbrales' : 'Registrar umbrales'}
          </button>
        )}
      </div>
      {error && <div className="callout callout-bad" style={{ marginBottom: 12 }}>{error}</div>}
      {aviso && <div className="callout callout-ok" style={{ marginBottom: 12 }}>{aviso}</div>}
      {datos === null && (
        <p className="small muted">
          Faltan el pliego del proceso o el salario mínimo del año del cierre para leer los parámetros financieros.
        </p>
      )}
      {datos && (
        <>
          {datos.avisos.map((a) => (
            <div key={a} className="callout callout-warn" style={{ marginBottom: 8 }}>
              <Icono nombre="alerta" />
              <div>{a}</div>
            </div>
          ))}
          <div className="param-fin-lotes">
            {datos.lotes.map((l) => (
              <div key={l.nombre} className="contrato-ficha">
                <div className="contrato-ficha-titulo">{l.nombre}</div>
                <div className="contrato-ficha-datos">
                  <span>
                    Presupuesto {pesos(l.presupuesto)} · plazo {l.plazo_meses ?? '—'} meses · anticipo{' '}
                    {l.anticipo == null ? '—' : `${Math.round(l.anticipo * 100)} %`}
                  </span>
                  <span>Capital de trabajo exigido {pesos(l.capital_de_trabajo_demandado)}</span>
                  <span>Capacidad residual exigida {pesos(l.capacidad_residual_del_proceso)}</span>
                </div>
              </div>
            ))}
          </div>
          {!datos.umbrales_completos && !editando && (
            <div className="callout callout-warn" style={{ marginTop: 12 }}>
              <Icono nombre="alerta" />
              <div>
                El pliego no trae los umbrales de la Matriz 2. Los indicadores se calculan, pero la capacidad financiera y la
                organizacional quedan en revisión hasta que alguien registre los umbrales del proceso.
              </div>
            </div>
          )}
          {editando ? (
            <div className="param-fin-umbrales">
              {CAMPOS.map((c) => (
                <div key={c.clave} className="field">
                  <label htmlFor={`umbral-${c.clave}`}>
                    {c.nombre} {c.signo}
                  </label>
                  <input
                    id={`umbral-${c.clave}`}
                    className="input"
                    inputMode="decimal"
                    value={valores[c.clave] ?? ''}
                    onChange={(e) => setValores({ ...valores, [c.clave]: e.target.value })}
                  />
                </div>
              ))}
              <div className="acciones">
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditando(false)} disabled={guardando}>
                  Cancelar
                </button>
                <button type="button" className="btn btn-primary btn-sm" onClick={guardar} disabled={guardando}>
                  {guardando ? <span className="spinner" /> : null} Guardar y volver a evaluar
                </button>
              </div>
            </div>
          ) : (
            datos.umbrales_completos && (
              <>
                <p className="small" style={{ marginTop: 12 }}>
                  {CAMPOS.map((c) => `${c.nombre} ${c.signo} ${texto(datos.umbrales[c.clave])}`).join(' · ')}
                  <span className="muted"> — {datos.umbrales.fuente}</span>
                </p>
                {datos.umbrales_mipyme && (
                  <p className="small muted" style={{ marginTop: 4 }}>
                    La Matriz 2 reserva otros a los proponentes que acrediten ser Mipyme:{' '}
                    {CAMPOS.map((c) => `${c.nombre} ${c.signo} ${texto(datos.umbrales_mipyme![c.clave])}`).join(' · ')}.
                    Se le aplican solo a quien lo acredite con su RUP, y en el informe queda dicho cuál se usó.
                  </p>
                )}
              </>
            )
          )}
        </>
      )}
    </section>
  )
}
