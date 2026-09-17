import { useCallback, useEffect, useRef, useState } from 'react'
import Icono from '../components/Icono'
import {
  activarPlantilla,
  ajustarMapeo,
  borrarPlantilla,
  descargarPlantilla,
  catalogoMotor,
  listarPlantillas,
  listarPlantillasEvaluacion,
  subirPlantilla,
  type CatalogoMotor,
  type MapeoPlantilla,
  type Plantilla,
  type PlantillaEvaluacion,
  type PlantillasTipo,
} from '../configuracion'
import { listarEntidades, type Entidad } from '../cuentas'
import { mensajeDe } from '../http'
import { REQUISITOS } from '../requisitos'
import { useSesion } from '../sesion'
import EditorEvaluacion from './configuracion/EditorEvaluacion'

const fecha = (iso: string) => new Date(iso).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' })

export default function PaginaConfiguracion() {
  const { usuario } = useSesion()!
  const esSuper = usuario.rol === 'superadmin'
  const [entidades, setEntidades] = useState<Entidad[]>([])
  const [entidadId, setEntidadId] = useState<string | null>(() => {
    if (!esSuper) return usuario.entidad?.id ?? null
    return new URLSearchParams(window.location.search).get('entidad')
  })
  const [plantillas, setPlantillas] = useState<PlantillasTipo[] | null>(null)
  const [evaluaciones, setEvaluaciones] = useState<PlantillaEvaluacion[] | null>(null)
  const [catalogos, setCatalogos] = useState<Record<string, CatalogoMotor>>({})
  const [tipo, setTipo] = useState('juridica')
  // Cambia al publicar: remonta el editor con la versión nueva.
  const [revision, setRevision] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [editando, setEditando] = useState<Plantilla | null>(null)

  useEffect(() => {
    if (!esSuper) return
    listarEntidades()
      .then((l) => {
        setEntidades(l)
        setEntidadId((actual) => actual ?? l[0]?.id ?? null)
      })
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [esSuper])

  const recargar = useCallback(() => {
    if (!entidadId) return
    const id = esSuper ? entidadId : null
    Promise.all([listarPlantillas(id), listarPlantillasEvaluacion(id)])
      .then(([p, e]) => {
        setPlantillas(p)
        setEvaluaciones(e)
        setRevision((r) => r + 1)
        setError(null)
      })
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [entidadId, esSuper])

  useEffect(() => {
    if (catalogos[tipo]) return
    catalogoMotor(tipo)
      .then((c) => setCatalogos((prev) => ({ ...prev, [tipo]: c })))
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [tipo, catalogos])

  useEffect(() => {
    recargar()
  }, [recargar])

  useEffect(() => {
    if (!aviso) return
    const t = window.setTimeout(() => setAviso(null), 3000)
    return () => window.clearTimeout(t)
  }, [aviso])

  async function accion(f: () => Promise<unknown>, exito: string) {
    try {
      await f()
      setAviso(exito)
      recargar()
    } catch (e) {
      setError(mensajeDe(e))
    }
  }

  const nombreEntidad = esSuper ? entidades.find((e) => e.id === entidadId)?.nombre : usuario.entidad?.nombre

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">{nombreEntidad ?? 'Configuración'}</div>
          <h1>Configuración de la entidad</h1>
          <p>Cómo evalúa la entidad cada tipo de evaluación: requisitos, verificaciones, parámetros y plantilla de Excel del informe.</p>
        </div>
        {esSuper && (
          <select className="select" style={{ width: 'auto', minWidth: 260 }} value={entidadId ?? ''} onChange={(e) => setEntidadId(e.target.value)} aria-label="Entidad">
            {entidades.map((e) => (
              <option key={e.id} value={e.id}>
                {e.nombre}
              </option>
            ))}
          </select>
        )}
      </div>

      {error && (
        <div className="callout callout-bad" style={{ marginBottom: 16 }} role="alert">
          <Icono nombre="alerta" />
          <div style={{ flex: 1 }}>{error}</div>
          <button className="btn btn-ghost btn-sm" type="button" onClick={() => setError(null)}>
            Cerrar
          </button>
        </div>
      )}

      <div className="pestanas" role="tablist">
        {(evaluaciones ?? []).map((t) => (
          <button key={t.tipo} type="button" role="tab" aria-selected={tipo === t.tipo} onClick={() => setTipo(t.tipo)}>
            Evaluación {t.tipo_nombre.toLowerCase()}
          </button>
        ))}
      </div>

      {!plantillas || !evaluaciones || !catalogos[tipo] ? (
        <div className="vacio">
          <span className="spinner oscuro" />
        </div>
      ) : (
        <>
          <EditorEvaluacion
            key={`${entidadId}-${tipo}-${revision}`}
            plantilla={evaluaciones.find((e) => e.tipo === tipo)!}
            catalogo={catalogos[tipo]}
            entidadId={entidadId}
            esSuper={esSuper}
            onPublicado={(m) => {
              setAviso(m)
              recargar()
            }}
            onError={setError}
          />
          <h2 className="seccion-titulo" style={{ color: 'var(--ink)', marginTop: 8 }}>
            <Icono nombre="documento" tam={16} /> Plantilla de Excel del informe
          </h2>
          <div className="plantillas">
            {plantillas
              .filter((t) => t.tipo === tipo)
              .map((t) => (
                <TarjetaPlantilla
                  key={t.tipo}
                  t={t}
                  onSubir={(archivo) => accion(() => subirPlantilla(t.tipo, archivo, esSuper ? entidadId : null), 'Plantilla subida')}
                  onEditar={setEditando}
                  onActivar={(p) => accion(() => activarPlantilla(p.id), 'Plantilla activada')}
                  onBorrar={(p) =>
                    window.confirm(`¿Eliminar la plantilla «${p.nombre_original}»?`) && accion(() => borrarPlantilla(p.id), 'Plantilla eliminada')
                  }
                  onDescargar={(p) => descargarPlantilla(p).catch((e: unknown) => setError(mensajeDe(e)))}
                />
              ))}
          </div>
        </>
      )}

      {editando && (
        <EditorMapeo
          plantilla={editando}
          onCerrar={() => setEditando(null)}
          onGuardado={(p) => {
            setEditando(p)
            setAviso('Mapeo guardado')
            recargar()
          }}
        />
      )}
      {aviso && <div className="toast">{aviso}</div>}
    </main>
  )
}

function TarjetaPlantilla({
  t,
  onSubir,
  onEditar,
  onActivar,
  onBorrar,
  onDescargar,
}: {
  t: PlantillasTipo
  onSubir: (f: File) => Promise<void>
  onEditar: (p: Plantilla) => void
  onActivar: (p: Plantilla) => void
  onBorrar: (p: Plantilla) => void
  onDescargar: (p: Plantilla) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [subiendo, setSubiendo] = useState(false)
  const activa = t.activa
  const anteriores = t.historial.filter((p) => !p.activa)

  return (
    <section className="card plantilla-tipo">
      <div className="card-head">
        <div>
          <h2>
            Evaluación {t.tipo_nombre.toLowerCase()} {!t.motor_disponible && <span className="tag tag-preparacion">Motor en preparación</span>}
          </h2>
          <p>
            {activa
              ? `Plantilla propia · subida el ${fecha(activa.subida_en)}${activa.subida_por ? ` por ${activa.subida_por}` : ''}`
              : t.usa_plantilla_del_sistema
                ? 'Sin plantilla propia: se usa la plantilla de ejemplo del sistema.'
                : 'Sin plantilla: suba la de la entidad para poder generar el informe.'}
          </p>
        </div>
        <button className="btn btn-primary btn-sm" type="button" disabled={subiendo} onClick={() => input.current?.click()}>
          {subiendo ? <span className="spinner" /> : <Icono nombre="subir" tam={15} />} {activa ? 'Reemplazar' : 'Subir plantilla'}
        </button>
        <input
          ref={input}
          type="file"
          accept=".xlsx"
          hidden
          onChange={async (e) => {
            const f = e.target.files?.[0]
            e.target.value = ''
            if (!f) return
            setSubiendo(true)
            await onSubir(f)
            setSubiendo(false)
          }}
        />
      </div>

      {activa && (
        <>
          <div className="plantilla-archivo">
            <Icono nombre="documento" tam={18} />
            <strong style={{ flex: 1, overflowWrap: 'anywhere' }}>{activa.nombre_original}</strong>
            <span className="pill" data-estado={activa.inspeccion.valida && !activa.inspeccion.problemas.length ? 'cumple' : 'revisar'}>
              <span className="dot" /> {activa.inspeccion.valida && !activa.inspeccion.problemas.length ? 'Lista' : 'Revisar mapeo'}
            </span>
          </div>
          <p className="small muted" style={{ margin: '8px 0' }}>
            {activa.inspeccion.hojas_proponente} hojas de proponente · {activa.inspeccion.hojas.length} hojas en total
          </p>
          {activa.inspeccion.problemas.length > 0 && (
            <ul className="small plantilla-problemas">
              {activa.inspeccion.problemas.slice(0, 4).map((p) => (
                <li key={p}>{p}</li>
              ))}
              {activa.inspeccion.problemas.length > 4 && <li>y {activa.inspeccion.problemas.length - 4} más…</li>}
            </ul>
          )}
          <div className="acciones">
            <button className="btn btn-secondary btn-sm" type="button" onClick={() => onEditar(activa)}>
              <Icono nombre="lapiz" tam={15} /> Ajustar mapeo
            </button>
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => onDescargar(activa)}>
              <Icono nombre="descargar" tam={15} /> Descargar
            </button>
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => onBorrar(activa)}>
              <Icono nombre="x" tam={15} /> Quitar
            </button>
          </div>
        </>
      )}

      {anteriores.length > 0 && (
        <details className="plantilla-historial">
          <summary className="small">Versiones anteriores ({anteriores.length})</summary>
          {anteriores.map((p) => (
            <div key={p.id} className="plantilla-archivo small">
              <span style={{ flex: 1, overflowWrap: 'anywhere' }}>
                {p.nombre_original} · {fecha(p.subida_en)}
              </span>
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => onActivar(p)}>
                Volver a usar
              </button>
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => onDescargar(p)} aria-label="Descargar">
                <Icono nombre="descargar" tam={14} />
              </button>
            </div>
          ))}
        </details>
      )}
    </section>
  )
}

