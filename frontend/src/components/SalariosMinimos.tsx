import { useEffect, useState } from 'react'
import { guardarSalarioMinimo, listarSalariosMinimos, type SalarioMinimo } from '../cuentas'
import { formatPesos } from '../format'
import { mensajeDe } from '../http'
import Icono from './Icono'

/** El Gobierno fija cada diciembre el salario mínimo del año siguiente; cada
 * proceso usa el del año de su fecha de cierre para comparar los límites de
 * cuantía del representante legal. */
export default function SalariosMinimos({ onAviso }: { onAviso: (t: string) => void }) {
  const hoy = new Date()
  const [lista, setLista] = useState<SalarioMinimo[] | null>(null)
  const [ano, setAno] = useState(String(hoy.getFullYear() + (hoy.getMonth() === 11 ? 1 : 0)))
  const [valor, setValor] = useState('')
  const [norma, setNorma] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listarSalariosMinimos()
      .then(setLista)
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [])

  const anos = new Set((lista ?? []).map((s) => s.ano))
  const faltaActual = lista !== null && !anos.has(hoy.getFullYear())
  const faltaSiguiente = lista !== null && hoy.getMonth() === 11 && !anos.has(hoy.getFullYear() + 1)

  async function guardar() {
    setEnviando(true)
    setError(null)
    try {
      const s = await guardarSalarioMinimo(Number(ano), Number(valor.replace(/\D/g, '')), norma)
      setLista((l) => [s, ...(l ?? []).filter((x) => x.ano !== s.ano)].sort((a, b) => b.ano - a.ano))
      setValor('')
      setNorma('')
      onAviso(`Salario mínimo de ${s.ano} guardado`)
    } catch (e) {
      setError(mensajeDe(e))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <section className="card" style={{ marginTop: 24 }}>
      <div className="card-head">
        <div>
          <h2>Salario mínimo por año</h2>
          <p>Cada proceso usa el del año de su fecha de cierre para saber si el límite de cuantía del representante legal alcanza.</p>
        </div>
        <Icono nombre="calendario" tam={22} />
      </div>
      {faltaActual && (
        <div className="callout callout-bad" style={{ marginBottom: 12 }}>
          <Icono nombre="alerta" />
          <div>Falta el salario mínimo de {hoy.getFullYear()}: los límites expresados en salarios mínimos quedarán para revisión humana.</div>
        </div>
      )}
      {faltaSiguiente && (
        <div className="callout callout-warn" style={{ marginBottom: 12 }}>
          <Icono nombre="reloj" />
          <div>Cuando se publique el decreto, registre el salario mínimo de {hoy.getFullYear() + 1}.</div>
        </div>
      )}
      {error && <div className="callout callout-bad" style={{ marginBottom: 12 }}>{error}</div>}
      {lista === null && !error && (
        <p className="small muted" role="status" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="spinner oscuro" /> Cargando…
        </p>
      )}
      {lista && lista.length > 0 && (
        <div className="tabla-wrap" style={{ marginBottom: 14 }}>
          <table className="tabla">
            <thead>
              <tr>
                <th>Año</th>
                <th>Valor mensual</th>
                <th>Norma</th>
                <th>Actualizado</th>
              </tr>
            </thead>
            <tbody>
              {lista.map((s) => (
                <tr key={s.ano}>
                  <td className="num">{s.ano}</td>
                  <td className="num">{formatPesos(s.valor)}</td>
                  <td className="small">{s.norma || '—'}</td>
                  <td className="small muted">{s.actualizado_por ?? 'Carga inicial'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <form
        className="grid-soporte"
        style={{ gridTemplateColumns: '100px 1fr 1.4fr auto' }}
        onSubmit={(e) => {
          e.preventDefault()
          guardar()
        }}
      >
        <input className="input" inputMode="numeric" value={ano} onChange={(e) => setAno(e.target.value.replace(/\D/g, '').slice(0, 4))} aria-label="Año" />
        <input className="input" inputMode="numeric" placeholder="Valor (ej. 1750905)" value={valor} onChange={(e) => setValor(e.target.value)} aria-label="Valor mensual" required />
        <input className="input" placeholder="Norma (ej. Decreto 1469 de 2025)" value={norma} onChange={(e) => setNorma(e.target.value)} aria-label="Norma" />
        <button type="submit" className="btn btn-secondary" disabled={enviando || ano.length !== 4 || !valor.trim()}>
          {enviando ? <span className="spinner oscuro" /> : 'Guardar'}
        </button>
      </form>
    </section>
  )
}
