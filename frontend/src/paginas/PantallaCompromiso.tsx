/** Compromiso de uso del evaluador (expediente LEG-004, numeral 6.4). Se
 * acepta una vez por versión del texto; sin aceptarlo no se deciden requisitos. */
import { useState } from 'react'
import { aceptarCompromiso, type Usuario } from '../cuentas'
import { mensajeDe } from '../http'

export default function PantallaCompromiso({ usuario, onAceptado, onSalir }: { usuario: Usuario; onAceptado: (u: Usuario) => void; onSalir: () => void }) {
  const [leido, setLeido] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <main className="page page-narrow">
      <section className="card">
        <div className="card-head">
          <div>
            <div className="eyebrow">Antes de empezar</div>
            <h1>Compromiso de uso de MiEvaluador</h1>
            <p>
              MiEvaluador es una herramienta de apoyo: verifica y propone, pero no decide. Para registrar decisiones sobre
              requisitos, lea y acepte este compromiso. Queda registrado con su nombre, la fecha y la versión del texto.
            </p>
          </div>
        </div>
        <p className="compromiso-texto">{usuario.compromiso_texto}</p>
        <label style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
          <input type="checkbox" checked={leido} onChange={(e) => setLeido(e.target.checked)} />
          <span>
            Yo, <strong>{usuario.nombre_completo}</strong>, leí el compromiso y lo acepto.
          </span>
        </label>
        {error && (
          <p className="small" style={{ color: 'var(--bad)', marginTop: 12 }}>
            {error}
          </p>
        )}
        <div className="dialogo-pie" style={{ marginTop: 20 }}>
          <button type="button" className="btn btn-ghost" onClick={onSalir}>
            Salir
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!leido || ocupado}
            onClick={async () => {
              setOcupado(true)
              setError(null)
              try {
                onAceptado(await aceptarCompromiso(usuario.compromiso_version ?? ''))
              } catch (e) {
                setError(mensajeDe(e))
              } finally {
                setOcupado(false)
              }
            }}
          >
            {ocupado ? <span className="spinner" /> : null} Acepto el compromiso
          </button>
        </div>
      </section>
    </main>
  )
}
