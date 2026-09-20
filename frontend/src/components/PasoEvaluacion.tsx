import { Fragment, useMemo, useState } from 'react'
import type { PersonaAntecedente, Proponente, ResultadoRequisito } from '../api'
import { esPendiente, estadoDe, resumenProponente, type Revisiones } from '../estado'
import { formatDuracion } from '../format'
import { GRUPOS, ORDEN_GRUPOS, REQUISITOS, requisitosOrdenados } from '../requisitos'
import Celda from './Celda'
import Icono from './Icono'

type Filtro = 'todos' | 'pendientes' | 'listos'

/** Estado de la evaluación en la fila central del servidor. */
export interface ProgresoEvaluacion {
  enFila: number
  procesando: number
  porDelante: number
  capacidad: number
  etaSegundos: number | null
}

interface Props {
  proponentes: Proponente[]
  resultados: Record<string, ResultadoRequisito[]>
  revisiones: Revisiones
  /** null = nada pendiente en la fila. */
  progreso: ProgresoEvaluacion | null
  ocupado: boolean
  hojaActiva: string | null
  /** false = sin permiso para lanzar la evaluación (solo lectura). */
  puedeEvaluar: boolean
  onDetener: () => void
  onContinuar: () => void
  /** `persona` = documento o nombre de la persona cuya casilla se tocó (antecedentes). */
  onAbrir: (hoja: string, requisito?: number, persona?: string) => void
  onSiguientePendiente: () => void
  onIrInforme: () => void
}

const ROL: Record<PersonaAntecedente['rol'], string> = {
  representante_legal: 'Representante legal',
  suplente: 'Suplente',
  integrante: 'Integrante',
  proponente: 'Proponente',
}

/** Cada persona o empresa del proponente y cómo le fue en cada requisito de
 * antecedentes: a un integrante jurídico no se le exigen los de persona
 * natural (queda "no aplica"). */
interface FilaPersona {
  clave: string
  nombre: string
  documento: string | null
  tipo: 'natural' | 'juridica'
  rol: PersonaAntecedente['rol']
  porRequisito: Map<number, PersonaAntecedente['estado']>
}

function personasDe(lista: ResultadoRequisito[] | undefined): FilaPersona[] {
  const filas = new Map<string, FilaPersona>()
  for (const r of lista ?? []) {
    for (const per of r.personas_antecedente ?? []) {
      const clave = per.documento || per.nombre.toUpperCase()
      const fila =
        filas.get(clave) ??
        { clave, nombre: per.nombre, documento: per.documento, tipo: per.tipo, rol: per.rol, porRequisito: new Map() }
      fila.porRequisito.set(r.requisito, per.estado)
      filas.set(clave, fila)
    }
  }
  const orden: PersonaAntecedente['rol'][] = ['proponente', 'representante_legal', 'suplente', 'integrante']
  return [...filas.values()].sort((a, b) => orden.indexOf(a.rol) - orden.indexOf(b.rol) || a.nombre.localeCompare(b.nombre))
}

const TIPO: Record<string, string> = {
  persona_natural: 'Persona natural',
  persona_juridica: 'Persona jurídica',
  consorcio: 'Consorcio',
  union_temporal: 'Unión temporal',
}


function Anillo({ pct }: { pct: number }) {
  const r = 42
  const c = 2 * Math.PI * r
  return (
    <div className="anillo">
      <svg width="96" height="96" viewBox="0 0 96 96">
        <circle cx="48" cy="48" r={r} stroke="var(--na-soft)" strokeWidth="8" fill="none" />
        <circle
          cx="48"
          cy="48"
          r={r}
          stroke="var(--brand)"
          strokeWidth="8"
          fill="none"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct / 100)}
          style={{ transition: 'stroke-dashoffset 0.5s ease' }}
        />
      </svg>
      <div className="anillo-text">{Math.round(pct)}%</div>
    </div>
  )
}

