import { useEffect, useRef, useState } from 'react'
import type { Proponente, ResultadoRequisito } from '../api'
import { useDialogo } from '../dialogo'
import { claveRevision, ETIQUETA_ESTADO, esPendiente, estadoDe, resumenProponente, usaIA, type Estado, type Revisiones } from '../estado'
import { GRUPOS, ORDEN_GRUPOS, ordenarArchivosPorRequisito, REQUISITOS } from '../requisitos'
import { fuenteDe } from '../historico'
import { archivosDelProponente } from '../evaluaciones'
import Icono from './Icono'
import DetalleFinanciero from './DetalleFinanciero'
import DetalleTecnico from './DetalleTecnico'
import { conGlosario } from '../glosario'
import ExplicacionIA from './ExplicacionIA'
import Motivos from './Motivos'
import QueFaltaRevisar from './QueFaltaRevisar'

const TIPO: Record<string, string> = {
  persona_natural: 'Persona natural',
  persona_juridica: 'Persona jurídica',
  consorcio: 'Consorcio',
  union_temporal: 'Unión temporal',
}

interface Props {
  proponente: Proponente
  /** Para pedirle al servidor la explicación en palabras de un resultado. */
  evaluacionId: string
  proponenteId: string
  resultados: ResultadoRequisito[]
  revisiones: Revisiones
  requisitoDestacado: number | null
  abriendoDocumento: string | null
  onCerrar: () => void
  /** null = solo lectura (sin permiso o evaluación aprobada). */
  onRevisar: ((hoja: string, requisito: number, cumple: boolean | undefined) => void) | null
  /** Otro integrante del comité tiene abierto este proponente: aquí solo se mira. */
  bloqueadoPor?: string | null
  onVerDocumento: (resultado: ResultadoRequisito, archivo: string) => void
  onAnterior: (() => void) | null
  onSiguiente: (() => void) | null
  onSiguientePendiente: (() => void) | null
  /** Contenido adicional al final (personas verificadas y antecedentes aportados). */
  extra?: React.ReactNode
  /** Deja estos documentos de la carpeta como asociados a mano al requisito (null = solo lectura). */
  onAsociarDocumentos: ((resultado: ResultadoRequisito, archivos: string[], excluidos: string[]) => Promise<void>) | null
  /** Subir el certificado que el evaluador consultó en línea (null = solo lectura). */
  onSubirCertificado: ((requisito: number) => void) | null
  /** Consultar el COPNIA en línea por la matrícula que se leyó del documento. */
  onConsultarCopnia: ((requisito: number, matricula: string) => Promise<void>) | null
  consultandoCopnia: number | null
}

function nombreArchivo(ruta: string): string {
  return ruta.split('/').pop() ?? ruta
}

function Pill({ estado }: { estado: Estado }) {
  return (
    <span className="pill" data-estado={estado}>
      <span className="dot" /> {ETIQUETA_ESTADO[estado]}
    </span>
  )
}

/** El pliego de este proceso no incluye el requisito (ni lo pide ni lo puntúa):
 * es igual para todos los proponentes, así que no se muestra como un requisito más. */
function fueraDelPliego(r: ResultadoRequisito | undefined): boolean {
  return Boolean(r && r.cumple === true && !r.error && (r.motivo ?? '').startsWith('N.A. — el pliego'))
}

