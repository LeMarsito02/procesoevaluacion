import { useEffect, useMemo, useState } from 'react'
import { evaluarRequisito, verDocumento, type ProcesoDocumentoBase, type Proponente, type ResultadoRequisito } from './api'
import { formatDuracion } from './format'

interface RequisitoSectionProps {
  numero: number
  requisito: number
  titulo: string
  descripcion: string
  textoBoton: string
  proponentes: Proponente[]
  construirPayload: () => ProcesoDocumentoBase
  onAbrirVisor: (nombre: string, url: string) => void
  onResultadosChange: (resultados: ResultadoRequisito[]) => void
  renderMotivo?: (r: ResultadoRequisito) => React.ReactNode
  renderExtraCumple?: (r: ResultadoRequisito) => React.ReactNode
  /** Resultados que llegan de "Evaluar todos los requisitos": reemplazan los
   * de esta sección igual que si se hubiera evaluado desde su botón. */
  resultadosExternos?: ResultadoRequisito[]
}

export default function RequisitoSection({
  numero,
  requisito,
  titulo,
  descripcion,
  textoBoton,
  proponentes,
  construirPayload,
  onAbrirVisor,
  onResultadosChange,
  renderMotivo,
  renderExtraCumple,
  resultadosExternos,
}: RequisitoSectionProps) {
  const [resultados, setResultados] = useState<ResultadoRequisito[]>([])
  const [evaluando, setEvaluando] = useState(false)
  const [errorEvaluacion, setErrorEvaluacion] = useState<string | null>(null)
  const [progreso, setProgreso] = useState<{ completados: number; total: number } | null>(null)
  const [inicioEvaluacion, setInicioEvaluacion] = useState<number | null>(null)
  const [ultimaEstimacion, setUltimaEstimacion] = useState<{ restanteMs: number; timestamp: number } | null>(null)
  const [ahora, setAhora] = useState(() => Date.now())
  const [overrides, setOverrides] = useState<Record<string, boolean>>({})
  const [cargandoDocumento, setCargandoDocumento] = useState<string | null>(null)
  const [errorVisor, setErrorVisor] = useState<string | null>(null)
  const [seleccionArchivo, setSeleccionArchivo] = useState<Record<string, string>>({})

  // Ajuste durante el render (patrón recomendado por React en vez de un
  // efecto): cuando llegan resultados nuevos de "Evaluar todos", reemplazan
  // los de la sección.
  const [externosAplicados, setExternosAplicados] = useState(resultadosExternos)
  if (resultadosExternos !== externosAplicados) {
    setExternosAplicados(resultadosExternos)
    if (resultadosExternos) {
      setOverrides({})
      setResultados(resultadosExternos)
    }
  }

  useEffect(() => {
    if (!evaluando) return
    const id = window.setInterval(() => setAhora(Date.now()), 500)
    return () => window.clearInterval(id)
  }, [evaluando])

  const tiempos = useMemo(() => {
    if (!inicioEvaluacion || !progreso) return null
    const transcurridoMs = ahora - inicioEvaluacion
    if (!ultimaEstimacion) return { transcurridoMs, restanteMs: null as number | null }
    const restanteMs = Math.max(0, ultimaEstimacion.restanteMs - (ahora - ultimaEstimacion.timestamp))
    return { transcurridoMs, restanteMs }
  }, [ahora, inicioEvaluacion, progreso, ultimaEstimacion])

  const resultadosConRevision = useMemo(
    () =>
      resultados.map((r) => {
        const override = overrides[r.hoja]
        if (override === undefined) return r
        return { ...r, cumple: override, motivo: override ? null : r.motivo, error: null }
      }),
    [resultados, overrides],
  )

  useEffect(() => {
    onResultadosChange(resultadosConRevision)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resultadosConRevision])

  const pendientesRevision = resultadosConRevision.filter((r) => r.error || r.cumple === false)
  const sinObservaciones = resultadosConRevision.filter((r) => !r.error && r.cumple === true)

  async function handleEvaluar() {
    setEvaluando(true)
    setErrorEvaluacion(null)
    setOverrides({})
    setResultados([])
    setProgreso({ completados: 0, total: proponentes.length })
    setUltimaEstimacion(null)
    const inicio = Date.now()
    setInicioEvaluacion(inicio)
    setAhora(inicio)
    try {
      const proceso = construirPayload()
      const nuevos = await evaluarRequisito(requisito, proceso, proponentes, (completados, total) => {
        setProgreso({ completados, total })
        const ahoraMs = Date.now()
        const msPorItem = (ahoraMs - inicio) / completados
        setUltimaEstimacion({ restanteMs: msPorItem * (total - completados), timestamp: ahoraMs })
      })
      setResultados(nuevos)
    } catch (err) {
      setErrorEvaluacion(err instanceof Error ? err.message : 'Error desconocido al evaluar.')
    } finally {
      setEvaluando(false)
      setProgreso(null)
      setInicioEvaluacion(null)
      setUltimaEstimacion(null)
    }
  }

  async function handleVerDocumento(r: ResultadoRequisito, archivo?: string) {
    const rutaArchivo = archivo ?? r.archivo_evaluado
    if (!rutaArchivo) return
    const proponente = proponentes.find((p) => p.hoja === r.hoja)
    if (!proponente) return

    setCargandoDocumento(r.hoja)
    setErrorVisor(null)
    try {
      const blob = await verDocumento(proponente.drive_file_id, rutaArchivo)
      const url = URL.createObjectURL(blob)
      onAbrirVisor(`${r.nombre_proponente} — ${rutaArchivo}`, url)
    } catch (err) {
      setErrorVisor(err instanceof Error ? err.message : 'No se pudo abrir el documento.')
    } finally {
      setCargandoDocumento(null)
    }
  }

  function marcarRevisado(hoja: string, cumple: boolean) {
    setOverrides((prev) => ({ ...prev, [hoja]: cumple }))
  }

  function quitarRevision(hoja: string) {
    setOverrides((prev) => {
      const next = { ...prev }
      delete next[hoja]
      return next
    })
  }

  if (proponentes.length === 0) return null

  return (
    <section className="panel">
      <h2>
        {numero}. {titulo}
      </h2>
      <p className="help-text">{descripcion}</p>

      <div className="actions" style={{ marginBottom: 16 }}>
        <button className="btn secondary" type="button" onClick={handleEvaluar} disabled={evaluando}>
          {evaluando ? 'Evaluando…' : textoBoton}
        </button>
      </div>

      {progreso && (
        <div style={{ marginBottom: 16 }}>
          <div className="progress-track">
            <div
              className="progress-fill"
              style={{ width: `${(progreso.completados / Math.max(progreso.total, 1)) * 100}%` }}
            />
          </div>
          <p className="help-text" style={{ marginTop: 6 }}>
            Evaluando {progreso.completados} de {progreso.total} proponentes… (
            {Math.round((progreso.completados / Math.max(progreso.total, 1)) * 100)}%)
            {tiempos && (
              <>
                {' — transcurrido: '}
                {formatDuracion(tiempos.transcurridoMs)}
                {tiempos.restanteMs !== null && (
                  <>
                    {', estimado restante: '}
                    {formatDuracion(tiempos.restanteMs)}
                  </>
                )}
              </>
            )}
          </p>
        </div>
      )}

      {errorEvaluacion && <div className="alert danger">{errorEvaluacion}</div>}
      {errorVisor && <div className="alert danger">{errorVisor}</div>}

      {pendientesRevision.length > 0 && (
        <>
          <h3 style={{ marginTop: 8 }}>Pendientes de revisión humana ({pendientesRevision.length})</h3>
          <p className="help-text">
            El programa marcó estos como "no cumple" o no pudo evaluarlos. Abre el documento y confirma si de
            verdad no cumple, o corrígelo si el programa se equivocó.
          </p>
          <table className="lotes-table">
            <thead>
              <tr>
                <th>Hoja</th>
                <th>Proponente</th>
                <th>Motivo</th>
                <th>Revisión</th>
              </tr>
            </thead>
            <tbody>
              {pendientesRevision.map((r) => {
                const overridden = overrides[r.hoja] !== undefined
                return (
                  <tr key={r.hoja}>
                    <td className="numero">{r.hoja}</td>
                    <td>{r.nombre_proponente}</td>
                    <td>{renderMotivo ? renderMotivo(r) : (r.error ?? r.motivo)}</td>
                    <td>
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                        {r.archivo_evaluado && (
                          <button
                            className="btn secondary"
                            type="button"
                            onClick={() => handleVerDocumento(r)}
                            disabled={cargandoDocumento === r.hoja}
                          >
                            {cargandoDocumento === r.hoja ? 'Abriendo…' : 'Ver documento'}
                          </button>
                        )}
                        {!r.archivo_evaluado && r.archivos_disponibles.length > 0 && (
                          <>
                            <select
                              value={seleccionArchivo[r.hoja] ?? r.archivos_disponibles[0]}
                              onChange={(e) =>
                                setSeleccionArchivo((prev) => ({ ...prev, [r.hoja]: e.target.value }))
                              }
                              style={{ maxWidth: 260 }}
                            >
                              {r.archivos_disponibles.map((a) => (
                                <option key={a} value={a}>
                                  {a}
                                </option>
                              ))}
                            </select>
                            <button
                              className="btn secondary"
                              type="button"
                              onClick={() =>
                                handleVerDocumento(r, seleccionArchivo[r.hoja] ?? r.archivos_disponibles[0])
                              }
                              disabled={cargandoDocumento === r.hoja}
                            >
                              {cargandoDocumento === r.hoja ? 'Abriendo…' : 'Ver documento'}
                            </button>
                          </>
                        )}
                        {overridden ? (
                          <>
                            <span style={{ fontSize: 13 }}>
                              Marcado manualmente: <strong>{overrides[r.hoja] ? 'CUMPLE' : 'NO CUMPLE'}</strong>
                            </span>
                            <button className="btn secondary" type="button" onClick={() => quitarRevision(r.hoja)}>
                              Deshacer
                            </button>
                          </>
                        ) : (
                          <button className="btn secondary" type="button" onClick={() => marcarRevisado(r.hoja, true)}>
                            Confirmar que sí cumple
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </>
      )}

      {sinObservaciones.length > 0 && (
        <details style={{ marginTop: 16 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
            Cumplen, sin necesidad de revisión ({sinObservaciones.length})
          </summary>
          <table className="lotes-table" style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>Hoja</th>
                <th>Proponente</th>
                <th>Archivo evaluado</th>
                {renderExtraCumple && <th>Detalle</th>}
              </tr>
            </thead>
            <tbody>
              {sinObservaciones.map((r) => (
                <tr key={r.hoja}>
                  <td className="numero">{r.hoja}</td>
                  <td>{r.nombre_proponente}</td>
                  <td>{r.archivo_evaluado}</td>
                  {renderExtraCumple && <td>{renderExtraCumple(r)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </section>
  )
}
