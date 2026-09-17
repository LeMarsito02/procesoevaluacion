import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  analizarDocumentoBase,
  evaluarTodosLosRequisitos,
  generarExcel,
  verDocumento,
  type AnalisisResponse,
  type Lote,
  type ProcesoDocumentoBase,
  type Proponente,
  type ResultadoRequisito,
} from './api'
import PanelProponente from './components/PanelProponente'
import PasoDatos, { type BaseCalculo } from './components/PasoDatos'
import PasoEvaluacion, { type ProgresoEvaluacion } from './components/PasoEvaluacion'
import PasoInforme from './components/PasoInforme'
import PasoNuevo from './components/PasoNuevo'
import Topbar, { type Paso } from './components/Topbar'
import VisorDocumento from './components/VisorDocumento'
import {
  aplicarRevision,
  borrarSesion,
  claveRevision,
  esPendiente,
  estadoDe,
  guardarSesion,
  leerSesion,
  resumenProponente,
  type Revisiones,
  type SesionGuardada,
} from './estado'
import { addMonthsClamped } from './format'
import { REQUISITOS } from './requisitos'

const PROGRESO_INICIAL: ProgresoEvaluacion = { evaluando: false, inicio: null, completadosEnEstaCorrida: 0, totalEnEstaCorrida: 0 }

