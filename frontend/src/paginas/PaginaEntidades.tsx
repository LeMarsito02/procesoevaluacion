import { useEffect, useState } from 'react'
import Icono from '../components/Icono'
import TarjetaCredenciales from '../components/TarjetaCredenciales'
import { subirPlantilla } from '../configuracion'
import {
  cambiarEstadoEntidad,
  crearCuentaSoporte,
  crearEntidad,
  listarEntidades,
  personalDeSoporte,
  type Credenciales,
  type Entidad,
  type PersonaSoporte,
} from '../cuentas'
import { navegar } from '../rutas'
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
                      <button type="button" className="btn btn-secondary btn-sm" onClick={() => navegar(`/configuracion?entidad=${e.id}`)}>
                        Configurar
                      </button>
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
      <PersonalSoporte onAviso={setAviso} onError={setError} />

      {creando && (
        <DialogoEntidad
          onCerrar={() => setCreando(false)}
          entidades={entidades ?? []}
          onCreada={(e, plantillas) => {
            setEntidades((l) => [...(l ?? []), e].sort((a, b) => a.nombre.localeCompare(b.nombre)))
            setAviso(`Entidad creada${plantillas ? ` con ${plantillas} plantilla(s) de Excel` : ''}.`)
          }}
        />
      )}
      {aviso && <div className="toast">{aviso}</div>}
    </main>
  )
}

const TIPOS_PLANTILLA = [
  { clave: 'juridica', nombre: 'Jurídica' },
  { clave: 'tecnica', nombre: 'Técnica' },
  { clave: 'financiera', nombre: 'Financiera' },
]

