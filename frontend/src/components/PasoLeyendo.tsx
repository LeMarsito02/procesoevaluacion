import { useEffect, useState } from 'react'
import type { Preparacion } from '../api'
import Icono from './Icono'

/** Etapas de la lectura y el avance con que empieza cada una (las fija el servidor). */
const ETAPAS = [
  { texto: 'Leyendo el Documento Base', desde: 5, hasta: 55 },
  { texto: 'Revisando las ofertas', desde: 55, hasta: 75 },
  { texto: 'Leyendo el pliego completo', desde: 75, hasta: 99 },
]

function transcurrido(desde: string | null): string {
  if (!desde) return ''
  const s = Math.max(0, Math.round((Date.now() - new Date(desde).getTime()) / 1000))
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`
}

/** Mientras el servidor lee el Documento Base, las ofertas y el pliego. Queda
 * guardado: se puede recargar la página o cerrarla y retomarlo después. */
export default function PasoLeyendo({
  preparacion,
  ocupado,
  sinConexion = false,
  onEliminar,
  onReintentar,
}: {
  preparacion: Preparacion
  ocupado: boolean
  /** La última consulta del avance falló: se sigue intentando. */
  sinConexion?: boolean
  onEliminar: () => void
  onReintentar: () => void
}) {
  const p = preparacion
  const [mostrado, setMostrado] = useState(p.progreso)
  const [, setReloj] = useState(0)
  const indice = ETAPAS.findIndex((e) => e.texto === p.etapa)
  // Dentro de una etapa la barra avanza despacio hacia el final de ese tramo,
  // sin llegar nunca a él: así no parece detenida ni promete de más.
  const tope = indice >= 0 ? ETAPAS[indice].hasta : p.estado === 'pendiente' ? 4 : p.progreso
  useEffect(() => {
    const t = window.setInterval(() => {
      setMostrado((m) => Math.max(p.progreso, m + Math.max(0, tope - Math.max(m, p.progreso)) * 0.015))
      setReloj((x) => x + 1)
    }, 500)
    return () => window.clearInterval(t)
  }, [p.progreso, tope])

  const error = p.estado === 'error'
  return (
    <main className="page page-narrow">
      <div className="page-head">
        <div>
          <div className="eyebrow">Nuevo proceso · {p.codigo}</div>
          <h1>{error ? 'No se pudo leer el proceso' : 'Leyendo el pliego'}</h1>
          <p>
            {error
              ? 'Revise el mensaje. Puede intentarlo de nuevo o eliminarlo y empezar con otros archivos.'
              : 'Se está leyendo el Documento Base, buscando las ofertas y revisando el pliego completo. Puede recargar o cerrar esta página: la lectura sigue y la encuentra en «Nuevo proceso».'}
          </p>
        </div>
      </div>

      {sinConexion && (
        <div className="callout callout-warn" role="status" style={{ marginBottom: 12 }}>
          <Icono nombre="alerta" />
          <div>Se perdió la conexión con el servidor. La lectura sigue allá; esta pantalla vuelve a consultar sola en unos segundos.</div>
        </div>
      )}
      <section className="card leyendo">
        {error ? (
          <div className="callout callout-bad" role="alert">
            <Icono nombre="alerta" />
            <div>{p.error}</div>
          </div>
        ) : (
          <>
            <div className="leyendo-cabeza">
              <strong>{p.estado === 'pendiente' ? 'En fila: empieza en un momento' : p.etapa || 'Leyendo…'}</strong>
              <span className="small muted">{transcurrido(p.iniciada_en ?? p.creada_en)}</span>
            </div>
            <div
              className="barra-progreso"
              role="progressbar"
              aria-label="Avance de la lectura"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(mostrado)}
            >
              <span style={{ width: `${Math.min(99, mostrado)}%` }} />
            </div>
            <ol className="leyendo-etapas">
              {ETAPAS.map((e, i) => {
                const estado = indice > i || p.estado === 'lista' ? 'hecha' : indice === i ? 'actual' : 'pendiente'
                return (
                  <li key={e.texto} data-estado={estado}>
                    <span className="leyendo-marca" aria-hidden="true">
                      {estado === 'hecha' ? <Icono nombre="check" tam={13} grosor={3} /> : estado === 'actual' ? <span className="spinner oscuro" /> : i + 1}
                    </span>
                    {e.texto}
                    <span className="sr-only">{estado === 'hecha' ? ' (lista)' : estado === 'actual' ? ' (en curso)' : ' (pendiente)'}</span>
                  </li>
                )
              })}
            </ol>
          </>
        )}

        <dl className="leyendo-datos small">
          <div>
            <dt>Documento Base</dt>
            <dd>{p.nombre_archivo}</dd>
          </div>
          <div>
            <dt>Ofertas</dt>
            <dd>{p.ofertas_subidas ? 'Subidas desde el equipo' : p.carpeta_drive || 'Sin ofertas todavía'}</dd>
          </div>
        </dl>

        <div className="acciones" style={{ justifyContent: 'space-between', marginTop: 18, flexWrap: 'wrap' }}>
          <button className="btn btn-ghost" type="button" disabled={ocupado} onClick={onEliminar}>
            <Icono nombre="x" tam={15} /> Eliminar y empezar de nuevo
          </button>
          {error && (
            <button className="btn btn-primary" type="button" disabled={ocupado} onClick={onReintentar}>
              Intentar de nuevo
            </button>
          )}
        </div>
      </section>
    </main>
  )
}
