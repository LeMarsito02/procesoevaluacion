import { useCallback, useEffect, useState } from 'react'
import Topbar from './components/Topbar'
import { cerrarSesion, obtenerYo, type Usuario } from './cuentas'
import { ErrorApi, MENSAJE_SISTEMA } from './http'
import PaginaConfiguracion from './paginas/PaginaConfiguracion'
import PaginaCuenta from './paginas/PaginaCuenta'
import PaginaEntidades from './paginas/PaginaEntidades'
import PaginaEntrar from './paginas/PaginaEntrar'
import PaginaEquipo from './paginas/PaginaEquipo'
import PaginaEvaluacion from './paginas/PaginaEvaluacion'
import PaginaFila from './paginas/PaginaFila'
import PaginaInicio from './paginas/PaginaInicio'
import PaginaNuevoProceso from './paginas/PaginaNuevoProceso'
import PaginaProcesos from './paginas/PaginaProcesos'
import PaginaInvitacion from './paginas/PaginaInvitacion'
import PaginaRestablecer from './paginas/PaginaRestablecer'
import { encajar, navegar, useRuta } from './rutas'
import { ContextoSesion, puedeCrearProcesos, puedeGestionarEquipo } from './sesion'

export default function Raiz() {
  const ruta = useRuta()
  const [usuario, setUsuario] = useState<Usuario | null>(null)
  const [cargando, setCargando] = useState(true)
  const [errorConexion, setErrorConexion] = useState(false)

  const consultarSesion = useCallback(
    () =>
      obtenerYo()
        .then((u) => {
          setUsuario(u)
          setErrorConexion(false)
        })
        .catch((e) => {
          setUsuario(null)
          setErrorConexion(!(e instanceof ErrorApi) || e.esDelSistema)
        })
        .finally(() => setCargando(false)),
    [],
  )

  useEffect(() => {
    consultarSesion()
  }, [consultarSesion])

  const comprobar = () => {
    setCargando(true)
    consultarSesion()
  }

  useEffect(() => {
    const vencida = () => setUsuario(null)
    window.addEventListener('sesion-vencida', vencida)
    return () => window.removeEventListener('sesion-vencida', vencida)
  }, [])

  const entrar = (u: Usuario) => {
    setUsuario(u)
    if (encajar('/invitacion/:token', ruta) || encajar('/restablecer/:uid/:token', ruta)) navegar('/', true)
  }

  const salir = useCallback(async () => {
    try {
      await cerrarSesion()
    } finally {
      setUsuario(null)
      navegar('/', true)
    }
  }, [])

  // Rutas públicas (con o sin sesión).
  const invitacion = encajar('/invitacion/:token', ruta)
  if (invitacion) return <PaginaInvitacion token={invitacion.token} onEntrar={entrar} />
  const restablecer = encajar('/restablecer/:uid/:token', ruta)
  if (restablecer) return <PaginaRestablecer uid={restablecer.uid} token={restablecer.token} />

  if (cargando) {
    return (
      <div className="pantalla-carga">
        <img src="/icono-mievaluador.png" alt="" width={56} height={56} />
        <span className="spinner oscuro" />
      </div>
    )
  }

  if (errorConexion) {
    return (
      <div className="pantalla-carga">
        <img src="/icono-mievaluador.png" alt="" width={56} height={56} />
        <p className="muted" style={{ maxWidth: 420, textAlign: 'center' }}>{MENSAJE_SISTEMA}</p>
        <button type="button" className="btn btn-primary" onClick={comprobar}>
          Reintentar
        </button>
      </div>
    )
  }

  if (!usuario) return <PaginaEntrar onEntrar={entrar} />

  const evaluacion = encajar('/evaluaciones/:id', ruta)
  let pagina: React.ReactNode
  let conTopbar = true
  if (evaluacion) {
    pagina = <PaginaEvaluacion key={evaluacion.id} id={evaluacion.id} />
    conTopbar = false
  } else if (ruta === '/procesos/nuevo' && puedeCrearProcesos(usuario)) {
    pagina = <PaginaNuevoProceso />
    conTopbar = false
  } else if (ruta === '/procesos') pagina = <PaginaProcesos />
  else if (ruta === '/configuracion' && (usuario.rol === 'superadmin' || usuario.rol === 'admin_entidad')) pagina = <PaginaConfiguracion />
  else if (ruta === '/fila' && (usuario.rol === 'superadmin' || usuario.rol === 'admin_entidad')) pagina = <PaginaFila />
  else if (ruta === '/equipo' && puedeGestionarEquipo(usuario)) pagina = <PaginaEquipo />
  else if (ruta === '/entidades' && usuario.rol === 'superadmin') pagina = <PaginaEntidades />
  else if (ruta === '/cuenta') pagina = <PaginaCuenta />
  else pagina = <PaginaInicio />

  return (
    <ContextoSesion.Provider value={{ usuario, salir }}>
      {conTopbar && <Topbar />}
      {pagina}
    </ContextoSesion.Provider>
  )
}
