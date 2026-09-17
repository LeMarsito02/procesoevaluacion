import QRCode from 'qrcode'
import { useEffect, useState } from 'react'
import Icono from '../components/Icono'
import { configurar2fa, fijarClaveInicial, iniciarSesion, solicitarRecuperacion, verificar2fa, type Usuario } from '../cuentas'
import CampoClave, { ReglasClave } from './CampoClave'
import MarcoAcceso from './MarcoAcceso'
import { mensajeDe } from '../http'

type Etapa = 'credenciales' | 'cambiar_clave' | 'verificar_2fa' | 'configurar_2fa' | 'recuperar' | 'recuperar_enviado'

const PROVEEDORES = ['Microsoft', 'Google', 'Empleados LeMarTek']

export default function PaginaEntrar({ onEntrar }: { onEntrar: (u: Usuario) => void }) {
  const [etapa, setEtapa] = useState<Etapa>('credenciales')
  const [email, setEmail] = useState('')
  const [clave, setClave] = useState('')
  const [codigo, setCodigo] = useState('')
  const [nueva, setNueva] = useState('')
  const [confirmacion, setConfirmacion] = useState('')
  const [qr, setQr] = useState<string | null>(null)
  const [secreto, setSecreto] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (etapa !== 'configurar_2fa' || secreto) return
    configurar2fa()
      .then(async (r) => {
        setSecreto(r.secreto)
        setQr(await QRCode.toDataURL(r.otpauth_uri, { width: 200, margin: 1, color: { dark: '#00143c' } }))
      })
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [etapa, secreto])

  async function ejecutar(accion: () => Promise<void>) {
    setEnviando(true)
    setError(null)
    try {
      await accion()
    } catch (e) {
      setError(mensajeDe(e, 'No se pudo conectar con el servidor.'))
    } finally {
      setEnviando(false)
    }
  }

  const entrar = () =>
    ejecutar(async () => {
      const r = await iniciarSesion(email, clave)
      setClave('')
      if (r.estado === 'ok' && r.usuario) onEntrar(r.usuario)
      else setEtapa(r.estado as Etapa)
    })

  // Primer ingreso (o contraseña reiniciada): elige su contraseña definitiva.
  const cambiar = () =>
    ejecutar(async () => {
      const r = await fijarClaveInicial(nueva)
      setNueva('')
      setConfirmacion('')
      if (r.estado === 'ok' && r.usuario) onEntrar(r.usuario)
      else setEtapa(r.estado as Etapa)
    })

  const verificar = () =>
    ejecutar(async () => {
      try {
        const r = await verificar2fa(codigo)
        if (r.usuario) onEntrar(r.usuario)
      } catch (e) {
        setCodigo('')
        if (e instanceof Error && /Vuelve a|Demasiados/.test(e.message)) {
          setEtapa('credenciales')
          setSecreto(null)
          setQr(null)
        }
        throw e
      }
    })

  const recuperar = () =>
    ejecutar(async () => {
      await solicitarRecuperacion(email)
      setEtapa('recuperar_enviado')
    })

  const alerta = error && (
    <div className="callout callout-bad" role="alert">
      <Icono nombre="alerta" />
      <div>{error}</div>
    </div>
  )

  if (etapa === 'cambiar_clave') {
    return (
      <MarcoAcceso>
        <div className="eyebrow">Primer ingreso</div>
        <h1 className="acceso-titulo">Elija su contraseña</h1>
        <p className="muted">
          Entró con la contraseña temporal que le entregaron. Escoja una propia: nadie más debe conocerla, ni siquiera quien creó su
          cuenta.
        </p>
        <form
          className="acceso-form"
          onSubmit={(e) => {
            e.preventDefault()
            cambiar()
          }}
        >
          <div className="field">
            <label htmlFor="nueva">Contraseña nueva</label>
            <CampoClave id="nueva" valor={nueva} onCambiar={setNueva} autoComplete="new-password" autoFocus />
          </div>
          <div className="field">
            <label htmlFor="nueva2">Repita la contraseña</label>
            <CampoClave id="nueva2" valor={confirmacion} onCambiar={setConfirmacion} autoComplete="new-password" />
            <ReglasClave clave={nueva} confirmacion={confirmacion} />
          </div>
          {alerta}
          <button className="btn btn-primary btn-lg btn-bloque" type="submit" disabled={enviando || nueva !== confirmacion || nueva.length < 10}>
            {enviando ? <span className="spinner" /> : 'Guardar y entrar'}
          </button>
          <button type="button" className="btn btn-ghost btn-bloque" onClick={() => window.location.reload()}>
            Volver al inicio
          </button>
        </form>
      </MarcoAcceso>
    )
  }

  if (etapa === 'verificar_2fa' || etapa === 'configurar_2fa') {
    return (
      <MarcoAcceso>
        <div className="eyebrow">Verificación en dos pasos</div>
        <h1 className="acceso-titulo">{etapa === 'configurar_2fa' ? 'Proteja su cuenta' : 'Ingrese su código'}</h1>
        {etapa === 'configurar_2fa' ? (
          <div className="dos-pasos">
            <p className="muted">
              Su cuenta tiene acceso a todas las entidades, así que requiere un segundo factor. Escanee este código con Google
              Authenticator, Microsoft Authenticator o similar.
            </p>
            <div className="qr">{qr ? <img src={qr} alt="Código QR para la app autenticadora" /> : <span className="spinner oscuro" />}</div>
            {secreto && (
              <p className="small muted">
                ¿No puede escanear? Clave manual: <code className="secreto">{secreto}</code>
              </p>
            )}
          </div>
        ) : (
          <p className="muted">Abra su app autenticadora y escriba el código de 6 dígitos de MiEvaluador.</p>
        )}
        <form
          className="acceso-form"
          onSubmit={(e) => {
            e.preventDefault()
            verificar()
          }}
        >
          <div className="field">
            <label htmlFor="codigo">Código de 6 dígitos</label>
            <input
              id="codigo"
              className="input input-codigo"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={7}
              value={codigo}
              onChange={(e) => setCodigo(e.target.value.replace(/[^\d ]/g, ''))}
              autoFocus
              required
            />
          </div>
          {alerta}
          <button className="btn btn-primary btn-lg btn-bloque" type="submit" disabled={enviando || codigo.replace(/\D/g, '').length !== 6}>
            {enviando ? <span className="spinner" /> : 'Verificar y entrar'}
          </button>
          <button type="button" className="btn btn-ghost btn-bloque" onClick={() => window.location.reload()}>
            Volver al inicio
          </button>
        </form>
      </MarcoAcceso>
    )
  }

  if (etapa === 'recuperar' || etapa === 'recuperar_enviado') {
    return (
      <MarcoAcceso>
        <div className="eyebrow">Recuperar acceso</div>
        <h1 className="acceso-titulo">¿Olvidó su contraseña?</h1>
        {etapa === 'recuperar_enviado' ? (
          <div className="acceso-form">
            <div className="callout callout-ok">
              <Icono nombre="check" />
              <div>
                Si <strong>{email}</strong> tiene una cuenta, le llegará un correo con un enlace para crear una contraseña nueva. El
                enlace vence en 2 horas.
              </div>
            </div>
            <button type="button" className="btn btn-secondary btn-bloque" onClick={() => setEtapa('credenciales')}>
              <Icono nombre="atras" /> Volver a iniciar sesión
            </button>
          </div>
        ) : (
          <form
            className="acceso-form"
            onSubmit={(e) => {
              e.preventDefault()
              recuperar()
            }}
          >
            <p className="muted">Escriba el correo de su cuenta y le enviaremos un enlace para restablecerla.</p>
            <div className="field">
              <label htmlFor="email">Correo electrónico</label>
              <input id="email" className="input" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus required />
            </div>
            {alerta}
            <button className="btn btn-primary btn-lg btn-bloque" type="submit" disabled={enviando}>
              {enviando ? <span className="spinner" /> : 'Enviar enlace'}
            </button>
            <button type="button" className="btn btn-ghost btn-bloque" onClick={() => setEtapa('credenciales')}>
              <Icono nombre="atras" /> Volver
            </button>
          </form>
        )}
      </MarcoAcceso>
    )
  }

  return (
    <MarcoAcceso>
      <div className="eyebrow">Bienvenido</div>
      <h1 className="acceso-titulo">Inicie sesión</h1>
      <form
        className="acceso-form"
        onSubmit={(e) => {
          e.preventDefault()
          entrar()
        }}
      >
        <div className="field">
          <label htmlFor="email">Correo electrónico</label>
          <div className="input-group">
            <Icono nombre="usuarios" tam={16} />
            <input id="email" className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus required />
          </div>
        </div>
        <div className="field">
          <div className="label-fila">
            <label htmlFor="clave">Contraseña</label>
            <button type="button" className="enlace" onClick={() => setEtapa('recuperar')}>
              ¿Olvidó su contraseña?
            </button>
          </div>
          <CampoClave id="clave" valor={clave} onCambiar={setClave} autoComplete="current-password" />
        </div>
        {alerta}
        <button className="btn btn-primary btn-lg btn-bloque" type="submit" disabled={enviando}>
          {enviando ? <span className="spinner" /> : 'Entrar'}
        </button>
      </form>

      <div className="separador">
        <span>o continúe con</span>
      </div>
      <div className="proveedores">
        {PROVEEDORES.map((p) => (
          <button key={p} type="button" className="btn btn-secondary btn-bloque proveedor" disabled title="Disponible próximamente">
            {p}
            <span className="tag">Próximamente</span>
          </button>
        ))}
      </div>
      <p className="small muted acceso-nota">¿No tiene cuenta? El administrador de su entidad debe crearla y entregarle sus credenciales.</p>
    </MarcoAcceso>
  )
}