function DialogoEntidad({
  entidades,
  onCerrar,
  onCreada,
}: {
  entidades: Entidad[]
  onCerrar: () => void
  onCreada: (e: Entidad, plantillas: number) => void
}) {
  const [nombre, setNombre] = useState('')
  const [nit, setNit] = useState('')
  const [sigla, setSigla] = useState('')
  const [email, setEmail] = useState('')
  const [nombreAdmin, setNombreAdmin] = useState('')
  const [base, setBase] = useState<'sistema' | 'copiar'>('sistema')
  const [copiarDe, setCopiarDe] = useState('')
  const [excel, setExcel] = useState<Record<string, File | null>>({})
  const [creada, setCreada] = useState<Entidad | null>(null)
  const [credenciales, setCredenciales] = useState<Credenciales | null>(null)
  const [listo, setListo] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function crear() {
    setEnviando(true)
    setError(null)
    try {
      // Si falla una plantilla, la entidad ya existe: al reintentar solo se suben las que faltan.
      let entidad = creada
      if (entidad === null) {
        const r = await crearEntidad({
          nombre, nit, email_admin: email, nombre_admin: nombreAdmin, sigla, base, copiar_de: base === 'copiar' ? copiarDe : null,
        })
        entidad = r.entidad
        setCreada(entidad)
        setCredenciales(r.credenciales)
      }
      let subidas = 0
      for (const [tipo, archivo] of Object.entries(excel)) {
        if (!archivo) continue
        await subirPlantilla(tipo, archivo, entidad.id)
        subidas++
        setExcel((p) => ({ ...p, [tipo]: null }))
      }
      onCreada(entidad, subidas)
      setListo(true)
    } catch (e) {
      setError(mensajeDe(e, 'No se pudo crear la entidad.'))
    } finally {
      setEnviando(false)
    }
  }

  const bloqueado = !!creada

  // Ya está todo: solo queda entregarle las credenciales a su administrador.
  if (listo && credenciales) {
    return (
      <>
        <div className="overlay" onClick={onCerrar} />
        <div className="dialogo" role="dialog" aria-modal="true" aria-labelledby="titulo-entidad-lista">
          <div className="card-head">
            <div>
              <h2 id="titulo-entidad-lista">{creada?.nombre} quedó creada</h2>
              <p>Entregue estas credenciales a su administrador: no se vuelven a mostrar.</p>
            </div>
            <Icono nombre="llave" tam={22} />
          </div>
          <TarjetaCredenciales
            nombre={credenciales.usuario.nombre_completo}
            email={credenciales.usuario.email}
            password={credenciales.password_temporal}
            contexto="Es el administrador de la entidad."
          />
          <div className="dialogo-pie">
            <button type="button" className="btn btn-primary" onClick={onCerrar}>
              Ya las entregué
            </button>
          </div>
        </div>
      </>
    )
  }

  return (
    <>
      <div className="overlay" onClick={onCerrar} />
      <div className="dialogo dialogo-ancho" role="dialog" aria-modal="true" aria-labelledby="titulo-entidad">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            crear()
          }}
        >
          <div className="card-head">
            <div>
              <h2 id="titulo-entidad">Nueva entidad</h2>
              <p>Se crean sus áreas, su forma de evaluar y la cuenta de su primer administrador.</p>
            </div>
            <button type="button" className="btn btn-ghost btn-icon" onClick={onCerrar} aria-label="Cerrar">
              <Icono nombre="x" />
            </button>
          </div>

          <div className="grid-2" style={{ gap: 14 }}>
            <div className="field" style={{ gridColumn: '1 / -1' }}>
              <label htmlFor="ent-nombre">Nombre</label>
              <input id="ent-nombre" className="input" value={nombre} onChange={(e) => setNombre(e.target.value)} autoFocus required disabled={bloqueado} />
            </div>
            <div className="field">
              <label htmlFor="ent-nit">NIT</label>
              <input id="ent-nit" className="input" value={nit} onChange={(e) => setNit(e.target.value)} placeholder="900123456" required disabled={bloqueado} />
            </div>
            <div className="field">
              <label htmlFor="ent-sigla">Sigla</label>
              <input id="ent-sigla" className="input" value={sigla} onChange={(e) => setSigla(e.target.value)} placeholder="IDU" disabled={bloqueado} />
              <span className="hint">Como aparece en los códigos de proceso y en las pólizas.</span>
            </div>
            <div className="field">
              <label htmlFor="ent-admin">Administrador de la entidad</label>
              <input id="ent-admin" className="input" value={nombreAdmin} onChange={(e) => setNombreAdmin(e.target.value)} placeholder="Nombre completo" required disabled={bloqueado} />
            </div>
            <div className="field">
              <label htmlFor="ent-email">Su correo</label>
              <input id="ent-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required disabled={bloqueado} />
              <span className="hint">Se le crea la cuenta con una contraseña temporal que usted le entrega.</span>
            </div>
          </div>

          <div className="field" style={{ marginTop: 18 }}>
            <label>¿Cómo evaluará?</label>
            <div className="opciones">
              <label className="opcion" data-activo={base === 'sistema'}>
                <input type="radio" name="base" checked={base === 'sistema'} onChange={() => setBase('sistema')} disabled={bloqueado} />
                <div>
                  <strong>Base del sistema</strong>
                  <span className="small muted">Evaluación jurídica estándar (17 requisitos) adaptada a su sigla. Se ajusta después en Configuración.</span>
                </div>
              </label>
              <label className="opcion" data-activo={base === 'copiar'}>
                <input type="radio" name="base" checked={base === 'copiar'} onChange={() => setBase('copiar')} disabled={bloqueado || entidades.length === 0} />
                <div>
                  <strong>Copiar de otra entidad</strong>
                  <span className="small muted">Mismos requisitos, parámetros y plantillas de Excel.</span>
                </div>
              </label>
            </div>
            {base === 'copiar' && (
              <select className="select" style={{ marginTop: 8 }} value={copiarDe} onChange={(e) => setCopiarDe(e.target.value)} required disabled={bloqueado}>
                <option value="">Elija la entidad…</option>
                {entidades.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.nombre}
                  </option>
                ))}
              </select>
            )}
          </div>

          <div className="field" style={{ marginTop: 18 }}>
            <label>Plantillas de Excel del informe (opcional)</label>
            <span className="hint">
              {base === 'copiar' ? 'Si sube una, reemplaza la copiada para ese tipo.' : 'También puede subirlas después en Configuración.'}
            </span>
            <div className="plantillas-nueva">
              {TIPOS_PLANTILLA.map((t) => (
                <label key={t.clave} className="plantilla-slot" data-lleno={!!excel[t.clave]}>
                  <Icono nombre={excel[t.clave] ? 'check' : 'subir'} tam={16} />
                  <span>
                    <strong>{t.nombre}</strong>
                    <span className="small muted">{excel[t.clave]?.name ?? 'Elegir archivo…'}</span>
                  </span>
                  <input type="file" accept=".xlsx" hidden onChange={(e) => setExcel((p) => ({ ...p, [t.clave]: e.target.files?.[0] ?? null }))} />
                </label>
              ))}
            </div>
          </div>

          {error && (
            <div className="callout callout-bad" style={{ marginTop: 16 }} role="alert">
              <Icono nombre="alerta" />
              <div>{error}</div>
            </div>
          )}
          <div className="dialogo-pie">
            <button type="button" className="btn btn-ghost" onClick={onCerrar}>
              {bloqueado ? 'Cerrar' : 'Cancelar'}
            </button>
            <button type="submit" className="btn btn-primary" disabled={enviando || (base === 'copiar' && !copiarDe)}>
              {enviando ? <span className="spinner" /> : bloqueado ? 'Reintentar plantillas' : 'Crear entidad'}
            </button>
          </div>
        </form>
      </div>
    </>
  )
}

