import { useEffect, useRef, useState } from 'react'
import { navegar, useRuta, volver } from '../rutas'
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
  // WCAG 2.4.2: el título de la pestaña dice dónde está la persona (lo leen
  // primero los lectores de pantalla y distingue varias pestañas abiertas).
  const pasoActual = pasos?.lista.find((p) => p.id === pasos.paso)?.nombre
  useEffect(() => {
    document.title = [pasoActual, codigoProceso, 'MiEvaluador'].filter(Boolean).join(' · ')
  }, [pasoActual, codigoProceso])

  return (
    <header className="topbar">
      {/* WCAG 2.4.1 (MinTIC, Res. 1519 de 2020): con teclado o lector de
          pantalla, saltar la barra y llegar directo al contenido. */}
      <a
        className="saltar-contenido"
        href="#contenido"
        onClick={(e) => {
          e.preventDefault()
          const principal = document.querySelector<HTMLElement>('main')
          if (!principal) return
          principal.tabIndex = -1
          principal.focus()
          principal.scrollIntoView()
        }}
      >
        Saltar al contenido principal
      </a>
      <div className="topbar-inner" data-con-pasos={!!pasos}>
        <button type="button" className="brand brand-boton" onClick={() => navegar('/')} aria-label="Ir al inicio">
          <img className="brand-mark" src="/icono-mievaluador.png" alt="" />
          <div className="brand-text">
            <strong className="wordmark">
              <span className="mi">Mi</span>Evaluador
            </strong>
            <span className="sub">{codigoProceso ? `Proceso ${codigoProceso}` : 'by LeMarTek'}</span>
          </div>
        </button>
        {pasos ? (
          // Dentro de un proceso los pasos ocupan el centro: en lugar de los
          // enlaces (no caben) queda siempre un botón para volver.
          <button type="button" className="btn btn-ghost btn-sm volver-topbar" onClick={volver} title="Volver a la pantalla anterior">
            <Icono nombre="atras" tam={15} /> <span className="volver-texto">Volver</span>
          </button>
        ) : (
          <Navegacion />
        )}
        {pasos && <Stepper {...pasos} />}
        <MenuUsuario />
      </div>
    </header>
  )
}

function Navegacion() {
  const sesion = useSesion()
  const ruta = useRuta()
  const [abierto, setAbierto] = useState(false)
  const caja = useRef<HTMLDivElement>(null)
  const [compactaAbierta, setCompactaAbierta] = useState(false)
  const cajaCompacta = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!compactaAbierta) return
    const cerrar = (e: MouseEvent) => {
      if (!cajaCompacta.current?.contains(e.target as Node)) setCompactaAbierta(false)
    }
    const escape = (e: KeyboardEvent) => e.key === 'Escape' && setCompactaAbierta(false)
    document.addEventListener('mousedown', cerrar)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('mousedown', cerrar)
      document.removeEventListener('keydown', escape)
    }
  }, [compactaAbierta])
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
  const enlaces = [
    { ruta: '/', nombre: 'Mis evaluaciones', visible: true, principal: true },
    { ruta: '/procesos', nombre: 'Procesos', visible: true, principal: true },
    { ruta: '/ops', nombre: 'OPS', visible: u.rol !== 'consulta', principal: true },
    { ruta: '/asistente', nombre: 'Asistente', visible: true, principal: true },
    { ruta: '/fila', nombre: 'Fila', visible: u.rol === 'superadmin' || u.rol === 'admin_entidad', principal: false },
    { ruta: '/equipo', nombre: 'Equipo', visible: puedeGestionarEquipo(u), principal: false },
    { ruta: '/metricas', nombre: 'Métricas', visible: u.rol === 'superadmin' || u.rol === 'admin_entidad', principal: false },
    { ruta: '/entidades', nombre: 'Entidades', visible: u.rol === 'superadmin', principal: false },
    { ruta: '/rendimiento', nombre: 'Rendimiento', visible: u.rol === 'superadmin', principal: false },
    { ruta: '/mejoras', nombre: 'Qué falta automatizar', visible: u.rol === 'superadmin' || u.rol === 'soporte', principal: false },
  ].filter((e) => e.visible)
  // Con muchas secciones (administradores) la barra no alcanza: las de
  // gestión pasan a un menú «Más» y quedan a la vista las de uso diario.
  const agrupar = enlaces.length > 5
  const visibles = agrupar ? enlaces.filter((e) => e.principal) : enlaces
  const resto = agrupar ? enlaces.filter((e) => !e.principal) : []
  // Crear algo nuevo no es estar en la lista de procesos ni en la de OPS: en
  // «¿Qué va a hacer?» ninguna sección se marca como la actual.
  const creando = ruta.startsWith('/procesos/nuevo') || ruta === '/ops/nueva'
  const activa = (r: string) => ruta === r || (!creando && (r === '/procesos' || r === '/ops') && ruta.startsWith(r))
  const enResto = resto.find((e) => activa(e.ruta))
  const actual = enlaces.find((e) => activa(e.ruta))
  return (
    <nav className="nav-principal" aria-label="Secciones">
      {/* En pantallas angostas (tableta, celular) las secciones van en un menú. */}
      <div className="nav-compacta" ref={cajaCompacta}>
        <button
          type="button"
          className="nav-compacta-boton"
          aria-expanded={compactaAbierta}
          aria-haspopup="menu"
          onClick={() => setCompactaAbierta((a) => !a)}
        >
          <span className="nav-hamburguesa" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span>{actual?.nombre ?? 'Menú'}</span>
        </button>
        {compactaAbierta && (
          <div className="menu-lista nav-compacta-lista" role="menu">
            {enlaces.map((e) => (
              <button
                key={e.ruta}
                type="button"
                role="menuitem"
                aria-current={activa(e.ruta) ? 'page' : undefined}
                onClick={() => {
                  setCompactaAbierta(false)
                  navegar(e.ruta)
                }}
              >
                {e.nombre}
              </button>
            ))}
          </div>
        )}
      </div>
      {visibles.map((e) => (
        <a
          key={e.ruta}
          className="nav-enlace"
          href={e.ruta}
          aria-current={activa(e.ruta) ? 'page' : undefined}
          onClick={(ev) => {
            ev.preventDefault()
            navegar(e.ruta)
          }}
        >
          {e.nombre}
        </a>
      ))}
      {resto.length > 0 && (
        <div className="nav-mas" ref={caja}>
          <button type="button" className="nav-mas-boton" data-activa={!!enResto} aria-expanded={abierto} aria-haspopup="menu" onClick={() => setAbierto((a) => !a)}>
            {enResto?.nombre ?? 'Más'} <span aria-hidden="true">▾</span>
          </button>
          {abierto && (
            <div className="menu-lista" role="menu">
              {resto.map((e) => (
                <button
                  key={e.ruta}
                  type="button"
                  role="menuitem"
                  aria-current={activa(e.ruta) ? 'page' : undefined}
                  onClick={() => {
                    setAbierto(false)
                    navegar(e.ruta)
                  }}
                >
                  {e.nombre}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
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
              title={p.nombre}
              // En pantallas angostas o ampliadas solo se ve el número: el
              // lector de pantalla debe anunciar el nombre del paso, no «3».
              aria-label={`Paso ${i + 1}: ${p.nombre}`}
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
        <span className="avatar" aria-hidden="true">{iniciales}</span>
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
