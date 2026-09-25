import type { PuntoDeRevision } from '../api'

/** Lo que falta por mirar en este punto del informe, separado por ámbito.
 * Importa la separación: lo que sale del pliego es igual para todos los
 * proponentes y se resuelve una vez en «Requisitos del pliego que el programa
 * no verifica»; lo de la oferta hay que mirarlo en esta oferta. Nada de esto
 * está aprobado —por eso aparece—, pero saber cuál es cuál es la diferencia
 * entre revisar una vez y revisarlo trece veces. */
export default function QueFaltaRevisar({
  revisiones,
  acreditada,
}: {
  revisiones: PuntoDeRevision[] | undefined
  acreditada?: boolean
}) {
  if (!revisiones || revisiones.length === 0) return null
  const delProceso = revisiones.filter((r) => r.ambito === 'proceso')
  const deLaOferta = revisiones.filter((r) => r.ambito === 'oferta')
  return (
    <div className="que-falta">
      {acreditada && deLaOferta.length === 0 && (
        <p className="que-falta-nota">
          Lo que trae la oferta está verificado. Lo que falta sale del pliego y es igual para todos los proponentes:
          resolverlo una vez los libera a todos.
        </p>
      )}
      {deLaOferta.length > 0 && (
        <div>
          <h4>Por revisar en esta oferta ({deLaOferta.length})</h4>
          <ul>
            {deLaOferta.map((r) => (
              <li key={r.clave}>
                {r.que}
                {r.donde && <span className="small muted"> · {r.donde}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {delProceso.length > 0 && (
        <div>
          <h4>Por resolver una vez en el proceso ({delProceso.length})</h4>
          <ul>
            {delProceso.map((r) => (
              <li key={r.clave}>{r.que}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
