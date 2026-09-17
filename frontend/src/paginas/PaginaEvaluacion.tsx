import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import type { ResultadoRequisito } from '../api'
import Icono from '../components/Icono'
import PanelProponente from '../components/PanelProponente'
import PasoDatos from '../components/PasoDatos'
import PasoEvaluacion from '../components/PasoEvaluacion'
import PasoInforme from '../components/PasoInforme'
import Topbar from '../components/Topbar'
import { PASOS_EVALUACION, type Paso } from '../pasos'
import VisorDocumento from '../components/VisorDocumento'
import { propsDatos, useDatosProceso } from '../datosProceso'
import * as ejecutor from '../ejecutor'
import { claveRevision, esPendiente, estadoDe, resumenProponente, type Revisiones } from '../estado'
import {
  aprobarEvaluacion,
  asignarEvaluacion,
  cargaEquipo,
  descargarInforme,
  guardarDocumentoBase,
  guardarRevision,
  obtenerEvaluacion,
  reabrirEvaluacion,
  verDocumentoProponente,
  type EvaluacionDetalle,
  type EvaluacionResumen,
  type MiembroCarga,
} from '../evaluaciones'
import { ErrorApi, mensajeDe } from '../http'
import { REQUISITOS } from '../requisitos'
import { navegar } from '../rutas'
import { useSesion } from '../sesion'

function agrupar(lista: ResultadoRequisito[]): Record<string, ResultadoRequisito[]> {
  const salida: Record<string, ResultadoRequisito[]> = {}
  for (const r of lista) (salida[r.hoja] ??= []).push(r)
  return salida
}

