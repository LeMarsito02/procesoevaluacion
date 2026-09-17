import Icono from './Icono'

export type Paso = 'nuevo' | 'datos' | 'evaluacion' | 'informe'

const PASOS: { id: Paso; nombre: string }[] = [
  { id: 'nuevo', nombre: 'Proceso' },
  { id: 'datos', nombre: 'Datos del proceso' },
  { id: 'evaluacion', nombre: 'Evaluación y revisión' },
  { id: 'informe', nombre: 'Informe' },
]

interface Props {
  paso: Paso
  codigoProceso: string | null
  pasosDisponibles: Set<Paso>
  onIr: (paso: Paso) => void
}

export default function Topbar({ paso, codigoProceso, pasosDisponibles, onIr }: Props) {
  const indiceActual = PASOS.findIndex((p) => p.id === paso)
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand">
          <div className="brand-mark">
            <Icono nombre="balanza" tam={20} />
          </div>
          <div className="brand-text">
            <strong>Evaluador Jurídico</strong>
            <span>{codigoProceso ? `Proceso ${codigoProceso}` : 'Verificación de requisitos habilitantes'}</span>
          </div>
        </div>
        <nav className="stepper" aria-label="Pasos de la evaluación">
          {PASOS.map((p, i) => {
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
                  {p.nombre}
                </button>
              </div>
            )
          })}
        </nav>
      </div>
    </header>
  )
}
