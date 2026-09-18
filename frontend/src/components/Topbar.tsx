import { useEffect, useRef, useState } from 'react'
import { navegar, useRuta } from '../rutas'
import { puedeGestionarEquipo, useSesion } from '../sesion'
import type { Paso } from '../pasos'
import Icono from './Icono'

interface PropsPasos {
  lista: { id: Paso; nombre: string }[]
  paso: Paso
  pasosDisponibles: Set<Paso>
  onIr: (paso: Paso) => void
}

interface Props {
  codigoProceso?: string | null
  /** Solo en la pantalla de evaluación. */
  pasos?: PropsPasos
}

export default function Topbar({ codigoProceso = null, pasos }: Props) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <button type="button" className="brand brand-boton" onClick={() => navegar('/')} aria-label="Ir al inicio">
          <img className="brand-mark" src="/icono-mievaluador.png" alt="" />
          <div className="brand-text">
            <strong className="wordmark">
              <span className="mi">Mi</span>Evaluador
            </strong>
            <span className="sub">{codigoProceso ? `Proceso ${codigoProceso}` : 'by LeMarTek'}</span>
          </div>
        </button>
        <Navegacion compacta={!!pasos} />
        {pasos && <Stepper {...pasos} />}
        <MenuUsuario />
      </div>
    </header>
  )
}

function Navegacion({ compacta }: { compacta: boolean }) {
  const sesion = useSesion()
  const ruta = useRuta()
  if (!sesion) return null
  const u = sesion.usuario
  const enlaces = [
    { ruta: '/', nombre: 'Mis evaluaciones', visible: true },
    { ruta: '/procesos', nombre: 'Procesos', visible: true },
    { ruta: '/fila', nombre: 'Fila', visible: u.rol === 'superadmin' || u.rol === 'admin_entidad' },
    { ruta: '/equipo', nombre: 'Equipo', visible: puedeGestionarEquipo(u) },
    { ruta: '/entidades', nombre: 'Entidades', visible: u.rol === 'superadmin' },
  ]
  return (
    <nav className="nav-principal" data-compacta={compacta} aria-label="Secciones">
      {enlaces
        .filter((e) => e.visible)
        .map((e) => (
          <a
            key={e.ruta}
            href={e.ruta}
            aria-current={ruta === e.ruta || (e.ruta === '/procesos' && ruta.startsWith('/procesos')) ? 'page' : undefined}
            onClick={(ev) => {
              ev.preventDefault()
              navegar(e.ruta)
            }}
          >
            {e.nombre}
          </a>
        ))}
    </nav>
  )
}

function Stepper({ lista, paso, pasosDisponibles, onIr }: PropsPasos) {
  const indiceActual = lista.findIndex((p) => p.id === paso)
  return (
    <nav className="stepper" aria-label="Pasos de la evaluación">
      {lista.map((p, i) => {
        const estado = i === indiceActual ? 'active' : i < indiceActual ? 'done' : 'todo'
        const clicable = p.id !== paso && pasosDisponibles.has(p.id)
        return (
          <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {i > 0 && <span className="step-sep" />}
            <button
              type="button"
              className="step"
              data-state={estado}
              data-clickable={clicable}
              disabled={!clicable}
              onClick={() => clicable && onIr(p.id)}
              aria-current={estado === 'active' ? 'step' : undefined}
            >
              <span className="step-dot">{estado === 'done' ? <Icono nombre="check" tam={13} grosor={3} /> : i + 1}</span>
              <span className="step-nombre">{p.nombre}</span>
            </button>
          </div>
        )
      })}
    </nav>
  )
}

function MenuUsuario() {
  const sesion = useSesion()
  const [abierto, setAbierto] = useState(false)
  const caja = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!abierto) return
    const cerrar = (e: MouseEvent) => {
      if (!caja.current?.contains(e.target as Node)) setAbierto(false)
    }
    const escape = (e: KeyboardEvent) => e.key === 'Escape' && setAbierto(false)
    document.addEventListener('mousedown', cerrar)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('mousedown', cerrar)
      document.removeEventListener('keydown', escape)
    }
  }, [abierto])

  if (!sesion) return null
  const u = sesion.usuario
  const iniciales = u.nombre_completo
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('')

  const ir = (ruta: string) => {
    setAbierto(false)
    navegar(ruta)
  }

  return (
    <div className="menu-usuario" ref={caja}>
      <button type="button" className="menu-boton" onClick={() => setAbierto((a) => !a)} aria-expanded={abierto} aria-haspopup="menu">
        <span className="avatar">{iniciales}</span>
        <span className="menu-nombre">
          <strong>{u.nombre_completo.split(' ')[0]}</strong>
          <span>{u.entidad?.nombre ?? u.rol_nombre}</span>
        </span>
      </button>
      {abierto && (
        <div className="menu-lista" role="menu">
          <div className="menu-cabecera">
            <strong>{u.nombre_completo}</strong>
            <span className="small muted">{u.email}</span>
            <span className="tag" style={{ marginTop: 6, alignSelf: 'flex-start' }}>
              {u.rol_nombre}
            </span>
          </div>
          <button type="button" role="menuitem" onClick={() => ir('/')}>
            <Icono nombre="balanza" tam={16} /> Mis evaluaciones
          </button>
          <button type="button" role="menuitem" onClick={() => ir('/procesos')}>
            <Icono nombre="carpeta" tam={16} /> Procesos de la entidad
          </button>
          {(u.rol === 'superadmin' || u.rol === 'admin_entidad') && (
            <button type="button" role="menuitem" onClick={() => ir('/fila')}>
              <Icono nombre="reloj" tam={16} /> Fila de evaluación
            </button>
          )}
          {(u.rol === 'superadmin' || u.rol === 'admin_entidad') && (
            <button type="button" role="menuitem" onClick={() => ir('/configuracion')}>
              <Icono nombre="documento" tam={16} /> Configuración de la entidad
            </button>
          )}
          {puedeGestionarEquipo(u) && (
            <button type="button" role="menuitem" onClick={() => ir('/equipo')}>
              <Icono nombre="usuarios" tam={16} /> Equipo
            </button>
          )}
          {u.rol === 'superadmin' && (
            <button type="button" role="menuitem" onClick={() => ir('/entidades')}>
              <Icono nombre="escudo" tam={16} /> Entidades
            </button>
          )}
          <button type="button" role="menuitem" onClick={() => ir('/cuenta')}>
            <Icono nombre="lapiz" tam={16} /> Mi cuenta y contraseña
          </button>
          <button type="button" role="menuitem" className="menu-salir" onClick={sesion.salir}>
            <Icono nombre="atras" tam={16} /> Cerrar sesión
          </button>
        </div>
      )}
    </div>
  )
}
