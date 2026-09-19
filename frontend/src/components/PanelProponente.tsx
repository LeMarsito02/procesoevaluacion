import { useEffect, useState } from 'react'
import type { Proponente, ResultadoRequisito } from '../api'
import { claveRevision, ETIQUETA_ESTADO, esPendiente, estadoDe, resumenProponente, usaIA, type Estado, type Revisiones } from '../estado'
import { GRUPOS, ORDEN_GRUPOS, ordenarArchivosPorRequisito, REQUISITOS } from '../requisitos'
import { fuenteDe } from '../historico'
import Icono from './Icono'

const TIPO: Record<string, string> = {
  persona_natural: 'Persona natural',
  persona_juridica: 'Persona jurídica',
  consorcio: 'Consorcio',
  union_temporal: 'Unión temporal',
}

interface Props {
  proponente: Proponente
  resultados: ResultadoRequisito[]
  revisiones: Revisiones
  requisitoDestacado: number | null
  abriendoDocumento: string | null
  onCerrar: () => void
  /** null = solo lectura (sin permiso o evaluación aprobada). */
  onRevisar: ((hoja: string, requisito: number, cumple: boolean | undefined) => void) | null
  onVerDocumento: (resultado: ResultadoRequisito, archivo: string) => void
  onAnterior: (() => void) | null
  onSiguiente: (() => void) | null
  onSiguientePendiente: (() => void) | null
  /** Contenido adicional al final (personas verificadas y antecedentes aportados). */
  extra?: React.ReactNode
  /** Subir el certificado que el evaluador consultó en línea (null = solo lectura). */
  onSubirCertificado: ((requisito: number) => void) | null
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

export default function PanelProponente(p: Props) {
  const porReq = new Map(p.resultados.map((r) => [r.requisito, r]))
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

  useEffect(() => {
    function tecla(e: KeyboardEvent) {
      if (e.key === 'Escape') p.onCerrar()
    }
    window.addEventListener('keydown', tecla)
    return () => window.removeEventListener('keydown', tecla)
  }, [p])

  useEffect(() => {
    if (p.requisitoDestacado) {
      document.getElementById(`req-${p.requisitoDestacado}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
  }, [p.requisitoDestacado])

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
      <aside className="drawer" role="dialog" aria-label={`Detalle de ${p.proponente.nombre_proponente}`}>
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
        </div>

        <div className="drawer-body">
          {ORDEN_GRUPOS.filter((g) => REQUISITOS.some((r) => r.grupo === g)).map((grupo) => (
            <div key={grupo}>
              <div className="grupo-titulo">{GRUPOS[grupo]}</div>
              {REQUISITOS.filter((info) => info.grupo === grupo).map((info) => {
                const r = porReq.get(info.numero)
                if (!r) return null
                const estado = estadoDe(r, p.revisiones)
                const abierto = abiertos.has(info.numero)
                const decision = p.revisiones[claveRevision(r.hoja, r.requisito)]
                const texto = r.error ?? r.motivo
                const archivos = r.archivo_evaluado
                  ? [r.archivo_evaluado]
                  : ordenarArchivosPorRequisito(info.numero, r.archivos_disponibles)
                const archivo = archivoElegido[info.numero] ?? (r.archivo_evaluado ?? '')
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
                          <strong style={{ color: 'var(--ink-2)' }}>Qué se verifica:</strong> {info.verifica}
                        </div>
                        {texto && estado !== 'revisado_cumple' && (
                          <div className="motivo" data-tono={estado === 'revisar' ? 'warn' : estado === 'error' ? 'bad' : undefined}>
                            {texto}
                          </div>
                        )}
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
                        {archivos.length > 0 && (
                          <div className="acciones">
                            {archivos.length > 1 || !r.archivo_evaluado ? (
                              <select
                                className="select"
                                style={{ height: 38, padding: '0 10px', maxWidth: 340, fontSize: 13 }}
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
                          </div>
                        )}
                        <div className="acciones" style={{ borderTop: '1px solid var(--line)', paddingTop: 10 }}>
                          {!p.onRevisar ? (
                            <span className="small muted">
                              {decision === undefined ? 'Solo lectura' : <>Decisión registrada: <strong>{decision ? 'Cumple' : 'No cumple'}</strong></>}
                            </span>
                          ) : decision === undefined ? (
                            esPendiente(estado) ? (
                              <>
                                <span className="small muted" style={{ marginRight: 'auto' }}>
                                  Su decisión:
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
          {p.extra}
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
