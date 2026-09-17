import { useState } from 'react'
import Icono from '../components/Icono'
import { cambiarClave } from '../cuentas'
import { useSesion } from '../sesion'
import CampoClave, { ReglasClave } from './CampoClave'
import { mensajeDe } from '../http'

export default function PaginaCuenta() {
  const { usuario } = useSesion()!
  const [actual, setActual] = useState('')
  const [nueva, setNueva] = useState('')
  const [confirmacion, setConfirmacion] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [resultado, setResultado] = useState<{ ok: boolean; texto: string } | null>(null)

  async function guardar() {
    setEnviando(true)
    setResultado(null)
    try {
      await cambiarClave(actual, nueva)
      setActual('')
      setNueva('')
      setConfirmacion('')
      setResultado({ ok: true, texto: 'Contraseña cambiada. Se cerraron sus sesiones en otros equipos.' })
    } catch (e) {
      setResultado({ ok: false, texto: mensajeDe(e, 'No se pudo cambiar la contraseña.') })
    } finally {
      setEnviando(false)
    }
  }

  return (
    <main className="page page-narrow">
      <div className="page-head">
        <div>
          <div className="eyebrow">Mi cuenta</div>
          <h1>{usuario.nombre_completo}</h1>
          <p>
            {usuario.email} · {usuario.rol_nombre}
            {usuario.entidad ? ` · ${usuario.entidad.nombre}` : ''}
          </p>
        </div>
      </div>
      <div className="card">
        <div className="card-head">
          <div>
            <h2>Áreas</h2>
            <p>Asignadas por el administrador de su entidad.</p>
          </div>
        </div>
        <div className="chips">
          {usuario.areas.length ? (
            usuario.areas.map((a) => (
              <span key={a.id} className="chip" data-activo="true">
                {a.nombre}
              </span>
            ))
          ) : (
            <span className="muted small">Sin áreas asignadas.</span>
          )}
        </div>
      </div>
      <form
        className="card"
        onSubmit={(e) => {
          e.preventDefault()
          guardar()
        }}
      >
        <div className="card-head">
          <div>
            <h2>Cambiar contraseña</h2>
          </div>
        </div>
        <div className="field" style={{ marginBottom: 16 }}>
          <label htmlFor="actual">Contraseña actual</label>
          <CampoClave id="actual" valor={actual} onCambiar={setActual} autoComplete="current-password" />
        </div>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="nueva">Contraseña nueva</label>
            <CampoClave id="nueva" valor={nueva} onCambiar={setNueva} autoComplete="new-password" />
          </div>
          <div className="field">
            <label htmlFor="nueva2">Repita la contraseña nueva</label>
            <CampoClave id="nueva2" valor={confirmacion} onCambiar={setConfirmacion} autoComplete="new-password" />
          </div>
        </div>
        <ReglasClave clave={nueva} confirmacion={confirmacion} />
        {resultado && (
          <div className={`callout ${resultado.ok ? 'callout-ok' : 'callout-bad'}`} style={{ marginTop: 16 }}>
            <Icono nombre={resultado.ok ? 'check' : 'alerta'} />
            <div>{resultado.texto}</div>
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 20 }}>
          <button className="btn btn-primary" type="submit" disabled={enviando || !actual || nueva.length < 10 || nueva !== confirmacion}>
            {enviando ? <span className="spinner" /> : 'Guardar contraseña'}
          </button>
        </div>
      </form>
    </main>
  )
}
