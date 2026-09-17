import { useEffect, useState } from 'react'
import Icono from '../components/Icono'
import { aceptarInvitacion, verInvitacion, type Usuario } from '../cuentas'
import CampoClave, { ReglasClave } from './CampoClave'
import MarcoAcceso from './MarcoAcceso'
import { mensajeDe } from '../http'

export default function PaginaInvitacion({ token, onEntrar }: { token: string; onEntrar: (u: Usuario) => void }) {
  const [info, setInfo] = useState<{ email: string; entidad: string; rol_nombre: string } | null>(null)
  const [errorCarga, setErrorCarga] = useState<string | null>(null)
  const [nombre, setNombre] = useState('')
  const [clave, setClave] = useState('')
  const [confirmacion, setConfirmacion] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    verInvitacion(token).then(setInfo).catch((e: unknown) => setErrorCarga(mensajeDe(e)))
  }, [token])

  async function aceptar() {
    setEnviando(true)
    setError(null)
    try {
      const r = await aceptarInvitacion(token, nombre, clave)
      if (r.usuario) onEntrar(r.usuario)
    } catch (e) {
      setError(mensajeDe(e, 'No se pudo crear la cuenta.'))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <MarcoAcceso>
      <div className="eyebrow">Invitación</div>
      {errorCarga ? (
        <>
          <h1 className="acceso-titulo">Invitación no disponible</h1>
          <div className="callout callout-warn">
            <Icono nombre="alerta" />
            <div>{errorCarga}</div>
          </div>
          <a className="btn btn-secondary btn-bloque" href="/" style={{ marginTop: 16 }}>
            Ir a iniciar sesión
          </a>
        </>
      ) : !info ? (
        <span className="spinner oscuro" />
      ) : (
        <>
          <h1 className="acceso-titulo">Únase a {info.entidad}</h1>
          <p className="muted">
            Lo invitaron como <strong>{info.rol_nombre.toLowerCase()}</strong>. Complete sus datos para crear la cuenta.
          </p>
          <form
            className="acceso-form"
            onSubmit={(e) => {
              e.preventDefault()
              aceptar()
            }}
          >
            <div className="field">
              <label>Correo electrónico</label>
              <input className="input" value={info.email} disabled />
            </div>
            <div className="field">
              <label htmlFor="nombre">Nombre completo</label>
              <input id="nombre" className="input" autoComplete="name" value={nombre} onChange={(e) => setNombre(e.target.value)} autoFocus required />
            </div>
            <div className="field">
              <label htmlFor="clave">Contraseña</label>
              <CampoClave id="clave" valor={clave} onCambiar={setClave} autoComplete="new-password" />
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
              {enviando ? <span className="spinner" /> : 'Crear cuenta y entrar'}
            </button>
          </form>
        </>
      )}
    </MarcoAcceso>
  )
}