export default function App() {
  const [paso, setPaso] = useState<Paso>('nuevo')
  const [sesionGuardada, setSesionGuardada] = useState<SesionGuardada | null>(() => leerSesion())

  // --- Paso 1 ---
  const [codigoProceso, setCodigoProceso] = useState('')
  const [fechaCierre, setFechaCierre] = useState('')
  const [carpetaDrive, setCarpetaDrive] = useState('')
  const [archivo, setArchivo] = useState<File | null>(null)
  const [analizando, setAnalizando] = useState(false)
  const [errorAnalisis, setErrorAnalisis] = useState<string | null>(null)

  // --- Paso 2 ---
  const [objetoGeneral, setObjetoGeneral] = useState('')
  const [lotes, setLotes] = useState<Lote[]>([])
  const [vigenciaMeses, setVigenciaMeses] = useState(3)
  const [porcentajePct, setPorcentajePct] = useState(10)
  const [baseCalculo, setBaseCalculo] = useState<BaseCalculo>('lote_mayor_valor')
  const [advertencias, setAdvertencias] = useState<string[]>([])
  const [proponentes, setProponentes] = useState<Proponente[]>([])
  const [noReconocidos, setNoReconocidos] = useState<string[]>([])
  const [driveError, setDriveError] = useState<string | null>(null)

  // --- Paso 3 ---
  const [resultados, setResultados] = useState<Record<string, ResultadoRequisito[]>>({})
  const [revisiones, setRevisiones] = useState<Revisiones>({})
  const [progreso, setProgreso] = useState<ProgresoEvaluacion>(PROGRESO_INICIAL)
  const [ahora, setAhora] = useState(() => Date.now())
  const cancelador = useRef<AbortController | null>(null)
  const [panel, setPanel] = useState<{ hoja: string; requisito: number | null } | null>(null)
  const [visor, setVisor] = useState<{ url: string; archivo: string; resultado: ResultadoRequisito } | null>(null)
  const [abriendoDocumento, setAbriendoDocumento] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  // --- Paso 4 ---
  const [generando, setGenerando] = useState(false)
  const [errorGeneracion, setErrorGeneracion] = useState<string | null>(null)

  const derivados = useMemo(() => {
    const presupuestoTotal = lotes.reduce((s, l) => s + (Number(l.valor_presupuesto) || 0), 0)
    const loteMayor = lotes.reduce<Lote | null>(
      (max, l) => (!max || (Number(l.valor_presupuesto) || 0) > (Number(max.valor_presupuesto) || 0) ? l : max),
      null,
    )
    const valorBase =
      baseCalculo === 'lote_mayor_valor' && loteMayor ? Number(loteMayor.valor_presupuesto) || 0 : presupuestoTotal
    return {
      presupuestoTotal,
      loteMayorNumero: loteMayor?.numero ?? '',
      valorBase,
      valorAsegurado: Math.round(valorBase * (porcentajePct / 100) * 100) / 100,
      fechaVencimiento: fechaCierre ? addMonthsClamped(fechaCierre, vigenciaMeses) : '',
    }
  }, [lotes, baseCalculo, porcentajePct, fechaCierre, vigenciaMeses])

  const construirPayload = useCallback(
    (): ProcesoDocumentoBase => ({
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
    }),
    [codigoProceso, fechaCierre, objetoGeneral, lotes, derivados, vigenciaMeses, porcentajePct, baseCalculo, advertencias],
  )

  // Reloj para el tiempo transcurrido/restante mientras se evalúa.
  useEffect(() => {
    if (!progreso.evaluando) return
    const id = window.setInterval(() => setAhora(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [progreso.evaluando])

  // Guardado automático en el navegador.
  useEffect(() => {
    if (!proponentes.length || !codigoProceso) return
    const id = window.setTimeout(() => {
      guardarSesion({
        version: 1,
        guardadoEn: Date.now(),
        codigoProceso,
        fechaCierre,
        carpetaDrive,
        proceso: construirPayload(),
        proponentes,
        noReconocidos,
        driveError,
        resultados,
        revisiones,
      })
    }, 600)
    return () => window.clearTimeout(id)
  }, [resultados, revisiones, proponentes, codigoProceso, fechaCierre, carpetaDrive, noReconocidos, driveError, construirPayload])

  useEffect(() => {
    if (!aviso) return
    const id = window.setTimeout(() => setAviso(null), 2600)
    return () => window.clearTimeout(id)
  }, [aviso])

  // Avisar antes de cerrar la pestaña con una evaluación en curso.
  useEffect(() => {
    if (!progreso.evaluando) return
    const alSalir = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', alSalir)
    return () => window.removeEventListener('beforeunload', alSalir)
  }, [progreso.evaluando])

  function cargarProceso(proceso: ProcesoDocumentoBase) {
    setObjetoGeneral(proceso.objeto_general)
    setLotes(proceso.lotes)
    setVigenciaMeses(proceso.garantia_seriedad.vigencia_meses)
    setPorcentajePct(Math.round(proceso.garantia_seriedad.porcentaje * 1000) / 10)
    setBaseCalculo(proceso.garantia_seriedad.base_calculo)
    setAdvertencias(proceso.advertencias)
  }

  async function analizar() {
    if (!archivo) return
    setAnalizando(true)
    setErrorAnalisis(null)
    try {
      const r: AnalisisResponse = await analizarDocumentoBase(codigoProceso.trim(), fechaCierre, archivo, carpetaDrive)
      cargarProceso(r.documento_base)
      setProponentes(r.proponentes)
      setNoReconocidos(r.proponentes_no_reconocidos)
      setDriveError(r.drive_error)
      setResultados({})
      setRevisiones({})
      setPaso('datos')
    } catch (err) {
      setErrorAnalisis(err instanceof Error ? err.message : 'No se pudo analizar el documento.')
    } finally {
      setAnalizando(false)
    }
  }

  function retomarSesion() {
    const s = sesionGuardada
    if (!s) return
    setCodigoProceso(s.codigoProceso)
    setFechaCierre(s.fechaCierre)
    setCarpetaDrive(s.carpetaDrive)
    cargarProceso(s.proceso)
    setProponentes(s.proponentes)
    setNoReconocidos(s.noReconocidos)
    setDriveError(s.driveError)
    setResultados(s.resultados)
    setRevisiones(s.revisiones)
    setSesionGuardada(null)
    setPaso(Object.keys(s.resultados).length ? 'evaluacion' : 'datos')
  }

  function nuevaEvaluacion() {
    cancelador.current?.abort()
    borrarSesion()
    setSesionGuardada(null)
    setCodigoProceso('')
    setFechaCierre('')
    setCarpetaDrive('')
    setArchivo(null)
    setProponentes([])
    setResultados({})
    setRevisiones({})
    setPanel(null)
    setProgreso(PROGRESO_INICIAL)
    setPaso('nuevo')
  }

  async function evaluar() {
    setPaso('evaluacion')
    const pendientes = proponentes.filter((pr) => !resultados[pr.hoja] || resultados[pr.hoja].some((r) => r.error))
    if (!pendientes.length || progreso.evaluando) return
    const controlador = new AbortController()
    cancelador.current = controlador
    const inicio = Date.now()
    setAhora(inicio)
    setProgreso({ evaluando: true, inicio, completadosEnEstaCorrida: 0, totalEnEstaCorrida: pendientes.length })
    await evaluarTodosLosRequisitos(
      construirPayload(),
      pendientes,
      (hoja, lista) => {
        setResultados((prev) => ({ ...prev, [hoja]: lista }))
        setProgreso((prev) => ({ ...prev, completadosEnEstaCorrida: prev.completadosEnEstaCorrida + 1 }))
      },
      controlador.signal,
    )
    setProgreso((prev) => ({ ...prev, evaluando: false }))
    if (!controlador.signal.aborted) setAviso('Evaluación terminada')
  }

  function detener() {
    cancelador.current?.abort()
    setProgreso((prev) => ({ ...prev, evaluando: false }))
    setAviso('Evaluación en pausa. Lo evaluado quedó guardado.')
  }

  function revisar(hoja: string, requisito: number, cumple: boolean | undefined) {
    setRevisiones((prev) => {
      const nuevo = { ...prev }
      const clave = claveRevision(hoja, requisito)
      if (cumple === undefined) delete nuevo[clave]
      else nuevo[clave] = cumple
      return nuevo
    })
    if (cumple !== undefined) setAviso(cumple ? 'Marcado como cumple' : 'Marcado como no cumple')
  }

  const evaluadosEnOrden = proponentes.filter((pr) => resultados[pr.hoja])

  function primerPendiente(lista: ResultadoRequisito[], revs: Revisiones): number | null {
    for (const info of REQUISITOS) {
      const r = lista.find((x) => x.requisito === info.numero)
      if (r && esPendiente(estadoDe(r, revs))) return info.numero
    }
    return null
  }

  function siguientePendiente(desdeHoja: string | null): { hoja: string; requisito: number } | null {
    const inicio = desdeHoja ? evaluadosEnOrden.findIndex((pr) => pr.hoja === desdeHoja) : -1
    const orden = [...evaluadosEnOrden.slice(inicio + 1), ...evaluadosEnOrden.slice(0, inicio + 1)]
    for (const pr of orden) {
      const lista = resultados[pr.hoja]
      if (desdeHoja === pr.hoja && resumenProponente(lista, revisiones).pendientes === 0) continue
      const req = primerPendiente(lista, revisiones)
      if (req !== null) return { hoja: pr.hoja, requisito: req }
    }
    return null
  }

  function irSiguientePendiente(desdeHoja: string | null) {
    const siguiente = siguientePendiente(desdeHoja)
    if (siguiente) {
      setPaso('evaluacion')
      setPanel(siguiente)
    } else {
      setPanel(null)
      setAviso('No quedan pendientes por revisar')
    }
  }

  async function abrirDocumento(resultado: ResultadoRequisito, rutaArchivo: string) {
    const proponente = proponentes.find((pr) => pr.hoja === resultado.hoja)
    if (!proponente) return
    setAbriendoDocumento(`${resultado.hoja}|${rutaArchivo}`)
    try {
      const blob = await verDocumento(proponente.drive_file_id, rutaArchivo)
      setVisor({ url: URL.createObjectURL(blob), archivo: rutaArchivo, resultado })
    } catch (err) {
      setAviso(err instanceof Error ? `No se pudo abrir: ${err.message}` : 'No se pudo abrir el documento')
    } finally {
      setAbriendoDocumento(null)
    }
  }

  function cerrarVisor() {
    if (visor) URL.revokeObjectURL(visor.url)
    setVisor(null)
  }

  async function descargarExcel() {
    setGenerando(true)
    setErrorGeneracion(null)
    try {
      const payload = construirPayload()
      const todos = Object.values(resultados)
        .flat()
        .map((r) => aplicarRevision(r, revisiones))
      const blob = await generarExcel(payload, proponentes, todos)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `INFORME EVALUACION JURIDICA ${payload.codigo_proceso}.xlsx`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      setAviso('Informe descargado')
    } catch (err) {
      setErrorGeneracion(err instanceof Error ? err.message : 'No se pudo generar el Excel.')
    } finally {
      setGenerando(false)
    }
  }

  const pasosDisponibles = new Set<Paso>(['nuevo'])
  if (proponentes.length || lotes.length) pasosDisponibles.add('datos')
  if (evaluadosEnOrden.length || progreso.evaluando) {
    pasosDisponibles.add('evaluacion')
    pasosDisponibles.add('informe')
  }

  const panelProponente = panel ? proponentes.find((pr) => pr.hoja === panel.hoja) : null
  const indicePanel = panel ? evaluadosEnOrden.findIndex((pr) => pr.hoja === panel.hoja) : -1

  return (
    <>
      <Topbar
        codigoProceso={paso === 'nuevo' ? null : codigoProceso}
        pasos={paso === 'nuevo' ? undefined : { paso, pasosDisponibles, onIr: setPaso }}
      />

      {paso === 'nuevo' && (
        <PasoNuevo
          codigoProceso={codigoProceso}
          fechaCierre={fechaCierre}
          carpetaDrive={carpetaDrive}
          archivo={archivo}
          analizando={analizando}
          error={errorAnalisis}
          sesionGuardada={sesionGuardada}
          onCambiar={(c) => {
            if (c.codigoProceso !== undefined) setCodigoProceso(c.codigoProceso)
            if (c.fechaCierre !== undefined) setFechaCierre(c.fechaCierre)
            if (c.carpetaDrive !== undefined) setCarpetaDrive(c.carpetaDrive)
            if (c.archivo !== undefined) setArchivo(c.archivo)
          }}
          onAnalizar={analizar}
          onRetomar={retomarSesion}
          onDescartarSesion={() => {
            borrarSesion()
            setSesionGuardada(null)
          }}
        />
      )}

      {paso === 'datos' && (
        <PasoDatos
          codigoProceso={codigoProceso}
          fechaCierre={fechaCierre}
          objetoGeneral={objetoGeneral}
          lotes={lotes}
          vigenciaMeses={vigenciaMeses}
          porcentajePct={porcentajePct}
          baseCalculo={baseCalculo}
          advertencias={advertencias}
          derivados={derivados}
          proponentes={proponentes}
          noReconocidos={noReconocidos}
          driveError={driveError}
          hayResultados={evaluadosEnOrden.length > 0}
          onCambiarObjeto={setObjetoGeneral}
          onCambiarLote={(i, cambios) => setLotes((prev) => prev.map((l, j) => (j === i ? { ...l, ...cambios } : l)))}
          onCambiarGarantia={(c) => {
            if (c.vigenciaMeses !== undefined) setVigenciaMeses(c.vigenciaMeses)
            if (c.porcentajePct !== undefined) setPorcentajePct(c.porcentajePct)
            if (c.baseCalculo !== undefined) setBaseCalculo(c.baseCalculo)
          }}
          onVolver={() => setPaso('nuevo')}
          onEvaluar={evaluar}
        />
      )}

      {paso === 'evaluacion' && (
        <PasoEvaluacion
          proponentes={proponentes}
          resultados={resultados}
          revisiones={revisiones}
          progreso={progreso}
          ahora={ahora}
          hojaActiva={panel?.hoja ?? null}
          onDetener={detener}
          onContinuar={evaluar}
          onAbrir={(hoja, requisito) => resultados[hoja] && setPanel({ hoja, requisito: requisito ?? null })}
          onSiguientePendiente={() => irSiguientePendiente(null)}
          onIrInforme={() => setPaso('informe')}
        />
      )}

      {paso === 'informe' && (
        <PasoInforme
          codigoProceso={codigoProceso}
          proponentes={proponentes}
          resultados={resultados}
          revisiones={revisiones}
          generando={generando}
          error={errorGeneracion}
          onGenerar={descargarExcel}
          onVolver={() => setPaso('evaluacion')}
          onRevisarPendientes={() => irSiguientePendiente(null)}
          onNuevaEvaluacion={nuevaEvaluacion}
        />
      )}

      {panel && panelProponente && resultados[panel.hoja] && (
        <PanelProponente
          key={`${panel.hoja}-${panel.requisito ?? ''}`}
          proponente={panelProponente}
          resultados={resultados[panel.hoja]}
          revisiones={revisiones}
          requisitoDestacado={panel.requisito}
          abriendoDocumento={abriendoDocumento}
          onCerrar={() => setPanel(null)}
          onRevisar={revisar}
          onVerDocumento={abrirDocumento}
          onAnterior={indicePanel > 0 ? () => setPanel({ hoja: evaluadosEnOrden[indicePanel - 1].hoja, requisito: null }) : null}
          onSiguiente={
            indicePanel >= 0 && indicePanel < evaluadosEnOrden.length - 1
              ? () => setPanel({ hoja: evaluadosEnOrden[indicePanel + 1].hoja, requisito: null })
              : null
          }
          onSiguientePendiente={siguientePendiente(panel.hoja) ? () => irSiguientePendiente(panel.hoja) : null}
        />
      )}

      {visor && (
        <VisorDocumento
          url={visor.url}
          archivo={visor.archivo}
          resultado={visor.resultado}
          revisiones={revisiones}
          onRevisar={revisar}
          onCerrar={cerrarVisor}
        />
      )}

      {aviso && (
        <div className="toast" role="status">
          {aviso}
        </div>
      )}
    </>
  )
}
