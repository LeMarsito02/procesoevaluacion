import { useEffect, useState } from 'react'
import Icono from '../components/Icono'
import { cambiarEstadoEntidad, crearEntidad, listarEntidades, type Entidad } from '../cuentas'
import { mensajeDe } from '../http'

export default function PaginaEntidades() {
  const [entidades, setEntidades] = useState<Entidad[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [creando, setCreando] = useState(false)
  const [aviso, setAviso] = useState<string | null>(null)

  useEffect(() => {
    listarEntidades().then(setEntidades).catch((e: unknown) => setError(mensajeDe(e)))
  }, [])

  useEffect(() => {
    if (!aviso) return
    const id = window.setTimeout(() => setAviso(null), 3500)
    return () => window.clearTimeout(id)
  }, [aviso])

  async function alternar(e: Entidad) {
    const accion = e.activa ? 'suspender' : 'reactivar'
    if (!window.confirm(`¿Seguro que desea ${accion} ${e.nombre}?${e.activa ? ' Sus usuarios perderán el acceso de inmediato.' : ''}`)) return
    try {
      const nueva = await cambiarEstadoEntidad(e.id, !e.activa)
      setEntidades((l) => l?.map((x) => (x.id === e.id ? nueva : x)) ?? null)
    } catch (err) {
      setError(mensajeDe(err, 'No se pudo cambiar el estado.'))
    }
  }

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Plataforma</div>
          <h1>Entidades</h1>
          <p>Cada entidad es un cliente aislado: sus usuarios, procesos y documentos no son visibles para las demás.</p>
        </div>
        <button className="btn btn-primary" type="button" onClick={() => setCreando(true)}>
          <Icono nombre="mas" /> Nueva entidad
        </button>
      </div>
      {error && (
        <div className="callout callout-bad" style={{ marginBottom: 16 }} role="alert">
          <Icono nombre="alerta" />
          <div>{error}</div>
        </div>
      )}
      {!entidades ? (
        <div className="vacio">
          <span className="spinner oscuro" />
        </div>
      ) : (
        <div className="tabla-wrap">
          <table className="tabla">
            <thead>
              <tr>
                <th>Entidad</th>
                <th>NIT</th>
                <th>Usuarios</th>
                <th>Creada</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {entidades.map((e) => (
                <tr key={e.id} data-inactivo={!e.activa}>
                  <td>
                    <strong>{e.nombre}</strong>
                  </td>
                  <td className="num">{e.nit}</td>
                  <td className="num">{e.usuarios}</td>
                  <td className="small muted">{new Date(e.creada_en).toLocaleDateString('es-CO', { dateStyle: 'medium' })}</td>
                  <td>
                    <div className="acciones">
                      <span className="pill" data-estado={e.activa ? 'cumple' : 'error'}>
                        <span className="dot" /> {e.activa ? 'Activa' : 'Suspendida'}
                      </span>
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => alternar(e)}>
                        {e.activa ? 'Suspender' : 'Reactivar'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {entidades.length === 0 && (
                <tr>
                  <td colSpan={5} className="vacio">
                    Aún no hay entidades. Cree la primera.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {creando && (
        <DialogoEntidad
          onCerrar={() => setCreando(false)}
          onCreada={(e, email) => {
            setCreando(false)
            setEntidades((l) => [...(l ?? []), e].sort((a, b) => a.nombre.localeCompare(b.nombre)))
            setAviso(`Entidad creada. Invitación enviada a ${email}`)
          }}
        />
      )}
      {aviso && <div className="toast">{aviso}</div>}
    </main>
  )
}

function DialogoEntidad({ onCerrar, onCreada }: { onCerrar: () => void; onCreada: (e: Entidad, email: string) => void }) {
  const [nombre, setNombre] = useState('')
  const [nit, setNit] = useState('')
  const [email, setEmail] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function crear() {
    setEnviando(true)
    setError(null)
    try {
      onCreada(await crearEntidad({ nombre, nit, email_admin: email }), email)
    } catch (e) {
      setError(mensajeDe(e, 'No se pudo crear la entidad.'))
      setEnviando(false)
    }
  }

  return (
    <>
      <div className="overlay" onClick={onCerrar} />
      <div className="dialogo" role="dialog" aria-modal="true" aria-labelledby="titulo-entidad">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            crear()
          }}
        >
          <div className="card-head">
            <div>
              <h2 id="titulo-entidad">Nueva entidad</h2>
              <p>Se crean sus áreas jurídica, técnica y financiera, y se invita a su primer administrador.</p>
            </div>
            <button type="button" className="btn btn-ghost btn-icon" onClick={onCerrar} aria-label="Cerrar">
              <Icono nombre="x" />
            </button>
          </div>
          <div className="field" style={{ marginBottom: 16 }}>
            <label htmlFor="ent-nombre">Nombre</label>
            <input id="ent-nombre" className="input" value={nombre} onChange={(e) => setNombre(e.target.value)} autoFocus required />
          </div>
          <div className="field" style={{ marginBottom: 16 }}>
            <label htmlFor="ent-nit">NIT</label>
            <input id="ent-nit" className="input" value={nit} onChange={(e) => setNit(e.target.value)} placeholder="900123456" required />
          </div>
          <div className="field">
            <label htmlFor="ent-email">Correo del administrador de la entidad</label>
            <input id="ent-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
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
            <button type="submit" className="btn btn-primary" disabled={enviando}>
              {enviando ? <span className="spinner" /> : 'Crear e invitar'}
            </button>
          </div>
        </form>
      </div>
    </>
  )
}
