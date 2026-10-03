import { useEffect, useMemo, useRef, useState } from 'react'
import { useDialogo } from '../dialogo'
import { cargaEquipo, designarComite, urlDesignacion, verComite, type Comite, type MiembroCarga } from '../evaluaciones'
import { listarDependencias, type Dependencia } from '../estructura'
import { mensajeDe } from '../http'
import Icono from './Icono'

interface Props {
  evaluacionId: string
  entidadId: string
  tipo: string
  tipoNombre: string
  /** El jefe de la dependencia o el administrador: designa el comité. */
  puedeDesignar: boolean
  onCerrar: () => void
  /** Tras designar: la evaluación cambia de responsable y estado. */
  onDesignado: () => void
}

/** Comité evaluador de una evaluación: dependencia, integrantes (el primero
 * coordina) y el historial de designaciones con su documento controlado. */
export default function ComiteEvaluador(p: Props) {
  const caja = useRef<HTMLDivElement>(null)
  useDialogo(caja)
  const [comite, setComite] = useState<Comite | null>(null)
  const [dependencias, setDependencias] = useState<Dependencia[]>([])
  const [equipo, setEquipo] = useState<MiembroCarga[]>([])
  const [dependencia, setDependencia] = useState<string>('')
  const [elegidos, setElegidos] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)

  useEffect(() => {
    verComite(p.evaluacionId)
      .then((c) => {
        setComite(c)
        setDependencia(c.dependencia?.id ?? '')
        setElegidos(c.miembros.map((m) => m.id))
      })
      .catch((e: unknown) => setError(mensajeDe(e)))
    if (!p.puedeDesignar) return
    listarDependencias(p.entidadId)
      .then((l) => setDependencias(l.filter((d) => d.tipo === p.tipo && d.activa)))
      .catch(() => setDependencias([]))
    cargaEquipo(p.entidadId)
      .then((l) => setEquipo(l.filter((m) => m.rol !== 'consulta')))
      .catch(() => setEquipo([]))
  }, [p.evaluacionId, p.entidadId, p.tipo, p.puedeDesignar])

  useEffect(() => {
    const tecla = (e: KeyboardEvent) => e.key === 'Escape' && p.onCerrar()
    window.addEventListener('keydown', tecla)
    return () => window.removeEventListener('keydown', tecla)
  }, [p])

  // Primero los integrantes de la dependencia elegida; luego el resto del equipo.
  const dep = dependencias.find((d) => d.id === dependencia)
  const candidatos = useMemo(() => {
    const deDependencia = new Set([...(dep?.miembros ?? []), ...(dep?.jefes ?? [])].map((m) => m.id))
    return [...equipo].sort((a, b) => Number(deDependencia.has(b.id)) - Number(deDependencia.has(a.id)) || a.nombre_completo.localeCompare(b.nombre_completo))
  }, [equipo, dep])
  const deDependencia = new Set([...(dep?.miembros ?? []), ...(dep?.jefes ?? [])].map((m) => m.id))

  function alternar(id: string) {
    setElegidos((l) => (l.includes(id) ? l.filter((x) => x !== id) : [...l, id]))
  }

  async function guardar() {
    setGuardando(true)
    setError(null)
    try {
      setComite(await designarComite(p.evaluacionId, elegidos, dependencia || null))
      p.onDesignado()
    } catch (e) {
      setError(mensajeDe(e))
    } finally {
      setGuardando(false)
    }
  }

  const cambios =
    comite != null &&
    (JSON.stringify(elegidos) !== JSON.stringify(comite.miembros.map((m) => m.id)) || (dependencia || null) !== (comite.dependencia?.id ?? null))

  return (
    <>
      <div className="overlay" style={{ zIndex: 60 }} onClick={p.onCerrar} />
      <div ref={caja} className="dialogo dialogo-ancho" style={{ zIndex: 61 }} role="dialog" aria-modal="true" aria-labelledby="titulo-comite" tabIndex={-1}>
        <div className="card-head">
          <div>
            <h2 id="titulo-comite">Comité evaluador · {p.tipoNombre}</h2>
            <p>
              Todos los integrantes trabajan el proceso a la vez; el primero coordina. Cada cambio genera un documento de
              designación con consecutivo, que queda en el expediente.
            </p>
          </div>
          <button className="btn btn-ghost btn-icon" type="button" onClick={p.onCerrar} aria-label="Cerrar">
            <Icono nombre="x" />
          </button>
        </div>

        {error && (
          <div className="callout callout-bad" role="alert">
            {error}
          </div>
        )}
        {!comite ? (
          <span className="spinner oscuro" role="status" aria-label="Cargando comité" />
        ) : p.puedeDesignar ? (
          <>
            <div className="field">
              <label htmlFor="comite-dependencia">Dependencia que evalúa</label>
              <select id="comite-dependencia" className="select" value={dependencia} onChange={(e) => setDependencia(e.target.value)}>
                <option value="">Sin dependencia (por área)</option>
                {dependencias.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.nombre}
                  </option>
                ))}
              </select>
            </div>
            <fieldset className="fieldset-limpio">
              <legend className="small" style={{ fontWeight: 600, marginBottom: 6 }}>
                Integrantes del comité (en el orden en que los marque; el primero coordina)
              </legend>
              <div className="comite-candidatos">
                {candidatos.map((m) => {
                  const pos = elegidos.indexOf(m.id)
                  return (
                    <label key={m.id} className="comite-candidato" data-elegido={pos >= 0}>
                      <input type="checkbox" checked={pos >= 0} onChange={() => alternar(m.id)} />
                      <span>
                        <strong>{m.nombre_completo}</strong>
                        <span className="small muted">
                          {m.rol_nombre}
                          {deDependencia.has(m.id) ? ' · de la dependencia' : ''} · {m.evaluaciones_activas} activas
                        </span>
                      </span>
                      {pos === 0 && <span className="pill pill-xs" data-estado="cumple">Coordina</span>}
                      {pos > 0 && <span className="small muted">#{pos + 1}</span>}
                    </label>
                  )
                })}
              </div>
            </fieldset>
            <div className="acciones" style={{ justifyContent: 'flex-end' }}>
              <button className="btn btn-primary" type="button" disabled={!cambios || elegidos.length === 0 || guardando} onClick={guardar}>
                {guardando ? <span className="spinner" /> : <Icono nombre="check" tam={16} />} Designar y generar documento
              </button>
            </div>
          </>
        ) : (
          <ul className="lista-simple">
            {comite.miembros.map((m, i) => (
              <li key={m.id}>
                {m.nombre_completo} {i === 0 && <span className="pill pill-xs" data-estado="cumple">Coordina</span>}
              </li>
            ))}
            {comite.miembros.length === 0 && <li className="muted">Todavía sin comité.</li>}
          </ul>
        )}

        {comite && comite.designaciones.length > 0 && (
          <div style={{ marginTop: 20 }}>
            <h3 style={{ fontSize: 15, marginBottom: 8 }}>Designaciones</h3>
            <div className="tabla-wrap">
              <table className="tabla">
                <thead>
                  <tr>
                    <th scope="col">Consecutivo</th>
                    <th scope="col">Versión</th>
                    <th scope="col">Integrantes</th>
                    <th scope="col">Designó</th>
                    <th scope="col">Documento</th>
                  </tr>
                </thead>
                <tbody>
                  {comite.designaciones.map((d) => (
                    <tr key={d.id}>
                      <td>
                        <strong>{d.consecutivo}</strong>
                        <div className="small muted">{new Date(d.designado_en).toLocaleString('es-CO')}</div>
                      </td>
                      <td>v{d.version}</td>
                      <td className="small">{d.miembros.map((m) => m.nombre).join(', ')}</td>
                      <td className="small">{d.designado_por}</td>
                      <td>
                        <a className="btn btn-ghost btn-sm" href={urlDesignacion(p.evaluacionId, d.id)} title={`Huella SHA-256: ${d.sha256}`}>
                          <Icono nombre="descargar" tam={15} /> Word
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
