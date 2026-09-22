import type { DetalleTecnico as Detalle, IntegranteFinanciero } from '../api'

const pesos = (v: number | null | undefined) =>
  v == null ? '—' : `$${v.toLocaleString('es-CO', { maximumFractionDigits: 0 })}`
const razon = (v: number | null | undefined, dec = 3) =>
  v == null ? 'indeterminado' : v.toLocaleString('es-CO', { minimumFractionDigits: dec, maximumFractionDigits: dec })
const porcentaje = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 10000) / 100} %`)

/** Cifras del RUP de cada integrante con las que se calcularon los indicadores. */
function CifrasRup({ integrantes }: { integrantes: IntegranteFinanciero[] }) {
  return (
    <>
      {integrantes.map((i) => (
        <div key={i.nombre} className="contrato-ficha" data-problema={i.financiera == null}>
          <div className="contrato-ficha-titulo">
            {i.nombre}
            {integrantes.length > 1 ? ` · ${porcentaje(i.participacion)}` : ''}
            {i.financiera?.fecha_corte ? ` · corte ${i.financiera.fecha_corte}` : ''}
          </div>
          {i.financiera ? (
            <div className="contrato-ficha-datos">
              <span>Activo corriente {pesos(i.financiera.activo_corriente)} · total {pesos(i.financiera.activo_total)}</span>
              <span>Pasivo corriente {pesos(i.financiera.pasivo_corriente)} · total {pesos(i.financiera.pasivo_total)}</span>
              <span>Patrimonio {pesos(i.financiera.patrimonio)}</span>
              <span>
                Utilidad operacional {pesos(i.financiera.utilidad_operacional)} · gastos de intereses{' '}
                {pesos(i.financiera.gastos_intereses)}
              </span>
            </div>
          ) : (
            <div className="contrato-ficha-datos">
              <span>No se leyó la información financiera de su RUP{i.rup ? '' : ' (no se encontró el RUP)'}.</span>
            </div>
          )}
        </div>
      ))}
    </>
  )
}

/** Desglose de un requisito financiero: indicadores, capital de trabajo,
 * capacidad residual por integrante o validez de los contadores. En fichas,
 * como el detalle técnico, para no desbordar el panel lateral. */
export default function DetalleFinanciero({ detalle }: { detalle: Detalle }) {
  const f = detalle.financiera
  if (!f || f.no_aplica) return null
  const integrantes = detalle.integrantes_financieros ?? []
  return (
    <div className="detalle-tecnico">
      <div className="detalle-tecnico-resumen">
        {'liquidez' in f && (
          <span>
            Liquidez <strong>{razon(f.liquidez)}</strong> · endeudamiento <strong>{razon(f.endeudamiento)}</strong> ·
            cobertura de intereses <strong>{razon(f.cobertura, 2)}</strong>
          </span>
        )}
        {'roa' in f && (
          <span>
            Rentabilidad del activo <strong>{razon(f.roa)}</strong> · del patrimonio <strong>{razon(f.roe)}</strong>
          </span>
        )}
        {f.capital_de_trabajo != null && (
          <span>
            Capital de trabajo <strong>{pesos(f.capital_de_trabajo)}</strong> · exigido {pesos(f.demandado)}
          </span>
        )}
        {f.exigida != null && (
          <span>
            Capacidad residual del proponente <strong>{f.crp != null ? pesos(f.crp) : 'sin calcular'}</strong> · exigida{' '}
            {pesos(f.exigida)}
          </span>
        )}
      </div>
      {f.integrantes?.map((r) => (
        <div key={r.nombre} className="contrato-ficha" data-problema={r.crp == null}>
          <div className="contrato-ficha-titulo">
            {r.nombre} · CRP {r.crp != null ? pesos(r.crp) : 'sin calcular'}
          </div>
          <div className="contrato-ficha-datos">
            <span>CO (mayor ingreso operacional) {pesos(r.co)}</span>
            <span>
              E {r.e != null ? razon(r.e, 2) : '—'} → {r.puntos_e ?? '—'} pts · CT {r.profesionales ?? 0} profesionales →{' '}
              {r.puntos_ct ?? 0} pts · CF liquidez {razon(r.liquidez, 2)} → {r.puntos_cf ?? '—'} pts
            </span>
            <span>SCE (saldo de contratos en ejecución) {r.sce != null ? pesos(r.sce) : 'sin leer'}</span>
          </div>
        </div>
      ))}
      {f.validez &&
        Object.entries(f.validez).map(([nombre, v]) => (
          <div key={nombre} className="contrato-ficha" data-problema={Object.values(v.tarjetas).some((t) => !t.startsWith('vigente'))}>
            <div className="contrato-ficha-titulo">{nombre}</div>
            <div className="contrato-ficha-datos">
              {Object.entries(v.tarjetas).map(([tp, estado]) => (
                <span key={tp}>
                  T.P. {tp}: certificado de la Junta Central de Contadores {estado}
                </span>
              ))}
              <span className="small muted">{v.estados.map((e) => e.split('/').pop()).join(' · ')}</span>
            </div>
          </div>
        ))}
      {('liquidez' in f || 'roa' in f || f.capital_de_trabajo != null) && integrantes.length > 0 && (
        <CifrasRup integrantes={integrantes} />
      )}
    </div>
  )
}
