import { useState } from 'react'
import Icono from '../components/Icono'
import { restablecerClave } from '../cuentas'
import { navegar } from '../rutas'
import CampoClave, { ReglasClave } from './CampoClave'
import MarcoAcceso from './MarcoAcceso'
import { mensajeDe } from '../http'

export default function PaginaRestablecer({ uid, token }: { uid: string; token: string }) {
  const [clave, setClave] = useState('')
  const [confirmacion, setConfirmacion] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [listo, setListo] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function guardar() {
    setEnviando(true)
    setError(null)
    try {
      await restablecerClave(uid, token, clave)
      setListo(true)
    } catch (e) {
      setError(mensajeDe(e, 'No se pudo cambiar la contraseña.'))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <MarcoAcceso>
      <div className="eyebrow">Recuperar acceso</div>
      <h1 className="acceso-titulo">Nueva contraseña</h1>
      {listo ? (
        <div className="acceso-form">
          <div className="callout callout-ok">
            <Icono nombre="check" />
            <div>Su contraseña se cambió. Por seguridad se cerraron las sesiones abiertas en otros equipos.</div>
          </div>
          <button type="button" className="btn btn-primary btn-lg btn-bloque" onClick={() => navegar('/', true)}>
            Iniciar sesión
          </button>
        </div>
      ) : (
        <form
          className="acceso-form"
          onSubmit={(e) => {
            e.preventDefault()
            guardar()
          }}
        >
          <div className="field">
            <label htmlFor="clave">Contraseña nueva</label>
            <CampoClave id="clave" valor={clave} onCambiar={setClave} autoComplete="new-password" autoFocus />
          </div>
          <div className="field">
            <label htmlFor="clave2">Repita la contraseña</label>
            <CampoClave id="clave2" valor={confirmacion} onCambiar={setConfirmacion} autoComplete="new-password" />
            <ReglasClave clave={clave} confirmacion={confirmacion} />
          </div>
          {error && (
            <div className="callout callout-bad" role="alert">
              <Icono nombre="alerta" />
              <div>{error}</div>
            </div>
          )}
          <button className="btn btn-primary btn-lg btn-bloque" type="submit" disabled={enviando || clave !== confirmacion || clave.length < 10}>
            {enviando ? <span className="spinner" /> : 'Guardar contraseña'}
          </button>
        </form>
      )}
    </MarcoAcceso>
  )
}
