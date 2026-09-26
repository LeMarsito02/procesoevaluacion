import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import Icono from './components/Icono'
import Topbar from './components/Topbar'
import { cerrarSesion, obtenerYo, salirDeEntidad, type Usuario } from './cuentas'
import { ErrorApi, MENSAJE_SISTEMA } from './http'
import PaginaCuenta from './paginas/PaginaCuenta'
import PaginaEntrar from './paginas/PaginaEntrar'
import PaginaEvaluacion from './paginas/PaginaEvaluacion'
import PaginaInicio from './paginas/PaginaInicio'
import PaginaNuevoProceso from './paginas/PaginaNuevoProceso'
import PaginaProcesos from './paginas/PaginaProcesos'
const PaginaConfiguracion = lazy(() => import('./paginas/PaginaConfiguracion'))
const PaginaEntidades = lazy(() => import('./paginas/PaginaEntidades'))
const PaginaEquipo = lazy(() => import('./paginas/PaginaEquipo'))
const PaginaFila = lazy(() => import('./paginas/PaginaFila'))
const PaginaMejoras = lazy(() => import('./paginas/PaginaMejoras'))
const PaginaRendimiento = lazy(() => import('./paginas/PaginaRendimiento'))
const PaginaSoporte = lazy(() => import('./paginas/PaginaSoporte'))
const PaginaRestablecer = lazy(() => import('./paginas/PaginaRestablecer'))

import { encajar, navegar, useRuta } from './rutas'
import { ContextoSesion, puedeCrearProcesos, puedeGestionarEquipo } from './sesion'

/** Mientras llega el trozo de una página que se carga aparte. Es el mismo
 * indicador que usan las páginas al pedir sus datos, así que no se nota el
 * cambio. */
function Cargando() {
  return (
    <div className="cargando-pagina" role="status">
      <span className="spinner oscuro" /> Cargando…
    </div>
  )
}

export default function Raiz() {
  const ruta = useRuta()
  const [usuario, setUsuario] = useState<Usuario | null>(null)
  const [cargando, setCargando] = useState(true)
  const [errorConexion, setErrorConexion] = useState(false)
  const [saliendoEntidad, setSaliendoEntidad] = useState(false)

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

  // La insignia de reCAPTCHA solo en la pantalla de acceso (donde se usa).
  useEffect(() => {
    document.body.dataset.conSesion = String(!!usuario)
  }, [usuario])

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
    if (encajar('/restablecer/:uid/:token', ruta)) navegar('/', true)
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
  const restablecer = encajar('/restablecer/:uid/:token', ruta)
  if (restablecer)
    return (
      <Suspense fallback={<Cargando />}>
        <PaginaRestablecer uid={restablecer.uid} token={restablecer.token} />
      </Suspense>
    )

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

  if (usuario.rol === 'soporte' && !usuario.entidad) {
    return (
      <ContextoSesion.Provider value={{ usuario, salir }}>
        <Topbar />
        <Suspense fallback={<Cargando />}>
          <PaginaSoporte
            onEntrar={(u) => {
              setUsuario(u)
              navegar('/', true)
            }}
          />
        </Suspense>
      </ContextoSesion.Provider>
    )
  }

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
  else if (ruta === '/rendimiento' && usuario.rol === 'superadmin') pagina = <PaginaRendimiento />
  // El registro junta información de varias entidades: solo nosotros.
  else if (ruta === '/mejoras' && (usuario.rol === 'superadmin' || usuario.rol === 'soporte')) pagina = <PaginaMejoras />
  else if (ruta === '/cuenta') pagina = <PaginaCuenta />
  else pagina = <PaginaInicio />

  return (
    <ContextoSesion.Provider value={{ usuario, salir }}>
      {usuario.acceso_soporte_hasta && (
        <div className="aviso-soporte" role="status">
          <Icono nombre="escudo" tam={15} /> Acceso de soporte a <strong>{usuario.entidad?.nombre}</strong> · solo lectura · hasta{' '}
          {new Date(usuario.acceso_soporte_hasta).toLocaleString('es-CO', { dateStyle: 'short', timeStyle: 'short' })}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={saliendoEntidad}
            onClick={() => {
              setSaliendoEntidad(true)
              salirDeEntidad()
                .then((u) => setUsuario(u))
                .catch(() => window.location.reload())
                .finally(() => setSaliendoEntidad(false))
            }}
          >
            {saliendoEntidad ? <span className="spinner oscuro" /> : null} Salir de la entidad
          </button>
        </div>
      )}
      {conTopbar && <Topbar />}
      <Suspense fallback={<Cargando />}>{pagina}</Suspense>
    </ContextoSesion.Provider>
  )
}
