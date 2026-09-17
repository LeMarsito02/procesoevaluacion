import { useEffect, useMemo, useState } from 'react'
import Icono from '../components/Icono'
import {
  actualizarUsuario,
  AREAS,
  invitar,
  listarAuditoria,
  listarEntidades,
  listarInvitaciones,
  listarUsuarios,
  revocarInvitacion,
  ROLES,
  type Entidad,
  type EventoAuditoria,
  type Invitacion,
  type Miembro,
  type Rol,
  type TipoArea,
} from '../cuentas'
import { useSesion } from '../sesion'
import { mensajeDe } from '../http'

type Pestana = 'usuarios' | 'invitaciones' | 'actividad'

const fecha = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' }) : '—'

const ACCIONES: Record<string, string> = {
  'sesion.inicio': 'Inició sesión',
  'sesion.cierre': 'Cerró sesión',
  'invitacion.creada': 'Envió una invitación',
  'invitacion.aceptada': 'Aceptó la invitación',
  'invitacion.revocada': 'Revocó una invitación',
  'usuario.actualizado': 'Modificó un usuario',
  'usuario.cambio_clave': 'Cambió su contraseña',
  'usuario.clave_restablecida': 'Restableció su contraseña',
  'usuario.recuperacion_solicitada': 'Pidió recuperar la contraseña',
  'usuario.2fa_activado': 'Activó la verificación en dos pasos',
  'entidad.creada': 'Creó la entidad',
  'entidad.suspendida': 'Suspendió la entidad',
  'entidad.activada': 'Reactivó la entidad',
}

