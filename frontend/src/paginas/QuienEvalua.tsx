import { useEffect, useState } from 'react'
import Icono from '../components/Icono'
import { listarEntidades, type Entidad } from '../cuentas'
import { cargaEquipo, listarTipos, type MiembroCarga, type TipoEvaluacion } from '../evaluaciones'
import { listarDependencias, sugerirDependencia, type Dependencia } from '../estructura'
import { gestionaEvaluaciones, useSesion } from '../sesion'
import type { Eleccion, SeleccionTipos } from './seleccionTipos'

interface Props {
  entidadId: string | null
  seleccion: SeleccionTipos
  onEntidad: (id: string) => void
  onSeleccion: (s: SeleccionTipos) => void
  /** Objeto del contrato: sugiere la dependencia que evalúa (p. ej. la técnica). */
  objeto?: string
  /** La Matriz 2 del proceso, que se pide al incluir la evaluación financiera. */
  matriz2?: File | null
  onMatriz2?: (archivo: File | null) => void
}

/** Qué evaluaciones tendrá el proceso y quién hace cada una (entidad: solo superadmin). */
export default function QuienEvalua({ entidadId, seleccion, onEntidad, onSeleccion, objeto = '', matriz2 = null, onMatriz2 }: Props) {
  const { usuario } = useSesion()!
  const esSuper = usuario.rol === 'superadmin'
  const gestiona = gestionaEvaluaciones(usuario)
  const [entidades, setEntidades] = useState<Entidad[]>([])
  const [equipo, setEquipo] = useState<MiembroCarga[]>([])
  const [tipos, setTipos] = useState<TipoEvaluacion[]>([])

  useEffect(() => {
    listarTipos()
      .then(setTipos)
      .catch(() => setTipos([]))
  }, [])

  useEffect(() => {
    if (!esSuper) return
    listarEntidades()
      .then((l) => setEntidades(l.filter((e) => e.activa)))
      .catch(() => setEntidades([]))
  }, [esSuper])

  useEffect(() => {
    if (!gestiona || !entidadId) return
    cargaEquipo(entidadId)
      .then(setEquipo)
      .catch(() => setEquipo([]))
  }, [gestiona, entidadId])

  // Dependencias de la entidad y la que sugiere el objeto del contrato, por área.
  const [dependencias, setDependencias] = useState<Dependencia[]>([])
  const [sugeridas, setSugeridas] = useState<Record<string, string>>({})
  useEffect(() => {
    if (!entidadId) return
    listarDependencias(esSuper ? entidadId : null)
      .then((l) => setDependencias(l.filter((d) => d.activa)))
      .catch(() => setDependencias([]))
  }, [entidadId, esSuper])
  useEffect(() => {
    if (!entidadId) return
    let vivo = true
    const tiposConVarias = [...new Set(dependencias.map((d) => d.tipo))].filter((t) => dependencias.filter((d) => d.tipo === t).length > 1)
    Promise.all(tiposConVarias.map((t) => sugerirDependencia(t, objeto, esSuper ? entidadId : null).then((r) => [t, r.dependencia?.id ?? ''] as const)))
      .then((pares) => vivo && setSugeridas(Object.fromEntries(pares)))
      .catch(() => undefined)
    return () => {
      vivo = false
    }
  }, [dependencias, objeto, entidadId, esSuper])

  function cambiar(clave: string, cambios: Partial<{ incluir: boolean; eleccion: Eleccion; dependencia: string; comite: string[] }>) {
    onSeleccion({ ...seleccion, [clave]: { ...seleccion[clave], ...cambios } })
  }

  const ninguno = !Object.values(seleccion).some((s) => s.incluir)

  return (
    <section className="card" style={{ marginTop: 20 }}>
      <div className="card-head">
        <div>
          <h2>Evaluaciones del proceso</h2>
          <p>
            Elija qué evaluaciones tendrá y quién hará cada una.
            {gestiona ? ' Puede dejarlas sin asignar y repartirlas después; la persona asignada recibe un correo.' : ' Usted quedará como responsable.'}
          </p>
        </div>
        <Icono nombre="usuarios" tam={22} />
      </div>

      {esSuper && (
        <div className="field" style={{ marginBottom: 16, maxWidth: 420 }}>
          <label htmlFor="entidad">Entidad</label>
          <select id="entidad" className="select" value={entidadId ?? ''} onChange={(e) => onEntidad(e.target.value)}>
            <option value="" disabled>
              Elija la entidad…
            </option>
            {entidades.map((e) => (
              <option key={e.id} value={e.id}>
                {e.nombre}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="tipos-evaluacion">
        {tipos.map((t) => {
          const sel = seleccion[t.clave]
          const candidatos = equipo.filter((m) => m.id !== usuario.id && (m.areas.includes(t.clave) || m.rol !== 'evaluador'))
          return (
            <div key={t.clave} className="tipo-evaluacion" data-activo={sel.incluir}>
              <label className="tipo-evaluacion-cabeza">
                <input type="checkbox" checked={sel.incluir} onChange={(e) => cambiar(t.clave, { incluir: e.target.checked })} />
                <div>
                  <strong>
                    Evaluación {t.nombre.toLowerCase()}{' '}
                    {!t.disponible && <span className="tag tag-preparacion">Motor en preparación</span>}
                  </strong>
                  <span className="small muted">{t.descripcion}</span>
                </div>
              </label>
              {sel.incluir && gestiona && (
                <div className="field tipo-evaluacion-responsable">
                  <label htmlFor={`resp-${t.clave}`}>Responsable</label>
                  <select
                    id={`resp-${t.clave}`}
                    className="select"
                    value={sel.eleccion}
                    onChange={(e) => {
                      // El nuevo responsable no puede quedar repetido entre los demás integrantes.
                      const nuevo = e.target.value === 'yo' ? usuario.id : e.target.value
                      cambiar(t.clave, { eleccion: e.target.value, comite: (sel.comite ?? []).filter((x) => x !== nuevo) })
                    }}
                    disabled={!entidadId}
                  >
                    <option value="">Sin asignar (asignar después)</option>
                    {!esSuper && <option value="yo">Yo me encargo</option>}
                    {candidatos.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.nombre_completo} · {m.evaluaciones_activas} activas
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {sel.incluir && gestiona && sel.eleccion !== '' && (
                <fieldset className="field tipo-evaluacion-responsable comite-elegir">
                  <legend>Más integrantes del comité</legend>
                  <span className="small muted">El responsable coordina; los que marque aquí también evalúan y reciben el correo de designación.</span>
                  <div className="comite-opciones">
                    {[...(sel.eleccion !== 'yo' && !esSuper ? [{ id: usuario.id, nombre_completo: `${usuario.nombre_completo} (yo)`, evaluaciones_activas: null as number | null }] : []), ...candidatos]
                      .filter((m) => m.id !== (sel.eleccion === 'yo' ? usuario.id : sel.eleccion))
                      .map((m) => {
                        const marcado = (sel.comite ?? []).includes(m.id)
                        return (
                          <label key={m.id} className="comite-opcion" data-marcado={marcado}>
                            <input
                              type="checkbox"
                              checked={marcado}
                              onChange={(e) =>
                                cambiar(t.clave, {
                                  comite: e.target.checked ? [...(sel.comite ?? []), m.id] : (sel.comite ?? []).filter((x) => x !== m.id),
                                })
                              }
                            />
                            <span>
                              {m.nombre_completo}
                              {m.evaluaciones_activas != null && <span className="small muted"> · {m.evaluaciones_activas} activas</span>}
                            </span>
                          </label>
                        )
                      })}
                    {candidatos.length === 0 && <span className="small muted">No hay más personas del área en el equipo.</span>}
                  </div>
                </fieldset>
              )}
              {sel.incluir && dependencias.filter((d) => d.tipo === t.clave).length > 1 && (
                <div className="field tipo-evaluacion-responsable">
                  <label htmlFor={`dep-${t.clave}`}>Dependencia que evalúa</label>
                  <select
                    id={`dep-${t.clave}`}
                    className="select"
                    value={sel.dependencia || sugeridas[t.clave] || ''}
                    onChange={(e) => cambiar(t.clave, { dependencia: e.target.value })}
                  >
                    {!sugeridas[t.clave] && <option value="">Elija la dependencia…</option>}
                    {dependencias
                      .filter((d) => d.tipo === t.clave)
                      .map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.nombre}
                          {d.id === sugeridas[t.clave] ? ' (sugerida por el objeto del contrato)' : ''}
                        </option>
                      ))}
                  </select>
                </div>
              )}
              {sel.incluir && t.clave === 'financiera' && onMatriz2 && (
                <div className="field tipo-evaluacion-responsable">
                  <label htmlFor="matriz2-proceso">Matriz 2 – Indicadores financieros y organizacionales</label>
                  <input
                    id="matriz2-proceso"
                    className="input"
                    type="file"
                    accept=".pdf,.doc,.docx,.xls,.xlsx"
                    onChange={(e) => onMatriz2(e.target.files?.[0] ?? null)}
                  />
                  <span className="small muted">
                    {matriz2
                      ? `Se cargará «${matriz2.name}» al crear el proceso.`
                      : 'Es un anexo aparte del pliego (está en el SECOP, junto a él). De ella salen los umbrales de liquidez, endeudamiento, cobertura y rentabilidad. Sin ella esos indicadores quedan a revisión en todos los proponentes; también se puede subir después.'}
                  </span>
                </div>
              )}
              {sel.incluir && !t.disponible && (
                <p className="small muted" style={{ margin: '8px 0 0 30px' }}>
                  Se crea y se asigna desde ya; la evaluación automática se habilitará cuando el módulo esté listo.
                </p>
              )}
            </div>
          )
        })}
      </div>
      {ninguno && <p className="small" style={{ color: 'var(--bad)', marginTop: 10 }}>Elija al menos una evaluación.</p>}
    </section>
  )
}