export default function PanelProponente(p: Props) {
  const panel = useRef<HTMLElement>(null)
  useDialogo(panel)
  const porReq = new Map(p.resultados.map((r) => [r.requisito, r]))
  const [asociando, setAsociando] = useState(false)
  async function asociar(r: ResultadoRequisito, archivos: string[], excluidos: string[] = r.archivos_excluidos ?? []) {
    if (!p.onAsociarDocumentos) return
    setAsociando(true)
    try {
      await p.onAsociarDocumentos(r, archivos, excluidos)
    } finally {
      setAsociando(false)
    }
  }
  const resumen = resumenProponente(p.resultados, p.revisiones)
  const tipo = p.resultados.find((r) => r.tipo_proponente)?.tipo_proponente

  const pendientesIniciales = () =>
    new Set(
      REQUISITOS.filter((info) => {
        const r = porReq.get(info.numero)
        return (r && esPendiente(estadoDe(r, p.revisiones))) || info.numero === p.requisitoDestacado
      }).map((i) => i.numero),
    )
  const [abiertos, setAbiertos] = useState<Set<number>>(pendientesIniciales)
  // Antecedentes que el evaluador consulta en línea y sube (Contraloría, Procuraduría, Policía, RNMC, REDAM).
  const fuente = (numero: number) => fuenteDe(REQUISITOS.find((x) => x.numero === numero)?.pistas ?? [])
  const [archivoElegido, setArchivoElegido] = useState<Record<number, string>>({})
  // Matrícula para consultar el COPNIA cuando no se leyó de la oferta (o se leyó mal).
  const [matriculaEscrita, setMatriculaEscrita] = useState<Record<number, string>>({})
  // La carpeta completa del proponente (todos los documentos de la oferta), que
  // se pide una sola vez cuando la persona quiere buscar un documento a mano.
  const [carpeta, setCarpeta] = useState<{ archivos: string[]; aportados: string[] } | null>(null)
  const [cargandoCarpeta, setCargandoCarpeta] = useState(false)
  const [errorCarpeta, setErrorCarpeta] = useState<string | null>(null)
  const [verCarpeta, setVerCarpeta] = useState<Set<number>>(new Set())
  async function abrirCarpeta(numero: number) {
    setErrorCarpeta(null)
    try {
      let datos = carpeta
      if (!datos) {
        setCargandoCarpeta(true)
        datos = await archivosDelProponente(p.evaluacionId, p.proponenteId)
        setCarpeta(datos)
      }
      setVerCarpeta((prev) => new Set(prev).add(numero))
    } catch (e) {
      setErrorCarpeta(e instanceof Error ? e.message : 'No se pudo abrir la carpeta del proponente.')
    } finally {
      setCargandoCarpeta(false)
    }
  }

  useEffect(() => {
    function tecla(e: KeyboardEvent) {
      // Con una ventana abierta encima (subir un certificado), el teclado es de esa ventana.
      if (document.querySelector('.ventana-fondo')) return
      // Al escribir en un campo las teclas son texto, no atajos.
      const foco = document.activeElement
      if (foco instanceof HTMLInputElement || foco instanceof HTMLTextAreaElement || foco instanceof HTMLSelectElement) {
        if (e.key === 'Escape') p.onCerrar()
        return
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return
      // Solo atajos para moverse. Decidir "cumple" o "no cumple" con una tecla
      // es demasiado fácil de pulsar sin querer, y eso queda en el informe.
      if (e.key === 'Escape') p.onCerrar()
      else if (e.key === 'ArrowRight') p.onSiguiente?.()
      else if (e.key === 'ArrowLeft') p.onAnterior?.()
      else if (e.key.toLowerCase() === 'p') p.onSiguientePendiente?.()
    }
    window.addEventListener('keydown', tecla)
    return () => window.removeEventListener('keydown', tecla)
  }, [p])

  useEffect(() => {
    if (p.requisitoDestacado) {
      document.getElementById(`req-${p.requisitoDestacado}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
  }, [p.requisitoDestacado])

  /** Abre un requisito y lo trae a la vista. Desde el índice de pendientes de
   * la cabecera: con veinte requisitos, encontrar los tres que faltan a fuerza
   * de rueda del ratón es el trabajo que la pantalla debería ahorrar. */
  function irAlRequisito(numero: number) {
    setAbiertos((prev) => new Set(prev).add(numero))
    window.requestAnimationFrame(() => {
      document.getElementById(`req-${numero}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    })
  }

  const pendientes = REQUISITOS.filter((info) => {
    const r = porReq.get(info.numero)
    return r && esPendiente(estadoDe(r, p.revisiones))
  })

  function alternar(numero: number) {
    setAbiertos((prev) => {
      const nuevo = new Set(prev)
      if (nuevo.has(numero)) nuevo.delete(numero)
      else nuevo.add(numero)
      return nuevo
    })
  }

  return (
    <>
      <div className="overlay" onClick={p.onCerrar} />
      <aside
        ref={panel}
        className="drawer"
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        aria-label={`Detalle de ${p.proponente.nombre_proponente}`}
      >
        <div className="drawer-head">
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="small muted" style={{ fontWeight: 600 }}>
                {p.proponente.hoja}
                {tipo && ` · ${TIPO[tipo] ?? tipo}`}
              </div>
              <h2>{p.proponente.nombre_proponente}</h2>
            </div>
            <button className="btn btn-ghost btn-icon" type="button" onClick={p.onCerrar} aria-label="Cerrar">
              <Icono nombre="x" />
            </button>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
            {resumen.pendientes > 0 ? (
              <span className="pill" data-estado="revisar">
                <span className="dot" /> {resumen.pendientes} por revisar
              </span>
            ) : (
              <span className="pill" data-estado="cumple">
                <span className="dot" /> Nada pendiente
              </span>
            )}
            {resumen.revisados > 0 && <span className="pill" data-estado="no_aplica">{resumen.revisados} decididos por usted</span>}
          </div>
          {p.bloqueadoPor && (
            <div className="callout callout-warn" role="status" style={{ marginTop: 12 }}>
              <Icono nombre="ojo" />
              <div>
                <strong>{p.bloqueadoPor} está revisando este proponente.</strong> Puede mirar, pero no decidir hasta que lo
                cierre; así nadie decide lo mismo dos veces.
              </div>
            </div>
          )}
          {pendientes.length > 0 && (
            <div className="indice-pendientes">
              <span className="small muted">Ir a:</span>
              {pendientes.map((info) => (
                <button key={info.numero} type="button" className="chip-req" onClick={() => irAlRequisito(info.numero)}>
                  <span className="chip-req-num">{info.numero}</span>
                  {info.corto}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="drawer-body">
          {ORDEN_GRUPOS.filter((g) => REQUISITOS.some((r) => r.grupo === g && !fueraDelPliego(porReq.get(r.numero)))).map((grupo) => (
            <div key={grupo}>
              <div className="grupo-titulo">{GRUPOS[grupo]}</div>
              {REQUISITOS.filter((info) => info.grupo === grupo).map((info) => {
                const r = porReq.get(info.numero)
                if (!r) return null
                // Lo que este pliego no pide no se lista como requisito: se nombra al final.
                if (fueraDelPliego(r)) return null
                const estado = estadoDe(r, p.revisiones)
                const abierto = abiertos.has(info.numero)
                const decision = p.revisiones[claveRevision(r.hoja, r.requisito)]
                const texto = r.revision_forzada ?? r.error ?? r.motivo
                const verTodo = verCarpeta.has(info.numero) && carpeta
                const archivos = verTodo
                  ? [...carpeta!.archivos, ...carpeta!.aportados]
                  : r.archivo_evaluado
                    ? [r.archivo_evaluado]
                    : ordenarArchivosPorRequisito(info.numero, r.archivos_disponibles)
                const archivo = archivoElegido[info.numero] ?? (r.archivo_evaluado ?? '')
                // Varios documentos sostienen el resultado: cada uno con su botón.
                const asociados = r.archivos_asociados ?? []
                const excluidos = r.archivos_excluidos ?? []
                const soportes = [...new Set([r.archivo_evaluado, ...(r.archivos_soporte ?? []), ...asociados].filter((a): a is string => Boolean(a)))].filter(
                  (a) => !excluidos.includes(a),
                )
                // Se listan uno por uno cuando hay varios o cuando alguien añadió o quitó alguno.
                // Lo que el programa dio por verificado no se toca, salvo que la persona haya dicho que no está de acuerdo.
                const bloqueadoPorVerificado = r.cumple === true && decision !== false
                const puedeCambiarDocumentos = Boolean(p.onAsociarDocumentos) && !bloqueadoPorVerificado
                const listar = soportes.length > 1 || asociados.length > 0 || excluidos.length > 0 || (puedeCambiarDocumentos && soportes.length > 0)
                return (
                  <div key={info.numero} id={`req-${info.numero}`} className="req" data-destacado={p.requisitoDestacado === info.numero}>
                    <button type="button" className="req-top" onClick={() => alternar(info.numero)} aria-expanded={abierto}>
                      <span className="req-num">{info.numero}</span>
                      <span className="req-titulo">{info.titulo}</span>
                      {usaIA(r) && estado !== 'revisado_cumple' && estado !== 'revisado_no_cumple' && (
                        <span className="pill pill-ai" title="Parte de la verificación se hizo con IA local y se comprobó contra el texto del documento">
                          <Icono nombre="chispa" tam={12} /> IA
                        </span>
                      )}
                      <Pill estado={estado} />
                    </button>
                    {abierto && (
                      <div className="req-body">
                        <div className="req-verifica">
                          <strong style={{ color: 'var(--ink-2)' }}>Qué se verifica:</strong> {conGlosario(info.verifica)}
                        </div>
                        {texto && estado !== 'revisado_cumple' && (
                          <Motivos motivo={texto} tono={estado === 'revisar' ? 'warn' : estado === 'error' ? 'bad' : undefined} />
                        )}
                        {r.detalle?.contratos && <DetalleTecnico detalle={r.detalle} />}
                        {r.detalle?.financiera && <DetalleFinanciero detalle={r.detalle} />}
                        {esPendiente(estado) && (
                          <QueFaltaRevisar revisiones={r.detalle?.revisiones} acreditada={r.detalle?.experiencia_acreditada} />
                        )}
                        {(texto || r.detalle) && (
                          <ExplicacionIA
                            evaluacionId={p.evaluacionId}
                            proponenteId={p.proponenteId}
                            requisito={info.numero}
                          />
                        )}
                        {p.onConsultarCopnia && fuente(info.numero)?.clave === 'copnia' && esPendiente(estado) && (() => {
                          // El COPNIA se consulta por la cédula del profesional (también acepta la matrícula).
                          const matricula = (matriculaEscrita[info.numero] ?? '').trim()
                          return (
                            <div className="acciones">
                              <span className="small muted">
                                Escriba la cédula del ingeniero que avala la oferta y el certificado del COPNIA se consulta en línea
                                {r.matricula_profesional ? ` (matrícula leída de la oferta: ${r.matricula_profesional})` : ''}:
                              </span>
                              <input
                                className="input"
                                style={{ maxWidth: 200, height: 34 }}
                                aria-label="Cédula del ingeniero"
                                placeholder="Cédula del ingeniero"
                                inputMode="numeric"
                                value={matriculaEscrita[info.numero] ?? ''}
                                onChange={(e) => setMatriculaEscrita((prev) => ({ ...prev, [info.numero]: e.target.value }))}
                              />
                              <button
                                className="btn btn-secondary btn-sm"
                                type="button"
                                disabled={p.consultandoCopnia !== null || matricula.length < 4}
                                onClick={() => void p.onConsultarCopnia?.(info.numero, matricula)}
                              >
                                {p.consultandoCopnia === info.numero ? <span className="spinner oscuro" /> : <Icono nombre="descargar" tam={15} />}
                                Consultar el COPNIA y adjuntarlo
                              </button>
                            </div>
                          )
                        })()}
                        {fuente(info.numero) && esPendiente(estado) && (
                          <div className="acciones">
                            <span className="small muted">
                              Si ya lo consultó en{' '}
                              <a className="enlace" href={fuente(info.numero)!.url} target="_blank" rel="noopener noreferrer">
                                {fuente(info.numero)!.nombre}
                              </a>
                              , adjúntelo aquí y queda en el expediente.
                            </span>
                            {p.onSubirCertificado && (
                              <button className="btn btn-secondary btn-sm" type="button" onClick={() => p.onSubirCertificado?.(info.numero)}>
                                <Icono nombre="subir" tam={15} /> Subir el certificado consultado
                              </button>
                            )}
                          </div>
                        )}
                        {!verCarpeta.has(info.numero) && (
                          <div className="acciones">
                            <button
                              className="btn btn-ghost btn-sm"
                              type="button"
                              disabled={cargandoCarpeta}
                              onClick={() => void abrirCarpeta(info.numero)}
                            >
                              {cargandoCarpeta ? <span className="spinner oscuro" /> : <Icono nombre="documento" tam={15} />}
                              Buscar en la carpeta del proponente
                            </button>
                            {archivos.length === 0 && (
                              <span className="small muted">El sistema no asoció ningún documento a este requisito.</span>
                            )}
                          </div>
                        )}
                        {verCarpeta.has(info.numero) && carpeta && (
                          <span className="small muted">
                            Viendo toda la carpeta: {carpeta.archivos.length + carpeta.aportados.length} documentos. Elija uno, ábralo y, si
                            corresponde a este requisito, añádalo: queda guardado.
                          </span>
                        )}
                        {errorCarpeta && <span className="small" style={{ color: 'var(--bad, #c0392b)' }}>{errorCarpeta}</span>}
                        {listar && (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            <span className="small muted">Documentos de este requisito ({soportes.length}):</span>
                            {soportes.map((a) => (
                              <div key={a} className="acciones">
                                <span className="archivo" title={a}>
                                  <Icono nombre="documento" tam={15} /> {nombreArchivo(a)}
                                </span>
                                <button
                                  className="btn btn-secondary btn-sm"
                                  type="button"
                                  onClick={() => p.onVerDocumento(r, a)}
                                  disabled={p.abriendoDocumento !== null}
                                >
                                  {p.abriendoDocumento === `${r.hoja}|${a}` ? <span className="spinner oscuro" /> : <Icono nombre="ojo" tam={15} />}
                                  Ver documento
                                </button>
                                {asociados.includes(a) && <span className="small muted">añadido a mano</span>}
                                {puedeCambiarDocumentos && (
                                  <button
                                    className="btn btn-ghost btn-icon"
                                    type="button"
                                    disabled={asociando}
                                    title="Quitar de este requisito (no corresponde)"
                                    aria-label={`Quitar ${nombreArchivo(a)} de este requisito`}
                                    onClick={() =>
                                      // Lo añadido a mano simplemente se retira; lo que trajo el programa queda como quitado.
                                      void asociar(
                                        r,
                                        asociados.filter((x) => x !== a),
                                        a === r.archivo_evaluado || (r.archivos_soporte ?? []).includes(a) ? [...excluidos, a] : excluidos,
                                      )
                                    }
                                  >
                                    <Icono nombre="papelera" tam={16} />
                                  </button>
                                )}
                              </div>
                            ))}
                            {excluidos.length > 0 && (
                              <div className="small muted" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                <span>Quitados por no corresponder ({excluidos.length}):</span>
                                {excluidos.map((a) => (
                                  <span key={a} title={a}>
                                    <s>{nombreArchivo(a)}</s>{' '}
                                    {puedeCambiarDocumentos && (
                                      <button
                                        className="enlace"
                                        type="button"
                                        disabled={asociando}
                                        onClick={() => void asociar(r, asociados, excluidos.filter((x) => x !== a))}
                                      >
                                        Restaurar
                                      </button>
                                    )}
                                  </span>
                                ))}
                              </div>
                            )}
                            {p.onAsociarDocumentos && bloqueadoPorVerificado && (
                              <span className="small muted">
                                El programa dio por verificado este requisito: para añadir o quitar documentos, primero marque que no
                                está de acuerdo.
                              </span>
                            )}
                            <span className="small muted">Cada documento que se añade o se quita queda registrado con quién y cuándo.</span>
                          </div>
                        )}
                        {(!listar || verTodo) && archivos.length > 0 && (
                          <div className="acciones">
                            {archivos.length > 1 || !r.archivo_evaluado ? (
                              <select
                                className="select"
                                style={{ height: 38, padding: '0 10px', maxWidth: 340, fontSize: 'calc(13px * var(--escala-texto, 1))' }}
                                value={archivo}
                                onChange={(e) => setArchivoElegido((prev) => ({ ...prev, [info.numero]: e.target.value }))}
                                aria-label="Documento a abrir"
                              >
                                <option value="" disabled>
                                  Elegir un documento del proponente…
                                </option>
                                {archivos.map((a) => (
                                  <option key={a} value={a}>
                                    {nombreArchivo(a)}
                                  </option>
                                ))}
                              </select>
                            ) : (
                              <span className="archivo">
                                <Icono nombre="documento" tam={15} /> {nombreArchivo(archivo)}
                              </span>
                            )}
                            <button
                              className="btn btn-secondary btn-sm"
                              type="button"
                              onClick={() => p.onVerDocumento(r, archivo)}
                              disabled={p.abriendoDocumento !== null || !archivo}
                            >
                              {p.abriendoDocumento === `${r.hoja}|${archivo}` ? <span className="spinner oscuro" /> : <Icono nombre="ojo" tam={15} />}
                              Ver documento
                            </button>
                            {verTodo && puedeCambiarDocumentos && (
                              <button
                                className="btn btn-primary btn-sm"
                                type="button"
                                disabled={asociando || !archivo || soportes.includes(archivo)}
                                title={soportes.includes(archivo) ? 'Ya está entre los documentos de este requisito' : undefined}
                                onClick={() => void asociar(r, [...asociados, archivo])}
                              >
                                {asociando ? <span className="spinner" /> : <Icono nombre="mas" tam={15} />} Añadir a este requisito
                              </button>
                            )}
                          </div>
                        )}
                        <div className="acciones decision" style={{ borderTop: '1px solid var(--line)', paddingTop: 10 }}>
                          {!p.onRevisar ? (
                            <span className="small muted">
                              {decision === undefined ? 'Solo lectura' : <>Decisión registrada: <strong>{decision ? 'Cumple' : 'No cumple'}</strong></>}
                            </span>
                          ) : decision === undefined ? (
                            esPendiente(estado) ? (
                              <>
                                <span
                                  className="small muted"
                                  style={{ marginRight: 'auto' }}
                                  title="Decida viendo la evidencia: abra el documento soporte primero (sin documento, explique en la justificación qué consultó)."
                                >
                                  {r.archivo_evaluado ? 'Abra el soporte y decida:' : 'Su decisión (explique qué consultó):'}
                                </span>
                                <button className="btn btn-ok btn-sm" type="button" onClick={() => p.onRevisar?.(r.hoja, r.requisito, true)}>
                                  <Icono nombre="check" tam={15} /> Cumple
                                </button>
                                <button className="btn btn-bad btn-sm" type="button" onClick={() => p.onRevisar?.(r.hoja, r.requisito, false)}>
                                  <Icono nombre="x" tam={15} /> No cumple
                                </button>
                              </>
                            ) : (
                              <button className="btn btn-ghost btn-sm" type="button" onClick={() => p.onRevisar?.(r.hoja, r.requisito, false)}>
                                ¿No está de acuerdo? Marcar como no cumple
                              </button>
                            )
                          ) : (
                            <>
                              <span className="small" style={{ marginRight: 'auto' }}>
                                Usted decidió: <strong>{decision ? 'Cumple' : 'No cumple'}</strong>
                              </span>
                              <button className="btn btn-ghost btn-sm" type="button" onClick={() => p.onRevisar?.(r.hoja, r.requisito, undefined)}>
                                <Icono nombre="deshacer" tam={15} /> Deshacer
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
          {REQUISITOS.some((info) => fueraDelPliego(porReq.get(info.numero))) && (
            <p className="small muted" style={{ marginTop: 12 }}>
              No aplican en este pliego (no se evalúan):{' '}
              {REQUISITOS.filter((info) => fueraDelPliego(porReq.get(info.numero)))
                .map((info) => info.titulo)
                .join('; ')}
              .
            </p>
          )}
          {p.extra}
          <p className="small muted atajos">
            Atajos: <kbd>←</kbd> <kbd>→</kbd> cambian de proponente · <kbd>P</kbd> salta al siguiente pendiente ·{' '}
            <kbd>Esc</kbd> cierra este panel.
          </p>
        </div>

        <div className="drawer-foot">
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="btn btn-ghost btn-sm" type="button" onClick={p.onAnterior ?? undefined} disabled={!p.onAnterior}>
              <Icono nombre="atras" tam={15} /> Anterior
            </button>
            <button className="btn btn-ghost btn-sm" type="button" onClick={p.onSiguiente ?? undefined} disabled={!p.onSiguiente}>
              Siguiente <Icono nombre="flecha" tam={15} />
            </button>
          </div>
          <button className="btn btn-primary btn-sm" type="button" onClick={p.onSiguientePendiente ?? undefined} disabled={!p.onSiguientePendiente}>
            Siguiente pendiente <Icono nombre="flecha" tam={15} />
          </button>
        </div>
      </aside>
    </>
  )
}
