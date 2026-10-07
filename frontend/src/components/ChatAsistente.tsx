import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import {
  CONSULTAS,
  estadoAsistente,
  nuevaConversacion,
  preguntar,
  verConversacion,
  type Conversacion,
  type Fuente,
  type Mensaje,
  type OpcionEvaluacion,
} from '../asistente'
import { mensajeDe } from '../http'
import { navegar } from '../rutas'
import { useSesion } from '../sesion'
import Icono from './Icono'

const SUGERENCIAS = [
  { corto: 'Cómo va la evaluación', pregunta: '¿Cómo va la evaluación?' },
  { corto: 'Qué me falta por revisar', pregunta: '¿Qué me falta por revisar?' },
  { corto: 'Proponentes que no cumplen', pregunta: '¿Qué proponentes tienen requisitos que no cumplen y por qué?' },
  { corto: 'Qué se verifica', pregunta: '¿Qué requisitos se verifican en esta evaluación?' },
]

/** Negritas y código en línea. Se construyen elementos, nunca HTML: lo que
 * escribe el modelo no puede inyectar marcado en la página. */
function enLinea(texto: string): ReactNode[] {
  return texto.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((parte, i) => {
    if (parte.startsWith('**') && parte.endsWith('**') && parte.length > 4) return <strong key={i}>{parte.slice(2, -2)}</strong>
    if (parte.startsWith('`') && parte.endsWith('`') && parte.length > 2) return <code key={i}>{parte.slice(1, -1)}</code>
    return <Fragment key={i}>{parte}</Fragment>
  })
}

/** Texto del asistente con el formato mínimo que usa: párrafos, títulos y listas. */
function Texto({ contenido }: { contenido: string }) {
  const bloques: ReactNode[] = []
  let lista: { ordenada: boolean; items: string[] } | null = null
  const cerrarLista = () => {
    if (!lista) return
    const items = lista.items.map((t, i) => <li key={i}>{enLinea(t)}</li>)
    bloques.push(lista.ordenada ? <ol key={bloques.length}>{items}</ol> : <ul key={bloques.length}>{items}</ul>)
    lista = null
  }
  for (const linea of contenido.split('\n')) {
    const vineta = /^\s*[-*•]\s+(.*)$/.exec(linea)
    const numero = /^\s*\d+[.)]\s+(.*)$/.exec(linea)
    const titulo = /^#{1,4}\s+(.*)$/.exec(linea)
    const item = vineta ?? numero
    if (item) {
      const ordenada = !vineta
      if (lista && lista.ordenada !== ordenada) cerrarLista()
      lista ??= { ordenada, items: [] }
      lista.items.push(item[1])
      continue
    }
    cerrarLista()
    if (titulo) bloques.push(<p key={bloques.length} className="chat-titulo">{enLinea(titulo[1])}</p>)
    else if (linea.trim()) bloques.push(<p key={bloques.length}>{enLinea(linea)}</p>)
  }
  cerrarLista()
  return <>{bloques}</>
}

function Fuentes({ fuentes, actual }: { fuentes: Fuente[]; actual?: string }) {
  // Dentro de una evaluación no se enlaza a ella misma.
  const otras = fuentes.filter((f) => f.evaluacion_id !== actual)
  if (otras.length === 0) return null
  return (
    <div className="chat-fuentes">
      <span className="small muted">Verifique en:</span>
      {otras.map((f) => (
        <a
          key={f.etiqueta}
          className="chat-fuente"
          href={`/evaluaciones/${f.evaluacion_id}`}
          onClick={(e) => {
            e.preventDefault()
            navegar(`/evaluaciones/${f.evaluacion_id}`)
          }}
        >
          <Icono nombre="documento" tam={13} /> {f.etiqueta}
        </a>
      ))}
    </div>
  )
}

interface Props {
  /** Chat abierto dentro de una evaluación: conversa solo sobre ella, sin
   * lista de conversaciones ni selector. */
  evaluacionFija?: { id: string; etiqueta: string }
  onCerrar?: () => void
}

