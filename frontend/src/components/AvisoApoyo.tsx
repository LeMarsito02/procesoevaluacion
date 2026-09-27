import Icono from './Icono'

/** Aviso permanente (expediente LEG-004, numeral 6.3): el sistema verifica y
 * propone; la decisión es del comité evaluador. */
export const TEXTO_AVISO =
  'Los resultados de MiEvaluador son verificaciones preliminares que usted adopta, corrige o descarta. La decisión es del comité evaluador.'

export default function AvisoApoyo() {
  return (
    <div className="aviso-apoyo" role="note">
      <Icono nombre="escudo" tam={14} /> {TEXTO_AVISO}
    </div>
  )
}
