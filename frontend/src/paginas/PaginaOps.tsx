import { useCallback, useEffect, useState } from 'react'
import Icono from '../components/Icono'
import { useDialogos } from '../dialogos'
import { formatFechaCorta, formatPesos } from '../format'
import { mensajeDe } from '../http'
import {
  agregarDocumentosOps,
  confirmarOps,
  decidirOps,
  eliminarOps,
  NOMBRE_ESTADO,
  NOMBRE_NIVEL,
  NOMBRE_POSGRADO,
  reabrirOps,
  reanalizarOps,
  urlCertificado,
  urlDocumento,
  verOps,
  type DecisionesOps,
  type DetalleOps,
  corregirDatosOps,
  type DocumentoOps,
  type EstadoDocumento,
  type PeriodoNuevo,
  type PeriodoOps,
  type Posgrado,
} from '../ops'
import { navegar } from '../rutas'
import { puedeCrearProcesos, useSesion } from '../sesion'
import { ZonaArchivos } from './PaginaNuevaOps'

const ESTADO_DOCUMENTO: Record<EstadoDocumento, { nombre: string; pill: string }> = {
  cumple: { nombre: 'Cumple', pill: 'cumple' },
  falta: { nombre: 'Falta', pill: 'error' },
  revision: { nombre: 'Por revisar', pill: 'revisar' },
  no_cumple: { nombre: 'No cumple', pill: 'error' },
  no_aplica: { nombre: 'No aplica', pill: 'no_aplica' },
}
const ESTADO_PERIODO: Record<PeriodoOps['estado'], { nombre: string; pill: string }> = {
  cuenta: { nombre: 'Cuenta', pill: 'cumple' },
  sobra: { nombre: 'Sobra', pill: 'revisar' },
  descartado: { nombre: 'No suma', pill: 'no_aplica' },
  retirado: { nombre: 'Retirado', pill: 'no_aplica' },
}

/** Una prestación de servicios: lo que leyó el sistema, lo que decide la
 * persona y el certificado de idoneidad. */
