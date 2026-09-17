import type { Proponente, ResultadoRequisito } from '../api'
import { resumenProponente, type Revisiones } from '../estado'
import Icono from './Icono'

interface Props {
  codigoProceso: string
  /** Nombre de archivo que genera el servidor. */
  nombreArchivo: string
  proponentes: Proponente[]
  resultados: Record<string, ResultadoRequisito[]>
  revisiones: Revisiones
  generando: boolean
  error: string | null
  onGenerar: () => void
  /** Reporte Word y expediente permanente. */
  extra?: React.ReactNode
  onVolver: () => void
  onRevisarPendientes: () => void
  onNuevaEvaluacion: () => void
}

export default function PasoInforme(p: Props) {
  const evaluados = p.proponentes.filter((pr) => p.resultados[pr.hoja])
  const resumenes = evaluados.map((pr) => ({ pr, ...resumenProponente(p.resultados[pr.hoja], p.revisiones) }))
  const pendientes = resumenes.reduce((s, r) => s + r.pendientes, 0)
  const conPendientes = resumenes.filter((r) => r.pendientes > 0).length
  const noCumplen = resumenes.filter((r) => r.noCumple > 0 && r.pendientes === 0).length
  const listos = resumenes.filter((r) => r.pendientes === 0 && r.noCumple === 0).length
  const faltan = p.proponentes.length - evaluados.length

  return (
    <main className="page page-narrow">
      <div className="page-head">
        <div>
          <div className="eyebrow">Evaluación jurídica</div>
          <h1>Informe de evaluación jurídica</h1>
          <p>Descargue el Excel con el resultado de cada proponente, listo para el informe del proceso {p.codigoProceso}.</p>
        </div>
      </div>

      <div className="kpis" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
        <div className="kpi" data-tone="ok">
          <div className="kpi-label">Cumplen todo</div>
          <div className="kpi-value">{listos}</div>
          <div className="kpi-sub">proponentes</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">Con algún “no cumple”</div>
          <div className="kpi-value" style={{ color: noCumplen ? 'var(--bad)' : undefined }}>
            {noCumplen}
          </div>
          <div className="kpi-sub">decidido por usted</div>
        </div>
        <div className="kpi" data-tone={conPendientes ? 'warn' : 'ok'}>
          <div className="kpi-label">Con pendientes</div>
          <div className="kpi-value">{conPendientes}</div>
          <div className="kpi-sub">{pendientes} verificaciones sin revisar</div>
        </div>
      </div>

      {faltan > 0 && (
        <div className="callout callout-warn" style={{ marginBottom: 16 }}>
          <Icono nombre="alerta" />
          <div>
            <strong>{faltan} proponente(s) aún no se han evaluado.</strong> Aparecerán vacíos en el informe.
          </div>
        </div>
      )}

      {pendientes > 0 ? (
        <div className="callout callout-warn" style={{ marginBottom: 20, alignItems: 'center' }}>
          <Icono nombre="alerta" />
          <div style={{ flex: 1 }}>
            <strong>Quedan {pendientes} verificaciones sin revisar.</strong> En el Excel aparecerán como “NO CUMPLE” con el
            motivo que encontró el sistema. Le recomendamos revisarlas antes de descargar.
          </div>
          <button className="btn btn-secondary btn-sm" type="button" onClick={p.onRevisarPendientes}>
            Revisar ahora
          </button>
        </div>
      ) : (
        faltan === 0 && (
          <div className="callout callout-ok" style={{ marginBottom: 20 }}>
            <Icono nombre="escudo" />
            <div>
              <strong>Todo está revisado.</strong> El informe refleja la verificación automática y sus decisiones.
            </div>
          </div>
        )
      )}

      {p.error && (
        <div className="callout callout-bad" style={{ marginBottom: 16 }}>
          <Icono nombre="alerta" />
          <div>{p.error}</div>
        </div>
      )}

      <section className="card" style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
        <div className="dropzone-icon" style={{ background: 'var(--ok-soft)', color: 'var(--ok)' }}>
          <Icono nombre="descargar" tam={22} />
        </div>
        <div style={{ flex: 1 }}>
          <strong>{p.nombreArchivo}</strong>
          <div className="small muted">Plantilla oficial con un resultado por requisito y por proponente.</div>
        </div>
        <button className="btn btn-primary btn-lg" type="button" onClick={p.onGenerar} disabled={p.generando || evaluados.length === 0}>
          {p.generando ? (
            <>
              <span className="spinner" /> Generando…
            </>
          ) : (
            <>
              <Icono nombre="descargar" /> Descargar Excel
            </>
          )}
        </button>
      </section>

      {p.extra}

      <div className="acciones-pie">
        <button className="btn btn-ghost" type="button" onClick={p.onVolver}>
          <Icono nombre="atras" /> Volver a la revisión
        </button>
        <button className="btn btn-ghost" type="button" onClick={p.onNuevaEvaluacion}>
          <Icono nombre="mas" /> Nuevo proceso
        </button>
      </div>
    </main>
  )
}