function PersonalSoporte({ onAviso, onError }: { onAviso: (t: string) => void; onError: (t: string) => void }) {
  const [personal, setPersonal] = useState<PersonaSoporte[]>([])
  const [email, setEmail] = useState('')
  const [nombre, setNombre] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [nuevas, setNuevas] = useState<{ soporte: PersonaSoporte; password_temporal: string } | null>(null)

  useEffect(() => {
    personalDeSoporte()
      .then(setPersonal)
      .catch(() => setPersonal([]))
  }, [])

  async function crear() {
    setEnviando(true)
    try {
      const r = await crearCuentaSoporte(email, nombre)
      setPersonal((l) => [...l, r.soporte])
      setEmail('')
      setNombre('')
      setNuevas(r)
    } catch (e) {
      onError(mensajeDe(e))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <section className="card" style={{ marginTop: 24 }}>
      <div className="card-head">
        <div>
          <h2>Personal de soporte LeMarTek</h2>
          <p>No ven datos de ninguna entidad salvo que su administrador les dé acceso temporal (solo lectura, con 2FA).</p>
        </div>
        <Icono nombre="escudo" tam={22} />
      </div>
      <div className="chips" style={{ marginBottom: 14 }}>
        {personal.length === 0 && <span className="small muted">Aún no hay personal de soporte.</span>}
        {personal.map((p) => (
          <span key={p.id} className="chip" data-activo="true" title={p.email}>
            {p.nombre_completo}
          </span>
        ))}
      </div>
      <form
        className="grid-soporte"
        style={{ gridTemplateColumns: '1fr 1fr auto' }}
        onSubmit={(e) => {
          e.preventDefault()
          crear()
        }}
      >
        <input className="input" placeholder="Nombre completo" value={nombre} onChange={(e) => setNombre(e.target.value)} required />
        <input className="input" type="email" placeholder="correo@lemartek.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <button type="submit" className="btn btn-secondary" disabled={enviando}>
          {enviando ? <span className="spinner oscuro" /> : 'Crear cuenta'}
        </button>
      </form>
      {nuevas && (
        <>
          <div className="overlay" onClick={() => setNuevas(null)} />
          <div className="dialogo" role="dialog" aria-modal="true" aria-labelledby="titulo-soporte-nuevo">
            <div className="card-head">
              <div>
                <h2 id="titulo-soporte-nuevo">Cuenta de soporte creada</h2>
                <p>Entréguele estas credenciales: no se vuelven a mostrar.</p>
              </div>
              <Icono nombre="llave" tam={22} />
            </div>
            <TarjetaCredenciales
              nombre={nuevas.soporte.nombre_completo}
              email={nuevas.soporte.email}
              password={nuevas.password_temporal}
              contexto="Al entrar tendrá que cambiarla y configurar su verificación en dos pasos."
            />
            <div className="dialogo-pie">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  onAviso('Cuenta de soporte creada')
                  setNuevas(null)
                }}
              >
                Ya las entregué
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  )
}