function descargar(blob: Blob, nombre: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = nombre
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export default function PaginaEvaluacion({ id }: { id: string }) {
  const [detalle, setDetalle] = useState<EvaluacionDetalle | null>(null)
  const [errorCarga, setErrorCarga] = useState<{ texto: string; noExiste: boolean } | null>(null)

  useEffect(() => {
    let vigente = true
    obtenerEvaluacion(id)
      .then((d) => vigente && setDetalle(d))
      .catch((e: unknown) => vigente && setErrorCarga({ texto: mensajeDe(e), noExiste: e instanceof ErrorApi && e.status === 404 }))
    return () => {
      vigente = false
    }
  }, [id])

  if (errorCarga) {
    return (
      <>
        <Topbar />
        <main className="page page-narrow">
          <div className="vacio">
            <h3>{errorCarga.noExiste ? 'Evaluación no encontrada' : 'No se pudo abrir la evaluación'}</h3>
            <p>{errorCarga.noExiste ? 'No existe o no pertenece a su entidad.' : errorCarga.texto}</p>
            <button className="btn btn-secondary" type="button" style={{ marginTop: 16 }} onClick={() => navegar('/')}>
              Ir a mis evaluaciones
            </button>
          </div>
        </main>
      </>
    )
  }
  if (!detalle) {
    return (
      <>
        <Topbar />
        <div className="vacio">
          <span className="spinner oscuro" />
        </div>
      </>
    )
  }
  return <Evaluacion key={id} inicial={detalle} />
}

function Evaluacion({ inicial }: { inicial: EvaluacionDetalle }) {
  const sesion = useSesion()!
  const id = inicial.evaluacion.id
  const [resumen, setResumen] = useState<EvaluacionResumen>(inicial.evaluacion)
  const [resultados, setResultados] = useState(() => agrupar(inicial.resultados))
  const [revisiones, setRevisiones] = useState<Revisiones>(() =>
    Object.fromEntries(inicial.revisiones.map((r) => [claveRevision(r.hoja, r.requisito), r.cumple])),
  )
  const proponentes = inicial.proponentes
  const codigo = inicial.documento_base.codigo_proceso
  const fechaCierre = inicial.documento_base.fecha_cierre
  const [paso, setPaso] = useState<Paso>(inicial.resultados.length ? 'evaluacion' : 'datos')
  const [panel, setPanel] = useState<{ hoja: string; requisito: number | null } | null>(null)
  const [visor, setVisor] = useState<{ url: string; archivo: string; resultado: ResultadoRequisito } | null>(null)
  const [abriendoDocumento, setAbriendoDocumento] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [generando, setGenerando] = useState(false)
  const [errorInforme, setErrorInforme] = useState<string | null>(null)
  const [guardandoDatos, setGuardandoDatos] = useState(false)
  const [ahora, setAhora] = useState(() => Date.now())

  const datos = useDatosProceso()
  const [datosCargados, setDatosCargados] = useState(false)
  if (!datosCargados) {
    datos.cargar(inicial.documento_base)
    setDatosCargados(true)
  }

  const soloLectura = !resumen.puede_trabajar || resumen.estado === 'aprobada'

  // --- Ejecución en segundo plano ---
  const ejecucion = useSyncExternalStore(
    useCallback(
      (avisar: () => void) =>
        ejecutor.suscribir(id, avisar, (pid, lista, error) => {
          const pr = proponentes.find((p) => p.id === pid)
          if (!pr) return
          const nuevos =
            lista ??
            REQUISITOS.map((q) => ({
              hoja: pr.hoja,
              numero_orden: pr.numero_orden,
              nombre_proponente: pr.nombre_proponente,
              requisito: q.numero,
              cumple: null,
              motivo: null,
              archivo_evaluado: null,
              lotes_encontrados: [],
              numero_proceso_encontrado: false,
              objeto_relacionado: null,
              tipo_proponente: null,
              firma_detectada: false,
              representante_legal: null,
              firma_nombre_certificado: null,
              firma_confirmada: null,
              matricula_profesional: null,
              profesion_certificada: null,
              copnia_vigente: null,
              copnia_sin_antecedentes: null,
              copnia_fecha_expedicion: null,
              error,
              archivos_disponibles: [],
            }))
          setResultados((prev) => ({ ...prev, [pr.hoja]: nuevos }))
        }),
      [id, proponentes],
    ),
    () => ejecutor.estadoEjecucion(id),
  )

  useEffect(() => {
    if (!ejecucion.evaluando) return
    const t = window.setInterval(() => setAhora(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [ejecucion.evaluando])

  // Al terminar una corrida, se refresca el estado guardado en el servidor.
  const corriendoAntes = useRef(ejecucion.evaluando)
  useEffect(() => {
    const termino = corriendoAntes.current && !ejecucion.evaluando
    corriendoAntes.current = ejecucion.evaluando
    if (!termino) return
    obtenerEvaluacion(id)
      .then((d) => {
        setResumen(d.evaluacion)
        setAviso('Evaluación terminada')
      })
      .catch(() => undefined)
  }, [ejecucion.evaluando, id])

  useEffect(() => {
    if (!aviso) return
    const t = window.setTimeout(() => setAviso(null), 2800)
    return () => window.clearTimeout(t)
  }, [aviso])

  function evaluarPendientes() {
    setPaso('evaluacion')
    const pendientes = proponentes.filter((pr) => !resultados[pr.hoja] || resultados[pr.hoja].some((r) => r.error)).map((p) => p.id)
    void ejecutor.iniciar(id, pendientes)
  }

  async function confirmarDatos() {
    if (soloLectura) {
      setPaso('evaluacion')
      return
    }
    setGuardandoDatos(true)
    try {
      await guardarDocumentoBase(id, datos.construir(codigo, fechaCierre))
      evaluarPendientes()
    } catch (err) {
      setAviso(mensajeDe(err, 'No se pudieron guardar los datos del proceso.'))
    } finally {
      setGuardandoDatos(false)
    }
  }

  async function revisar(hoja: string, requisito: number, cumple: boolean | undefined) {
    const pr = proponentes.find((p) => p.hoja === hoja)
    if (!pr) return
    const clave = claveRevision(hoja, requisito)
    const anterior = revisiones[clave]
    setRevisiones((prev) => {
      const nuevo = { ...prev }
      if (cumple === undefined) delete nuevo[clave]
      else nuevo[clave] = cumple
      return nuevo
    })
    try {
      await guardarRevision(id, pr.id, requisito, cumple ?? null)
      if (cumple !== undefined) setAviso(cumple ? 'Marcado como cumple' : 'Marcado como no cumple')
    } catch (err) {
      setRevisiones((prev) => {
        const nuevo = { ...prev }
        if (anterior === undefined) delete nuevo[clave]
        else nuevo[clave] = anterior
        return nuevo
      })
      setAviso(`No se guardó la decisión: ${mensajeDe(err)}`)
    }
  }

  const evaluadosEnOrden = proponentes.filter((pr) => resultados[pr.hoja])

  function siguientePendiente(desdeHoja: string | null): { hoja: string; requisito: number } | null {
    const inicio = desdeHoja ? evaluadosEnOrden.findIndex((pr) => pr.hoja === desdeHoja) : -1
    const orden = [...evaluadosEnOrden.slice(inicio + 1), ...evaluadosEnOrden.slice(0, inicio + 1)]
    for (const pr of orden) {
      const lista = resultados[pr.hoja]
      if (desdeHoja === pr.hoja && resumenProponente(lista, revisiones).pendientes === 0) continue
      for (const info of REQUISITOS) {
        const r = lista.find((x) => x.requisito === info.numero)
        if (r && esPendiente(estadoDe(r, revisiones))) return { hoja: pr.hoja, requisito: info.numero }
      }
    }
    return null
  }

  function irSiguientePendiente(desdeHoja: string | null) {
    const s = siguientePendiente(desdeHoja)
    if (s) {
      setPaso('evaluacion')
      setPanel(s)
    } else {
      setPanel(null)
      setAviso('No quedan pendientes por revisar')
    }
  }

  async function abrirDocumento(resultado: ResultadoRequisito, archivo: string) {
    const pr = proponentes.find((p) => p.hoja === resultado.hoja)
    if (!pr) return
    setAbriendoDocumento(`${resultado.hoja}|${archivo}`)
    try {
      const blob = await verDocumentoProponente(id, pr.id, archivo)
      setVisor({ url: URL.createObjectURL(blob), archivo, resultado })
    } catch (err) {
      setAviso(`No se pudo abrir: ${mensajeDe(err)}`)
    } finally {
      setAbriendoDocumento(null)
    }
  }

  async function generarInforme() {
    setGenerando(true)
    setErrorInforme(null)
    try {
      const { blob, nombre } = await descargarInforme(id)
      descargar(blob, nombre ?? `INFORME ${codigo}.xlsx`)
      setAviso('Informe descargado')
    } catch (err) {
      setErrorInforme(mensajeDe(err, 'No se pudo generar el informe.'))
    } finally {
      setGenerando(false)
    }
  }

  const disponibles = new Set<Paso>(['datos'])
  if (evaluadosEnOrden.length || ejecucion.evaluando) {
    disponibles.add('evaluacion')
    disponibles.add('informe')
  }
  const panelProponente = panel ? proponentes.find((pr) => pr.hoja === panel.hoja) : null
  const indicePanel = panel ? evaluadosEnOrden.findIndex((pr) => pr.hoja === panel.hoja) : -1
  const onRevisar = soloLectura ? null : revisar

  return (
    <>
      <Topbar codigoProceso={codigo} pasos={{ lista: PASOS_EVALUACION, paso, pasosDisponibles: disponibles, onIr: setPaso }} />
      <BarraEvaluacion
        resumen={resumen}
        esYo={resumen.responsable?.id === sesion.usuario.id}
        onCambio={(r) => setResumen(r)}
        onAviso={setAviso}
      />

      {paso === 'datos' && (
        <PasoDatos
          codigoProceso={codigo}
          fechaCierre={fechaCierre}
          {...propsDatos(datos, fechaCierre)}
          proponentes={proponentes}
          noReconocidos={inicial.proponentes_no_reconocidos}
          driveError={null}
          hayResultados={evaluadosEnOrden.length > 0}
          soloLectura={soloLectura}
          ocupado={guardandoDatos}
          textoAccion={
            soloLectura
              ? 'Ver evaluación'
              : evaluadosEnOrden.length === proponentes.length
                ? 'Guardar y ver evaluación'
                : `Guardar y evaluar ${proponentes.length - evaluadosEnOrden.length} proponentes`
          }
          onVolver={null}
          onEvaluar={confirmarDatos}
        />
      )}

      {paso === 'evaluacion' && (
        <PasoEvaluacion
          proponentes={proponentes}
          resultados={resultados}
          revisiones={revisiones}
          progreso={{
            evaluando: ejecucion.evaluando,
            inicio: ejecucion.inicio,
            completadosEnEstaCorrida: ejecucion.completados,
            totalEnEstaCorrida: ejecucion.total,
          }}
          ahora={ahora}
          hojaActiva={panel?.hoja ?? null}
          puedeEvaluar={!soloLectura}
          onDetener={() => {
            ejecutor.detener(id)
            setAviso('Evaluación en pausa. Lo evaluado quedó guardado.')
          }}
          onContinuar={evaluarPendientes}
          onAbrir={(hoja, requisito) => resultados[hoja] && setPanel({ hoja, requisito: requisito ?? null })}
          onSiguientePendiente={() => irSiguientePendiente(null)}
          onIrInforme={() => setPaso('informe')}
        />
      )}

      {paso === 'informe' && (
        <PasoInforme
          codigoProceso={codigo}
          nombreArchivo={`INFORME EVALUACION ${resumen.tipo.toUpperCase()} ${codigo}${resumen.estado === 'aprobada' ? '' : ' (BORRADOR)'}.xlsx`}
          proponentes={proponentes}
          resultados={resultados}
          revisiones={revisiones}
          generando={generando}
          error={errorInforme}
          onGenerar={generarInforme}
          onVolver={() => setPaso('evaluacion')}
          onRevisarPendientes={() => irSiguientePendiente(null)}
          onNuevaEvaluacion={() => navegar('/procesos/nuevo')}
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
          onRevisar={onRevisar}
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
          onRevisar={onRevisar}
          onCerrar={() => {
            URL.revokeObjectURL(visor.url)
            setVisor(null)
          }}
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

/** Estado, responsable y acciones del jefe (asignar, aprobar, reabrir). */
function BarraEvaluacion({
  resumen,
  esYo,
  onCambio,
  onAviso,
}: {
  resumen: EvaluacionResumen
  esYo: boolean
  onCambio: (r: EvaluacionResumen) => void
  onAviso: (t: string) => void
}) {
  const [equipo, setEquipo] = useState<MiembroCarga[] | null>(null)
  const [ocupado, setOcupado] = useState(false)

  useEffect(() => {
    if (!resumen.puede_gestionar) return
    cargaEquipo()
      .then(setEquipo)
      .catch(() => setEquipo([]))
  }, [resumen.puede_gestionar])

  const candidatos = useMemo(() => (equipo ?? []).filter((m) => m.areas.includes(resumen.tipo)), [equipo, resumen.tipo])

  async function accion(f: () => Promise<EvaluacionResumen>, exito: string) {
    setOcupado(true)
    try {
      onCambio(await f())
      onAviso(exito)
    } catch (err) {
      onAviso(mensajeDe(err))
    } finally {
      setOcupado(false)
    }
  }

  const { avance } = resumen
  return (
    <div className="barra-evaluacion">
      <div className="barra-evaluacion-inner">
        <span className="tag">{resumen.tipo_nombre}</span>
        <span className="pill" data-estado-ev={resumen.estado}>
          <span className="dot" /> {resumen.estado_nombre}
        </span>
        <span className="small muted">
          {avance.evaluados}/{avance.proponentes} evaluados · {avance.pendientes} por revisar
        </span>
        <div className="barra-evaluacion-der">
          {!resumen.puede_trabajar && (
            <span className="small muted" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <Icono nombre="ojo" tam={15} /> Solo lectura
            </span>
          )}
          <span className="small">Responsable:</span>
          {resumen.puede_gestionar && equipo && resumen.estado !== 'aprobada' ? (
            <select
              className="select select-sm"
              value={resumen.responsable?.id ?? ''}
              disabled={ocupado}
              onChange={(e) =>
                accion(
                  () => asignarEvaluacion(resumen.id, e.target.value || null),
                  e.target.value ? 'Evaluación asignada' : 'Evaluación sin responsable',
                )
              }
            >
              <option value="">Sin asignar</option>
              {candidatos.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.nombre_completo} · {m.evaluaciones_activas} activas
                </option>
              ))}
            </select>
          ) : (
            <strong className="small">{resumen.responsable ? (esYo ? 'Usted' : resumen.responsable.nombre_completo) : 'Sin asignar'}</strong>
          )}
          {resumen.puede_gestionar &&
            (resumen.estado === 'aprobada' ? (
              <button className="btn btn-secondary btn-sm" type="button" disabled={ocupado} onClick={() => accion(() => reabrirEvaluacion(resumen.id), 'Evaluación reabierta')}>
                <Icono nombre="deshacer" tam={15} /> Reabrir
              </button>
            ) : (
              <button
                className="btn btn-ok btn-sm"
                type="button"
                disabled={ocupado || avance.pendientes > 0 || avance.evaluados < avance.proponentes}
                title={avance.pendientes > 0 ? 'Quedan requisitos por revisar' : undefined}
                onClick={() => {
                  if (window.confirm('¿Aprobar la evaluación? El informe quedará como definitivo y no se podrá modificar sin reabrirla.')) {
                    accion(() => aprobarEvaluacion(resumen.id), 'Evaluación aprobada')
                  }
                }}
              >
                <Icono nombre="check" tam={15} /> Aprobar
              </button>
            ))}
        </div>
      </div>
    </div>
  )
}
