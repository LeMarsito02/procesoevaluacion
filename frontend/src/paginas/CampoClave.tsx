import { useState } from 'react'
import Icono from '../components/Icono'

interface Props {
  id: string
  valor: string
  onCambiar: (v: string) => void
  autoComplete: 'current-password' | 'new-password'
  autoFocus?: boolean
}

export default function CampoClave({ id, valor, onCambiar, autoComplete, autoFocus }: Props) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="input-group input-clave">
      <Icono nombre="escudo" tam={16} />
      <input
        id={id}
        className="input"
        type={visible ? 'text' : 'password'}
        value={valor}
        onChange={(e) => onCambiar(e.target.value)}
        autoComplete={autoComplete}
        autoFocus={autoFocus}
        required
      />
      <button type="button" className="ver-clave" onClick={() => setVisible((v) => !v)} aria-label={visible ? 'Ocultar contraseña' : 'Mostrar contraseña'}>
        <Icono nombre="ojo" tam={16} />
      </button>
    </div>
  )
}

/** Reglas visibles mientras se escribe (el servidor valida las definitivas). */
export function ReglasClave({ clave, confirmacion }: { clave: string; confirmacion?: string }) {
  const reglas = [
    { ok: clave.length >= 10, texto: 'Al menos 10 caracteres' },
    { ok: /\D/.test(clave), texto: 'No solo números' },
    ...(confirmacion !== undefined ? [{ ok: clave.length > 0 && clave === confirmacion, texto: 'Las dos contraseñas coinciden' }] : []),
  ]
  return (
    <ul className="reglas">
      {reglas.map((r) => (
        <li key={r.texto} data-ok={r.ok}>
          <Icono nombre={r.ok ? 'check' : 'menos'} tam={13} grosor={3} /> {r.texto}
        </li>
      ))}
    </ul>
  )
}