export default function PaginaEquipo() {
  const sesion = useSesion()!
  const yo = sesion.usuario
  const esSuper = yo.rol === 'superadmin'
  const esAdmin = esSuper || yo.rol === 'admin_entidad'

  const [entidades, setEntidades] = useState<Entidad[]>([])
  const [entidadId, setEntidadId] = useState<string | null>(esSuper ? null : (yo.entidad?.id ?? null))
  const [pestana, setPestana] = useState<Pestana>('usuarios')
  const [usuarios, setUsuarios] = useState<Miembro[]>([])
  const [invitaciones, setInvitaciones] = useState<Invitacion[]>([])
  const [eventos, setEventos] = useState<EventoAuditoria[]>([])
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [invitando, setInvitando] = useState(false)
  const [filtro, setFiltro] = useState('')

  useEffect(() => {
    if (!esSuper) return
    listarEntidades()
      .then((lista) => {
        setEntidades(lista)
        setEntidadId((actual) => actual ?? lista[0]?.id ?? null)
      })
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [esSuper])

  const idConsulta = esSuper ? entidadId : null
  const claveCarga = esSuper ? entidadId : 'propia'
  const [cargadaPara, setCargadaPara] = useState<string | null>(null)
  const cargando = claveCarga !== null && cargadaPara !== claveCarga

  useEffect(() => {
    if (claveCarga === null) return
    let vigente = true
    Promise.all([
      listarUsuarios(idConsulta),
      esAdmin ? listarInvitaciones(idConsulta) : Promise.resolve([]),
      esAdmin ? listarAuditoria(idConsulta) : Promise.resolve([]),
    ])
      .then(([u, i, a]) => {
        if (!vigente) return
        setUsuarios(u)
        setInvitaciones(i)
        setEventos(a)
        setError(null)
      })
      .catch((e: unknown) => vigente && setError(mensajeDe(e)))
      .finally(() => vigente && setCargadaPara(claveCarga))
    return () => {
      vigente = false
    }
  }, [claveCarga, idConsulta, esAdmin])

  useEffect(() => {
    if (!aviso) return
    const id = window.setTimeout(() => setAviso(null), 3500)
    return () => window.clearTimeout(id)
  }, [aviso])

  async function cambiar(u: Miembro, cambios: { rol?: Rol; areas?: TipoArea[]; activo?: boolean }) {
    try {
      const nuevo = await actualizarUsuario(u.id, cambios)
      setUsuarios((lista) => lista.map((x) => (x.id === u.id ? nuevo : x)))
      setAviso('Cambios guardados')
    } catch (e) {
      setError(mensajeDe(e, 'No se pudo guardar.'))
    }
  }

  const visibles = useMemo(() => {
    const t = filtro.trim().toLowerCase()
    return t ? usuarios.filter((u) => `${u.nombre_completo} ${u.email}`.toLowerCase().includes(t)) : usuarios
  }, [usuarios, filtro])

  const nombreEntidad = esSuper ? entidades.find((e) => e.id === entidadId)?.nombre : yo.entidad?.nombre

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">{nombreEntidad ?? 'Equipo'}</div>
          <h1>Equipo</h1>
          <p>{esAdmin ? 'Invite personas, asígneles un rol y las áreas donde evalúan.' : 'Personas de sus áreas.'}</p>
        </div>
        <div className="acciones">
          {esSuper && (
            <select className="select" value={entidadId ?? ''} onChange={(e) => setEntidadId(e.target.value)} aria-label="Entidad">
              {entidades.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.nombre}
                </option>
              ))}
            </select>
          )}
          {esAdmin && (
            <button className="btn btn-primary" type="button" onClick={() => setInvitando(true)} disabled={!entidadId}>
              <Icono nombre="mas" /> Invitar persona
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="callout callout-bad" style={{ marginBottom: 16 }} role="alert">
          <Icono nombre="alerta" />
          <div style={{ flex: 1 }}>{error}</div>
          <button className="btn btn-ghost btn-sm" type="button" onClick={() => setError(null)}>
            Cerrar
          </button>
        </div>
      )}

      {esAdmin && (
        <div className="toolbar">
          <div className="segmented" role="tablist">
            <button type="button" aria-pressed={pestana === 'usuarios'} onClick={() => setPestana('usuarios')}>
              Usuarios ({usuarios.length})
            </button>
            <button type="button" aria-pressed={pestana === 'invitaciones'} onClick={() => setPestana('invitaciones')}>
              Invitaciones pendientes ({invitaciones.length})
            </button>
            <button type="button" aria-pressed={pestana === 'actividad'} onClick={() => setPestana('actividad')}>
              Actividad
            </button>
          </div>
          {pestana === 'usuarios' && (
            <div className="input-group search" style={{ marginLeft: 'auto' }}>
              <Icono nombre="buscar" tam={16} />
              <input className="input" placeholder="Buscar por nombre o correo" value={filtro} onChange={(e) => setFiltro(e.target.value)} />
            </div>
          )}
        </div>
      )}

      {cargando ? (
        <div className="vacio">
          <span className="spinner oscuro" />
        </div>
      ) : pestana === 'usuarios' ? (
        <div className="tabla-wrap">
          <table className="tabla">
            <thead>
              <tr>
                <th>Persona</th>
                <th>Rol</th>
                <th>Áreas</th>
                <th>Último ingreso</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {visibles.map((u) => {
                const soyYo = u.id === yo.id
                const editable = esAdmin && !soyYo
                return (
                  <tr key={u.id} data-inactivo={!u.activo}>
                    <td>
                      <div className="persona">
                        <span className="avatar">{iniciales(u.nombre_completo)}</span>
                        <div>
                          <strong>
                            {u.nombre_completo} {soyYo && <span className="tag">Usted</span>}
                          </strong>
                          <div className="small muted">{u.email}</div>
                        </div>
                      </div>
                    </td>
                    <td>
                      {editable ? (
                        <select className="select select-sm" value={u.rol} onChange={(e) => cambiar(u, { rol: e.target.value as Rol })}>
                          {ROLES.map((r) => (
                            <option key={r.id} value={r.id}>
                              {r.nombre}
                            </option>
                          ))}
                        </select>
                      ) : (
                        u.rol_nombre
                      )}
                    </td>
                    <td>
                      <div className="chips">
                        {AREAS.map((a) => {
                          const activa = u.areas.some((x) => x.tipo === a.id)
                          if (!esAdmin) return activa ? <span key={a.id} className="chip" data-activo="true">{a.nombre}</span> : null
                          return (
                            <button
                              key={a.id}
                              type="button"
                              className="chip"
                              data-activo={activa}
                              aria-pressed={activa}
                              onClick={() => {
                                const actuales = u.areas.map((x) => x.tipo)
                                cambiar(u, { areas: activa ? actuales.filter((t) => t !== a.id) : [...actuales, a.id] })
                              }}
                            >
                              {a.nombre}
                            </button>
                          )
                        })}
                      </div>
                    </td>
                    <td className="small muted nowrap">{fecha(u.ultimo_ingreso)}</td>
                    <td>
                      {editable ? (
                        <button
                          type="button"
                          className={`btn btn-sm ${u.activo ? 'btn-ghost' : 'btn-secondary'}`}
                          onClick={() => {
                            if (!u.activo || window.confirm(`¿Desactivar a ${u.nombre_completo}? Perderá el acceso de inmediato.`)) {
                              cambiar(u, { activo: !u.activo })
                            }
                          }}
                        >
                          {u.activo ? 'Desactivar' : 'Reactivar'}
                        </button>
                      ) : (
                        <span className="pill" data-estado={u.activo ? 'cumple' : 'no_aplica'}>
                          <span className="dot" /> {u.activo ? 'Activo' : 'Inactivo'}
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
              {visibles.length === 0 && (
                <tr>
                  <td colSpan={5} className="vacio">
                    No hay usuarios que coincidan.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : pestana === 'invitaciones' ? (
        <div className="tabla-wrap">
          <table className="tabla">
            <thead>
              <tr>
                <th>Correo</th>
                <th>Rol</th>
                <th>Áreas</th>
                <th>Vence</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {invitaciones.map((i) => (
                <tr key={i.id}>
                  <td>
                    <strong>{i.email}</strong>
                  </td>
                  <td>{i.rol_nombre}</td>
                  <td className="small">{i.areas.map((t) => AREAS.find((a) => a.id === t)?.nombre).join(', ') || '—'}</td>
                  <td className="small nowrap">
                    {i.vigente ? fecha(i.expira_en) : <span className="pill" data-estado="error">Vencida</span>}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <button
                      type="button"
                      className="btn btn-bad btn-sm"
                      onClick={async () => {
                        try {
                          await revocarInvitacion(i.id)
                          setInvitaciones((l) => l.filter((x) => x.id !== i.id))
                          setAviso('Invitación revocada')
                        } catch (e) {
                          setError(mensajeDe(e, 'No se pudo revocar.'))
                        }
                      }}
                    >
                      Revocar
                    </button>
                  </td>
                </tr>
              ))}
              {invitaciones.length === 0 && (
                <tr>
                  <td colSpan={5} className="vacio">
                    No hay invitaciones pendientes.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="tabla-wrap">
          <table className="tabla">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Quién</th>
                <th>Acción</th>
                <th>Detalle</th>
              </tr>
            </thead>
            <tbody>
              {eventos.map((ev, n) => (
                <tr key={n}>
                  <td className="small nowrap">{fecha(ev.fecha)}</td>
                  <td className="small">{ev.usuario ?? '—'}</td>
                  <td>{ACCIONES[ev.accion] ?? ev.accion}</td>
                  <td className="small muted">{detalle(ev.detalles)}</td>
                </tr>
              ))}
              {eventos.length === 0 && (
                <tr>
                  <td colSpan={4} className="vacio">
                    Aún no hay actividad registrada.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {invitando && entidadId && (
        <DialogoInvitar
          entidadId={idConsulta}
          onCerrar={() => setInvitando(false)}
          onInvitado={(inv) => {
            setInvitando(false)
            setInvitaciones((l) => [inv, ...l.filter((x) => x.email !== inv.email)])
            setAviso(`Invitación enviada a ${inv.email}`)
          }}
        />
      )}
      {aviso && <div className="toast">{aviso}</div>}
    </main>
  )
}

function iniciales(nombre: string) {
  return nombre
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('')
}

function detalle(d: Record<string, unknown>) {
  return Object.entries(d)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.map((x) => (Array.isArray(x) ? x.join(', ') || '—' : String(x))).join(' → ') : String(v)}`)
    .join(' · ')
}

function DialogoInvitar({
  entidadId,
  onCerrar,
  onInvitado,
}: {
  entidadId: string | null
  onCerrar: () => void
  onInvitado: (i: Invitacion) => void
}) {
  const [email, setEmail] = useState('')
  const [rol, setRol] = useState<Rol>('evaluador')
  const [areas, setAreas] = useState<TipoArea[]>(['juridica'])
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const necesitaArea = rol === 'jefe_area' || rol === 'evaluador'

  async function enviar() {
    setEnviando(true)
    setError(null)
    try {
      onInvitado(await invitar({ email, rol, areas }, entidadId))
    } catch (e) {
      setError(mensajeDe(e, 'No se pudo invitar.'))
      setEnviando(false)
    }
  }

  return (
    <>
      <div className="overlay" onClick={onCerrar} />
      <div className="dialogo" role="dialog" aria-modal="true" aria-labelledby="titulo-invitar">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            enviar()
          }}
        >
          <div className="card-head">
            <div>
              <h2 id="titulo-invitar">Invitar persona</h2>
              <p>Recibirá un correo para crear su contraseña. El enlace vence en 7 días.</p>
            </div>
            <button type="button" className="btn btn-ghost btn-icon" onClick={onCerrar} aria-label="Cerrar">
              <Icono nombre="x" />
            </button>
          </div>
          <div className="field" style={{ marginBottom: 18 }}>
            <label htmlFor="inv-email">Correo electrónico</label>
            <input id="inv-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus required />
          </div>
          <div className="field" style={{ marginBottom: 18 }}>
            <label>Rol</label>
            <div className="opciones">
              {ROLES.map((r) => (
                <label key={r.id} className="opcion" data-activo={rol === r.id}>
                  <input type="radio" name="rol" value={r.id} checked={rol === r.id} onChange={() => setRol(r.id)} />
                  <div>
                    <strong>{r.nombre}</strong>
                    <span className="small muted">{r.descripcion}</span>
                  </div>
                </label>
              ))}
            </div>
          </div>
          <div className="field">
            <label>Áreas</label>
            <div className="chips">
              {AREAS.map((a) => {
                const activa = areas.includes(a.id)
                return (
                  <button
                    key={a.id}
                    type="button"
                    className="chip"
                    data-activo={activa}
                    aria-pressed={activa}
                    onClick={() => setAreas((l) => (activa ? l.filter((t) => t !== a.id) : [...l, a.id]))}
                  >
                    {activa && <Icono nombre="check" tam={12} grosor={3} />} {a.nombre}
                  </button>
                )
              })}
            </div>
            {necesitaArea && areas.length === 0 && <span className="hint">Elija al menos un área para que pueda evaluar.</span>}
          </div>
          {error && (
            <div className="callout callout-bad" style={{ marginTop: 16 }} role="alert">
              <Icono nombre="alerta" />
              <div>{error}</div>
            </div>
          )}
          <div className="dialogo-pie">
            <button type="button" className="btn btn-ghost" onClick={onCerrar}>
              Cancelar
            </button>
            <button type="submit" className="btn btn-primary" disabled={enviando || (necesitaArea && areas.length === 0)}>
              {enviando ? <span className="spinner" /> : 'Enviar invitación'}
            </button>
          </div>
        </form>
      </div>
    </>
  )
}
