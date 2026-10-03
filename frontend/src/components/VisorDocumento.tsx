import { useEffect, useRef } from 'react'
import type { ResultadoRequisito } from '../api'
import { useDialogo } from '../dialogo'
import { claveRevision, ETIQUETA_ESTADO, esPendiente, estadoDe, type Revisiones } from '../estado'
import { REQUISITO_POR_NUMERO } from '../requisitos'
import { conGlosario } from '../glosario'
import Icono from './Icono'
import ExplicacionIA from './ExplicacionIA'
import Motivos from './Motivos'

/** El visor se abrió desde la muestra de control: se decide sobre el ítem de la muestra. */
export interface DecisionMuestra {
  conforme: () => void
  noConforme: () => void
}

interface Props {
  url: string
  archivo: string
  /** Para pedir la explicación en palabras del resultado que se está mirando. */
  evaluacionId?: string
  proponenteId?: string
  resultado: ResultadoRequisito
  revisiones: Revisiones
  onRevisar: ((hoja: string, requisito: number, cumple: boolean | undefined) => void) | null
  onCerrar: () => void
  muestra?: DecisionMuestra
}

export default function VisorDocumento({ url, archivo, evaluacionId, proponenteId, resultado, revisiones, onRevisar, onCerrar, muestra }: Props) {
  const caja = useRef<HTMLDivElement>(null)
  useDialogo(caja)
  const info = REQUISITO_POR_NUMERO[resultado.requisito]
  const estado = estadoDe(resultado, revisiones)
  const decision = revisiones[claveRevision(resultado.hoja, resultado.requisito)]

  useEffect(() => {
    function tecla(e: KeyboardEvent) {
      if (e.key === 'Escape') onCerrar()
    }
    window.addEventListener('keydown', tecla)
    return () => window.removeEventListener('keydown', tecla)
  }, [onCerrar])

  return (
    <>
      <div className="overlay" style={{ zIndex: 49 }} onClick={onCerrar} />
      <div ref={caja} className="visor" role="dialog" aria-modal="true" tabIndex={-1} aria-label={`Documento ${archivo}`}>
        <div className="visor-doc">
          <div className="visor-doc-head">
            <Icono nombre="documento" />
            <span title={archivo}>{archivo.split('/').pop()}</span>
            <a className="btn btn-ghost btn-sm" href={url} target="_blank" rel="noreferrer">
              Abrir en pestaña nueva
            </a>
            <button className="btn btn-ghost btn-icon" type="button" onClick={onCerrar} aria-label="Cerrar documento">
              <Icono nombre="x" />
            </button>
          </div>
          <iframe title={archivo} src={url} />
        </div>
        <div className="visor-lado">
          <div>
            <div className="small muted" style={{ fontWeight: 600 }}>
              {resultado.hoja} · {resultado.nombre_proponente}
            </div>
            <h2 className="serif" style={{ fontSize: 'calc(19px * var(--escala-texto, 1))', marginTop: 4 }}>
              {info?.titulo ?? `Requisito ${resultado.requisito}`}
            </h2>
          </div>
          <span className="pill" data-estado={estado} style={{ alignSelf: 'flex-start' }}>
            <span className="dot" /> {ETIQUETA_ESTADO[estado]}
          </span>
          {info && (
            <p className="small" style={{ color: 'var(--ink-2)' }}>
              <strong>Qué se verifica:</strong> {conGlosario(info.verifica)}
            </p>
          )}
          <Motivos
            motivo={resultado.error ?? resultado.motivo}
            tono={estado === 'revisar' ? 'warn' : estado === 'error' ? 'bad' : undefined}
          />
          {evaluacionId && proponenteId && (
            <ExplicacionIA evaluacionId={evaluacionId} proponenteId={proponenteId} requisito={resultado.requisito} />
          )}
          <div className="decision" style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
            {muestra ? (
              <>
                <span className="small muted">Muestra de control: ¿la verificación del sistema es correcta?</span>
                <button className="btn btn-ok" type="button" onClick={() => { onCerrar(); muestra.conforme() }}>
                  <Icono nombre="check" tam={16} /> Conforme
                </button>
                <button className="btn btn-bad" type="button" onClick={() => { onCerrar(); muestra.noConforme() }}>
                  <Icono nombre="x" tam={16} /> No conforme
                </button>
              </>
            ) : !onRevisar ? (
              <span className="small muted">
                {decision === undefined ? 'Solo lectura' : <>Decisión registrada: <strong>{decision ? 'Cumple' : 'No cumple'}</strong></>}
              </span>
            ) : decision === undefined ? (
              <>
                {esPendiente(estado) || resultado.cumple == null ? (
                  <>
                    <span className="small muted">Después de revisar el documento:</span>
                    <button className="btn btn-ok" type="button" onClick={() => onRevisar?.(resultado.hoja, resultado.requisito, true)}>
                      <Icono nombre="check" tam={16} /> Cumple
                    </button>
                    <button className="btn btn-bad" type="button" onClick={() => onRevisar?.(resultado.hoja, resultado.requisito, false)}>
                      <Icono nombre="x" tam={16} /> No cumple
                    </button>
                  </>
                ) : (
                  <>
                    {/* El sistema ya decidió: se está de acuerdo o no con esa decisión. */}
                    <span className="small muted">¿Está de acuerdo con el resultado del sistema?</span>
                    <button className="btn btn-ok" type="button" onClick={() => onRevisar?.(resultado.hoja, resultado.requisito, resultado.cumple!)}>
                      <Icono nombre="check" tam={16} /> De acuerdo
                    </button>
                    <button className="btn btn-bad" type="button" onClick={() => onRevisar?.(resultado.hoja, resultado.requisito, !resultado.cumple)}>
                      <Icono nombre="x" tam={16} /> En desacuerdo
                    </button>
                  </>
                )}
              </>
            ) : (
              <>
                <span className="small">
                  Usted decidió: <strong>{decision ? 'Cumple' : 'No cumple'}</strong>
                </span>
                <button className="btn btn-secondary" type="button" onClick={() => onRevisar?.(resultado.hoja, resultado.requisito, undefined)}>
                  <Icono nombre="deshacer" tam={16} /> Deshacer decisión
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
