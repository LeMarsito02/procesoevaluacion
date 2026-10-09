import { useEffect, useState } from 'react'
import { explicacionDelResultado } from '../evaluaciones'
import { mensajeDe } from '../http'
import Icono from './Icono'

/** El resultado contado en palabras llanas, debajo del detalle técnico.
 *
 * No reemplaza al detalle: ese es el dato que se puede verificar contra el
 * documento y sigue arriba. Esto solo traduce la jerga del pliego ("CRP sin
 * calcular", "SCE sin leer") para quien revisa, que es abogado y no tiene por
 * qué saberse las siglas de la fórmula de capacidad residual.
 *
 * Se pide al pulsar, no al abrir: el modelo corre en local y tarda unos
 * segundos, y no todas las fichas necesitan explicación. La respuesta queda
 * guardada en el servidor: al volver a abrir el requisito aparece sola, sin
 * tener que pedirla otra vez (ni esperar al modelo). */
export default function ExplicacionIA({
  evaluacionId,
  proponenteId,
  requisito,
}: {
  evaluacionId: string
  proponenteId: string
  requisito: number
}) {
  const [texto, setTexto] = useState<string | null>(null)
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // La que ya se redactó para este resultado se muestra al abrir.
  useEffect(() => {
    let vigente = true
    explicacionDelResultado(evaluacionId, proponenteId, requisito, true)
      .then(({ texto: guardado }) => {
        if (vigente && guardado) setTexto(guardado)
      })
      .catch(() => {})
    return () => {
      vigente = false
    }
  }, [evaluacionId, proponenteId, requisito])

  async function pedirExplicacion() {
    setCargando(true)
    setError(null)
    try {
      const { texto: recibido } = await explicacionDelResultado(evaluacionId, proponenteId, requisito)
      if (recibido) setTexto(recibido)
      else setError('La explicación automática no está disponible en este momento.')
    } catch (err) {
      setError(mensajeDe(err, 'No se pudo generar la explicación.'))
    } finally {
      setCargando(false)
    }
  }

  if (texto) {
    return (
      <div className="explicacion-ia">
        <div className="explicacion-ia-titulo">
          <Icono nombre="chispa" tam={14} /> En palabras
        </div>
        <p>{texto}</p>
        <p className="small muted">
          Redactado por el asistente local a partir del resultado de arriba. No decide nada: lo que vale para el
          informe es el detalle y los documentos.
        </p>
      </div>
    )
  }
  return (
    <div className="explicacion-ia-pedir">
      <button type="button" className="btn btn-ghost btn-sm" onClick={pedirExplicacion} disabled={cargando}>
        {cargando ? 'Redactando…' : 'Explicar en palabras'}
      </button>
      {error && <span className="small muted">{error}</span>}
    </div>
  )
}
