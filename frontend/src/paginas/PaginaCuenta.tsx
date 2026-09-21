import { useState } from 'react'
import Icono from '../components/Icono'
import { cambiarClave, solicitarRecuperacion } from '../cuentas'
import { useSesion } from '../sesion'
import CampoClave, { ReglasClave } from './CampoClave'
import { mensajeDe } from '../http'
import { tokenRecaptcha } from '../recaptcha'

export default function PaginaCuenta() {
  const { usuario } = useSesion()!
  const [actual, setActual] = useState('')
  const [nueva, setNueva] = useState('')
  const [confirmacion, setConfirmacion] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [resultado, setResultado] = useState<{ ok: boolean; texto: string } | null>(null)
  const [olvido, setOlvido] = useState<'inicio' | 'enviando' | 'enviado' | 'error'>('inicio')

  async function enviarEnlace() {
    setOlvido('enviando')
    try {
      await solicitarRecuperacion(usuario.email, await tokenRecaptcha('RECUPERAR_CLAVE'))
      setOlvido('enviado')
    } catch {
      setOlvido('error')
    }
  }

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
            <p>¿Recuerda su contraseña actual? Escríbala y elija una nueva.</p>
          </div>
          <Icono nombre="escudo" tam={22} />
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

      <section className="card">
        <div className="card-head">
          <div>
            <h2>¿No recuerda su contraseña actual?</h2>
            <p>
              Le enviamos a <strong>{usuario.email}</strong> un enlace para crear una nueva, sin necesidad de la actual. El enlace
              vence en 2 horas.
            </p>
          </div>
        </div>
        {olvido === 'enviado' ? (
          <div className="callout callout-ok">
            <Icono nombre="check" />
            <div>Listo. Revise su correo (también la carpeta de spam) y siga el enlace.</div>
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <button className="btn btn-secondary" type="button" onClick={enviarEnlace} disabled={olvido === 'enviando'}>
              {olvido === 'enviando' ? <span className="spinner oscuro" /> : <Icono nombre="flecha" tam={16} />} Enviarme el enlace
            </button>
            {olvido === 'error' && <span className="small" style={{ color: 'var(--bad)' }}>No se pudo enviar. Inténtelo de nuevo en unos minutos.</span>}
          </div>
        )}
      </section>
    </main>
  )
}
