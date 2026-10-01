/**
 * Control humano de la verificación (expediente LEG-004, numerales 1.2, 3 y 3.1).
 *
 * - Muestra de control: lo que MiEvaluador verificó se adopta en bloque después de
 *   revisar, contra su soporte, 10 verificaciones sorteadas (repartidas entre
 *   ofertas y requisitos distintos). Un error envía todo ese requisito a revisión
 *   humana en el proceso.
 * - Puntaje técnico: el evaluador revisa la tabla y adopta los puntajes con un clic.
 *
 * Solo con la muestra cerrada (y el puntaje adoptado, en técnica) se puede aprobar.
 */
import { useCallback, useEffect, useState } from 'react'
import type { ResultadoRequisito } from '../api'
import {
  adoptarPuntajes,
  cerrarMuestra,
  crearMuestra,
  descargarActaMuestra,
  revisarItemMuestra,
  verMuestra,
  verPuntajes,
  type EstadoMuestra,
  type ItemMuestra,
  type PuntajeProponente,
} from '../evaluaciones'
import { mensajeDe } from '../http'
import { REQUISITOS } from '../requisitos'
import Icono from './Icono'
import { useDialogos } from '../dialogos'

interface Props {
  evaluacionId: string
  tipo: string
  puedeTrabajar: boolean
  aprobada: boolean
  pendientes: number
  resultados: Record<string, ResultadoRequisito[]>
  onVerDocumento: (resultado: ResultadoRequisito, archivo: string) => void
  onAviso: (texto: string) => void
  /** La muestra cambió resultados (amplió la revisión) o el estado para aprobar. */
  onCambio: () => void
  onDescargar: (blob: Blob, nombre: string) => void
}

function tituloRequisito(numero: number) {
  return REQUISITOS.find((r) => r.numero === numero)?.titulo ?? `Requisito ${numero}`
}

