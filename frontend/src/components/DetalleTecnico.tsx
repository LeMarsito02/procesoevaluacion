import type { DetalleTecnico as Detalle } from '../api'
import { conGlosario } from '../glosario'

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
/** Cuánta de la experiencia exigida quedó acreditada. Es la pregunta que se
 * hace quien revisa —¿alcanza o no?— y en dos cifras sueltas hay que dividir
 * mentalmente; en una barra se ve de un golpe. */
function BarraExperiencia({ certificado, exigido }: { certificado: number; exigido: number }) {
  const proporcion = exigido > 0 ? certificado / exigido : 0
  const alcanza = proporcion >= 1
  return (
    <div className="barra-medida" data-alcanza={alcanza}>
      <div className="barra-medida-pista">
        <div className="barra-medida-relleno" style={{ width: `${Math.min(100, Math.round(proporcion * 100))}%` }} />
      </div>
      <span className="small">
        {alcanza
          ? `Alcanza (${Math.round(proporcion * 100)} % de lo exigido)`
          : `Falta el ${Math.max(0, Math.round((1 - proporcion) * 100))} % de lo exigido`}
      </span>
    </div>
  )
}


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
              {' · '}se exigen <strong>{smmlv(detalle.valor_a_certificar)}</strong>
              {detalle.factor != null && ` (${porcentaje(detalle.factor)} del presupuesto del lote)`}
            </>
          )}
        </span>
        {detalle.valor_a_certificar ? (
          <BarraExperiencia certificado={detalle.valor_certificado ?? 0} exigido={detalle.valor_a_certificar} />
        ) : null}
        <span>
          Al menos un contrato llega al porcentaje exigido: <Marca valor={detalle.un_contrato_70} />
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
              <span key={p} className="contrato-ficha-problema">{conGlosario(p)}</span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
