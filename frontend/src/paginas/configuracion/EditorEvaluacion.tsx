import { useMemo, useState } from 'react'
import Icono from '../../components/Icono'
import {
  activarVersionPlantilla,
  proponerRequisito,
  publicarPlantillaEvaluacion,
  type CatalogoMotor,
  type DefinicionEvaluacion,
  type Parametro,
  type PlantillaEvaluacion,
  type RequisitoDefinicion,
} from '../../configuracion'
import { mensajeDe } from '../../http'
import EditorRequisito from './EditorRequisito'

const fecha = (iso: string) => new Date(iso).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' })

interface Props {
  plantilla: PlantillaEvaluacion
  catalogo: CatalogoMotor
  entidadId: string | null
  esSuper: boolean
  onPublicado: (mensaje: string) => void
  onError: (mensaje: string) => void
}

/** Qué requisitos pide la entidad para este tipo de evaluación, cómo se verifica cada uno y con qué parámetros. */
export default function EditorEvaluacion({ plantilla, catalogo, entidadId, esSuper, onPublicado, onError }: Props) {
  const [definicion, setDefinicion] = useState<DefinicionEvaluacion>(() => structuredClone(plantilla.definicion))
  const [nombre, setNombre] = useState(plantilla.activa?.nombre ?? `Evaluación ${plantilla.tipo_nombre.toLowerCase()}`)
  const [nota, setNota] = useState('')
  const [editando, setEditando] = useState<{ indice: number | null; req: RequisitoDefinicion } | null>(null)
  const [publicando, setPublicando] = useState(false)
  const [descripcionIA, setDescripcionIA] = useState('')
  const [proponiendo, setProponiendo] = useState(false)

  const cambios = useMemo(() => JSON.stringify(definicion) !== JSON.stringify(plantilla.definicion), [definicion, plantilla.definicion])
  const ordenados = [...definicion.requisitos].map((r, i) => ({ r, i })).sort((a, b) => a.r.numero - b.r.numero)
  const siguienteNumero = Math.max(0, ...definicion.requisitos.map((r) => r.numero)) + 1
  const usadas = new Set(definicion.requisitos.map((r) => r.verificacion))
  const disponiblesMotor = catalogo.verificaciones.filter((v) => !usadas.has(v.clave))

  function aplicar(req: RequisitoDefinicion, indice: number | null) {
    const lista = [...definicion.requisitos]
    if (indice === null) lista.push(req)
    else lista[indice] = req
    setDefinicion({ ...definicion, requisitos: lista })
    setEditando(null)
  }

  function nuevoPersonalizado(base?: Partial<RequisitoDefinicion>): RequisitoDefinicion {
    return {
      numero: siguienteNumero,
      titulo: '',
      corto: '',
      grupo: 'adicionales',
      verificacion: 'personalizado',
      verifica: '',
      fila_excel: null,
      config: { frases_documento: [], paginas: 3, bloques: [], aplica_a: [] },
      ...base,
    }
  }

  async function proponer() {
    setProponiendo(true)
    try {
      const propuesta = await proponerRequisito(plantilla.tipo, descripcionIA)
      setEditando({ indice: null, req: nuevoPersonalizado({ ...propuesta, numero: siguienteNumero, fila_excel: null }) })
      setDescripcionIA('')
    } catch (e) {
      onError(mensajeDe(e))
    } finally {
      setProponiendo(false)
    }
  }

  async function publicar() {
    setPublicando(true)
    try {
      const v = await publicarPlantillaEvaluacion({ tipo: plantilla.tipo, nombre, definicion, nota }, esSuper ? entidadId : null)
      setNota('')
      onPublicado(`Versión ${v.version} publicada. Los procesos nuevos ya la usan.`)
    } catch (e) {
      onError(mensajeDe(e))
    } finally {
      setPublicando(false)
    }
  }

  const valorParametro = (p: Parametro) => definicion.parametros[p.clave] ?? p.defecto

  return (
    <div className="editor-evaluacion">
      <section className="card">
        <div className="card-head">
          <div>
            <h2>Versión vigente</h2>
            <p>
              {plantilla.activa
                ? `v${plantilla.activa.version} · «${plantilla.activa.nombre}» · publicada el ${fecha(plantilla.activa.creada_en)}${plantilla.activa.creada_por ? ` por ${plantilla.activa.creada_por}` : ''}`
                : 'La entidad usa la base del sistema (evaluación jurídica del ICCU). Publique una versión para adaptarla.'}
            </p>
          </div>
          {!plantilla.motor_disponible && <span className="tag tag-preparacion">Motor en preparación</span>}
        </div>
        {plantilla.versiones.length > 1 && (
          <details className="plantilla-historial">
            <summary className="small">Historial ({plantilla.versiones.length} versiones)</summary>
            {plantilla.versiones.map((v) => (
              <div key={v.id} className="plantilla-archivo small">
                <span style={{ flex: 1 }}>
                  <strong>v{v.version}</strong> · {v.nombre} · {fecha(v.creada_en)} · {v.evaluaciones} evaluaciones
                  {v.nota && <span className="muted"> · {v.nota}</span>}
                </span>
                {v.activa ? (
                  <span className="pill" data-estado="cumple">
                    <span className="dot" /> Vigente
                  </span>
                ) : (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() =>
                      activarVersionPlantilla(v.id)
                        .then(() => onPublicado(`Versión ${v.version} activada`))
                        .catch((e: unknown) => onError(mensajeDe(e)))
                    }
                  >
                    Volver a esta
                  </button>
                )}
              </div>
            ))}
          </details>
        )}
      </section>

      {plantilla.tipo === 'juridica' && (
        <section className="card">
          <div className="card-head">
            <div>
              <h2>Parámetros</h2>
              <p>Valores que usan las verificaciones del motor.</p>
            </div>
          </div>
          <div className="grid-2" style={{ gap: 16 }}>
            {catalogo.parametros.map((p) => (
              <div key={p.clave} className="field">
                <label htmlFor={`p-${p.clave}`}>
                  {p.nombre} {p.unidad && <span className="muted">({p.unidad})</span>}
                </label>
                {p.tipo === 'entero' ? (
                  <input
                    id={`p-${p.clave}`}
                    className="input"
                    type="number"
                    min={p.minimo ?? undefined}
                    max={p.maximo ?? undefined}
                    value={Number(valorParametro(p))}
                    onChange={(e) => setDefinicion({ ...definicion, parametros: { ...definicion.parametros, [p.clave]: Number(e.target.value) } })}
                  />
                ) : p.tipo === 'texto' ? (
                  <input
                    id={`p-${p.clave}`}
                    className="input"
                    value={String(valorParametro(p))}
                    onChange={(e) => setDefinicion({ ...definicion, parametros: { ...definicion.parametros, [p.clave]: e.target.value } })}
                  />
                ) : (
                  <textarea
                    id={`p-${p.clave}`}
                    className="textarea"
                    rows={2}
                    value={(valorParametro(p) as string[]).join('\n')}
                    onChange={(e) =>
                      setDefinicion({ ...definicion, parametros: { ...definicion.parametros, [p.clave]: e.target.value.split('\n') } })
                    }
                  />
                )}
                <span className="hint">
                  {p.descripcion}
                  {p.tipo === 'lista_texto' && ' Uno por línea.'}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="card">
        <div className="card-head">
          <div>
            <h2>Requisitos ({definicion.requisitos.length})</h2>
            <p>En el orden y con los nombres con los que la entidad los evalúa y los reporta.</p>
          </div>
        </div>
        <div className="tabla-wrap">
          <table className="tabla">
            <thead>
              <tr>
                <th style={{ width: 56 }}>No.</th>
                <th>Requisito</th>
                <th>Grupo</th>
                <th>Cómo se verifica</th>
                <th style={{ width: 80 }}>Fila Excel</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {ordenados.map(({ r, i }) => {
                const motor = catalogo.verificaciones.find((v) => v.clave === r.verificacion)
                return (
                  <tr key={`${r.verificacion}-${i}`}>
                    <td className="num">
                      <strong>{r.numero}</strong>
                    </td>
                    <td>
                      <strong>{r.titulo}</strong>
                      <div className="small muted">{r.corto}</div>
                    </td>
                    <td className="small">{catalogo.grupos[r.grupo]}</td>
                    <td className="small">
                      {motor ? (
                        <>
                          <span className="tag">Motor</span> {motor.corto}
                        </>
                      ) : (
                        <>
                          <span className="tag tag-bloques">Bloques</span> {r.config?.bloques.length ?? 0} verificaciones
                        </>
                      )}
                    </td>
                    <td className="num small">{r.fila_excel ?? '—'}</td>
                    <td className="nowrap" style={{ textAlign: 'right' }}>
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditando({ indice: i, req: structuredClone(r) })}>
                        <Icono nombre="lapiz" tam={14} /> Editar
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        aria-label="Quitar"
                        onClick={() => setDefinicion({ ...definicion, requisitos: definicion.requisitos.filter((_, j) => j !== i) })}
                      >
                        <Icono nombre="x" tam={14} />
                      </button>
                    </td>
                  </tr>
                )
              })}
              {definicion.requisitos.length === 0 && (
                <tr>
                  <td colSpan={6} className="vacio">
                    Aún no hay requisitos. Agregue verificaciones del motor o cree requisitos con bloques.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="agregar-requisito">
          {disponiblesMotor.length > 0 && (
            <select
              className="select"
              value=""
              onChange={(e) => {
                const v = catalogo.verificaciones.find((x) => x.clave === e.target.value)
                if (!v) return
                setEditando({
                  indice: null,
                  req: { numero: siguienteNumero, titulo: v.titulo, corto: v.corto, grupo: v.grupo, verificacion: v.clave, verifica: v.verifica, fila_excel: null, config: null },
                })
              }}
            >
              <option value="">+ Agregar verificación del motor…</option>
              {disponiblesMotor.map((v) => (
                <option key={v.clave} value={v.clave}>
                  {v.titulo}
                </option>
              ))}
            </select>
          )}
          <button type="button" className="btn btn-secondary" onClick={() => setEditando({ indice: null, req: nuevoPersonalizado() })}>
            <Icono nombre="mas" tam={15} /> Nuevo requisito con bloques
          </button>
        </div>

        <div className="proponer-ia">
          <label htmlFor="ia" className="small">
            <Icono nombre="chispa" tam={14} /> <strong>¿Prefiere describirlo?</strong> La IA propone la regla con bloques; usted la revisa y la prueba antes de guardarla.
          </label>
          <div className="acciones">
            <input
              id="ia"
              className="input"
              style={{ flex: 1 }}
              placeholder="Ej.: certificado de la Junta Central de Contadores del contador, máximo 3 meses, que diga que no registra antecedentes"
              value={descripcionIA}
              onChange={(e) => setDescripcionIA(e.target.value)}
            />
            <button type="button" className="btn btn-secondary" disabled={proponiendo || descripcionIA.trim().length < 15} onClick={proponer}>
              {proponiendo ? <span className="spinner oscuro" /> : 'Proponer'}
            </button>
          </div>
        </div>
      </section>

      <section className="card publicar" data-cambios={cambios}>
        <div className="grid-2" style={{ gap: 14 }}>
          <div className="field">
            <label htmlFor="v-nombre">Nombre de la versión</label>
            <input id="v-nombre" className="input" value={nombre} onChange={(e) => setNombre(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="v-nota">Qué cambió (queda en el historial)</label>
            <input id="v-nota" className="input" value={nota} placeholder="Ej.: se agrega certificado JCC del contador" onChange={(e) => setNota(e.target.value)} />
          </div>
        </div>
        <div className="acciones" style={{ justifyContent: 'space-between', marginTop: 14 }}>
          <span className="small muted">
            {cambios ? 'Hay cambios sin publicar.' : 'Sin cambios.'} Las evaluaciones en curso siguen con su versión hasta que se actualicen.
          </span>
          <div className="acciones">
            {cambios && (
              <button type="button" className="btn btn-ghost" onClick={() => setDefinicion(structuredClone(plantilla.definicion))}>
                Descartar cambios
              </button>
            )}
            <button type="button" className="btn btn-primary" disabled={publicando || (!cambios && !!plantilla.activa)} onClick={publicar}>
              {publicando ? <span className="spinner" /> : `Publicar versión ${(plantilla.versiones[0]?.version ?? 0) + 1}`}
            </button>
          </div>
        </div>
      </section>

      {editando && (
        <EditorRequisito
          tipo={plantilla.tipo}
          catalogo={catalogo}
          inicial={editando.req}
          numerosUsados={definicion.requisitos.filter((_, j) => j !== editando.indice).map((r) => r.numero)}
          parametros={definicion.parametros}
          entidadId={entidadId}
          onGuardar={(r) => aplicar(r, editando.indice)}
          onCerrar={() => setEditando(null)}
        />
      )}
    </div>
  )
}
