import type { DetalleTecnico as Detalle } from '../api'

const smmlv = (v: number | null | undefined) =>
  v == null ? '—' : v.toLocaleString('es-CO', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const porcentaje = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 10000) / 100} %`)

function Marca({ valor }: { valor: boolean | null | undefined }) {
  if (valor == null) return <span className="marca-tecnica" data-tono="warn">por revisar</span>
  return <span className="marca-tecnica" data-tono={valor ? 'ok' : 'bad'}>{valor ? 'cumple' : 'no cumple'}</span>
}

/** Desglose de la experiencia de un lote: cada contrato del Formato 3 tal
 * como quedó verificado en el RUP. En fichas, sin tabla ancha, para que el
 * panel lateral no necesite desplazamiento horizontal. */
export default function DetalleTecnico({ detalle }: { detalle: Detalle }) {
  if (!detalle.contratos) return null
  const integrantes = detalle.integrantes ?? []
  return (
    <div className="detalle-tecnico">
      <div className="detalle-tecnico-resumen">
        <span>
          Certifica <strong>{smmlv(detalle.valor_certificado)}</strong> SMMLV
          {detalle.valor_a_certificar != null && (
            <>
              {' '}de <strong>{smmlv(detalle.valor_a_certificar)}</strong> ({porcentaje(detalle.factor)} del presupuesto)
            </>
          )}
        </span>
        <span>
          Un contrato por el porcentaje exigido: <Marca valor={detalle.un_contrato_70} />
        </span>
        {detalle.longitud_minima_km != null && (
          <span>
            Longitud de al menos {detalle.longitud_minima_km.toLocaleString('es-CO', { maximumFractionDigits: 3 })} km en un
            contrato: <Marca valor={detalle.longitud} />
          </span>
        )}
        {integrantes.length > 1 && (
          <span>
            Porcentajes de los integrantes (3.5.3 D): <Marca valor={detalle.condiciones_plural} />
          </span>
        )}
      </div>
      {integrantes.length > 1 && (
        <ul className="detalle-tecnico-integrantes">
          {integrantes.map((i) => (
            <li key={i.nombre}>
              <strong>{i.nombre}</strong> · {porcentaje(i.participacion)} del proponente · aporta{' '}
              {smmlv(detalle.aporte_por_integrante?.[i.nombre] ?? 0)} SMMLV{i.rup ? '' : ' · sin RUP'}
            </li>
          ))}
        </ul>
      )}
      {detalle.contratos.map((c) => (
        <div key={`${c.orden}-${c.consecutivos.join('-')}`} className="contrato-ficha" data-problema={c.problemas.length > 0}>
          <div className="contrato-ficha-titulo">
            Contrato {c.orden} · consecutivo RUP {c.consecutivos.join(', ') || '—'}
          </div>
          <div className="contrato-ficha-datos">
            <span>{c.contratante || 'Contratante no indicado'}{c.numero_contrato ? ` · ${c.numero_contrato}` : ''}</span>
            <span>
              Valor RUP {smmlv(c.valor_smmlv)} × {porcentaje(c.participacion)} = <strong>{smmlv(c.valor_aportado)}</strong> SMMLV
            </span>
            <span>
              UNSPSC: {c.unspsc == null ? '—' : c.unspsc ? 'sí' : 'no'}
              {c.longitud_km != null && ` · longitud ${c.longitud_km.toLocaleString('es-CO', { maximumFractionDigits: 3 })} km`}
              {c.longitud_km == null && c.area_m2 != null &&
                ` · área intervenida ${c.area_m2.toLocaleString('es-CO', { maximumFractionDigits: 2 })} m² (sin longitud: pide aclaración)`}
              {c.de_un_socio && ' · experiencia de socio'}
            </span>
            {c.objeto && <span className="muted">{c.objeto}</span>}
            {c.problemas.map((p) => (
              <span key={p} className="contrato-ficha-problema">{p}</span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
