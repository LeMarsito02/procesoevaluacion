import { useEffect, useRef, useState, type FormEvent } from 'react'
import type { ResultadoRequisito } from '../api'
import { buscarEnDocumento, paginaDelDocumento } from '../evaluaciones'
import { mensajeDe } from '../http'
import { useDialogo } from '../dialogo'
import { claveRevision, ETIQUETA_ESTADO, esPendiente, estadoDe, type Revisiones } from '../estado'
import { REQUISITO_POR_NUMERO } from '../requisitos'
import { conGlosario } from '../glosario'
import Icono from './Icono'
import ExplicacionIA from './ExplicacionIA'
import Motivos from './Motivos'

/** El navegador no muestra un PDF dentro de la página: tabletas y teléfonos
 * (Chrome en Android, Safari en iPad y iPhone). Ahí el marco queda en blanco. */
function sinVisorDePdf(): boolean {
  const n = navigator as Navigator & { pdfViewerEnabled?: boolean }
  if (n.pdfViewerEnabled === false) return true
  const agente = navigator.userAgent
  return /Android|iPhone|iPad|iPod/i.test(agente) || (/Macintosh/.test(agente) && navigator.maxTouchPoints > 1)
}

/** El documento página por página, como imágenes que dibuja el servidor. */
function PaginasDocumento({
  evaluacionId, proponenteId, archivo, pagina, onPagina,
}: { evaluacionId: string; proponenteId: string; archivo: string; pagina: number; onPagina: (n: number) => void }) {
  const [imagen, setImagen] = useState<string | null>(null)
  const [paginas, setPaginas] = useState(1)
  const [zoom, setZoom] = useState(1)
  // Qué página y con qué nitidez está cargada (o falló): lo demás está en camino.
  const [lista, setLista] = useState<string | null>(null)
  const [error, setError] = useState<{ clave: string; texto: string } | null>(null)
  // Más resolución al acercar, para que la letra pequeña se lea.
  const nitida = zoom > 1
  const clave = `${archivo}|${pagina}|${nitida}`
  const cargando = lista !== clave && error?.clave !== clave

  useEffect(() => {
    let vigente = true
    let url: string | null = null
    const esta = `${archivo}|${pagina}|${nitida}`
    paginaDelDocumento(evaluacionId, proponenteId, archivo, pagina, nitida ? 160 : 110)
      .then((r) => {
        if (!vigente) return
        url = URL.createObjectURL(r.blob)
        setImagen(url)
        setPaginas(r.paginas)
        setLista(esta)
      })
      .catch((e) => vigente && setError({ clave: esta, texto: mensajeDe(e, 'No se pudo mostrar la página.') }))
    return () => {
      vigente = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [evaluacionId, proponenteId, archivo, pagina, nitida])

  return (
    <div className="visor-paginas">
      <div className="visor-paginas-barra">
        <button className="btn btn-secondary btn-sm" type="button" disabled={pagina <= 1} onClick={() => onPagina(pagina - 1)}>
          ‹ Anterior
        </button>
        <span className="small">
          Página {pagina} de {paginas}
        </span>
        <button className="btn btn-secondary btn-sm" type="button" disabled={pagina >= paginas} onClick={() => onPagina(pagina + 1)}>
          Siguiente ›
        </button>
        <span style={{ flex: 1 }} />
        <button className="btn btn-ghost btn-sm" type="button" disabled={zoom <= 1} onClick={() => setZoom((z) => Math.max(1, z - 0.5))} aria-label="Alejar">
          −
        </button>
        <span className="small">{Math.round(zoom * 100)} %</span>
        <button className="btn btn-ghost btn-sm" type="button" disabled={zoom >= 3} onClick={() => setZoom((z) => Math.min(3, z + 0.5))} aria-label="Acercar">
          +
        </button>
      </div>
      <div className="visor-paginas-hoja">
        {error?.clave === clave ? (
          <div className="callout callout-bad">{error.texto}</div>
        ) : imagen ? (
          <img src={imagen} alt={`Página ${pagina} de ${archivo.split('/').pop()}`} style={{ width: `${zoom * 100}%`, opacity: cargando ? 0.5 : 1 }} />
        ) : (
          <span className="spinner oscuro" />
        )}
      </div>
    </div>
  )
}

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

  // Buscador propio: el del navegador (Ctrl+F) solo funciona con el foco dentro
  // del PDF y no encuentra nada en las páginas escaneadas, que son casi todas.
  const puedeBuscar = Boolean(evaluacionId && proponenteId)
  const campo = useRef<HTMLInputElement>(null)
  const [consulta, setConsulta] = useState('')
  const [hallazgos, setHallazgos] = useState<{ pagina: number; fragmento: string }[] | null>(null)
  const [actual, setActual] = useState(-1)
  const [buscando, setBuscando] = useState(false)
  const [errorBusqueda, setErrorBusqueda] = useState<string | null>(null)
  const pagina = actual >= 0 && hallazgos ? hallazgos[actual]?.pagina : undefined
  // En tabletas y teléfonos el documento se muestra página por página, como imágenes.
  const [porPaginas] = useState(() => puedeBuscar && sinVisorDePdf())
  // La página que se mira; cuando la búsqueda señala otra, se salta a esa.
  const [vista, setVista] = useState<{ n: number; deBusqueda: number | undefined }>({ n: 1, deBusqueda: undefined })
  if (pagina !== vista.deBusqueda) setVista({ n: pagina ?? vista.n, deBusqueda: pagina })
  const paginaVista = vista.n
  const setPaginaVista = (n: number) => setVista((v) => ({ ...v, n }))

  function ir(indice: number) {
    if (!hallazgos?.length) return
    setActual(((indice % hallazgos.length) + hallazgos.length) % hallazgos.length)
  }

  async function buscar(e?: FormEvent) {
    e?.preventDefault()
    const q = consulta.trim()
    if (!puedeBuscar || q.length < 2) return
    setBuscando(true)
    setErrorBusqueda(null)
    try {
      const encontrados = await buscarEnDocumento(evaluacionId!, proponenteId!, archivo, q)
      setHallazgos(encontrados)
      setActual(encontrados.length ? 0 : -1)
    } catch (err) {
      setErrorBusqueda(mensajeDe(err, 'No se pudo buscar en el documento.'))
    } finally {
      setBuscando(false)
    }
  }

  useEffect(() => {
    function tecla(e: KeyboardEvent) {
      if (e.key === 'Escape') onCerrar()
      const ctrl = e.ctrlKey || e.metaKey
      if (puedeBuscar && ctrl && e.key.toLowerCase() === 'f') {
        e.preventDefault()
        campo.current?.focus()
        campo.current?.select()
      } else if (ctrl && e.key.toLowerCase() === 'g' && hallazgos?.length) {
        e.preventDefault()
        setActual((a) => (((e.shiftKey ? a - 1 : a + 1) % hallazgos.length) + hallazgos.length) % hallazgos.length)
      }
    }
    window.addEventListener('keydown', tecla)
    return () => window.removeEventListener('keydown', tecla)
  }, [onCerrar, puedeBuscar, hallazgos])

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
          {puedeBuscar && (
            <div className="visor-buscar">
              <form onSubmit={buscar} role="search">
                <Icono nombre="buscar" tam={15} />
                <input
                  ref={campo}
                  type="search"
                  value={consulta}
                  onChange={(e) => {
                    setConsulta(e.target.value)
                    setHallazgos(null)
                    setActual(-1)
                  }}
                  placeholder="Buscar en el documento (también en las páginas escaneadas)"
                  aria-label="Buscar en el documento"
                />
                {hallazgos && hallazgos.length > 0 && (
                  <>
                    <span className="small muted">
                      {actual + 1} de {hallazgos.length}{hallazgos.length >= 100 ? '+' : ''}
                    </span>
                    <button className="btn btn-ghost btn-sm" type="button" onClick={() => ir(actual - 1)} aria-label="Anterior">
                      ‹
                    </button>
                    <button className="btn btn-ghost btn-sm" type="button" onClick={() => ir(actual + 1)} aria-label="Siguiente">
                      ›
                    </button>
                  </>
                )}
                <button className="btn btn-secondary btn-sm" type="submit" disabled={buscando || consulta.trim().length < 2}>
                  {buscando ? <span className="spinner oscuro" /> : 'Buscar'}
                </button>
              </form>
              {errorBusqueda && <div className="small" style={{ color: 'var(--bad)' }}>{errorBusqueda}</div>}
              {hallazgos && hallazgos.length === 0 && <div className="small muted">No aparece en el documento.</div>}
              {pagina !== undefined && (
                <div className="small visor-fragmento">
                  <strong>Página {pagina}:</strong> {hallazgos![actual].fragmento}
                </div>
              )}
            </div>
          )}
          {/* La página cambia el fragmento #page=N; el key vuelve a abrir el PDF ahí. */}
          {porPaginas ? (
            <PaginasDocumento
              evaluacionId={evaluacionId!}
              proponenteId={proponenteId!}
              archivo={archivo}
              pagina={paginaVista}
              onPagina={setPaginaVista}
            />
          ) : (
            <iframe key={pagina ?? 0} title={archivo} src={pagina ? `${url}#page=${pagina}` : url} />
          )}
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