const CAMPOS_TEXTO: { clave: keyof MapeoPlantilla; nombre: string; ayuda?: string }[] = [
  { clave: 'prefijo_codigo', nombre: 'Sigla de la entidad', ayuda: 'Se antepone al código del proceso (ej. ICCU).' },
  { clave: 'hoja_proponente_patron', nombre: 'Nombre de las hojas por proponente', ayuda: 'Expresión regular; ^P-\\d+$ = P-01, P-02…' },
  { clave: 'celda_titulo', nombre: 'Celda del título' },
  { clave: 'celda_objeto', nombre: 'Celda del objeto del proceso' },
  { clave: 'celda_nombre_proponente', nombre: 'Celda del nombre del proponente' },
  { clave: 'columna_resultado', nombre: 'Columna del resultado (SI/NO)' },
  { clave: 'columna_detalle', nombre: 'Columna del detalle (documento o motivo)' },
  { clave: 'texto_cumple', nombre: 'Texto cuando cumple' },
  { clave: 'texto_no_cumple', nombre: 'Texto cuando no cumple' },
  { clave: 'texto_revisar', nombre: 'Texto cuando hay que revisar' },
]

function EditorMapeo({ plantilla, onCerrar, onGuardado }: { plantilla: Plantilla; onCerrar: () => void; onGuardado: (p: Plantilla) => void }) {
  const [mapeo, setMapeo] = useState<MapeoPlantilla>(plantilla.mapeo)
  const [guardando, setGuardando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function guardar() {
    setGuardando(true)
    setError(null)
    try {
      onGuardado(await ajustarMapeo(plantilla.id, mapeo))
    } catch (e) {
      setError(mensajeDe(e))
    } finally {
      setGuardando(false)
    }
  }

  const nombreRequisito = (n: string) => REQUISITOS.find((r) => String(r.numero) === n)?.titulo ?? `Requisito ${n}`

  return (
    <>
      <div className="overlay" onClick={onCerrar} />
      <div className="dialogo dialogo-ancho" role="dialog" aria-modal="true" aria-labelledby="titulo-mapeo">
        <div className="card-head">
          <div>
            <h2 id="titulo-mapeo">Mapeo de la plantilla</h2>
            <p>Dónde escribe MiEvaluador cada dato dentro de «{plantilla.nombre_original}».</p>
          </div>
          <button type="button" className="btn btn-ghost btn-icon" onClick={onCerrar} aria-label="Cerrar">
            <Icono nombre="x" />
          </button>
        </div>

        <div className="grid-2" style={{ gap: 14 }}>
          {CAMPOS_TEXTO.map((c) => (
            <div key={c.clave} className="field">
              <label htmlFor={`m-${c.clave}`}>{c.nombre}</label>
              <input
                id={`m-${c.clave}`}
                className="input"
                value={(mapeo[c.clave] as string | null) ?? ''}
                onChange={(e) => setMapeo({ ...mapeo, [c.clave]: e.target.value || null })}
              />
              {c.ayuda && <span className="hint">{c.ayuda}</span>}
            </div>
          ))}
        </div>

        <h3 className="grupo-titulo" style={{ marginTop: 20 }}>
          Fila de cada requisito (en la primera hoja de proponente)
        </h3>
        <div className="tabla-wrap" style={{ maxHeight: 340, overflow: 'auto' }}>
          <table className="tabla">
            <thead>
              <tr>
                <th>Requisito</th>
                <th style={{ width: 90 }}>Fila</th>
                <th>Texto encontrado en esa fila</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(mapeo.filas_por_requisito).map(([req, fila]) => {
                const texto = plantilla.inspeccion.filas[req]
                return (
                  <tr key={req}>
                    <td className="small">
                      <strong>{req}.</strong> {nombreRequisito(req)}
                    </td>
                    <td>
                      <input
                        className="input select-sm"
                        type="number"
                        min={1}
                        value={fila}
                        onChange={(e) =>
                          setMapeo({ ...mapeo, filas_por_requisito: { ...mapeo.filas_por_requisito, [req]: Number(e.target.value) } })
                        }
                      />
                    </td>
                    <td className="small" style={{ color: texto ? 'var(--ink-2)' : 'var(--bad)' }}>
                      {texto || 'Fila vacía: revise el número'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="small muted" style={{ marginTop: 8 }}>
          El texto encontrado se actualiza al guardar. Compare cada requisito con el texto de su fila para confirmar que calzan.
        </p>

        {error && (
          <div className="callout callout-bad" style={{ marginTop: 12 }} role="alert">
            <Icono nombre="alerta" />
            <div>{error}</div>
          </div>
        )}
        <div className="dialogo-pie">
          <button type="button" className="btn btn-ghost" onClick={onCerrar}>
            Cerrar
          </button>
          <button type="button" className="btn btn-primary" onClick={guardar} disabled={guardando}>
            {guardando ? <span className="spinner" /> : 'Guardar y revisar'}
          </button>
        </div>
      </div>
    </>
  )
}
