import { useEffect, useState } from 'react'
import ChatAsistente from './ChatAsistente'
import Icono from './Icono'

/** Botón flotante que abre el asistente dentro de una evaluación, ya situado
 * en ella: las preguntas son sobre lo que la persona tiene en pantalla. */
export default function BotonAsistente({ evaluacionId, etiqueta }: { evaluacionId: string; etiqueta: string }) {
  const [abierto, setAbierto] = useState(false)
  useEffect(() => {
    if (!abierto) return
    const tecla = (e: KeyboardEvent) => e.key === 'Escape' && setAbierto(false)
    window.addEventListener('keydown', tecla)
    return () => window.removeEventListener('keydown', tecla)
  }, [abierto])

  if (abierto) return <ChatAsistente evaluacionFija={{ id: evaluacionId, etiqueta }} onCerrar={() => setAbierto(false)} />
  return (
    <button type="button" className="chat-flotante no-imprimir" onClick={() => setAbierto(true)} aria-label="Abrir el asistente para preguntar sobre esta evaluación">
      <Icono nombre="chispa" tam={18} /> Preguntar al asistente
    </button>
  )
}