export default function PasoEvaluacion(p: Props) {
  // El catálogo depende de la plantilla de la entidad (se instala al abrir la evaluación).
  const REQS_ORDENADOS = requisitosOrdenados()
  const gruposPresentes = ORDEN_GRUPOS.filter((g) => REQUISITOS.some((r) => r.grupo === g))
  const [filtro, setFiltro] = useState<Filtro>('todos')
  const [busqueda, setBusqueda] = useState('')
  // Los antecedentes se exigen persona por persona: el abogado puede ver el
  // detalle de todos los proponentes a la vez.
  const [verPersonas, setVerPersonas] = useState(() => localStorage.getItem('matriz-por-persona') === 'si')
  const alternarPersonas = () =>
    setVerPersonas((antes) => {
      localStorage.setItem('matriz-por-persona', antes ? 'no' : 'si')
      return !antes
    })
  // Requisitos que se exigen persona por persona (los de antecedentes).
  const exigidos = useMemo(
    () => new Set(Object.values(p.resultados).flat().flatMap((r) => (r.personas_antecedente?.length ? [r.requisito] : []))),
    [p.resultados],
  )
  const hayPersonas = exigidos.size > 0

  const evaluados = p.proponentes.filter((pr) => p.resultados[pr.hoja]).length
  const faltan = p.proponentes.length - evaluados
  const conError = p.proponentes.filter((pr) => p.resultados[pr.hoja]?.some((r) => r.error)).length

  const kpis = useMemo(() => {
    let celdas = 0
    let automaticas = 0
    let pendientes = 0
    let revisadas = 0
    let proponentesListos = 0
    for (const pr of p.proponentes) {
      const lista = p.resultados[pr.hoja]
      if (!lista) continue
      const res = resumenProponente(lista, p.revisiones)
      if (res.pendientes === 0) proponentesListos++
      for (const r of lista) {
        if (!REQUISITOS.some((q) => q.numero === r.requisito)) continue
        celdas++
        const e = estadoDe(r, p.revisiones)
        if (e === 'cumple' || e === 'no_aplica') automaticas++
        if (esPendiente(e)) pendientes++
        if (e === 'revisado_cumple' || e === 'revisado_no_cumple') revisadas++
      }
    }
    return { celdas, automaticas, pendientes, revisadas, proponentesListos }
  }, [p.proponentes, p.resultados, p.revisiones])

  const filas = useMemo(() => {
    const q = busqueda.trim().toLowerCase()
    return p.proponentes.filter((pr) => {
      if (q && !`${pr.hoja} ${pr.nombre_proponente}`.toLowerCase().includes(q)) return false
      if (filtro === 'todos') return true
      const lista = p.resultados[pr.hoja]
      if (!lista) return filtro === 'pendientes'
      const { pendientes } = resumenProponente(lista, p.revisiones)
      return filtro === 'pendientes' ? pendientes > 0 : pendientes === 0
    })
  }, [p.proponentes, p.resultados, p.revisiones, filtro, busqueda])

  const evaluando = p.progreso !== null
  const pct = (evaluados / Math.max(p.proponentes.length, 1)) * 100

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Evaluación jurídica</div>
          <h1>Evaluación y revisión</h1>
          <p>
            Haga clic en un proponente o en cualquier casilla para ver el detalle. Solo necesita revisar las casillas en{' '}
            <strong style={{ color: 'var(--warn)' }}>ámbar</strong>: son los casos que el sistema no pudo confirmar por sí
            solo.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          {kpis.pendientes > 0 && (
            <button className="btn btn-secondary" type="button" onClick={p.onSiguientePendiente}>
              Revisar pendientes <Icono nombre="flecha" tam={16} />
            </button>
          )}
          <button className="btn btn-primary" type="button" onClick={p.onIrInforme} disabled={evaluados === 0}>
            <Icono nombre="descargar" tam={16} /> Generar informe
          </button>
        </div>
      </div>

      {(evaluando || faltan > 0) && (
        <section className="card progreso-card" style={{ marginBottom: 20 }}>
          <Anillo pct={pct} />
          <div style={{ flex: 1, minWidth: 0 }}>
            {p.progreso ? (
              <>
                <h2 style={{ fontSize: 18, display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span className="pulso" />
                  {p.progreso.procesando > 0 ? 'Evaluando proponentes…' : 'En la fila, esperando turno…'}
                </h2>
                <p className="muted" style={{ marginTop: 4 }}>
                  {evaluados} de {p.proponentes.length} evaluados · {p.progreso.procesando} en proceso · {p.progreso.enFila} en fila
                  {p.progreso.porDelante > 0 && ` · ${p.progreso.porDelante} de otros procesos antes`}
                </p>
                <p className="small" style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Icono nombre="reloj" tam={14} />
                  {p.progreso.capacidad === 0 ? (
                    <span style={{ color: 'var(--warn)' }}>El servicio de evaluación no está activo. Seguirá en cuanto se reanude.</span>
                  ) : p.progreso.etaSegundos !== null ? (
                    <strong>Termina en aprox. {formatDuracion(p.progreso.etaSegundos * 1000)}</strong>
                  ) : (
                    'Calculando tiempo…'
                  )}
                </p>
                <p className="small muted" style={{ marginTop: 6 }}>
                  La evaluación corre en el servidor: puede revisar lo que ya terminó, cambiar de página o cerrar la pestaña. Le
                  avisaremos por correo cuando termine.
                </p>
              </>
            ) : (
              <>
                <h2 style={{ fontSize: 18 }}>Evaluación incompleta</h2>
                <p className="muted" style={{ marginTop: 4 }}>
                  Faltan {faltan} de {p.proponentes.length} proponentes por evaluar.
                </p>
              </>
            )}
          </div>
          {!p.puedeEvaluar ? null : evaluando ? (
            p.progreso!.enFila > 0 && (
              <button className="btn btn-secondary" type="button" onClick={p.onDetener} disabled={p.ocupado}>
                <Icono nombre="pausa" tam={15} /> Pausar
              </button>
            )
          ) : (
            <button className="btn btn-primary" type="button" onClick={p.onContinuar} disabled={p.ocupado}>
              {p.ocupado ? <span className="spinner" /> : null} Evaluar los que faltan <Icono nombre="flecha" tam={16} />
            </button>
          )}
        </section>
      )}

      <div className="kpis">
        <div className="kpi">
          <div className="kpi-label">Proponentes evaluados</div>
          <div className="kpi-value">
            {evaluados}
            <span className="muted" style={{ fontSize: 18 }}> / {p.proponentes.length}</span>
          </div>
          <div className="kpi-sub">{kpis.proponentesListos} sin nada pendiente</div>
        </div>
        <div className="kpi" data-tone="ok">
          <div className="kpi-label">Verificados automáticamente</div>
          <div className="kpi-value">{kpis.celdas ? Math.round((kpis.automaticas / kpis.celdas) * 100) : 0}%</div>
          <div className="kpi-sub">
            {kpis.automaticas} de {kpis.celdas} verificaciones
          </div>
        </div>
        <button
          type="button"
          className="kpi"
          data-tone={kpis.pendientes > 0 ? 'warn' : 'ok'}
          onClick={() => setFiltro('pendientes')}
        >
          <div className="kpi-label">Pendientes de su revisión</div>
          <div className="kpi-value">{kpis.pendientes}</div>
          <div className="kpi-sub">{kpis.pendientes > 0 ? 'Ver solo proponentes con pendientes' : 'Todo revisado'}</div>
        </button>
        <div className="kpi">
          <div className="kpi-label">Revisados por usted</div>
          <div className="kpi-value">{kpis.revisadas}</div>
          <div className="kpi-sub">decisiones manuales</div>
        </div>
      </div>

      {conError > 0 && !evaluando && (
        <div className="callout callout-warn" style={{ marginBottom: 16, alignItems: 'center' }}>
          <Icono nombre="alerta" />
          <div style={{ flex: 1 }}>
            {conError} proponente(s) no se pudieron evaluar por completo (casillas rojas). Puede reintentarlos o revisarlos
            manualmente.
          </div>
          {p.puedeEvaluar && (
            <button className="btn btn-secondary btn-sm" type="button" onClick={p.onContinuar}>
              Reintentar
            </button>
          )}
        </div>
      )}

      <div className="toolbar">
        <div className="segmented" role="group" aria-label="Filtrar proponentes">
          {(
            [
              ['todos', `Todos (${p.proponentes.length})`],
              ['pendientes', 'Con pendientes'],
              ['listos', 'Sin pendientes'],
            ] as [Filtro, string][]
          ).map(([id, nombre]) => (
            <button key={id} type="button" aria-pressed={filtro === id} onClick={() => setFiltro(id)}>
              {nombre}
            </button>
          ))}
        </div>
        <button
          type="button"
          className={`btn btn-sm ${verPersonas ? 'btn-primary' : 'btn-secondary'}`}
          onClick={alternarPersonas}
          disabled={!hayPersonas}
          aria-pressed={verPersonas}
          title={
            hayPersonas
              ? 'Muestra, debajo de cada proponente, a quién se le exigió cada antecedente'
              : 'Aparece cuando el proceso se evalúa con esta versión del programa'
          }
        >
          <Icono nombre="usuarios" tam={15} /> {verPersonas ? 'Ocultar personas' : 'Ver antecedentes por persona'}
        </button>
        <div className="input-group search">
          <Icono nombre="buscar" tam={16} />
          <input
            className="input"
            style={{ height: 38 }}
            placeholder="Buscar proponente…"
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
          />
        </div>
      </div>

      <div className="matriz-wrap">
        <table className="matriz">
          <thead>
            <tr className="grupo-row">
              <th className="col-prop" />
              {gruposPresentes.map((g) => (
                <th key={g} colSpan={REQUISITOS.filter((r) => r.grupo === g).length} style={{ borderLeft: '1px solid var(--line)' }}>
                  {GRUPOS[g]}
                </th>
              ))}
              <th />
            </tr>
            <tr className="req-row">
              <th className="col-prop" style={{ verticalAlign: 'bottom', paddingBottom: 10 }}>
                Proponente
              </th>
              {REQS_ORDENADOS.map((r, i) => (
                <th
                  key={r.numero}
                  className="req-h"
                  title={`${r.numero}. ${r.titulo}\n${r.verifica}`}
                  style={i > 0 && REQS_ORDENADOS[i - 1].grupo !== r.grupo ? { borderLeft: '1px solid var(--line)' } : undefined}
                >
                  <div className="req-h-label">{r.corto}</div>
                </th>
              ))}
              <th className="col-estado" style={{ verticalAlign: 'bottom', paddingBottom: 10 }}>
                Estado
              </th>
            </tr>
          </thead>
          <tbody>
            {filas.map((pr) => {
              const lista = p.resultados[pr.hoja]
              const personas = personasDe(lista)
              const abierta = verPersonas && personas.length > 0
              const porReq = new Map((lista ?? []).map((r) => [r.requisito, r]))
              const res = resumenProponente(lista, p.revisiones)
              const tipo = lista?.find((r) => r.tipo_proponente)?.tipo_proponente
              return (
                <Fragment key={pr.hoja}>
                <tr data-activo={p.hojaActiva === pr.hoja}>
                  <td className="col-prop">
                    <button type="button" className="prop-cell" onClick={() => lista && p.onAbrir(pr.hoja)} disabled={!lista}>
                      <span className="prop-num">{pr.hoja}</span>
                      <span style={{ minWidth: 0 }}>
                        <div className="prop-name" title={pr.nombre_proponente}>
                          {pr.nombre_proponente}
                        </div>
                        <div className="prop-meta">{lista ? (tipo ? TIPO[tipo] ?? '' : '') : 'En espera…'}</div>
                      </span>
                    </button>
                  </td>
                  {REQS_ORDENADOS.map((info, i) => (
                    <td
                      key={info.numero}
                      style={i > 0 && REQS_ORDENADOS[i - 1].grupo !== info.grupo ? { borderLeft: '1px solid var(--line)' } : undefined}
                    >
                      <Celda
                        resultado={porReq.get(info.numero)}
                        info={info}
                        revisiones={p.revisiones}
                        onClick={() => p.onAbrir(pr.hoja, info.numero)}
                      />
                    </td>
                  ))}
                  <td className="col-estado">
                    {!lista ? (
                      <span className="pill" data-estado="no_aplica">
                        En espera
                      </span>
                    ) : res.pendientes > 0 ? (
                      <span className="pill" data-estado="revisar">
                        <span className="dot" /> {res.pendientes} por revisar
                      </span>
                    ) : res.noCumple > 0 ? (
                      <span className="pill" data-estado="revisado_no_cumple">
                        <span className="dot" /> No cumple
                      </span>
                    ) : (
                      <span className="pill" data-estado="cumple">
                        <span className="dot" /> Listo
                      </span>
                    )}
                  </td>
                </tr>
                {abierta &&
                  personas.map((per) => (
                    <tr key={`${pr.hoja}-${per.clave}`} className="fila-persona">
                      <td className="col-prop">
                        <span className="persona-nombre" title={per.documento ? `${per.tipo === 'juridica' ? 'NIT' : 'C.C.'} ${per.documento}` : undefined}>
                          {per.nombre}
                        </span>
                        <span className="prop-meta">{ROL[per.rol]}{per.tipo === 'juridica' ? ' · persona jurídica' : ''}</span>
                      </td>
                      {REQS_ORDENADOS.map((info, i) => (
                        <td
                          key={info.numero}
                          style={i > 0 && REQS_ORDENADOS[i - 1].grupo !== info.grupo ? { borderLeft: '1px solid var(--line)' } : undefined}
                        >
                          <CeldaPersona
                            estado={per.porRequisito.get(info.numero)}
                            exigido={exigidos.has(info.numero)}
                            titulo={`${info.titulo} · ${per.nombre}`}
                            onClick={() => p.onAbrir(pr.hoja, info.numero, per.clave)}
                          />
                        </td>
                      ))}
                      <td className="col-estado" />
                    </tr>
                  ))}
                </Fragment>
              )
            })}
          </tbody>
        </table>
        {filas.length === 0 && (
          <div className="vacio">
            <h3>Sin resultados</h3>
            <p>No hay proponentes que coincidan con el filtro o la búsqueda.</p>
          </div>
        )}
      </div>

      <div className="leyenda">
        <span>
          <i style={{ background: 'var(--ok-soft)', border: '1px solid #bfe0cf' }} /> Cumple
        </span>
        <span>
          <i style={{ background: 'var(--warn-soft)', border: '1px solid #efcf96' }} /> Por revisar
        </span>
        <span>
          <i style={{ background: 'var(--na-soft)' }} /> No aplica
        </span>
        <span>
          <i style={{ background: 'var(--bad-soft)', border: '1px solid #f0bdb6' }} /> No se pudo evaluar
        </span>
        <span>
          <i style={{ background: 'var(--ok)' }} /> / <i style={{ background: 'var(--bad)' }} /> Decidido por usted
        </span>
      </div>
    </main>
  )
}


/** Cómo le fue a una persona en un requisito de antecedentes. */
function CeldaPersona({
  estado,
  exigido,
  titulo,
  onClick,
}: {
  estado: PersonaAntecedente['estado'] | undefined
  exigido: boolean
  titulo: string
  onClick: () => void
}) {
  // El requisito no se verifica persona por persona (queda en blanco), o a
  // esta persona no se le exige (a una empresa no se le pide REDAM ni
  // antecedentes judiciales): "N.A.".
  if (!exigido) return null
  if (!estado) {
    return (
      <button type="button" className="celda celda-persona" data-estado="no_aplica" title={`${titulo}: no se le exige`} onClick={onClick}>
        N.A.
      </button>
    )
  }
  const mapa = { cumple: 'cumple', falta: 'revisar', con_novedad: 'error', vencido: 'error' } as const
  const texto = { cumple: 'Cumple', falta: 'Falta', con_novedad: 'Con novedad', vencido: 'Vencido' }[estado]
  return (
    <button
      type="button"
      className="celda celda-persona"
      data-estado={mapa[estado]}
      title={`${titulo}: ${texto.toLowerCase()} — clic para ver el detalle`}
      onClick={onClick}
    >
      {estado === 'cumple' ? <Icono nombre="check" tam={13} grosor={2.6} /> : estado === 'falta' ? '!' : <Icono nombre="x" tam={12} grosor={2.6} />}
    </button>
  )
}
