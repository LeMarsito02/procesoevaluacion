import { useEffect, useState } from 'react'
import type { ResultadoRequisito } from '../../api'
import Icono from '../../components/Icono'
import {
  probarRequisito,
  type Bloque,
  type CatalogoMotor,
  type ConfigPersonalizado,
  type GrupoRequisito,
  type RequisitoDefinicion,
  type TipoProponente,
} from '../../configuracion'
import { listarProcesos, obtenerEvaluacion, type EvaluacionResumen, type ProponenteGuardado } from '../../evaluaciones'
import { mensajeDe } from '../../http'

const NOMBRES_BLOQUE: Record<Bloque['tipo'], { nombre: string; ayuda: string }> = {
  vigencia_maxima: { nombre: 'Vigencia máxima', ayuda: 'La fecha de expedición no supera N meses antes del cierre.' },
  contiene: { nombre: 'Debe decir', ayuda: 'Aparece al menos una de estas frases (ej. NO REGISTRA ANTECEDENTES).' },
  no_contiene: { nombre: 'No debe decir', ayuda: 'No aparece ninguna de estas frases (ej. SANCIONADO).' },
  menciona_representante: { nombre: 'Es del representante legal', ayuda: 'Menciona al representante legal del proponente.' },
  menciona_proponente: { nombre: 'Es del proponente', ayuda: 'Menciona el nombre del proponente.' },
}

const NOMBRES_TIPO_PROPONENTE: Record<TipoProponente, string> = {
  persona_natural: 'Persona natural',
  persona_juridica: 'Persona jurídica',
  consorcio: 'Consorcio',
  union_temporal: 'Unión temporal',
}

const lineas = (texto: string) => texto.split('\n').map((l) => l.trim()).filter(Boolean)

interface Props {
  tipo: string
  catalogo: CatalogoMotor
  inicial: RequisitoDefinicion
  numerosUsados: number[]
  parametros: Record<string, unknown>
  entidadId: string | null
  onGuardar: (r: RequisitoDefinicion) => void
  onCerrar: () => void
}

