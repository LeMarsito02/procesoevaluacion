import { useMemo, useState } from 'react'
import './App.css'
import {
  analizarDocumentoBase,
  generarExcel,
  type AnalisisResponse,
  type Lote,
  type ProcesoDocumentoBase,
  type Proponente,
  type ResultadoRequisito,
} from './api'
import { addMonthsClamped, formatFechaCorta, formatPesos } from './format'
import RequisitoSection from './RequisitoSection'

type BaseCalculo = 'lote_mayor_valor' | 'presupuesto_total'

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function App() {
  const [step, setStep] = useState<'form' | 'review'>('form')

  // --- Paso 1: formulario de entrada ---
  const [codigoProceso, setCodigoProceso] = useState('')
  const [fechaCierre, setFechaCierre] = useState(todayIso())
  const [archivo, setArchivo] = useState<File | null>(null)
  const [carpetaDrive, setCarpetaDrive] = useState('')
  const [analizando, setAnalizando] = useState(false)
  const [errorAnalisis, setErrorAnalisis] = useState<string | null>(null)

  // --- Proponentes leídos de Drive ---
  const [proponentes, setProponentes] = useState<Proponente[]>([])
  const [noReconocidos, setNoReconocidos] = useState<string[]>([])
  const [driveError, setDriveError] = useState<string | null>(null)

  // --- Resultados de cada requisito (los llenan los RequisitoSection) ---
  // Un mapa numero de requisito -> sus resultados, para no tener que agregar
  // un useState nuevo cada vez que se conecta un requisito más.
  const [resultadosPorRequisito, setResultadosPorRequisito] = useState<Record<number, ResultadoRequisito[]>>({})

  function actualizarResultados(numero: number, resultados: ResultadoRequisito[]) {
    setResultadosPorRequisito((prev) => ({ ...prev, [numero]: resultados }))
  }

  const todosLosResultados = useMemo(() => Object.values(resultadosPorRequisito).flat(), [resultadosPorRequisito])

  // --- Visor de documentos (compartido entre requisitos) ---
  const [visor, setVisor] = useState<{ nombre: string; url: string } | null>(null)

  function abrirVisor(nombre: string, url: string) {
    setVisor({ nombre, url })
  }

  function cerrarVisor() {
    if (visor) URL.revokeObjectURL(visor.url)
    setVisor(null)
  }

  // --- Paso 2: datos editables tras el análisis ---
  const [objetoGeneral, setObjetoGeneral] = useState('')
  const [lotes, setLotes] = useState<Lote[]>([])
  const [vigenciaMeses, setVigenciaMeses] = useState(3)
  const [porcentajePct, setPorcentajePct] = useState(10)
  const [baseCalculo, setBaseCalculo] = useState<BaseCalculo>('lote_mayor_valor')
  const [advertencias, setAdvertencias] = useState<string[]>([])

  const [generando, setGenerando] = useState(false)
  const [errorGeneracion, setErrorGeneracion] = useState<string | null>(null)

  const derivados = useMemo(() => {
    const presupuestoTotal = lotes.reduce((sum, l) => sum + (Number(l.valor_presupuesto) || 0), 0)
    const loteMayor = lotes.reduce<Lote | null>((max, l) => {
      const valor = Number(l.valor_presupuesto) || 0
      if (!max || valor > (Number(max.valor_presupuesto) || 0)) return l
      return max
    }, null)

    const valorBase = baseCalculo === 'lote_mayor_valor' && loteMayor ? Number(loteMayor.valor_presupuesto) || 0 : presupuestoTotal
    const valorAsegurado = Math.round(valorBase * (porcentajePct / 100) * 100) / 100
    const fechaVencimiento = fechaCierre ? addMonthsClamped(fechaCierre, vigenciaMeses) : ''

    return {
      presupuestoTotal,
      loteMayorNumero: loteMayor?.numero ?? '',
      valorBase,
      valorAsegurado,
      fechaVencimiento,
    }
  }, [lotes, baseCalculo, porcentajePct, fechaCierre, vigenciaMeses])

  async function handleAnalizar(e: React.FormEvent) {
    e.preventDefault()
    if (!archivo) {
      setErrorAnalisis('Selecciona el PDF del Documento Base.')
      return
    }
    setAnalizando(true)
    setErrorAnalisis(null)
    try {
      const resultado = await analizarDocumentoBase(codigoProceso.trim(), fechaCierre, archivo, carpetaDrive)
      cargarProceso(resultado)
      setStep('review')
    } catch (err) {
      setErrorAnalisis(err instanceof Error ? err.message : 'Error desconocido al analizar el documento.')
    } finally {
      setAnalizando(false)
    }
  }

  function cargarProceso(resultado: AnalisisResponse) {
    const proceso = resultado.documento_base
    setObjetoGeneral(proceso.objeto_general)
    setLotes(proceso.lotes)
    setVigenciaMeses(proceso.garantia_seriedad.vigencia_meses)
    setPorcentajePct(Math.round(proceso.garantia_seriedad.porcentaje * 1000) / 10)
    setBaseCalculo(proceso.garantia_seriedad.base_calculo)
    setAdvertencias(proceso.advertencias)
    setProponentes(resultado.proponentes)
    setNoReconocidos(resultado.proponentes_no_reconocidos)
    setDriveError(resultado.drive_error)
    setResultadosPorRequisito({})
  }

  function updateLote(index: number, patch: Partial<Lote>) {
    setLotes((prev) => prev.map((l, i) => (i === index ? { ...l, ...patch } : l)))
  }

  function construirPayload(): ProcesoDocumentoBase {
    return {
      codigo_proceso: codigoProceso.trim(),
      fecha_cierre: fechaCierre,
      objeto_general: objetoGeneral,
      lotes,
      lote_mayor_valor: derivados.loteMayorNumero,
      presupuesto_total: derivados.presupuestoTotal,
      garantia_seriedad: {
        vigencia_meses: vigenciaMeses,
        porcentaje: porcentajePct / 100,
        base_calculo: baseCalculo,
        lote_base: baseCalculo === 'lote_mayor_valor' ? derivados.loteMayorNumero : null,
        valor_base: derivados.valorBase,
        valor_asegurado: derivados.valorAsegurado,
        fecha_cierre: fechaCierre,
        fecha_vencimiento: derivados.fechaVencimiento,
      },
      advertencias,
    }
  }

  async function handleGenerarExcel() {
    setGenerando(true)
    setErrorGeneracion(null)
    try {
      const payload = construirPayload()
      const blob = await generarExcel(payload, proponentes, todosLosResultados)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `INFORME EVALUACION JURIDICA ${payload.codigo_proceso}.xlsx`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setErrorGeneracion(err instanceof Error ? err.message : 'Error desconocido al generar el Excel.')
    } finally {
      setGenerando(false)
    }
  }

  return (
    <>
      <header className="app-header">
        <h1>Evaluación de procesos de contratación</h1>
        <p>Analiza el Documento Base y genera el Excel de evaluación jurídica.</p>
      </header>

      <div className="step-indicator">
        <span className={step === 'form' ? 'active' : ''}>
          {step === 'form' ? <strong>1. Documento Base</strong> : '1. Documento Base'}
        </span>
        <span>→</span>
        <span>{step === 'review' ? <strong>2. Revisión y Excel</strong> : '2. Revisión y Excel'}</span>
      </div>

      {step === 'form' && (
        <section className="panel">
          <h2>1. Datos del proceso y Documento Base</h2>
          <form onSubmit={handleAnalizar}>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="codigo">Código del proceso</label>
                <input
                  id="codigo"
                  type="text"
                  placeholder="CM-037-2026"
                  value={codigoProceso}
                  onChange={(e) => setCodigoProceso(e.target.value)}
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="fecha">Fecha de cierre</label>
                <input
                  id="fecha"
                  type="date"
                  value={fechaCierre}
                  onChange={(e) => setFechaCierre(e.target.value)}
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="archivo">Documento Base (PDF)</label>
                <input
                  id="archivo"
                  type="file"
                  accept="application/pdf"
                  onChange={(e) => setArchivo(e.target.files?.[0] ?? null)}
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="drive">Carpeta de Drive con proponentes (opcional)</label>
                <input
                  id="drive"
                  type="text"
                  placeholder="https://drive.google.com/drive/folders/..."
                  value={carpetaDrive}
                  onChange={(e) => setCarpetaDrive(e.target.value)}
                />
              </div>
            </div>

            {errorAnalisis && <div className="alert danger">{errorAnalisis}</div>}

            <div className="actions">
              <button className="btn" type="submit" disabled={analizando}>
                {analizando ? 'Analizando…' : 'Analizar documento base'}
              </button>
            </div>
          </form>
        </section>
      )}

      {step === 'review' && (
        <>
          <section className="panel">
            <h2>2. Objeto y lotes</h2>
            <p className="help-text">Revisa y corrige los datos extraídos antes de generar el Excel.</p>

            <div className="field" style={{ marginBottom: 16 }}>
              <label htmlFor="objeto-general">Objeto general del proceso</label>
              <textarea
                id="objeto-general"
                rows={2}
                value={objetoGeneral}
                onChange={(e) => setObjetoGeneral(e.target.value)}
              />
            </div>

            <table className="lotes-table">
              <thead>
                <tr>
                  <th>Lote</th>
                  <th>Objeto</th>
                  <th>Plazo (meses)</th>
                  <th>Valor Presupuesto Oficial</th>
                  <th>Lugar de ejecución</th>
                </tr>
              </thead>
              <tbody>
                {lotes.map((lote, i) => (
                  <tr key={i}>
                    <td className="numero">{lote.numero}</td>
                    <td>
                      <textarea
                        rows={3}
                        value={lote.objeto}
                        onChange={(e) => updateLote(i, { objeto: e.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        min={0}
                        value={lote.plazo_meses}
                        onChange={(e) => updateLote(i, { plazo_meses: Number(e.target.value) })}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        min={0}
                        value={lote.valor_presupuesto}
                        onChange={(e) => updateLote(i, { valor_presupuesto: Number(e.target.value) })}
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        value={lote.lugar_ejecucion ?? ''}
                        onChange={(e) => updateLote(i, { lugar_ejecucion: e.target.value })}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="summary-grid">
              <div className="summary-card">
                <div className="label">Lote de mayor valor</div>
                <div className="value">{derivados.loteMayorNumero || '—'}</div>
              </div>
              <div className="summary-card">
                <div className="label">Presupuesto Oficial total</div>
                <div className="value">{formatPesos(derivados.presupuestoTotal)}</div>
              </div>
            </div>
          </section>

          <section className="panel">
            <h2>3. Garantía de seriedad de la oferta</h2>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="vigencia">Vigencia (meses desde el cierre)</label>
                <input
                  id="vigencia"
                  type="number"
                  min={1}
                  value={vigenciaMeses}
                  onChange={(e) => setVigenciaMeses(Number(e.target.value))}
                />
              </div>
              <div className="field">
                <label htmlFor="porcentaje">Porcentaje asegurado (%)</label>
                <input
                  id="porcentaje"
                  type="number"
                  min={0}
                  step={0.1}
                  value={porcentajePct}
                  onChange={(e) => setPorcentajePct(Number(e.target.value))}
                />
              </div>
              <div className="field">
                <label htmlFor="base">Base de cálculo</label>
                <select id="base" value={baseCalculo} onChange={(e) => setBaseCalculo(e.target.value as BaseCalculo)}>
                  <option value="lote_mayor_valor">Lote de mayor valor</option>
                  <option value="presupuesto_total">Presupuesto Oficial total</option>
                </select>
              </div>
            </div>

            <div className="summary-grid">
              <div className="summary-card">
                <div className="label">Valor base</div>
                <div className="value">{formatPesos(derivados.valorBase)}</div>
              </div>
              <div className="summary-card">
                <div className="label">Valor asegurado requerido</div>
                <div className="value">{formatPesos(derivados.valorAsegurado)}</div>
              </div>
              <div className="summary-card">
                <div className="label">Fecha de cierre</div>
                <div className="value">{formatFechaCorta(fechaCierre)}</div>
              </div>
              <div className="summary-card">
                <div className="label">Vencimiento mínimo de la garantía</div>
                <div className="value">{formatFechaCorta(derivados.fechaVencimiento)}</div>
              </div>
            </div>

            {advertencias.length > 0 && (
              <div className="alert warn" style={{ marginTop: 16 }}>
                <strong>Revisa estos puntos:</strong>
                <ul>
                  {advertencias.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <section className="panel">
            <h2>4. Proponentes (Google Drive)</h2>

            {driveError && <div className="alert danger">{driveError}</div>}

            {!driveError && proponentes.length === 0 && (
              <p className="help-text">
                No se cargó ninguna carpeta de Drive o no se encontraron proponentes. Puedes generar el Excel de
                todas formas y completar los proponentes más adelante.
              </p>
            )}

            {proponentes.length > 0 && (
              <table className="lotes-table">
                <thead>
                  <tr>
                    <th>No.</th>
                    <th>Hoja</th>
                    <th>Proponente</th>
                    <th>Archivo en Drive</th>
                  </tr>
                </thead>
                <tbody>
                  {proponentes.map((p) => (
                    <tr key={p.drive_file_id}>
                      <td>{p.numero_orden}</td>
                      <td className="numero">{p.hoja}</td>
                      <td>{p.nombre_proponente}</td>
                      <td>{p.nombre_archivo}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {noReconocidos.length > 0 && (
              <div className="alert warn" style={{ marginTop: 16 }}>
                <strong>Archivos que no se pudieron interpretar (no siguen el patrón "pN nombre"):</strong>
                <ul>
                  {noReconocidos.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <RequisitoSection
            numero={5}
            requisito={1}
            titulo="Requisito 1: Carta de presentación de la oferta"
            descripcion={`Descarga el zip de cada proponente desde Drive, busca el Formato 1 por su título interno (sin importar el nombre del archivo) y verifica que mencione algún lote del Documento Base, el número del proceso, el objeto, y que tenga una firma del representante legal. Con ${proponentes.length} proponentes esto puede tardar varios minutos.`}
            textoBoton="Evaluar Formato 1 de todos los proponentes"
            proponentes={proponentes}
            construirPayload={construirPayload}
            onAbrirVisor={abrirVisor}
            onResultadosChange={(r) => actualizarResultados(1, r)}
          />

          <RequisitoSection
            numero={6}
            requisito={2}
            titulo="Requisito 2: Propuesta suscrita o avalada por un Ingeniero y/o Arquitecto"
            descripcion={`Busca el certificado COPNIA (Consejo Profesional Nacional de Ingeniería) por su título interno dentro de los documentos de cada proponente, y verifica que el nombre certificado coincida con quien firma la propuesta, que la matrícula esté vigente, y que el certificado no tenga más de 3 meses de expedido. Con ${proponentes.length} proponentes esto puede tardar varios minutos.`}
            textoBoton="Evaluar COPNIA de todos los proponentes"
            proponentes={proponentes}
            construirPayload={construirPayload}
            onAbrirVisor={abrirVisor}
            onResultadosChange={(r) => actualizarResultados(2, r)}
            renderExtraCumple={(r) => (
              <>
                {r.profesion_certificada ?? '—'} · Mat. {r.matricula_profesional ?? '—'} ·{' '}
                {r.copnia_fecha_expedicion ?? '—'}
              </>
            )}
          />

          <RequisitoSection
            numero={7}
            requisito={3}
            titulo="Requisito 3: Antecedentes disciplinarios del Ingeniero/Arquitecto (COPNIA)"
            descripcion={`Usa el mismo certificado COPNIA del Requisito 2 y verifica que certifique que el profesional está libre de antecedentes disciplinarios, y que no tenga más de 3 meses de expedido. Con ${proponentes.length} proponentes esto puede tardar varios minutos.`}
            textoBoton="Evaluar antecedentes COPNIA de todos los proponentes"
            proponentes={proponentes}
            construirPayload={construirPayload}
            onAbrirVisor={abrirVisor}
            onResultadosChange={(r) => actualizarResultados(3, r)}
            renderExtraCumple={(r) => (
              <>
                {r.profesion_certificada ?? '—'} · Mat. {r.matricula_profesional ?? '—'} ·{' '}
                {r.copnia_fecha_expedicion ?? '—'}
              </>
            )}
          />

          <RequisitoSection
            numero={8}
            requisito={4}
            titulo="Requisito 4: Conformación de Proponente Plural (Formato 2)"
            descripcion={`N.A. automático si el proponente es persona natural o jurídica individual. Si es Consorcio o Unión Temporal, busca el Formato 2 por su título interno y verifica que los integrantes sumen 100% de participación y que se pueda identificar al representante legal designado. Con ${proponentes.length} proponentes esto puede tardar varios minutos.`}
            textoBoton="Evaluar Conformación de Proponente Plural de todos los proponentes"
            proponentes={proponentes}
            construirPayload={construirPayload}
            onAbrirVisor={abrirVisor}
            onResultadosChange={(r) => actualizarResultados(4, r)}
            renderExtraCumple={(r) => r.tipo_proponente ?? '—'}
          />

          <RequisitoSection
            numero={9}
            requisito={5}
            titulo="Requisito 5: REDAM (Registro de Deudores Alimentarios Morosos)"
            descripcion={`Busca el certificado REDAM del representante legal (y del suplente, si es Consorcio/UT) por su título interno, y verifica que confirme que no está inscrito como deudor alimentario moroso. Con ${proponentes.length} proponentes esto puede tardar varios minutos.`}
            textoBoton="Evaluar REDAM de todos los proponentes"
            proponentes={proponentes}
            construirPayload={construirPayload}
            onAbrirVisor={abrirVisor}
            onResultadosChange={(r) => actualizarResultados(5, r)}
          />

          <RequisitoSection
            numero={10}
            requisito={14}
            titulo="Requisito 14: Boletín de Responsables Fiscales - Contraloría"
            descripcion={`Busca el certificado de la Contraloría (Boletín de Responsables Fiscales - SIBOR) del representante legal (y del suplente, si es Consorcio/UT), y verifica que confirme que no está reportado como responsable fiscal. Con ${proponentes.length} proponentes esto puede tardar varios minutos.`}
            textoBoton="Evaluar Contraloría de todos los proponentes"
            proponentes={proponentes}
            construirPayload={construirPayload}
            onAbrirVisor={abrirVisor}
            onResultadosChange={(r) => actualizarResultados(14, r)}
          />

          <RequisitoSection
            numero={11}
            requisito={15}
            titulo="Requisito 15: Antecedentes Disciplinarios - Procuraduría"
            descripcion={`Busca el certificado de la Procuraduría (Registro de Sanciones e Inhabilidades - SIRI) del representante legal (y del suplente, si es Consorcio/UT), y verifica que confirme que no registra sanciones ni inhabilidades vigentes. Con ${proponentes.length} proponentes esto puede tardar varios minutos.`}
            textoBoton="Evaluar Procuraduría de todos los proponentes"
            proponentes={proponentes}
            construirPayload={construirPayload}
            onAbrirVisor={abrirVisor}
            onResultadosChange={(r) => actualizarResultados(15, r)}
          />

          <RequisitoSection
            numero={12}
            requisito={16}
            titulo="Requisito 16: Antecedentes Judiciales - Policía Nacional"
            descripcion={`Busca el certificado de la Policía Nacional (antecedentes penales y requerimientos judiciales) del representante legal (y del suplente, si es Consorcio/UT), y verifica que confirme que no tiene asuntos pendientes con las autoridades judiciales. Con ${proponentes.length} proponentes esto puede tardar varios minutos.`}
            textoBoton="Evaluar Policía Nacional de todos los proponentes"
            proponentes={proponentes}
            construirPayload={construirPayload}
            onAbrirVisor={abrirVisor}
            onResultadosChange={(r) => actualizarResultados(16, r)}
          />

          <RequisitoSection
            numero={13}
            requisito={17}
            titulo="Requisito 17: Multas - RNMC (Código Nacional de Policía)"
            descripcion={`Busca el certificado del Registro Nacional de Medidas Correctivas (RNMC) del representante legal (y del suplente, si es Consorcio/UT), y verifica que confirme que no tiene medidas correctivas pendientes por cumplir. Con ${proponentes.length} proponentes esto puede tardar varios minutos.`}
            textoBoton="Evaluar RNMC de todos los proponentes"
            proponentes={proponentes}
            construirPayload={construirPayload}
            onAbrirVisor={abrirVisor}
            onResultadosChange={(r) => actualizarResultados(17, r)}
          />

          <RequisitoSection
            numero={14}
            requisito={13}
            titulo="Requisito 13: Registro Único Tributario - RUT"
            descripcion="El abogado confirmó que este requisito no se exige actualmente en este proceso — se marca N.A. para todos los proponentes automáticamente, sin necesidad de revisar documentos."
            textoBoton="Marcar RUT como N.A. para todos los proponentes"
            proponentes={proponentes}
            construirPayload={construirPayload}
            onAbrirVisor={abrirVisor}
            onResultadosChange={(r) => actualizarResultados(13, r)}
          />

          {errorGeneracion && <div className="alert danger">{errorGeneracion}</div>}

          <div className="actions">
            <button className="btn secondary" type="button" onClick={() => setStep('form')}>
              ← Volver
            </button>
            <button className="btn" type="button" onClick={handleGenerarExcel} disabled={generando}>
              {generando ? 'Generando…' : 'Generar y descargar Excel'}
            </button>
          </div>
        </>
      )}

      {visor && (
        <div className="modal-overlay" onClick={cerrarVisor}>
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span>{visor.nombre}</span>
              <button className="btn secondary" type="button" onClick={cerrarVisor}>
                Cerrar
              </button>
            </div>
            <iframe title={visor.nombre} src={visor.url} className="modal-iframe" />
          </div>
        </div>
      )}
    </>
  )
}

export default App
