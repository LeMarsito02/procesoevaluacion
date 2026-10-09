import type { Proponente, ResultadoRequisito } from '../api'
import type { FormatoInforme } from '../evaluaciones'
import { resumenProponente, type Revisiones } from '../estado'
import Icono from './Icono'
import { useDialogos } from '../dialogos'

interface Props {
  /** Área de la evaluación ("Técnica"), para el rótulo y el título. */
  areaNombre: string
  codigoProceso: string
  /** Nombre de archivo que genera el servidor. */
  nombreArchivo: string
  proponentes: Proponente[]
  resultados: Record<string, ResultadoRequisito[]>
  revisiones: Revisiones
  generando: boolean
  error: string | null
  onGenerar: (formato?: FormatoInforme) => void
  /** Informe con las tres áreas del proceso. */
  onGenerarConsolidado?: (formato?: 'xlsx' | 'pdf') => void
  generandoConsolidado?: boolean
  /** Reporte Word y expediente permanente. */
  extra?: React.ReactNode
  onVolver: () => void
  onRevisarPendientes: () => void
  onNuevaEvaluacion: () => void
}

export default function PasoInforme(p: Props) {
  const { confirmar } = useDialogos()
  const evaluados = p.proponentes.filter((pr) => p.resultados[pr.hoja])
  const resumenes = evaluados.map((pr) => ({ pr, ...resumenProponente(p.resultados[pr.hoja], p.revisiones) }))
  const pendientes = resumenes.reduce((s, r) => s + r.pendientes, 0)
  const conPendientes = resumenes.filter((r) => r.pendientes > 0).length
  const noCumplen = resumenes.filter((r) => r.noCumple > 0 && r.pendientes === 0).length
  const listos = resumenes.filter((r) => r.pendientes === 0 && r.noCumple === 0).length
  const faltan = p.proponentes.length - evaluados.length

  /** Descargar con pendientes no se bloquea —a veces hay que sacar un borrador—
   * pero sí se confirma: en el Excel esas verificaciones salen como NO CUMPLE,
   * y eso en el informe oficial es rechazar a un proponente por algo que nadie
   * llegó a mirar. */
  async function descargar(formato: FormatoInforme = 'xlsx') {
    // El CSV no marca NO CUMPLE lo pendiente: lo deja «Pendiente de revisión».
    if (pendientes > 0 && formato !== 'csv') {
      const seguir = await confirmar({
        titulo: '¿Descargar el informe con verificaciones sin revisar?',
        mensaje: (
          <>
            Quedan <strong>{pendientes} verificaciones</strong> que nadie ha revisado. En el Excel saldrán como
            «NO CUMPLE» con el motivo que encontró el programa: estaría rechazando por algo que nadie llegó a mirar.
          </>
        ),
        aceptar: 'Descargar así',
        cancelar: 'Volver a revisarlas',
        peligro: true,
      })
      if (!seguir) return
    }
    p.onGenerar(formato)
  }

  return (
    <main className="page page-narrow">
      <div className="page-head">
        <div>
          <div className="eyebrow">Evaluación {p.areaNombre.toLowerCase()}</div>
          <h1>Informe de evaluación {p.areaNombre.toLowerCase()}</h1>
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
            <strong>Quedan {pendientes} verificaciones sin revisar.</strong> Si descarga el informe ahora, esas
            verificaciones salen como “NO CUMPLE” con el motivo que encontró el programa: estaría rechazando por algo
            que nadie llegó a mirar. Revíselas primero.
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

      <section className="card" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 18 }}>
        <div className="dropzone-icon" style={{ background: 'var(--ok-soft)', color: 'var(--ok)' }}>
          <Icono nombre="descargar" tam={22} />
        </div>
        <div style={{ flex: 1 }}>
          <strong>{p.nombreArchivo}</strong>
          <div className="small muted">Plantilla oficial con un resultado por requisito y por proponente.</div>
        </div>
        <button
          className={pendientes > 0 ? 'btn btn-secondary btn-lg' : 'btn btn-primary btn-lg'}
          type="button"
          onClick={() => void descargar()}
          disabled={p.generando || evaluados.length === 0}
        >
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
        <div className="informe-formatos">
          <button className="btn btn-ghost btn-sm" type="button" onClick={() => void descargar('pdf')} disabled={p.generando || evaluados.length === 0}>
            PDF
          </button>
          <button className="btn btn-ghost btn-sm" type="button" onClick={() => void descargar('csv')} disabled={p.generando || evaluados.length === 0} title="Resultados por proponente y requisito, con la decisión final">
            CSV
          </button>
        </div>
      </section>

      {p.onGenerarConsolidado && (
        <section className="card" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 18, marginTop: 16 }}>
          <div className="dropzone-icon">
            <Icono nombre="balanza" tam={22} />
          </div>
          <div style={{ flex: 1 }}>
            <strong>Consolidado del proceso</strong>
            <div className="small muted">
              Jurídica, técnica y financiera por lote, con el puntaje que asigna el programa y el orden de elegibilidad.
            </div>
          </div>
          <button className="btn btn-secondary" type="button" onClick={() => p.onGenerarConsolidado?.('xlsx')} disabled={p.generandoConsolidado}>
            {p.generandoConsolidado ? <span className="spinner oscuro" /> : <Icono nombre="descargar" />} Descargar consolidado
          </button>
          <button className="btn btn-ghost btn-sm" type="button" onClick={() => p.onGenerarConsolidado?.('pdf')} disabled={p.generandoConsolidado}>
            PDF
          </button>
        </section>
      )}

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