/** Editor de un requisito: datos visibles y, si es nuevo, sus bloques y la prueba contra ofertas reales. */
export default function EditorRequisito({ tipo, catalogo, inicial, numerosUsados, parametros, entidadId, onGuardar, onCerrar }: Props) {
  const [req, setReq] = useState<RequisitoDefinicion>(inicial)
  const [frases, setFrases] = useState((inicial.config?.frases_documento ?? []).join('\n'))
  const personalizado = req.verificacion === 'personalizado'
  const motor = catalogo.verificaciones.find((v) => v.clave === req.verificacion)
  const config: ConfigPersonalizado = req.config ?? { frases_documento: [], paginas: 3, bloques: [], aplica_a: [] }
  const numeroRepetido = numerosUsados.includes(req.numero)

  function cambiarConfig(cambios: Partial<ConfigPersonalizado>) {
    setReq({ ...req, config: { ...config, ...cambios } })
  }

  function listo(): RequisitoDefinicion {
    return personalizado ? { ...req, config: { ...config, frases_documento: lineas(frases) } } : req
  }

  const incompleto =
    req.titulo.trim().length < 3 || !req.corto.trim() || numeroRepetido || (personalizado && lineas(frases).length === 0)

  return (
    <>
      <div className="overlay" onClick={onCerrar} />
      <div className="dialogo dialogo-ancho" role="dialog" aria-modal="true" aria-labelledby="titulo-req">
        <div className="card-head">
          <div>
            <h2 id="titulo-req">{personalizado ? 'Requisito con bloques' : 'Requisito del motor'}</h2>
            <p>{personalizado ? 'Cómo se reconoce el documento y qué se verifica en él.' : motor?.verifica}</p>
          </div>
          <button type="button" className="btn btn-ghost btn-icon" onClick={onCerrar} aria-label="Cerrar">
            <Icono nombre="x" />
          </button>
        </div>

        <div className="grid-req">
          <div className="field">
            <label htmlFor="r-num">Número</label>
            <input id="r-num" className="input" type="number" min={1} value={req.numero} onChange={(e) => setReq({ ...req, numero: Number(e.target.value) })} />
            {numeroRepetido && <span className="hint" style={{ color: 'var(--bad)' }}>Ya hay un requisito con ese número.</span>}
          </div>
          <div className="field" style={{ gridColumn: 'span 2' }}>
            <label htmlFor="r-titulo">Nombre del requisito</label>
            <input id="r-titulo" className="input" value={req.titulo} onChange={(e) => setReq({ ...req, titulo: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="r-corto">Nombre corto (matriz)</label>
            <input id="r-corto" className="input" maxLength={20} value={req.corto} onChange={(e) => setReq({ ...req, corto: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="r-grupo">Grupo</label>
            <select id="r-grupo" className="select" value={req.grupo} onChange={(e) => setReq({ ...req, grupo: e.target.value as GrupoRequisito })}>
              {Object.entries(catalogo.grupos).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="r-fila">Fila en el Excel</label>
            <input
              id="r-fila"
              className="input"
              type="number"
              min={1}
              placeholder="Según el mapeo"
              value={req.fila_excel ?? ''}
              onChange={(e) => setReq({ ...req, fila_excel: e.target.value ? Number(e.target.value) : null })}
            />
          </div>
          <div className="field" style={{ gridColumn: '1 / -1' }}>
            <label htmlFor="r-verifica">Qué se verifica (lo ve el evaluador)</label>
            <input id="r-verifica" className="input" value={req.verifica} placeholder={motor?.verifica} onChange={(e) => setReq({ ...req, verifica: e.target.value })} />
          </div>
        </div>

        {personalizado && (
          <>
            <h3 className="grupo-titulo" style={{ marginTop: 20 }}>
              1. Cómo se reconoce el documento
            </h3>
            <div className="grid-2" style={{ gap: 14 }}>
              <div className="field">
                <label htmlFor="r-frases">Frases del título o encabezado (una por línea)</label>
                <textarea id="r-frases" className="textarea" rows={3} value={frases} placeholder="JUNTA CENTRAL DE CONTADORES" onChange={(e) => setFrases(e.target.value)} />
                <span className="hint">Basta con que aparezca una. Mayúsculas y tildes no importan.</span>
              </div>
              <div className="field">
                <label htmlFor="r-paginas">Páginas a leer de cada PDF</label>
                <input id="r-paginas" className="input" type="number" min={1} max={20} value={config.paginas} onChange={(e) => cambiarConfig({ paginas: Number(e.target.value) })} />
                <label style={{ marginTop: 10 }}>Aplica a</label>
                <div className="chips">
                  {catalogo.tipos_proponente.map((t) => {
                    const activo = config.aplica_a.includes(t)
                    return (
                      <button
                        key={t}
                        type="button"
                        className="chip"
                        data-activo={activo}
                        onClick={() => cambiarConfig({ aplica_a: activo ? config.aplica_a.filter((x) => x !== t) : [...config.aplica_a, t] })}
                      >
                        {NOMBRES_TIPO_PROPONENTE[t]}
                      </button>
                    )
                  })}
                </div>
                <span className="hint">Sin selección = aplica a todos. A los demás se les marca «N.A.».</span>
              </div>
            </div>

            <h3 className="grupo-titulo" style={{ marginTop: 20 }}>
              2. Qué se verifica en el documento
            </h3>
            <div className="bloques">
              {config.bloques.map((b, i) => (
                <div key={i} className="bloque">
                  <div className="bloque-cabeza">
                    <strong>{NOMBRES_BLOQUE[b.tipo].nombre}</strong>
                    <span className="small muted" style={{ flex: 1 }}>
                      {NOMBRES_BLOQUE[b.tipo].ayuda}
                    </span>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => cambiarConfig({ bloques: config.bloques.filter((_, j) => j !== i) })}>
                      <Icono nombre="x" tam={14} />
                    </button>
                  </div>
                  {b.tipo === 'vigencia_maxima' && (
                    <div className="acciones">
                      <input
                        className="input select-sm"
                        style={{ width: 90 }}
                        type="number"
                        min={1}
                        value={b.meses ?? 1}
                        onChange={(e) => cambiarConfig({ bloques: config.bloques.map((x, j) => (j === i ? { ...x, meses: Number(e.target.value) } : x)) })}
                      />
                      <span className="small">meses antes de la fecha de cierre</span>
                    </div>
                  )}
                  {(b.tipo === 'contiene' || b.tipo === 'no_contiene') && (
                    <textarea
                      className="textarea"
                      rows={2}
                      placeholder="Una frase por línea"
                      value={(b.frases ?? []).join('\n')}
                      onChange={(e) => cambiarConfig({ bloques: config.bloques.map((x, j) => (j === i ? { ...x, frases: e.target.value.split('\n') } : x)) })}
                    />
                  )}
                </div>
              ))}
              <div className="chips">
                {(Object.keys(NOMBRES_BLOQUE) as Bloque['tipo'][]).map((t) => (
                  <button
                    key={t}
                    type="button"
                    className="chip"
                    onClick={() =>
                      cambiarConfig({
                        bloques: [...config.bloques, { tipo: t, meses: t === 'vigencia_maxima' ? 3 : null, frases: t === 'contiene' || t === 'no_contiene' ? [] : [] }],
                      })
                    }
                  >
                    <Icono nombre="mas" tam={12} /> {NOMBRES_BLOQUE[t].nombre}
                  </button>
                ))}
              </div>
            </div>

            <ProbarRequisito tipo={tipo} requisito={listo()} parametros={parametros} entidadId={entidadId} deshabilitado={incompleto} />
          </>
        )}

        <div className="dialogo-pie">
          <button type="button" className="btn btn-ghost" onClick={onCerrar}>
            Cancelar
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={incompleto}
            onClick={() => onGuardar({ ...listo(), config: personalizado ? { ...config, frases_documento: lineas(frases), bloques: config.bloques.map((b) => ({ ...b, frases: (b.frases ?? []).map((f) => f.trim()).filter(Boolean) })) } : null })}
          >
            Aplicar
          </button>
        </div>
      </div>
    </>
  )
}

/** Prueba el requisito contra hasta 5 proponentes de una evaluación ya creada. */
function ProbarRequisito({
  tipo,
  requisito,
  parametros,
  entidadId,
  deshabilitado,
}: {
  tipo: string
  requisito: RequisitoDefinicion
  parametros: Record<string, unknown>
  entidadId: string | null
  deshabilitado: boolean
}) {
  const [evaluaciones, setEvaluaciones] = useState<EvaluacionResumen[]>([])
  const [evaluacionId, setEvaluacionId] = useState('')
  const [proponentes, setProponentes] = useState<ProponenteGuardado[]>([])
  const [elegidos, setElegidos] = useState<string[]>([])
  const [probando, setProbando] = useState(false)
  const [resultados, setResultados] = useState<ResultadoRequisito[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listarProcesos()
      .then((procesos) =>
        setEvaluaciones(procesos.flatMap((p) => p.evaluaciones).filter((e) => e.tipo === tipo && (!entidadId || e.entidad_id === entidadId))),
      )
      .catch(() => setEvaluaciones([]))
  }, [tipo, entidadId])

  useEffect(() => {
    if (!evaluacionId) return
    obtenerEvaluacion(evaluacionId)
      .then((d) => {
        setProponentes(d.proponentes)
        setElegidos(d.proponentes.slice(0, 3).map((p) => p.id))
      })
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [evaluacionId])

  async function probar() {
    setProbando(true)
    setError(null)
    setResultados(null)
    try {
      setResultados(await probarRequisito({ evaluacion_id: evaluacionId, requisito, parametros, proponente_ids: elegidos }))
    } catch (e) {
      setError(mensajeDe(e))
    } finally {
      setProbando(false)
    }
  }

  return (
    <section className="probar">
      <h3 className="grupo-titulo">3. Probar con ofertas reales (no se guarda nada)</h3>
      {evaluaciones.length === 0 ? (
        <p className="small muted">Cuando la entidad tenga un proceso creado podrá probar el requisito contra sus ofertas.</p>
      ) : (
        <>
          <div className="grid-2" style={{ gap: 14 }}>
            <div className="field">
              <label htmlFor="p-ev">Proceso</label>
              <select id="p-ev" className="select" value={evaluacionId} onChange={(e) => setEvaluacionId(e.target.value)}>
                <option value="">Elija un proceso…</option>
                {evaluaciones.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.proceso_codigo}
                  </option>
                ))}
              </select>
            </div>
            {proponentes.length > 0 && (
              <div className="field">
                <label>Proponentes (máximo 5)</label>
                <select
                  className="select"
                  multiple
                  size={4}
                  value={elegidos}
                  onChange={(e) => setElegidos(Array.from(e.target.selectedOptions, (o) => o.value).slice(0, 5))}
                  style={{ height: 'auto' }}
                >
                  {proponentes.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.hoja} · {p.nombre_proponente}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
          <button type="button" className="btn btn-secondary btn-sm" style={{ marginTop: 10 }} disabled={deshabilitado || probando || !evaluacionId || !elegidos.length} onClick={probar}>
            {probando ? <span className="spinner oscuro" /> : <Icono nombre="chispa" tam={14} />} Probar
          </button>
        </>
      )}
      {error && <p className="small" style={{ color: 'var(--bad)' }}>{error}</p>}
      {resultados && (
        <div className="tabla-wrap" style={{ marginTop: 10 }}>
          <table className="tabla">
            <tbody>
              {resultados.map((r) => (
                <tr key={r.hoja}>
                  <td className="nowrap">
                    <strong>{r.hoja}</strong> <span className="small muted">{r.nombre_proponente}</span>
                  </td>
                  <td>
                    <span className="pill" data-estado={r.error ? 'error' : (r.motivo ?? '').startsWith('N.A.') ? 'no_aplica' : r.cumple ? 'cumple' : 'revisar'}>
                      <span className="dot" /> {r.error ? 'Error' : (r.motivo ?? '').startsWith('N.A.') ? 'No aplica' : r.cumple ? 'Cumple' : 'Por revisar'}
                    </span>
                  </td>
                  <td className="small">
                    {r.error ?? r.motivo ?? ''}
                    {r.archivo_evaluado && <div className="muted">{r.archivo_evaluado}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
