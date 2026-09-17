import { useState } from 'react'
import Icono from './Icono'

interface Props {
  nombre: string
  email: string
  password: string
  /** Texto que explica de dónde salieron estas credenciales. */
  contexto?: string
}

/** Credenciales de una cuenta recién creada o reiniciada: se ven una sola vez,
 * así que la pantalla insiste en entregarlas antes de cerrar. */
export default function TarjetaCredenciales({ nombre, email, password, contexto }: Props) {
  const [copiado, setCopiado] = useState(false)

  const texto = `MiEvaluador\nCorreo: ${email}\nContraseña temporal: ${password}\n\nAl entrar por primera vez el sistema le pedirá cambiarla.`

  async function copiar() {
    try {
      await navigator.clipboard.writeText(texto)
      setCopiado(true)
      window.setTimeout(() => setCopiado(false), 2500)
    } catch {
      setCopiado(false)
    }
  }

  return (
    <div className="credenciales">
      <div className="callout callout-ok">
        <Icono nombre="check" />
        <div>
          Cuenta creada para <strong>{nombre}</strong>.{contexto ? ` ${contexto}` : ''} Entréguele estas credenciales; la contraseña{' '}
          <strong>no se muestra otra vez</strong> ni se envía por correo.
        </div>
      </div>
      <dl className="credenciales-datos">
        <div>
          <dt>Correo</dt>
          <dd>
            <code className="secreto">{email}</code>
          </dd>
        </div>
        <div>
          <dt>Contraseña temporal</dt>
          <dd>
            <code className="secreto clave-temporal">{password}</code>
          </dd>
        </div>
      </dl>
      <button type="button" className="btn btn-secondary btn-bloque" onClick={copiar}>
        <Icono nombre={copiado ? 'check' : 'copiar'} tam={16} /> {copiado ? 'Credenciales copiadas' : 'Copiar credenciales'}
      </button>
      <p className="small muted">La persona debe cambiarla al entrar por primera vez.</p>
    </div>
  )
}