export default function ControlHumano(p: Props) {
  const { confirmar, pedirTexto } = useDialogos()
  const [estado, setEstado] = useState<EstadoMuestra | null>(null)
  const [puntajes, setPuntajes] = useState<PuntajeProponente[] | null>(null)
  const [ocupado, setOcupado] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [hallazgo, setHallazgo] = useState<ItemMuestra | null>(null)

  const cargar = useCallback(() => {
    verMuestra(p.evaluacionId)
      .then(setEstado)
      .catch((e: unknown) => setError(mensajeDe(e)))
    if (p.tipo === 'tecnica')
      verPuntajes(p.evaluacionId)
        .then(setPuntajes)
        .catch(() => setPuntajes([]))
  }, [p.evaluacionId, p.tipo])

  useEffect(() => {
    cargar()
  }, [cargar, p.pendientes, p.aprobada])

  async function ejecutar(clave: string, f: () => Promise<EstadoMuestra>, exito?: string) {
    setOcupado(clave)
    setError(null)
    try {
      setEstado(await f())
      if (exito) p.onAviso(exito)
      p.onCambio()
    } catch (e) {
      setError(mensajeDe(e))
    } finally {
      setOcupado(null)
    }
  }

  function resultadoDe(item: ItemMuestra) {
    return (p.resultados[item.hoja] ?? []).find((r) => r.requisito === item.requisito)
  }

  const muestra = estado?.muestra ?? null
  const enCurso = muestra && (muestra.estado === 'en_curso' || muestra.estado === 'con_hallazgos')
  const revisados = muestra?.items.filter((i) => i.resultado).length ?? 0
  const puedeActuar = p.puedeTrabajar && !p.aprobada
  const porAdoptar = puntajes?.filter((x) => x.resuelto && !x.adoptado).length ?? 0

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <div>
          <h2>Control humano de la verificación</h2>
          <p>
            Lo que MiEvaluador verificó se adopta en bloque después de revisar, contra su soporte,{' '}
            {estado?.verificaciones_por_muestra ?? 10} verificaciones sorteadas entre ofertas y requisitos distintos. Si
            encuentra un error, ese requisito vuelve a revisión humana en todas las ofertas.
          </p>
        </div>
      </div>

      {error && (
        <div className="callout callout-bad" style={{ marginBottom: 12 }}>
          <Icono nombre="alerta" />
          <div>{error}</div>
        </div>
      )}

      {!muestra && (
        <div className="acciones" style={{ justifyContent: 'space-between' }}>
          <span className="small muted">
            {p.pendientes > 0
              ? 'Puede sortearla ya: si sale un error, ese requisito vuelve a revisión y lo resuelve junto con lo demás.'
              : 'Aún no se ha hecho la muestra de control de esta evaluación.'}
          </span>
          {puedeActuar && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={ocupado !== null}
              onClick={() => ejecutar('crear', () => crearMuestra(p.evaluacionId), 'Muestra sorteada')}
            >
              {ocupado === 'crear' ? <span className="spinner" /> : <Icono nombre="check" tam={15} />} Sortear la muestra de control
            </button>
          )}
        </div>
      )}

      {muestra && (
        <>
          <div className="acciones" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
            <span className="small">
              <span className="pill" data-estado={muestra.estado === 'cerrada' ? 'cumple' : muestra.estado === 'con_hallazgos' ? 'error' : 'revisar'}>
                <span className="dot" /> {muestra.estado_nombre}
              </span>{' '}
              {muestra.items.length === 0
                ? 'Nada que revisar: todo se revisó individualmente'
                : `${revisados}/${muestra.items.length} verificaciones revisadas`}
              {muestra.requisitos_ampliados.length > 0 && (
                <> · requisitos ampliados a revisión total: {muestra.requisitos_ampliados.join(', ')}</>
              )}
            </span>
            <span style={{ display: 'flex', gap: 8 }}>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={ocupado !== null}
                onClick={() =>
                  descargarActaMuestra(p.evaluacionId)
                    .then(({ blob, nombre }) => p.onDescargar(blob, nombre ?? 'ACTA MUESTRA DE CONTROL.docx'))
                    .catch((e: unknown) => setError(mensajeDe(e)))
                }
              >
                <Icono nombre="descargar" tam={15} /> Acta
              </button>
              {puedeActuar && enCurso && (
                <button
                  type="button"
                  className="btn btn-ok btn-sm"
                  disabled={ocupado !== null || revisados < muestra.items.length || p.pendientes > 0}
                  title={
                    revisados < muestra.items.length
                      ? 'Faltan verificaciones de la muestra por revisar'
                      : p.pendientes > 0
                        ? `Quedan ${p.pendientes} requisitos por revisar: la muestra se cierra cuando no queda nada pendiente`
                        : undefined
                  }
                  onClick={() => ejecutar('cerrar', () => cerrarMuestra(p.evaluacionId), 'Muestra de control cerrada')}
                >
                  {ocupado === 'cerrar' ? <span className="spinner" /> : <Icono nombre="check" tam={15} />} Cerrar la muestra
                </button>
              )}
              {puedeActuar && muestra.estado === 'cerrada' && estado?.motivo_para_no_aprobar && (
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={ocupado !== null}
                  onClick={() => ejecutar('crear', () => crearMuestra(p.evaluacionId), 'Nueva muestra sorteada')}
                >
                  Sortear una nueva muestra
                </button>
              )}
            </span>
          </div>
          {estado?.motivo_para_no_aprobar && muestra.estado === 'cerrada' && (
            <p className="small muted">{estado.motivo_para_no_aprobar}</p>
          )}

          {muestra.items.length > 0 && (
            <div className="muestra-lista">
              {muestra.items.map((item) => {
                const r = resultadoDe(item)
                const archivo = r?.archivo_evaluado ?? null
                return (
                  <div key={item.id} className="muestra-fila">
                    <span className="muestra-req">
                      <strong>{item.hoja}</strong> · {item.proponente}
                      <br />
                      <span className="small">
                        {item.requisito}. {tituloRequisito(item.requisito)}
                      </span>
                      {item.usa_ia && (
                        <span className="pill pill-ai" style={{ marginLeft: 6 }}>
                          IA
                        </span>
                      )}
                    </span>
                    <span>
                      {item.soporte_pliego ? (
                        <a
                          className="btn btn-ghost btn-sm"
                          href={`/api/evaluaciones/${p.evaluacionId}/pliego`}
                          target="_blank"
                          rel="noopener noreferrer"
                          title="Esta decisión sale del pliego, no de la oferta"
                        >
                          <Icono nombre="ojo" tam={15} /> Ver pliego
                        </a>
                      ) : r && archivo ? (
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => p.onVerDocumento(r, archivo)}>
                          <Icono nombre="ojo" tam={15} /> Ver soporte
                        </button>
                      ) : (
                        <span className="small muted">Sin documento</span>
                      )}
                    </span>
                    <span className="muestra-accion">
                      {item.resultado ? (
                        <span className="small">
                          <strong>{item.resultado === 'conforme' ? 'Conforme' : 'No conforme'}</strong>
                          {item.usuario && ` · ${item.usuario}`}
                          {item.nota && ` · ${item.nota}`}
                        </span>
                      ) : puedeActuar && enCurso ? (
                        <>
                          <button
                            type="button"
                            className="btn btn-ok btn-sm"
                            disabled={ocupado !== null}
                            title="Revisé el soporte y la verificación del sistema es correcta"
                            onClick={async () => {
                              let nota = ''
                              if (!archivo && !item.soporte_pliego) {
                                // Sin documento que abrir, la ley pide dejar dicho qué se consultó.
                                const escrito = await pedirTexto({
                                  titulo: '¿Qué consultó para confirmar este requisito?',
                                  mensaje: (
                                    <>
                                      Esta verificación no tiene un documento que abrir, así que su justificación es la
                                      evidencia. <strong>Queda en el acta de la muestra</strong>, a su nombre.
                                    </>
                                  ),
                                  etiqueta: 'Qué consultó',
                                  placeholder: 'Ej.: el RUP del integrante, donde el indicador aparece en la página 3',
                                  largo: true,
                                  minimo: 15,
                                  aceptar: 'Marcar conforme',
                                })
                                if (escrito === null) return
                                nota = escrito
                              }
                              void ejecutar(`item-${item.id}`, () => revisarItemMuestra(p.evaluacionId, item.id, true, nota))
                            }}
                          >
                            Conforme
                          </button>
                          <button type="button" className="btn btn-bad btn-sm" disabled={ocupado !== null} onClick={() => setHallazgo(item)}>
                            No conforme
                          </button>
                        </>
                      ) : (
                        <span className="small muted">Sin revisar</span>
                      )}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}

      {puntajes && puntajes.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <h3>Puntaje técnico preliminar</h3>
          <p className="small muted">
            El puntaje es evaluación en sentido estricto: no se adopta por muestra. Revise la tabla y adopte los puntajes con
            un clic. Si después cambia un factor, ese puntaje vuelve a quedar sin adoptar.
          </p>
          <div className="tabla-wrap">
            <table className="tabla">
              <thead>
                <tr>
                  <th>Prop.</th>
                  <th>Proponente</th>
                  <th>Puntaje preliminar</th>
                  <th>Adopción</th>
                </tr>
              </thead>
              <tbody>
                {puntajes.map((x) => (
                  <tr key={x.proponente_id}>
                    <td>{x.hoja}</td>
                    <td>{x.nombre}</td>
                    <td>{x.resuelto ? x.puntaje : <span className="small muted">Factores pendientes</span>}</td>
                    <td>
                      {x.adoptado ? (
                        <span className="small">
                          Adoptado por {x.adoptado_por}
                          {x.adoptado_en && ` el ${new Date(x.adoptado_en).toLocaleString('es-CO', { dateStyle: 'short', timeStyle: 'short' })}`}
                        </span>
                      ) : (
                        <span className="small muted">{x.adopcion_desactualizada ? 'Adopción desactualizada' : 'Sin adoptar'}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {puedeActuar && porAdoptar > 0 && (
            <div className="acciones" style={{ justifyContent: 'flex-end', marginTop: 10 }}>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={ocupado !== null}
                onClick={async () => {
                  const seguro = await confirmar({
                    titulo: `¿Adopta los ${porAdoptar} puntajes de la tabla?`,
                    mensaje: 'Los adopta como evaluador técnico y queda en la auditoría a su nombre.',
                    aceptar: 'Adoptar los puntajes',
                  })
                  if (!seguro) return
                  setOcupado('puntajes')
                  setError(null)
                  try {
                    setPuntajes(await adoptarPuntajes(p.evaluacionId))
                    p.onAviso('Puntajes adoptados')
                    p.onCambio()
                  } catch (e) {
                    setError(mensajeDe(e))
                  } finally {
                    setOcupado(null)
                  }
                }}
              >
                {ocupado === 'puntajes' ? <span className="spinner" /> : <Icono nombre="check" tam={15} />} Adoptar los {porAdoptar} puntajes
              </button>
            </div>
          )}
        </div>
      )}

      {hallazgo && (
        <DialogoHallazgo
          item={hallazgo}
          onCerrar={() => setHallazgo(null)}
          onConfirmar={(nota) => {
            const item = hallazgo
            setHallazgo(null)
            void ejecutar(
              `item-${item.id}`,
              () => revisarItemMuestra(p.evaluacionId, item.id, false, nota),
              'Hallazgo registrado: el requisito pasa a revisión en todas las ofertas',
            )
          }}
        />
      )}
    </section>
  )
}

function DialogoHallazgo({ item, onCerrar, onConfirmar }: { item: ItemMuestra; onCerrar: () => void; onConfirmar: (nota: string) => void }) {
  const [nota, setNota] = useState('')
  return (
    <>
      <div className="overlay" style={{ zIndex: 60 }} onClick={onCerrar} />
      <div className="dialogo" style={{ zIndex: 61 }} role="dialog" aria-modal="true" aria-labelledby="titulo-hallazgo">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (nota.trim().length >= 5) onConfirmar(nota.trim())
          }}
        >
          <div className="card-head">
            <div>
              <h2 id="titulo-hallazgo">No conforme</h2>
              <p>
                {item.hoja} · {tituloRequisito(item.requisito)}. El requisito pasará a revisión humana en todas las ofertas del
                proceso.
              </p>
            </div>
          </div>
          <div className="field">
            <label htmlFor="nota-hallazgo">¿Qué encontró? (queda en el acta de la muestra)</label>
            <textarea id="nota-hallazgo" className="textarea" rows={4} autoFocus value={nota} onChange={(e) => setNota(e.target.value)} />
          </div>
          <div className="dialogo-pie">
            <button type="button" className="btn btn-ghost" onClick={onCerrar}>
              Cancelar
            </button>
            <button type="submit" className="btn btn-bad" disabled={nota.trim().length < 5}>
              Registrar hallazgo
            </button>
          </div>
        </form>
      </div>
    </>
  )
}
