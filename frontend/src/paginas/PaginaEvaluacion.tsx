import { useEffect, useMemo, useRef, useState } from 'react'
import type { ResultadoRequisito } from '../api'
import Icono from '../components/Icono'
import AntecedentesProponente from '../components/AntecedentesProponente'
import DocumentosFinales from '../components/DocumentosFinales'
import PliegoProceso from '../components/PliegoProceso'
import PanelProponente from '../components/PanelProponente'
import PasoDatos from '../components/PasoDatos'
import PasoEvaluacion from '../components/PasoEvaluacion'
import PasoInforme from '../components/PasoInforme'
import Topbar from '../components/Topbar'
import { PASOS_EVALUACION, type Paso } from '../pasos'
import VisorDocumento from '../components/VisorDocumento'
import { propsDatos, useDatosProceso } from '../datosProceso'
import { claveRevision, esPendiente, estadoDe, resumenProponente, type Revisiones } from '../estado'
import {
  actualizarPlantillaEvaluacion,
  aprobarEvaluacion,
  encolarEvaluacion,
  novedadesEvaluacion,
  pausarEvaluacion,
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
import { consultarEnLinea } from '../historico'
import { ErrorApi, mensajeDe } from '../http'
import { establecerCatalogo, REQUISITOS } from '../requisitos'
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
  const [panel, setPanel] = useState<{ hoja: string; requisito: number | null; persona?: string } | null>(null)
  // Requisito cuyo certificado consultado se va a subir desde su tarjeta.
  const [subirCertificado, setSubirCertificado] = useState<number | null>(null)
  // Requisito cuyo COPNIA se está consultando en línea.
  const [consultandoCopnia, setConsultandoCopnia] = useState<number | null>(null)
  const [visor, setVisor] = useState<{ url: string; archivo: string; resultado: ResultadoRequisito } | null>(null)
  const [abriendoDocumento, setAbriendoDocumento] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [generando, setGenerando] = useState(false)
  const [errorInforme, setErrorInforme] = useState<string | null>(null)
  const [guardandoDatos, setGuardandoDatos] = useState(false)
  const [ocupadoFila, setOcupadoFila] = useState(false)

  const datos = useDatosProceso()
  const [datosCargados, setDatosCargados] = useState(false)
  if (!datosCargados) {
    establecerCatalogo(inicial.catalogo)
    datos.cargar(inicial.documento_base)
    setDatosCargados(true)
  }

  const soloLectura = !resumen.puede_trabajar || resumen.estado === 'aprobada'

  // --- Fila del servidor: mientras haya trabajos pendientes se consultan las novedades ---
  const enFila = resumen.fila !== null
  const desde = useRef<string | null>(null)
  useEffect(() => {
    if (!enFila) return
    let vigente = true
    const consultar = async () => {
      try {
        const n = await novedadesEvaluacion(id, desde.current)
        if (!vigente) return
        desde.current = n.hasta
        if (n.resultados.length) {
          setResultados((prev) => {
            const nuevo = { ...prev }
            for (const [hoja, lista] of Object.entries(agrupar(n.resultados))) {
              const porRequisito = new Map((nuevo[hoja] ?? []).map((r) => [r.requisito, r]))
              for (const r of lista) porRequisito.set(r.requisito, r)
              nuevo[hoja] = [...porRequisito.values()]
            }
            return nuevo
          })
        }
        setResumen(n.evaluacion)
        if (!n.evaluacion.fila) setAviso('Evaluación terminada')
      } catch {
        // Un fallo puntual de red no detiene el seguimiento.
      }
    }
    const t = window.setInterval(consultar, 4000)
    return () => {
      vigente = false
      window.clearInterval(t)
    }
  }, [enFila, id])

  // Al adjuntar un certificado el servidor vuelve a evaluar al proponente: se
  // pide el estado para que el seguimiento de la fila se active y el
  // requisito se actualice solo en la pantalla.
  async function seguirReevaluacion() {
    try {
      const n = await novedadesEvaluacion(id, desde.current)
      desde.current = n.hasta
      setResumen(n.evaluacion)
    } catch {
      // Si falla, el usuario igual puede recargar la página.
    }
  }

  useEffect(() => {
    if (!aviso) return
    const t = window.setTimeout(() => setAviso(null), 2800)
    return () => window.clearTimeout(t)
  }, [aviso])

  async function evaluarPendientes() {
    setPaso('evaluacion')
    setOcupadoFila(true)
    try {
      // La primera consulta trae todo y fija la marca de tiempo del servidor (evita desfases de reloj).
      desde.current = null
      setResumen(await encolarEvaluacion(id))
    } catch (err) {
      setAviso(mensajeDe(err, 'No se pudo poner la evaluación en la fila.'))
    } finally {
      setOcupadoFila(false)
    }
  }

  async function pausar() {
    setOcupadoFila(true)
    try {
      setResumen(await pausarEvaluacion(id))
      setAviso('Evaluación en pausa. Lo evaluado quedó guardado.')
    } catch (err) {
      setAviso(mensajeDe(err))
    } finally {
      setOcupadoFila(false)
    }
  }

  async function confirmarDatos() {
    if (soloLectura) {
      setPaso('evaluacion')
      return
    }
    setGuardandoDatos(true)
    try {
      await guardarDocumentoBase(id, datos.construir(codigo, fechaCierre))
      await evaluarPendientes()
    } catch (err) {
      setAviso(mensajeDe(err, 'No se pudieron guardar los datos del proceso.'))
    } finally {
      setGuardandoDatos(false)
    }
  }

  const [justificando, setJustificando] = useState<{ hoja: string; requisito: number; cumple: boolean } | null>(null)

  // Cada decisión manual lleva su justificación: queda en el reporte formal.
  function pedirJustificacion(hoja: string, requisito: number, cumple: boolean | undefined) {
    if (cumple === undefined) void revisar(hoja, requisito, undefined, '')
    else setJustificando({ hoja, requisito, cumple })
  }

  async function revisar(hoja: string, requisito: number, cumple: boolean | undefined, nota: string) {
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
      await guardarRevision(id, pr.id, requisito, cumple ?? null, nota)
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
  if (evaluadosEnOrden.length || enFila) {
    disponibles.add('evaluacion')
    disponibles.add('informe')
  }
  const panelProponente = panel ? proponentes.find((pr) => pr.hoja === panel.hoja) : null
  const indicePanel = panel ? evaluadosEnOrden.findIndex((pr) => pr.hoja === panel.hoja) : -1
  const onRevisar = soloLectura ? null : pedirJustificacion

  if (!resumen.tipo_disponible) {
    return (
      <>
        <Topbar codigoProceso={codigo} />
        <BarraEvaluacion resumen={resumen} esYo={resumen.responsable?.id === sesion.usuario.id} onCambio={setResumen} onAviso={setAviso} />
        <main className="page page-narrow">
          <section className="card en-preparacion">
            <Icono nombre="reloj" tam={36} />
            <h2>Evaluación {resumen.tipo_nombre.toLowerCase()} en preparación</h2>
            <p className="muted">
              La evaluación ya está creada{resumen.responsable ? ` y asignada a ${resumen.responsable.nombre_completo}` : ''}. La
              evaluación automática de requisitos {resumen.tipo_nombre.toLowerCase()}s se habilitará en cuanto el módulo esté
              listo; desde ese momento podrá evaluarse aquí mismo sin volver a crear el proceso.
            </p>
            <p className="small muted" style={{ marginTop: 12 }}>
              {proponentes.length} proponentes · cierre {fechaCierre}
            </p>
          </section>
        </main>
        {aviso && (
          <div className="toast" role="status">
            {aviso}
          </div>
        )}
      </>
    )
  }

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
          antesDeAcciones={<PliegoProceso evaluacionId={id} pliego={inicial.pliego} />}
        />
      )}

      {paso === 'evaluacion' && (
        <PasoEvaluacion
          proponentes={proponentes}
          resultados={resultados}
          revisiones={revisiones}
          progreso={
            resumen.fila && {
              enFila: resumen.fila.en_fila,
              procesando: resumen.fila.procesando,
              porDelante: resumen.fila.por_delante,
              capacidad: resumen.fila.capacidad,
              etaSegundos: resumen.fila.eta_segundos,
            }
          }
          ocupado={ocupadoFila}
          hojaActiva={panel?.hoja ?? null}
          puedeEvaluar={!soloLectura}
          onDetener={pausar}
          onContinuar={evaluarPendientes}
          onAbrir={(hoja, requisito, persona) => resultados[hoja] && setPanel({ hoja, requisito: requisito ?? null, persona })}
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
          extra={<DocumentosFinales resumen={resumen} />}
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
          onSubirCertificado={soloLectura ? null : (requisito) => setSubirCertificado(requisito)}
          consultandoCopnia={consultandoCopnia}
          onConsultarCopnia={
            soloLectura || !panelProponente
              ? null
              : async (requisito, matricula) => {
                  setConsultandoCopnia(requisito)
                  try {
                    await consultarEnLinea(id, panelProponente.id, { requisito, matricula })
                    setAviso('El certificado del COPNIA quedó adjunto. Se está volviendo a evaluar el requisito…')
                    await seguirReevaluacion()
                  } catch (e) {
                    setAviso(mensajeDe(e))
                  } finally {
                    setConsultandoCopnia(null)
                  }
                }
          }
          onAnterior={indicePanel > 0 ? () => setPanel({ hoja: evaluadosEnOrden[indicePanel - 1].hoja, requisito: null }) : null}
          onSiguiente={
            indicePanel >= 0 && indicePanel < evaluadosEnOrden.length - 1
              ? () => setPanel({ hoja: evaluadosEnOrden[indicePanel + 1].hoja, requisito: null })
              : null
          }
          onSiguientePendiente={siguientePendiente(panel.hoja) ? () => irSiguientePendiente(panel.hoja) : null}
          extra={
            <AntecedentesProponente
              key={panelProponente.id}
              evaluacionId={id}
              proponenteId={panelProponente.id}
              soloLectura={soloLectura}
              onVerPdf={(blob) => window.open(URL.createObjectURL(blob), '_blank', 'noopener')}
              onVerDocumento={(archivo, requisito) => {
                const resultado = (resultados[panelProponente.hoja] ?? []).find((r) => r.requisito === requisito)
                if (resultado) void abrirDocumento(resultado, archivo)
              }}
              subirRequisito={subirCertificado}
              onSubidaAtendida={() => setSubirCertificado(null)}
              onCertificadoAdjunto={() => void seguirReevaluacion()}
              marca={resultados[panelProponente.hoja]}
              foco={panel.persona && panel.requisito ? { persona: panel.persona, requisito: panel.requisito } : null}
            />
          }
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

      {justificando && (
        <DialogoJustificacion
          titulo={`${REQUISITOS.find((r) => r.numero === justificando.requisito)?.titulo ?? `Requisito ${justificando.requisito}`} · ${justificando.hoja}`}
          cumple={justificando.cumple}
          onCerrar={() => setJustificando(null)}
          onConfirmar={(nota) => {
            const { hoja, requisito, cumple } = justificando
            setJustificando(null)
            void revisar(hoja, requisito, cumple, nota)
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

function DialogoJustificacion({
  titulo,
  cumple,
  onCerrar,
  onConfirmar,
}: {
  titulo: string
  cumple: boolean
  onCerrar: () => void
  onConfirmar: (nota: string) => void
}) {
  const [nota, setNota] = useState('')
  return (
    <>
      <div className="overlay" style={{ zIndex: 60 }} onClick={onCerrar} />
      <div className="dialogo" style={{ zIndex: 61 }} role="dialog" aria-modal="true" aria-labelledby="titulo-justificacion">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (nota.trim().length >= 5) onConfirmar(nota.trim())
          }}
        >
          <div className="card-head">
            <div>
              <h2 id="titulo-justificacion">{cumple ? 'Marcar como cumple' : 'Marcar como no cumple'}</h2>
              <p>{titulo}</p>
            </div>
          </div>
          <div className="field">
            <label htmlFor="nota">¿Por qué? (aparece en el reporte formal con su nombre y la fecha)</label>
            <textarea
              id="nota"
              className="textarea"
              rows={4}
              autoFocus
              value={nota}
              placeholder={
                cumple
                  ? 'Ej.: Se revisó el certificado en la página 3 del RUP; fue expedido el 15/08/2026, dentro de la vigencia.'
                  : 'Ej.: El certificado aportado fue expedido el 10/03/2026, supera los 3 meses exigidos al cierre.'
              }
              onChange={(e) => setNota(e.target.value)}
            />
          </div>
          <div className="dialogo-pie">
            <button type="button" className="btn btn-ghost" onClick={onCerrar}>
              Cancelar
            </button>
            <button type="submit" className={`btn ${cumple ? 'btn-ok' : 'btn-bad'}`} disabled={nota.trim().length < 5}>
              {cumple ? 'Confirmar: cumple' : 'Confirmar: no cumple'}
            </button>
          </div>
        </form>
      </div>
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
    cargaEquipo(resumen.entidad_id)
      .then(setEquipo)
      .catch(() => setEquipo([]))
  }, [resumen.puede_gestionar, resumen.entidad_id])

  const candidatos = useMemo(
    () => (equipo ?? []).filter((m) => m.areas.includes(resumen.tipo) || m.rol !== 'evaluador' || m.id === resumen.responsable?.id),
    [equipo, resumen.tipo, resumen.responsable],
  )

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
        <span className="small muted" title="Plantilla de evaluación de la entidad con la que se evalúa">
          · {resumen.plantilla_nombre}
          {resumen.plantilla_version !== null && ` (v${resumen.plantilla_version})`}
        </span>
        {resumen.plantilla_desactualizada && resumen.puede_trabajar && resumen.estado !== 'aprobada' && (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            disabled={ocupado}
            title="La entidad publicó una versión nueva de su plantilla de evaluación"
            onClick={() => {
              if (window.confirm('Hay una versión nueva de la plantilla de evaluación. ¿Actualizar? Se volverá a evaluar a todos los proponentes y se descartarán las decisiones de requisitos que ya no existan.')) {
                setOcupado(true)
                actualizarPlantillaEvaluacion(resumen.id)
                  // El catálogo de requisitos cambia: se recarga la evaluación completa.
                  .then(() => window.location.reload())
                  .catch((err: unknown) => {
                    onAviso(mensajeDe(err))
                    setOcupado(false)
                  })
              }
            }}
          >
            <Icono nombre="alerta" tam={14} /> Plantilla nueva disponible
          </button>
        )}
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
