import type { ResultadoRequisito } from '../api'
import { ETIQUETA_ESTADO, estadoDe, type Revisiones } from '../estado'
import type { InfoRequisito } from '../requisitos'
import Icono from './Icono'

interface Props {
  resultado: ResultadoRequisito | undefined
  info: InfoRequisito
  revisiones: Revisiones
  onClick: () => void
}

export default function Celda({ resultado, info, revisiones, onClick }: Props) {
  if (!resultado) {
    return <span className="celda" data-estado="pendiente" title={`${info.titulo}: aún no evaluado`} />
  }
  const estado = estadoDe(resultado, revisiones)
  const icono =
    estado === 'cumple' || estado === 'revisado_cumple' ? (
      <Icono nombre="check" tam={15} grosor={2.6} />
    ) : estado === 'no_aplica' ? (
      <Icono nombre="menos" tam={14} grosor={2.4} />
    ) : estado === 'revisar' ? (
      <strong style={{ fontSize: 14, lineHeight: 1 }}>!</strong>
    ) : (
      <Icono nombre="x" tam={14} grosor={2.6} />
    )
  return (
    <button
      type="button"
      className="celda"
      data-estado={estado}
      title={`${info.numero}. ${info.titulo}: ${ETIQUETA_ESTADO[estado]}`}
      aria-label={`${info.titulo}: ${ETIQUETA_ESTADO[estado]}`}
      onClick={onClick}
    >
      {icono}
    </button>
  )
}