export default function PaginaOps({ id }: { id: string }) {
  const { usuario } = useSesion()!
  const { confirmar } = useDialogos()
  const [d, setD] = useState<DetalleOps | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [datos, setDatos] = useState(false)

  useEffect(() => {
    verOps(id)
      .then(setD)
      .catch((e: unknown) => setError(mensajeDe(e, 'No se encontró la contratación.')))
  }, [id])

  // Mientras el trabajador lee los documentos se consulta el avance.
  const leyendo = d?.estado === 'pendiente' || d?.estado === 'analizando'
  useEffect(() => {
    if (!leyendo) return
    const t = window.setInterval(() => {
      verOps(id)
        .then(setD)
        .catch(() => undefined)
    }, 3000)
    return () => window.clearInterval(t)
  }, [leyendo, id])

  useEffect(() => {
    document.title = [d?.contratista_nombre, 'OPS', 'MiEvaluador'].filter(Boolean).join(' · ')
  }, [d?.contratista_nombre])

  const hacer = useCallback(async (accion: () => Promise<DetalleOps>) => {
    setOcupado(true)
    setError(null)
    try {
      setD(await accion())
    } catch (e) {
      setError(mensajeDe(e))
    } finally {
      setOcupado(false)
    }
  }, [])
  const decidir = useCallback((cambios: DecisionesOps) => hacer(() => decidirOps(id, cambios)), [hacer, id])

  if (!d) {
    return (
      <main className="page">
        {error ? (
          <div className="callout callout-bad" role="alert">
            <Icono nombre="alerta" />
            <div>{error}</div>
          </div>
        ) : (
          <div className="vacio">
            <span className="spinner oscuro" />
          </div>
        )}
      </main>
    )
  }

  const editable = puedeCrearProcesos(usuario) && d.estado === 'lista'
  const analizada = d.experiencia !== undefined

  async function eliminar() {
    if (!(await confirmar({ titulo: `¿Eliminar la OPS de ${d!.contratista_nombre}?`, mensaje: 'Se borran sus documentos y lo revisado. No se puede deshacer.', aceptar: 'Eliminar' }))) return
    try {
      await eliminarOps(id)
      navegar('/ops', true)
    } catch (e) {
      setError(mensajeDe(e))
    }
  }

  return (
    <main className="page ops">
      <div className="page-head">
        <div>
          <div className="eyebrow">Prestación de servicios{d.referencia ? ` · ${d.referencia}` : ''}</div>
          <h1>{d.contratista_nombre || 'Contratista por identificar'}</h1>
          <p>
            {d.contratista_cedula ? `C.C. ${Number(d.contratista_cedula).toLocaleString('es-CO')} · ` : ''}
            <span className="pill" data-estado-ops={d.estado}>{NOMBRE_ESTADO[d.estado]}</span>
            {d.confirmada_por && ` por ${d.confirmada_por}`}
          </p>
          {d.estudio?.objeto && <p className="small muted ops-objeto">{d.estudio.objeto}</p>}
          {(editable || d.estado === 'error') && puedeCrearProcesos(usuario) && (
            <button type="button" className="enlace small" onClick={() => setDatos(true)}>
              Corregir los datos del contratista
            </button>
          )}
        </div>
        <div className="page-head-acciones">
          {analizada && d.perfil && (
            <a className="btn btn-primary" href={urlCertificado(id)}>
              <Icono nombre="descargar" /> Certificado de idoneidad
            </a>
          )}
          {editable && (
            <button type="button" className="btn btn-ok" disabled={ocupado} onClick={() => void hacer(() => confirmarOps(id))}>
              <Icono nombre="check" /> Confirmar
            </button>
          )}
          {d.estado === 'confirmada' && puedeCrearProcesos(usuario) && (
            <button type="button" className="btn btn-secondary" disabled={ocupado} onClick={() => void hacer(() => reabrirOps(id))}>
              <Icono nombre="deshacer" /> Reabrir
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="callout callout-bad" role="alert" style={{ marginBottom: 16 }}>
          <Icono nombre="alerta" />
          <div>{error}</div>
        </div>
      )}
      {leyendo && (
        <div className="callout callout-info" role="status" style={{ marginBottom: 16 }}>
          <span className="spinner oscuro" />
          <div>
            <strong>{d.estado === 'pendiente' ? 'En fila para leer los documentos.' : 'Leyendo los documentos…'}</strong>
            <div className="small">Suele tardar menos de un minuto; los documentos escaneados toman más. Puede dejar esta página abierta.</div>
          </div>
        </div>
      )}
      {d.estado === 'error' && (
        <div className="callout callout-bad" role="alert" style={{ marginBottom: 16 }}>
          <Icono nombre="alerta" />
          <div>
            {d.error || 'No se pudieron leer los documentos.'}{' '}
            <button type="button" className="enlace" onClick={() => void hacer(() => reanalizarOps(id))}>
              Intentar de nuevo
            </button>
          </div>
        </div>
      )}

      {analizada && (
        <>
          <Resumen d={d} />
          {(d.revisiones?.length ?? 0) > 0 && (
            <div className="callout callout-warn" style={{ marginBottom: 20 }}>
              <Icono nombre="alerta" />
              <div>
                <strong>Para revisar</strong>
                <ul>
                  {d.revisiones!.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          <Perfil d={d} id={id} editable={editable} ocupado={ocupado} onDecidir={decidir} />
          <Experiencia d={d} id={id} editable={editable} ocupado={ocupado} onDecidir={decidir} />
          <Documentos d={d} id={id} editable={editable} ocupado={ocupado} onDecidir={decidir} />
        </>
      )}

      <Archivos d={d} id={id} editable={editable || d.estado === 'error'} ocupado={ocupado} onAgregar={(origen, archivos) => hacer(() => agregarDocumentosOps(id, origen, archivos))} />

      {datos && (
        <DatosContratista
          d={d}
          onCerrar={() => setDatos(false)}
          onGuardar={async (cambios) => {
            await hacer(() => corregirDatosOps(id, cambios))
            setDatos(false)
          }}
        />
      )}

      <div className="ops-pie small muted">
        Creada el {formatFechaCorta(d.creada_en.slice(0, 10))} por {d.creada_por}
        {d.segundos != null && ` · documentos leídos en ${d.segundos < 60 ? `${Math.round(d.segundos)} s` : `${Math.round(d.segundos / 60)} min`}`}
        {editable && (
          <>
            {' · '}
            <button type="button" className="enlace" disabled={ocupado} onClick={() => void hacer(() => reanalizarOps(id))}>
              Volver a leer los documentos
            </button>
          </>
        )}
        {d.estado !== 'confirmada' && puedeCrearProcesos(usuario) && (
          <>
            {' · '}
            <button type="button" className="enlace" style={{ color: 'var(--bad)' }} onClick={() => void eliminar()}>
              Eliminar
            </button>
          </>
        )}
      </div>
    </main>
  )
}

interface PropsSeccion {
  d: DetalleOps
  id: string
  editable: boolean
  ocupado: boolean
  onDecidir: (cambios: DecisionesOps) => Promise<void>
}

function Resumen({ d }: { d: DetalleOps }) {
  const documentos = d.documentos ?? []
  const alDia = documentos.length - (d.documentos_pendientes ?? 0)
  const conclusion =
    d.cumple == null ? { texto: 'Por revisar', tono: 'revisar' } : d.cumple ? { texto: 'Cumple el perfil', tono: 'cumple' } : { texto: 'No cumple el perfil', tono: 'error' }
  const honorarios = d.perfil?.honorarios_mensuales ?? 0
  return (
    <div className="ops-resumen">
      <div className="ops-dato" data-tono={conclusion.tono}>
        <span>Conclusión</span>
        <strong>{conclusion.texto}</strong>
        <small>{d.estado === 'confirmada' ? 'Confirmada por una persona' : 'Preliminar: la decide una persona'}</small>
      </div>
      <div className="ops-dato">
        <span>Experiencia que cuenta</span>
        <strong>{d.total}</strong>
        <small>
          {d.perfil
            ? d.perfil.anios_maximos != null
              ? `El perfil pide entre ${d.perfil.anios_minimos} y ${d.perfil.anios_maximos} años`
              : `El perfil pide mínimo ${d.perfil.anios_minimos} años`
            : 'Falta registrar el perfil'}
        </small>
      </div>
      <div className="ops-dato" data-tono={d.tope != null && honorarios > d.tope ? 'error' : undefined}>
        <span>Honorarios mensuales</span>
        <strong>{honorarios ? formatPesos(honorarios) : '—'}</strong>
        <small>{d.tope != null ? `Tope ${formatPesos(d.tope)} · franja ${d.franja}` : 'Sin tabla de honorarios para verificar el tope'}</small>
      </div>
      <div className="ops-dato" data-tono={d.documentos_pendientes ? 'revisar' : 'cumple'}>
        <span>Documentos</span>
        <strong>
          {alDia} de {documentos.length}
        </strong>
        <small>{d.documentos_pendientes ? `${d.documentos_pendientes} por revisar` : 'Todos al día'}</small>
      </div>
    </div>
  )
}

function Perfil({ d, editable, ocupado, onDecidir }: PropsSeccion) {
  const p = d.perfil
  const [editando, setEditando] = useState(false)
  const [minimo, setMinimo] = useState('')
  const [maximo, setMaximo] = useState('')
  const [especificaMin, setEspecificaMin] = useState('')
  const [especificaMax, setEspecificaMax] = useState('')
  const [posgrado, setPosgrado] = useState<Posgrado>('ninguno')
  const [honorarios, setHonorarios] = useState('')
  const [grado, setGrado] = useState('')
  const [acredita, setAcredita] = useState<Posgrado | ''>('')

  function abrir() {
    setMinimo(p ? String(p.anios_minimos) : '')
    setMaximo(p?.anios_maximos != null ? String(p.anios_maximos) : '')
    setEspecificaMin(p?.especifica_minima ? String(p.especifica_minima) : '')
    setEspecificaMax(p?.especifica_maxima != null ? String(p.especifica_maxima) : '')
    setPosgrado(p?.posgrado ?? 'ninguno')
    setHonorarios(p?.honorarios_mensuales ? String(p.honorarios_mensuales) : '')
    setGrado(d.grado ?? '')
    setAcredita(d.posgrado_corregido ? (d.posgrado ?? '') : '')
    setEditando(true)
  }

  async function guardar() {
    await onDecidir({
      perfil: {
        anios_minimos: Number(minimo),
        anios_maximos: maximo.trim() ? Number(maximo) : null,
        posgrado,
        honorarios_mensuales: Number(honorarios.replace(/\D/g, '')) || 0,
        especifica_minima: Number(especificaMin) || 0,
        especifica_maxima: especificaMax.trim() ? Number(especificaMax) : null,
      },
      ...(grado !== (d.grado ?? '') ? { grado: grado || null } : {}),
      ...(acredita !== (d.posgrado_corregido ? (d.posgrado ?? '') : '') ? { posgrado: acredita } : {}),
    })
    setEditando(false)
  }

  const titulos = (d.titulos ?? []).filter((t) => t.nivel !== 'bachiller')
  const pideEspecifica = !!p && (p.especifica_minima > 0 || p.especifica_maxima != null)

  return (
    <section className="card ops-tarjeta">
      <div className="card-head">
        <div>
          <h2>Perfil y formación</h2>
          <p className="small muted">
            {d.estudio ? (
              <>
                Leído del{' '}
                <a href={urlDocumento(d.id, d.estudio.documento_id)} target="_blank" rel="noreferrer">
                  estudio previo
                </a>
                {p?.corregido && ' y corregido por una persona'}.
              </>
            ) : (
              'No se encontró el estudio previo: registre el perfil.'
            )}
          </p>
        </div>
        {editable && !editando && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={abrir}>
            <Icono nombre="lapiz" tam={15} /> {p ? 'Corregir' : 'Registrar perfil'}
          </button>
        )}
      </div>
      {p?.descripcion && !editando && <blockquote className="ops-cita">«{p.descripcion}»</blockquote>}

      {editando ? (
        <div className="ops-form">
          <h3 className="ops-seccion">Lo que exige el estudio previo</h3>
          <div className="grid-3">
            <div className="field">
              <label htmlFor="pf-min">Años mínimos de experiencia</label>
              <input id="pf-min" className="input" type="number" min={0} step="0.5" value={minimo} onChange={(e) => setMinimo(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="pf-max">Años máximos (vacío si no hay)</label>
              <input id="pf-max" className="input" type="number" min={0} step="0.5" value={maximo} onChange={(e) => setMaximo(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="pf-pos">Posgrado exigido</label>
              <select id="pf-pos" className="input" value={posgrado} onChange={(e) => setPosgrado(e.target.value as Posgrado)}>
                {(Object.keys(NOMBRE_POSGRADO) as Posgrado[]).map((k) => (
                  <option key={k} value={k}>
                    {NOMBRE_POSGRADO[k]}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="pf-emin">Experiencia específica: años mínimos</label>
              <input id="pf-emin" className="input" type="number" min={0} step="0.5" value={especificaMin} onChange={(e) => setEspecificaMin(e.target.value)} />
              <span className="hint">Vacío si el perfil no la pide.</span>
            </div>
            <div className="field">
              <label htmlFor="pf-emax">Experiencia específica: años máximos</label>
              <input id="pf-emax" className="input" type="number" min={0} step="0.5" value={especificaMax} onChange={(e) => setEspecificaMax(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="pf-hon">Honorarios mensuales</label>
              <input id="pf-hon" className="input" inputMode="numeric" value={honorarios} onChange={(e) => setHonorarios(e.target.value)} />
            </div>
          </div>
          <h3 className="ops-seccion" style={{ marginTop: 18 }}>
            Lo que acredita el contratista
          </h3>
          <div className="grid-3">
            <div className="field">
              <label htmlFor="pf-grado">Fecha de grado</label>
              <input id="pf-grado" className="input" type="date" value={grado} onChange={(e) => setGrado(e.target.value)} />
              <span className="hint">La experiencia profesional cuenta desde el grado.</span>
            </div>
            <div className="field">
              <label htmlFor="pf-acr">Posgrado</label>
              <select id="pf-acr" className="input" value={acredita} onChange={(e) => setAcredita(e.target.value as Posgrado | '')}>
                <option value="">El que se leyó de los diplomas</option>
                {(Object.keys(NOMBRE_POSGRADO) as Posgrado[]).map((k) => (
                  <option key={k} value={k}>
                    {NOMBRE_POSGRADO[k]}
                  </option>
                ))}
              </select>
              <span className="hint">Cámbielo si un diploma escaneado no se pudo leer.</span>
            </div>
          </div>
          <div className="dialogo-pie">
            <button type="button" className="btn btn-ghost" onClick={() => setEditando(false)}>
              Cancelar
            </button>
            <button type="button" className="btn btn-primary" disabled={ocupado || !minimo.trim()} onClick={() => void guardar()}>
              Guardar
            </button>
          </div>
        </div>
      ) : (
        <dl className="ops-ficha">
          <div>
            <dt>Experiencia exigida</dt>
            <dd>
              {p ? (p.anios_maximos != null ? `Entre ${p.anios_minimos} y ${p.anios_maximos} años` : `Mínimo ${p.anios_minimos} años`) : '—'}
              {pideEspecifica && (
                <div className="small muted">
                  y específica {p!.especifica_maxima != null ? `entre ${p!.especifica_minima} y ${p!.especifica_maxima} años` : `mínimo ${p!.especifica_minima} años`}
                </div>
              )}
            </dd>
          </div>
          <div>
            <dt>Posgrado</dt>
            <dd>
              {p ? NOMBRE_POSGRADO[p.posgrado] : '—'}
              <div className="small muted">
                Acredita: {NOMBRE_POSGRADO[d.posgrado ?? 'ninguno'].toLowerCase()}
                {d.posgrado_corregido && ' (corregido)'}
              </div>
            </dd>
          </div>
          <div>
            <dt>Valor y plazo</dt>
            <dd>
              {d.estudio?.valor ? formatPesos(d.estudio.valor) : '—'}
              {d.estudio?.plazo_meses ? ` · ${d.estudio.plazo_meses} meses` : ''}
              {d.cdp && (
                <div className="small muted">
                  <a href={urlDocumento(d.id, d.cdp.documento_id)} target="_blank" rel="noreferrer">
                    CDP
                  </a>{' '}
                  por {formatPesos(d.cdp.valor)}
                </div>
              )}
            </dd>
          </div>
          <div>
            <dt>Fecha de grado</dt>
            <dd>
              {d.grado ? formatFechaCorta(d.grado) : 'Sin leer'}
              {d.grado_corregido && <span className="small muted"> · corregida</span>}
              {d.matricula?.fecha && <div className="small muted">Matrícula profesional del {formatFechaCorta(d.matricula.fecha)}</div>}
            </dd>
          </div>
          <div className="ops-ficha-ancha">
            <dt>Formación acreditada</dt>
            <dd>
              {titulos.length === 0 && !d.matricula?.profesion && 'No se leyeron títulos.'}
              {titulos.length === 0 && d.matricula?.profesion && (
                <div>
                  <span className="tag">Profesional</span> {d.matricula.profesion} <span className="small muted">· según su matrícula; el diploma no se pudo leer</span>
                </div>
              )}
              {titulos.map((t, i) => (
                <div key={i}>
                  <span className="tag">{NOMBRE_NIVEL[t.nivel] ?? t.nivel}</span>{' '}
                  {t.nombre || (t.nivel === 'profesional' && d.matricula?.profesion) || 'Título sin nombre legible'}
                  {t.fecha && <span className="small muted"> · {formatFechaCorta(t.fecha)}</span>}
                  {t.declarado && <span className="small ops-motivo"> · declarado en la hoja de vida: confirme el diploma</span>}
                  {t.documento_id && (
                    <>
                      {' '}
                      <a className="small" href={urlDocumento(d.id, t.documento_id, t.pagina)} target="_blank" rel="noreferrer">
                        ver
                      </a>
                    </>
                  )}
                </div>
              ))}
            </dd>
          </div>
        </dl>
      )}
    </section>
  )
}

const PERIODO_VACIO: PeriodoNuevo = { inicio: '', fin: '', entidad: '', referencia: '', relacionada: false }

function Experiencia({ d, editable, ocupado, onDecidir }: PropsSeccion) {
  const filas = d.experiencia ?? []
  // Periodo que se está corrigiendo ('nuevo' = uno que se agrega a mano).
  const [editando, setEditando] = useState<string | null>(null)
  const [borrador, setBorrador] = useState<PeriodoNuevo>(PERIODO_VACIO)
  const pideEspecifica = !!d.perfil && (d.perfil.especifica_minima > 0 || d.perfil.especifica_maxima != null)

  const accion = (f: PeriodoOps) => {
    if (f.estado === 'cuenta') return { texto: 'Retirar', cambio: { incluir: false } }
    if (f.estado === 'sobra') return { texto: 'Conservar', cambio: { incluir: true } }
    if (f.estado === 'retirado') return { texto: 'Volver a contar', cambio: { incluir: null } }
    return null
  }

  function editar(f: PeriodoOps) {
    setBorrador({ inicio: f.inicio, fin: f.fin, entidad: f.entidad, referencia: f.referencia, relacionada: !!f.relacionada })
    setEditando(f.id)
  }

  async function guardar() {
    if (editando === 'nuevo') await onDecidir({ agregar: borrador })
    else if (editando) {
      const f = filas.find((x) => x.id === editando)!
      await onDecidir({
        periodos: {
          [editando]: {
            incluir: f.estado === 'retirado' ? false : f.fijo ? true : null,
            relacionada: borrador.relacionada,
            inicio: borrador.inicio,
            fin: borrador.fin,
            entidad: borrador.entidad,
            referencia: borrador.referencia,
          },
        },
      })
    }
    setEditando(null)
  }

  const formulario = (
    <div className="ops-form ops-form-periodo">
      <div className="grid-2">
        <div className="field">
          <label htmlFor="pe-entidad">Entidad o empresa</label>
          <input id="pe-entidad" className="input" value={borrador.entidad} onChange={(e) => setBorrador({ ...borrador, entidad: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="pe-ref">Contrato o cargo</label>
          <input id="pe-ref" className="input" value={borrador.referencia} onChange={(e) => setBorrador({ ...borrador, referencia: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="pe-inicio">Inicio</label>
          <input id="pe-inicio" className="input" type="date" value={borrador.inicio} onChange={(e) => setBorrador({ ...borrador, inicio: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="pe-fin">Terminación</label>
          <input id="pe-fin" className="input" type="date" value={borrador.fin} onChange={(e) => setBorrador({ ...borrador, fin: e.target.value })} />
        </div>
      </div>
      <label className="ops-check" style={{ marginTop: 12 }}>
        <input type="checkbox" checked={borrador.relacionada} onChange={(e) => setBorrador({ ...borrador, relacionada: e.target.checked })} />
        Es experiencia relacionada con las obligaciones del contrato
      </label>
      <div className="dialogo-pie">
        <button type="button" className="btn btn-ghost" onClick={() => setEditando(null)}>
          Cancelar
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={ocupado || !borrador.inicio || !borrador.fin || borrador.fin < borrador.inicio || !borrador.entidad.trim()}
          onClick={() => void guardar()}
        >
          {editando === 'nuevo' ? 'Agregar periodo' : 'Guardar'}
        </button>
      </div>
    </div>
  )

  return (
    <section className="card ops-tarjeta">
      <div className="card-head">
        <div>
          <h2>Experiencia</h2>
          <p className="small muted">
            En línea y sin traslapes: el tiempo trabajado en un mismo periodo cuenta una sola vez. Meses de 30 días y año de 360.
          </p>
        </div>
        <div className="ops-total">
          <strong>{d.total}</strong>
          <span className="small muted">
            {d.total_leido !== d.total ? `de ${d.total_leido} leídos` : 'en total'}
            {d.relacionada_dias ? ` · ${d.relacionada} relacionada` : ''}
          </span>
        </div>
      </div>
      {pideEspecifica && (
        <p className="small ops-ayuda">
          El perfil pide experiencia específica: marque como <strong>Relacionada</strong> los periodos que la acreditan. Hoy suman {d.relacionada}.
        </p>
      )}
      {filas.length === 0 ? (
        <div className="vacio">No se leyó ningún periodo en las certificaciones. Revise que estén entre los documentos del contratista o agréguelo a mano.</div>
      ) : (
        <div className="tabla-wrap">
          <table className="tabla ops-tabla">
            <thead>
              <tr>
                <th>Entidad y contrato o cargo</th>
                <th>Inicio</th>
                <th>Terminación</th>
                <th>Tiempo que cuenta</th>
                <th>Tipo</th>
                <th>Estado</th>
                {editable && <th aria-label="Acciones" />}
              </tr>
            </thead>
            <tbody>
              {filas.map((f) => {
                const a = accion(f)
                const activa = f.estado === 'cuenta' || f.estado === 'sobra'
                if (editando === f.id)
                  return (
                    <tr key={f.id}>
                      <td colSpan={editable ? 7 : 6}>{formulario}</td>
                    </tr>
                  )
                return (
                  <tr key={f.id} data-apagada={!activa || f.estado === 'sobra'}>
                    <td style={{ maxWidth: 360 }}>
                      <strong>{f.referencia || 'Sin contrato o cargo leído'}</strong>
                      <div className="small muted">
                        {f.entidad || 'Entidad sin leer'}
                        {f.documento_id && (
                          <>
                            {' · '}
                            <a href={urlDocumento(d.id, f.documento_id, f.pagina)} target="_blank" rel="noreferrer">
                              pág. {f.pagina}
                            </a>
                          </>
                        )}
                        {f.manual && ' · agregado a mano'}
                        {f.corregido && !f.manual && ' · corregido'}
                      </div>
                      {f.motivo && <div className="small ops-motivo">{f.motivo}</div>}
                      {f.nota && <div className="small ops-motivo">{f.nota}</div>}
                      {f.abierto && !f.nota && <div className="small ops-motivo">Sin fecha de terminación: se contó hasta que se expidió la certificación.</div>}
                    </td>
                    <td className="small nowrap">
                      {formatFechaCorta(f.inicio)}
                      {f.recortado && f.cuenta_desde && <div className="muted">cuenta desde {formatFechaCorta(f.cuenta_desde)}</div>}
                    </td>
                    <td className="small nowrap">{formatFechaCorta(f.fin)}</td>
                    <td className="small">{f.duracion || '—'}</td>
                    <td>
                      {activa &&
                        (editable ? (
                          <label className="ops-check" title="Sus obligaciones son las mismas del contrato que se va a celebrar">
                            <input
                              type="checkbox"
                              checked={!!f.relacionada}
                              disabled={ocupado}
                              onChange={(e) =>
                                void onDecidir({
                                  periodos: {
                                    [f.id]: {
                                      incluir: f.fijo ? true : null,
                                      relacionada: e.target.checked,
                                      ...(f.corregido ? { inicio: f.inicio, fin: f.fin, entidad: f.entidad, referencia: f.referencia } : {}),
                                    },
                                  },
                                })
                              }
                            />
                            Relacionada
                          </label>
                        ) : (
                          <span className="small">{f.relacionada ? 'Relacionada' : 'Profesional'}</span>
                        ))}
                      {activa && (f.obligaciones_iguales?.length ?? 0) > 0 && (
                        <div className="small muted">
                          Repite {f.obligaciones_iguales!.length === 1 ? 'la obligación' : 'las obligaciones'} {f.obligaciones_iguales!.join(', ')}
                        </div>
                      )}
                    </td>
                    <td>
                      <span className="pill" data-estado={ESTADO_PERIODO[f.estado].pill}>
                        {ESTADO_PERIODO[f.estado].nombre}
                      </span>
                    </td>
                    {editable && (
                      <td className="nowrap ops-acciones">
                        {a && (
                          <button
                            type="button"
                            className="enlace small"
                            disabled={ocupado}
                            onClick={() =>
                              void onDecidir({
                                periodos: {
                                  [f.id]: {
                                    ...a.cambio,
                                    relacionada: f.relacionada ?? null,
                                    ...(f.corregido ? { inicio: f.inicio, fin: f.fin, entidad: f.entidad, referencia: f.referencia } : {}),
                                  },
                                },
                              })
                            }
                          >
                            {a.texto}
                          </button>
                        )}
                        <button type="button" className="enlace small" disabled={ocupado} onClick={() => editar(f)}>
                          Corregir
                        </button>
                        {f.manual && (
                          <button type="button" className="enlace small" style={{ color: 'var(--bad)' }} disabled={ocupado} onClick={() => void onDecidir({ quitar: f.id })}>
                            Quitar
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {editable &&
        (editando === 'nuevo' ? (
          formulario
        ) : (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            style={{ marginTop: 14 }}
            onClick={() => {
              setBorrador(PERIODO_VACIO)
              setEditando('nuevo')
            }}
          >
            <Icono nombre="mas" tam={15} /> Agregar un periodo que no se leyó
          </button>
        ))}
      {(d.perfil?.obligaciones.length ?? 0) > 0 && (
        <details className="ops-obligaciones">
          <summary>Obligaciones específicas del contrato ({d.perfil!.obligaciones.length})</summary>
          <ol>
            {d.perfil!.obligaciones.map((o, i) => (
              <li key={i}>{o}</li>
            ))}
          </ol>
        </details>
      )}
    </section>
  )
}

function Documentos({ d, editable, ocupado, onDecidir }: PropsSeccion) {
  const [soloPendientes, setSoloPendientes] = useState(false)
  const documentos = d.documentos ?? []
  const pendiente = (x: DocumentoOps) => x.estado_final === 'falta' || x.estado_final === 'revision' || x.estado_final === 'no_cumple'
  const visibles = soloPendientes ? documentos.filter(pendiente) : documentos

  async function decidir(doc: DocumentoOps, estado: EstadoDocumento | null) {
    await onDecidir({ documentos: { [doc.clave]: estado ? { estado, nota: '' } : null } })
  }

  return (
    <section className="card ops-tarjeta">
      <div className="card-head">
        <div>
          <h2>Documentos del contratista</h2>
          <p className="small muted">Cada documento se reconoce por lo que dice. Lo que el sistema no pudo confirmar lo decide usted.</p>
        </div>
        <button type="button" className="chip" data-activo={soloPendientes} onClick={() => setSoloPendientes((v) => !v)}>
          Solo por revisar ({d.documentos_pendientes ?? 0})
        </button>
      </div>
      <div className="tabla-wrap">
        <table className="tabla ops-tabla">
          <thead>
            <tr>
              <th>Documento</th>
              <th>Estado</th>
              <th>Archivo</th>
              {editable && <th>Su decisión</th>}
            </tr>
          </thead>
          <tbody>
            {visibles.map((x) => (
              <tr key={x.clave}>
                <td style={{ maxWidth: 340 }}>
                  <strong>{x.nombre}</strong>
                  {x.motivo && !x.decision && <div className="small ops-motivo">{x.motivo}</div>}
                  {x.decision && <div className="small muted">Decidido por una persona{x.estado !== x.decision.estado ? ` (el sistema: ${ESTADO_DOCUMENTO[x.estado].nombre.toLowerCase()})` : ''}</div>}
                </td>
                <td>
                  <span className="pill" data-estado={ESTADO_DOCUMENTO[x.estado_final].pill}>
                    {ESTADO_DOCUMENTO[x.estado_final].nombre}
                  </span>
                </td>
                <td className="small" style={{ maxWidth: 260 }}>
                  {x.documento_id ? (
                    <a className="recortar" style={{ display: 'block' }} href={urlDocumento(d.id, x.documento_id)} target="_blank" rel="noreferrer">
                      {x.archivo}
                    </a>
                  ) : (
                    <span className="muted">—</span>
                  )}
                  {x.adicionales.map(
                    (a) =>
                      a.documento_id && (
                        <a key={a.documento_id} className="recortar" style={{ display: 'block' }} href={urlDocumento(d.id, a.documento_id)} target="_blank" rel="noreferrer">
                          {a.archivo}
                        </a>
                      ),
                  )}
                </td>
                {editable && (
                  <td className="nowrap">
                    {x.decision ? (
                      <button type="button" className="enlace small" disabled={ocupado} onClick={() => void decidir(x, null)}>
                        Deshacer
                      </button>
                    ) : pendiente(x) ? (
                      <div className="ops-decidir">
                        <button type="button" className="btn btn-sm btn-ok" disabled={ocupado} onClick={() => void decidir(x, 'cumple')}>
                          Cumple
                        </button>
                        <button type="button" className="btn btn-sm btn-ghost" disabled={ocupado} onClick={() => void decidir(x, 'no_cumple')}>
                          No cumple
                        </button>
                        <button type="button" className="btn btn-sm btn-ghost" disabled={ocupado} onClick={() => void decidir(x, 'no_aplica')}>
                          No aplica
                        </button>
                      </div>
                    ) : null}
                  </td>
                )}
              </tr>
            ))}
            {visibles.length === 0 && (
              <tr>
                <td colSpan={editable ? 4 : 3} className="vacio">
                  No queda ningún documento por revisar.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Archivos({
  d,
  id,
  editable,
  ocupado,
  onAgregar,
}: {
  d: DetalleOps
  id: string
  editable: boolean
  ocupado: boolean
  onAgregar: (origen: 'entidad' | 'contratista', archivos: File[]) => Promise<void>
}) {
  const [nuevos, setNuevos] = useState<File[]>([])
  const [origen, setOrigen] = useState<'entidad' | 'contratista'>('contratista')
  const sinReconocer = d.sin_reconocer ?? []
  return (
    <section className="card ops-tarjeta">
      <div className="card-head">
        <div>
          <h2>Archivos cargados</h2>
          <p className="small muted">
            {d.archivos.filter((a) => a.origen === 'contratista').length} del contratista y {d.archivos.filter((a) => a.origen === 'entidad').length} de la entidad.
          </p>
        </div>
      </div>
      {sinReconocer.length > 0 && (
        <p className="small" style={{ marginBottom: 12 }}>
          <strong>Sin reconocer:</strong>{' '}
          {sinReconocer.map((a, i) => (
            <span key={a.archivo}>
              {i > 0 && ', '}
              {a.documento_id ? (
                <a href={urlDocumento(id, a.documento_id)} target="_blank" rel="noreferrer">
                  {a.archivo}
                </a>
              ) : (
                a.archivo
              )}
            </span>
          ))}
          . De estos también se leen certificaciones y títulos.
        </p>
      )}
      <details className="ops-obligaciones">
        <summary>Ver los {d.archivos.length} archivos</summary>
        <ul className="ops-archivos">
          {d.archivos.map((a) => (
            <li key={a.id}>
              <span className="tag">{a.origen === 'entidad' ? 'Entidad' : 'Contratista'}</span>{' '}
              <a href={urlDocumento(id, a.id)} target="_blank" rel="noreferrer">
                {a.nombre}
              </a>
            </li>
          ))}
        </ul>
      </details>
      {editable && (
        <div className="ops-agregar">
          <div className="field" style={{ maxWidth: 260 }}>
            <label htmlFor="ops-origen">¿De quién es lo que va a agregar?</label>
            <select id="ops-origen" className="input" value={origen} onChange={(e) => setOrigen(e.target.value as 'entidad' | 'contratista')}>
              <option value="contratista">Del contratista</option>
              <option value="entidad">De la entidad</option>
            </select>
          </div>
          <ZonaArchivos titulo="Agregar documentos" ayuda="Al agregarlos se leen todos de nuevo; lo que usted ya decidió se conserva." archivos={nuevos} onCambiar={setNuevos} />
          <button
            type="button"
            className="btn btn-secondary"
            disabled={ocupado || nuevos.length === 0}
            onClick={() => void onAgregar(origen, nuevos).then(() => setNuevos([]))}
          >
            <Icono nombre="subir" /> Agregar y volver a leer
          </button>
        </div>
      )}
    </section>
  )
}

/** Nombre, cédula, libreta militar y fecha del estudio previo. Al cambiarlos
 * se leen los documentos de nuevo; lo ya decidido se conserva. */
function DatosContratista({
  d,
  onCerrar,
  onGuardar,
}: {
  d: DetalleOps
  onCerrar: () => void
  onGuardar: (cambios: Parameters<typeof corregirDatosOps>[1]) => Promise<void>
}) {
  const [nombre, setNombre] = useState(d.contratista_nombre)
  const [cedula, setCedula] = useState(d.contratista_cedula)
  const [referencia, setReferencia] = useState(d.referencia)
  const [fecha, setFecha] = useState(d.fecha_referencia)
  const [libreta, setLibreta] = useState<'' | 'si' | 'no'>(d.exige_libreta == null ? '' : d.exige_libreta ? 'si' : 'no')
  const [guardando, setGuardando] = useState(false)
  const valido = nombre.trim().length >= 5 && cedula.replace(/\D/g, '').length >= 5 && !!fecha
  return (
    <>
      <div className="overlay" onClick={onCerrar} />
      <div className="dialogo" role="dialog" aria-modal="true" aria-labelledby="titulo-datos">
        <h2 id="titulo-datos">Datos del contratista</h2>
        <p className="small muted">Si cambia el nombre, la cédula, la libreta o la fecha, los documentos se leen de nuevo. Lo que ya decidió se conserva.</p>
        <div className="grid-2" style={{ marginTop: 14 }}>
          <div className="field">
            <label htmlFor="dc-nombre">Nombre completo</label>
            <input id="dc-nombre" className="input" value={nombre} onChange={(e) => setNombre(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="dc-cedula">Cédula</label>
            <input id="dc-cedula" className="input" inputMode="numeric" value={cedula} onChange={(e) => setCedula(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="dc-ref">Número del proceso o contrato</label>
            <input id="dc-ref" className="input" value={referencia} onChange={(e) => setReferencia(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="dc-fecha">Fecha del estudio previo</label>
            <input id="dc-fecha" className="input" type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />
          </div>
        </div>
        <div className="field" style={{ marginTop: 14 }}>
          <label htmlFor="dc-libreta">¿Es hombre menor de 50 años?</label>
          <select id="dc-libreta" className="input" value={libreta} onChange={(e) => setLibreta(e.target.value as '' | 'si' | 'no')}>
            <option value="">No lo sé todavía</option>
            <option value="si">Sí: se le exige libreta militar</option>
            <option value="no">No: la libreta militar no aplica</option>
          </select>
        </div>
        <div className="dialogo-pie">
          <button type="button" className="btn btn-ghost" onClick={onCerrar}>
            Cancelar
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!valido || guardando}
            onClick={() => {
              setGuardando(true)
              void onGuardar({
                contratista_nombre: nombre,
                contratista_cedula: cedula,
                referencia,
                fecha_referencia: fecha,
                exige_libreta: libreta === '' ? null : libreta === 'si',
              }).finally(() => setGuardando(false))
            }}
          >
            {guardando && <span className="spinner" />} Guardar
          </button>
        </div>
      </div>
    </>
  )
}
