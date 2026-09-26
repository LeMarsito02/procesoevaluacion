import { conGlosario, partirMotivos } from '../glosario'

/** Lo que el motor concluyó sobre un requisito.
 *
 * El motor devuelve los motivos en una sola línea separados por "; ". Con tres
 * o cuatro problemas —y es lo normal en una oferta con varios contratos— eso
 * es un párrafo que hay que releer para saber cuántas cosas pasan. En lista se
 * cuentan de un vistazo, y cada una se puede leer sola. */
export default function Motivos({
  motivo,
  tono,
}: {
  motivo: string | null | undefined
  tono?: 'warn' | 'bad' | undefined
}) {
  const partes = partirMotivos(motivo)
  if (partes.length === 0) return null
  if (partes.length === 1) {
    return (
      <div className="motivo" data-tono={tono}>
        {conGlosario(partes[0])}
      </div>
    )
  }
  return (
    <ul className="motivo motivo-lista" data-tono={tono}>
      {partes.map((parte, i) => (
        <li key={i}>{conGlosario(parte)}</li>
      ))}
    </ul>
  )
}
