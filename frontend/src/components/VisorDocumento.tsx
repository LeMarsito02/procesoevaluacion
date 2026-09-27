import { useEffect, useRef } from 'react'
import type { ResultadoRequisito } from '../api'
import { useDialogo } from '../dialogo'
import { claveRevision, ETIQUETA_ESTADO, esPendiente, estadoDe, type Revisiones } from '../estado'
import { REQUISITO_POR_NUMERO } from '../requisitos'
import { conGlosario } from '../glosario'
import Icono from './Icono'
import ExplicacionIA from './ExplicacionIA'
import Motivos from './Motivos'

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
}

export default function VisorDocumento({ url, archivo, evaluacionId, proponenteId, resultado, revisiones, onRevisar, onCerrar }: Props) {
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
            <h2 className="serif" style={{ fontSize: 19, marginTop: 4 }}>
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
            {!onRevisar ? (
              <span className="small muted">
                {decision === undefined ? 'Solo lectura' : <>Decisión registrada: <strong>{decision ? 'Cumple' : 'No cumple'}</strong></>}
              </span>
            ) : decision === undefined ? (
              <>
                <span className="small muted">{esPendiente(estado) ? 'Después de revisar el documento:' : '¿Está de acuerdo con el resultado?'}</span>
                <button className="btn btn-ok" type="button" onClick={() => onRevisar?.(resultado.hoja, resultado.requisito, true)}>
                  <Icono nombre="check" tam={16} /> Cumple
                </button>
                <button className="btn btn-bad" type="button" onClick={() => onRevisar?.(resultado.hoja, resultado.requisito, false)}>
                  <Icono nombre="x" tam={16} /> No cumple
                </button>
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
