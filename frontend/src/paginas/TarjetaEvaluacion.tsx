import Icono from '../components/Icono'
import type { EvaluacionResumen } from '../evaluaciones'
import { navegar } from '../rutas'
import { diasParaCierre, porcentajeAvance, textoCierre } from './avance'

export function EstadoEvaluacionPill({ e }: { e: EvaluacionResumen }) {
  return (
    <span className="pill" data-estado-ev={e.estado}>
      <span className="dot" /> {e.estado_nombre}
    </span>
  )
}

export default function TarjetaEvaluacion({
  e,
  accion,
  mostrarEntidad = false,
}: {
  e: EvaluacionResumen
  accion?: React.ReactNode
  mostrarEntidad?: boolean
}) {
  const pct = porcentajeAvance(e)
  const dias = diasParaCierre(e.fecha_cierre)
  return (
    <article className="tarjeta-ev" data-estado={e.estado}>
      <button type="button" className="tarjeta-ev-principal" onClick={() => navegar(`/evaluaciones/${e.id}`)}>
        <div className="tarjeta-ev-cabeza">
          <span className="tag">{e.tipo_nombre}</span>
          <EstadoEvaluacionPill e={e} />
          <span className="small tarjeta-ev-cierre" data-urgente={dias >= 0 && dias <= 3}>
            <Icono nombre="calendario" tam={14} /> {textoCierre(e.fecha_cierre)}
          </span>
        </div>
        {mostrarEntidad && <span className="eyebrow" style={{ margin: 0 }}>{e.entidad_nombre}</span>}
        <h3>{e.proceso_codigo}</h3>
        <p className="tarjeta-ev-objeto">{e.proceso_objeto || 'Sin objeto registrado'}</p>
        <div className="tarjeta-ev-avance">
          <div className="barra" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div style={{ width: `${pct}%` }} data-animada={e.estado === 'evaluando'} />
          </div>
          <span className="num small">{pct}%</span>
        </div>
        <div className="tarjeta-ev-datos small muted">
          <span>
            {e.avance.evaluados}/{e.avance.proponentes} evaluados
          </span>
          {e.avance.pendientes > 0 && <span className="tarjeta-ev-pendientes">{e.avance.pendientes} por revisar</span>}
          {e.avance.con_error > 0 && <span>{e.avance.con_error} con error</span>}
          <span>
            <Icono nombre="usuarios" tam={13} /> {e.responsable?.nombre_completo ?? 'Sin asignar'}
          </span>
        </div>
      </button>
      {accion && <div className="tarjeta-ev-accion">{accion}</div>}
    </article>
  )
}
