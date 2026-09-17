import { useEffect, useState } from 'react'
import Icono from '../components/Icono'
import { listarEntidades, type Entidad } from '../cuentas'
import { cargaEquipo, type MiembroCarga } from '../evaluaciones'
import { gestionaEvaluaciones, useSesion } from '../sesion'

/** '' = sin asignar; 'yo' = quien crea; otro valor = id de la persona. */
export type Eleccion = '' | 'yo' | string

interface Props {
  entidadId: string | null
  eleccion: Eleccion
  onEntidad: (id: string) => void
  onEleccion: (e: Eleccion) => void
}

/** Entidad (solo superadmin) y responsable de la evaluación al crear el proceso. */
export default function QuienEvalua({ entidadId, eleccion, onEntidad, onEleccion }: Props) {
  const { usuario } = useSesion()!
  const esSuper = usuario.rol === 'superadmin'
  const gestiona = gestionaEvaluaciones(usuario)
  const [entidades, setEntidades] = useState<Entidad[]>([])
  const [equipo, setEquipo] = useState<MiembroCarga[]>([])

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

  const candidatos = equipo.filter((m) => m.id !== usuario.id && (m.areas.includes('juridica') || m.rol !== 'evaluador'))

  return (
    <section className="card" style={{ marginTop: 20 }}>
      <div className="card-head">
        <div>
          <h2>¿Quién hará la evaluación jurídica?</h2>
          <p>
            {gestiona
              ? 'Puede dejarla sin asignar y repartirla después, o asignarla ahora (la persona recibe un correo).'
              : 'Usted quedará como responsable de este proceso.'}
          </p>
        </div>
        <Icono nombre="usuarios" tam={22} />
      </div>
      {gestiona ? (
        <div className="grid-2">
          {esSuper && (
            <div className="field">
              <label htmlFor="entidad">Entidad</label>
              <select
                id="entidad"
                className="select"
                value={entidadId ?? ''}
                onChange={(e) => {
                  onEntidad(e.target.value)
                  onEleccion('')
                }}
              >
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
          <div className="field">
            <label htmlFor="responsable">Responsable</label>
            <select id="responsable" className="select" value={eleccion} onChange={(e) => onEleccion(e.target.value)} disabled={!entidadId}>
              <option value="">Sin asignar (asignar después)</option>
              {!esSuper && <option value="yo">Yo me encargo</option>}
              {candidatos.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.nombre_completo} · {m.evaluaciones_activas} activas · {m.pendientes} por revisar
                </option>
              ))}
            </select>
          </div>
        </div>
      ) : (
        <div className="persona">
          <span className="avatar">{usuario.nombre_completo.slice(0, 1).toUpperCase()}</span>
          <strong>{usuario.nombre_completo}</strong>
        </div>
      )}
    </section>
  )
}
