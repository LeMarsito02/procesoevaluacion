import { useEffect, useState } from 'react'
import { confirmarParametrosPliego, parametrosPliego, type ParametroPliego } from '../evaluaciones'
import { mensajeDe } from '../http'
import Icono from './Icono'

const ORIGENES: Record<string, string> = {
  regla: 'leído del pliego',
  'regla+ia': 'leído del pliego y confirmado por la IA',
  persona: 'confirmado por una persona',
  ia: 'solo lo leyó la IA',
  conflicto: 'las dos lecturas no coinciden',
}

const comoTexto = (v: unknown): string => {
  if (v == null || v === '') return '—'
  if (Array.isArray(v)) return v.join(', ')
  if (typeof v === 'number') return String(v).replace('.', ',')
  return String(v)
}

/** Lo que el programa entendió del pliego de este proceso, con la frase que
 * lo respalda. Lo que solo vio la IA, o en lo que las dos lecturas no
 * coinciden, mantiene los lotes en revisión: confirmarlo aquí es lo que
 * devuelve el automatismo, y queda registrado quién lo confirmó. */
export default function ParametrosPliego({ evaluacionId, soloLectura }: { evaluacionId: string; soloLectura: boolean }) {
  const [datos, setDatos] = useState<ParametroPliego[] | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)
  const [correcciones, setCorrecciones] = useState<Record<string, string>>({})

  function cargar() {
    parametrosPliego(evaluacionId)
      .then(setDatos)
      .catch((e) => setError(mensajeDe(e, 'No se pudieron leer los parámetros del pliego.')))
  }
  useEffect(cargar, [evaluacionId])

  if (datos === undefined && !error) return null
  if (datos && datos.length === 0) return null
  const porRevisar = (datos ?? []).filter((p) => !p.en_firme)

  async function confirmar() {
    setGuardando(true)
    setAviso(null)
    const valores: Record<string, unknown> = {}
    for (const p of porRevisar) {
      const corregido = correcciones[p.campo]
      valores[p.campo] = corregido !== undefined && corregido.trim() !== '' ? corregido.trim() : (p.valor_reglas ?? p.valor_ia)
    }
    try {
      const r = await confirmarParametrosPliego(evaluacionId, valores)
      setAviso(
        `Se confirmaron ${Object.keys(valores).length} parámetro(s).` +
          (r.reevaluados ? ` Se volverán a evaluar ${r.reevaluados} proponente(s).` : ''),
      )
      setCorrecciones({})
      cargar()
    } catch (e) {
      setError(mensajeDe(e, 'No se pudieron confirmar los parámetros.'))
    } finally {
      setGuardando(false)
    }
  }

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <div>
          <h2>Lo que se entendió del pliego</h2>
          <p>Cada parámetro con la frase del pliego que lo respalda. Mientras haya alguno sin confirmar, ningún lote se aprueba solo.</p>
        </div>
      </div>
      {error && <div className="callout callout-bad" style={{ marginBottom: 12 }}>{error}</div>}
      {aviso && <div className="callout callout-ok" style={{ marginBottom: 12 }}>{aviso}</div>}
      {porRevisar.length > 0 && (
        <div className="callout callout-warn" style={{ marginBottom: 12 }}>
          <Icono nombre="alerta" />
          <div>{porRevisar.length} parámetro(s) necesitan tu confirmación.</div>
        </div>
      )}
      <div className="tabla-wrap">
        <table className="tabla">
          <thead>
            <tr>
              <th>Parámetro</th>
              <th>Valor</th>
              <th>De dónde salió</th>
              <th>Lo que dice el pliego</th>
              {!soloLectura && <th>Corregir</th>}
            </tr>
          </thead>
          <tbody>
            {(datos ?? []).map((p) => {
              const valor = p.confirmado ?? p.valor_reglas ?? p.valor_ia
              return (
                <tr key={p.campo}>
                  <td>{p.campo}</td>
                  <td>
                    {comoTexto(valor)}
                    {p.origen === 'conflicto' && (
                      <div className="small muted">la IA leyó: {comoTexto(p.valor_ia)}</div>
                    )}
                  </td>
                  <td className="small">{ORIGENES[p.origen] ?? p.origen}</td>
                  <td className="small muted">
                    {p.cita ? `«${p.cita}»` : '—'}
                    {p.seccion && <div className="small muted">{p.seccion}</div>}
                  </td>
                  {!soloLectura && (
                    <td>
                      {p.en_firme ? (
                        <span className="small muted">—</span>
                      ) : (
                        <input
                          type="text"
                          placeholder={comoTexto(valor)}
                          value={correcciones[p.campo] ?? ''}
                          onChange={(e) => setCorrecciones({ ...correcciones, [p.campo]: e.target.value })}
                        />
                      )}
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {!soloLectura && porRevisar.length > 0 && (
        <div className="acciones" style={{ marginTop: 12 }}>
          <button type="button" className="btn btn-primary btn-sm" disabled={guardando} onClick={confirmar}>
            {guardando ? 'Confirmando…' : `Confirmar los ${porRevisar.length} pendientes`}
          </button>
          <p className="small muted" style={{ margin: 0 }}>
            Al confirmar, los proponentes ya evaluados vuelven a la fila para que el cambio cuente.
          </p>
        </div>
      )}
    </section>
  )
}