/** El asistente de consulta: como página completa (con conversaciones y
 * selector de evaluación) o como panel dentro de una evaluación. */
export default function ChatAsistente({ evaluacionFija, onCerrar }: Props) {
  const fija = evaluacionFija?.id
  const [conversaciones, setConversaciones] = useState<Conversacion[]>([])
  const [opciones, setOpciones] = useState<OpcionEvaluacion[]>([])
  const [alcance, setAlcance] = useState<string>(fija ?? '')
  const [activa, setActiva] = useState<string | null>(null)
  const [mensajes, setMensajes] = useState<Mensaje[]>([])
  const [texto, setTexto] = useState('')
  const [aviso, setAviso] = useState('')
  const [habilitado, setHabilitado] = useState(true)
  const [escribiendo, setEscribiendo] = useState(false)
  const [consultando, setConsultando] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)
  const final = useRef<HTMLDivElement>(null)
  const campo = useRef<HTMLTextAreaElement>(null)
  const corte = useRef<AbortController | null>(null)
  const nombre = useSesion()?.usuario.nombre_completo.split(' ')[0] ?? ''

  useEffect(() => {
    let vigente = true
    estadoAsistente(fija)
      .then(async (e) => {
        if (!vigente) return
        setConversaciones(e.conversaciones)
        setOpciones(e.evaluaciones)
        setAviso(e.aviso)
        setHabilitado(e.habilitado)
        // Dentro de una evaluación se retoma la última conversación sobre ella.
        if (fija && e.conversaciones.length > 0) {
          const c = await verConversacion(e.conversaciones[0].id)
          if (!vigente) return
          setActiva(c.id)
          setMensajes(c.mensajes)
        }
      })
      .catch((e: unknown) => vigente && setError(mensajeDe(e)))
      .finally(() => vigente && setCargando(false))
    return () => {
      vigente = false
      corte.current?.abort()
    }
  }, [fija])

  useEffect(() => {
    final.current?.scrollIntoView({ block: 'end' })
  }, [mensajes, consultando])

  async function abrir(id: string) {
    if (escribiendo || id === activa) return
    setError(null)
    try {
      const c = await verConversacion(id)
      setActiva(id)
      setMensajes(c.mensajes)
      setAlcance(fija ?? c.evaluacion_id ?? '')
      campo.current?.focus()
    } catch (e) {
      setError(mensajeDe(e))
    }
  }

  function nueva() {
    if (escribiendo) return
    setActiva(null)
    setMensajes([])
    setError(null)
    campo.current?.focus()
  }

  async function enviar(pregunta: string) {
    const limpia = pregunta.trim()
    if (!limpia || escribiendo) return
    setError(null)
    setEscribiendo(true)
    setTexto('')
    setMensajes((l) => [
      ...l,
      { id: -Date.now(), rol: 'usuario', contenido: limpia, fuentes: [] },
      { id: -Date.now() - 1, rol: 'asistente', contenido: '', fuentes: [] },
    ])
    // Cambia solo el último mensaje, que es la respuesta que se está escribiendo.
    const enRespuesta = (cambio: (m: Mensaje) => Mensaje) => setMensajes((l) => l.map((m, i) => (i === l.length - 1 ? cambio(m) : m)))
    const sobre = alcance || null
    try {
      let id = activa
      if (!id) {
        const c = await nuevaConversacion(sobre)
        id = c.id
        setActiva(id)
        setConversaciones((l) => [{ ...c, titulo: limpia.slice(0, 80) }, ...l])
      }
      corte.current = new AbortController()
      await preguntar(
        id,
        limpia,
        sobre,
        (e) => {
          if (e.tipo === 'texto') {
            setConsultando(null)
            enRespuesta((m) => ({ ...m, contenido: m.contenido + e.texto }))
          } else if (e.tipo === 'consulta') setConsultando(CONSULTAS[e.nombre] ?? 'Consultando')
          else if (e.tipo === 'espera') setConsultando('En fila: hay otras consultas antes de la suya')
          else if (e.tipo === 'fuentes') enRespuesta((m) => ({ ...m, fuentes: e.fuentes }))
          else if (e.tipo === 'error') setError(e.texto)
        },
        corte.current.signal,
      )
    } catch (e) {
      if (!corte.current?.signal.aborted) setError(mensajeDe(e))
    } finally {
      setEscribiendo(false)
      setConsultando(null)
      // Una respuesta que quedó vacía (error o detenida) no se deja como burbuja en blanco.
      setMensajes((l) => (l.length && l[l.length - 1].rol === 'asistente' && !l[l.length - 1].contenido.trim() ? l.slice(0, -1) : l))
      campo.current?.focus()
    }
  }

  const vacia = mensajes.length === 0

  const avisos = (
    <>
      {error && (
        <div className="callout callout-bad chat-error" role="alert">
          <Icono nombre="alerta" />
          <div>{error}</div>
        </div>
      )}
      {!habilitado && !cargando && (
        <div className="callout callout-warn chat-error" role="status">
          <Icono nombre="info" />
          <div>El asistente no está habilitado en esta instalación.</div>
        </div>
      )}
    </>
  )

  const entrada = (
    <form
      className="chat-entrada"
      onSubmit={(e) => {
        e.preventDefault()
        void enviar(texto)
      }}
    >
      <label htmlFor="chat-pregunta" className="sr-only">
        Su pregunta
      </label>
      <textarea
        id="chat-pregunta"
        ref={campo}
        rows={1}
        maxLength={2000}
        placeholder={fija ? 'Pregunte sobre esta evaluación…' : vacia ? '¿Qué quiere saber de sus evaluaciones?' : 'Escriba su siguiente pregunta…'}
        value={texto}
        disabled={!habilitado}
        autoFocus
        onChange={(e) => setTexto(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            void enviar(texto)
          }
        }}
      />
      <div className="chat-entrada-pie">
        {fija ? (
          <span className="small muted">Enter para enviar</span>
        ) : (
          <label className="chat-alcance">
            <Icono nombre="carpeta" tam={15} />
            <span className="sr-only">Evaluación sobre la que pregunta</span>
            <select value={alcance} onChange={(e) => setAlcance(e.target.value)} disabled={escribiendo}>
              <option value="">Todas mis evaluaciones</option>
              {opciones.map((o) => (
                <option key={o.id} value={o.id} title={o.objeto}>
                  {o.etiqueta}
                </option>
              ))}
            </select>
          </label>
        )}
        {escribiendo ? (
          <button type="button" className="chat-enviar" data-detener onClick={() => corte.current?.abort()} aria-label="Detener la respuesta" title="Detener">
            <span className="chat-cuadro" aria-hidden="true" />
          </button>
        ) : (
          <button type="submit" className="chat-enviar" disabled={!habilitado || !texto.trim()} aria-label="Enviar la pregunta" title="Enviar">
            <Icono nombre="flecha" tam={18} />
          </button>
        )}
      </div>
    </form>
  )

  const sugerencias = habilitado && (
    <div className="chat-sugerencias">
      {SUGERENCIAS.map((s) => (
        <button key={s.corto} type="button" className="chat-sugerencia" onClick={() => void enviar(s.pregunta)}>
          {s.corto}
        </button>
      ))}
    </div>
  )

  const hilo = (
    <div className="chat-mensajes" role="log" aria-live="polite" aria-busy={escribiendo}>
      <div className="chat-columna">
        {mensajes.map((m, i) => {
          const ultimo = i === mensajes.length - 1
          return (
            <article key={m.id} className="chat-mensaje" data-rol={m.rol}>
              <span className="sr-only">{m.rol === 'usuario' ? 'Usted' : 'Asistente'}:</span>
              {m.rol === 'usuario' ? (
                <p>{m.contenido}</p>
              ) : (
                <>
                  <span className="chat-sello chat-sello-chico" aria-hidden="true">
                    <Icono nombre="chispa" tam={15} />
                  </span>
                  <div className="chat-cuerpo">
                    <Texto contenido={m.contenido} />
                    {ultimo && escribiendo && (
                      <p className="chat-estado" role="status">
                        <span className="chat-puntos" aria-hidden="true">
                          <i />
                          <i />
                          <i />
                        </span>
                        {consultando ?? (m.contenido ? 'Escribiendo' : 'Pensando')}…
                      </p>
                    )}
                    <Fuentes fuentes={m.fuentes} actual={fija} />
                  </div>
                </>
              )}
            </article>
          )
        })}
        <div ref={final} />
      </div>
    </div>
  )

  if (evaluacionFija) {
    return (
      <aside className="chat-panel" role="dialog" aria-label={`Asistente · ${evaluacionFija.etiqueta}`}>
        <header className="chat-panel-cabecera">
          <span className="chat-sello chat-sello-chico" aria-hidden="true">
            <Icono nombre="chispa" tam={15} />
          </span>
          <div className="chat-panel-titulo">
            <strong>Asistente</strong>
            <span className="small muted">{evaluacionFija.etiqueta}</span>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={nueva} disabled={escribiendo || vacia} title="Empezar otra conversación">
            <Icono nombre="mas" tam={15} /> Nueva
          </button>
          <button type="button" className="btn btn-ghost btn-icon" onClick={onCerrar} aria-label="Cerrar el asistente">
            <Icono nombre="x" />
          </button>
        </header>
        {vacia ? (
          <div className="chat-panel-inicio">
            <p className="chat-panel-saludo">{nombre ? `¿Qué quiere saber de esta evaluación, ${nombre}?` : '¿Qué quiere saber de esta evaluación?'}</p>
            {sugerencias}
          </div>
        ) : (
          hilo
        )}
        <div className="chat-pie">
          <div className="chat-columna">
            {avisos}
            {entrada}
            <p className="chat-aviso small muted">{aviso}</p>
          </div>
        </div>
      </aside>
    )
  }

  return (
    <main className="chat">
      <aside className="chat-lateral" aria-label="Conversaciones">
        <button type="button" className="chat-nueva" onClick={nueva} disabled={escribiendo}>
          <Icono nombre="mas" tam={16} /> Nueva conversación
        </button>
        <p className="chat-rotulo">Recientes</p>
        <nav className="chat-lista">
          {conversaciones.map((c) => (
            <button key={c.id} type="button" className="chat-item" aria-current={c.id === activa} onClick={() => void abrir(c.id)} disabled={escribiendo}>
              {c.titulo || 'Conversación sin título'}
            </button>
          ))}
          {!cargando && conversaciones.length === 0 && <p className="small muted chat-sin">Sus conversaciones aparecerán aquí.</p>}
        </nav>
      </aside>

      {vacia ? (
        <section className="chat-principal chat-inicio" aria-label="Nueva conversación con el asistente">
          <div className="chat-columna">
            <h1 className="chat-saludo">
              <span className="chat-sello" aria-hidden="true">
                <Icono nombre="chispa" tam={24} />
              </span>
              {nombre ? `¿En qué le ayudo, ${nombre}?` : '¿En qué le ayudo?'}
            </h1>
            {avisos}
            {entrada}
            {sugerencias}
            <p className="chat-aviso small muted">{aviso}</p>
          </div>
        </section>
      ) : (
        <section className="chat-principal" aria-label="Conversación con el asistente">
          {hilo}
          <div className="chat-pie">
            <div className="chat-columna">
              {avisos}
              {entrada}
              <p className="chat-aviso small muted">{aviso}</p>
            </div>
          </div>
        </section>
      )}
    </main>
  )
}
