import { useEffect, useState } from 'react'
import Icono from '../components/Icono'
import { listarEntidades, type Entidad } from '../cuentas'
import { cargaEquipo, listarTipos, type MiembroCarga, type TipoEvaluacion } from '../evaluaciones'
import { gestionaEvaluaciones, useSesion } from '../sesion'
import type { Eleccion, SeleccionTipos } from './seleccionTipos'

interface Props {
  entidadId: string | null
  seleccion: SeleccionTipos
  onEntidad: (id: string) => void
  onSeleccion: (s: SeleccionTipos) => void
}

/** Qué evaluaciones tendrá el proceso y quién hace cada una (entidad: solo superadmin). */
export default function QuienEvalua({ entidadId, seleccion, onEntidad, onSeleccion }: Props) {
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

  function cambiar(clave: string, cambios: Partial<{ incluir: boolean; eleccion: Eleccion }>) {
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
                    onChange={(e) => cambiar(t.clave, { eleccion: e.target.value })}
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
