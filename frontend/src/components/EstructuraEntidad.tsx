import { useCallback, useEffect, useRef, useState } from 'react'
import { useDialogo } from '../dialogo'
import { cargaEquipo, type MiembroCarga } from '../evaluaciones'
import { crearDependencia, editarDependencia, listarDependencias, type Dependencia, type DependenciaIn } from '../estructura'
import { mensajeDe } from '../http'
import Icono from './Icono'

const AREAS = [
  { tipo: 'juridica', nombre: 'Jurídica' },
  { tipo: 'financiera', nombre: 'Financiera' },
  { tipo: 'tecnica', nombre: 'Técnica' },
]

interface Props {
  entidadId: string
  esSuper: boolean
  onAviso: (t: string) => void
}

/** Estructura de evaluación de la entidad: qué dependencia evalúa cada área,
 * quiénes son sus jefes (designan el comité y aprueban) y sus integrantes. */
export default function EstructuraEntidad({ entidadId, esSuper, onAviso }: Props) {
  const [dependencias, setDependencias] = useState<Dependencia[] | null>(null)
  const [equipo, setEquipo] = useState<MiembroCarga[]>([])
  const [editando, setEditando] = useState<{ dependencia: Dependencia | null; tipo: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const id = esSuper ? entidadId : null

  const recargar = useCallback(() => {
    listarDependencias(id)
      .then(setDependencias)
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [id])

  useEffect(() => {
    recargar()
    cargaEquipo(entidadId)
      .then(setEquipo)
      .catch(() => setEquipo([]))
  }, [recargar, entidadId])

  return (
    <section className="card estructura">
      <div className="card-head">
        <div>
          <h2>Estructura de evaluación</h2>
          <p>
            Qué dependencia evalúa cada área. Sus jefes designan el comité de cada proceso y aprueban; sus integrantes
            aparecen primero al designar. En la técnica, las palabras clave sugieren la dependencia según el objeto del
            contrato.
          </p>
        </div>
        <Icono nombre="usuarios" tam={22} />
      </div>
      {error && (
        <div className="callout callout-bad" role="alert">
          {error}
        </div>
      )}
      {!dependencias ? (
        <span className="spinner oscuro" role="status" aria-label="Cargando estructura" />
      ) : (
        <div className="estructura-areas">
          {AREAS.map((a) => {
            const deArea = dependencias.filter((d) => d.tipo === a.tipo)
            return (
              <div key={a.tipo} className="estructura-area">
                <h3>Evaluación {a.nombre.toLowerCase()}</h3>
                {deArea.length === 0 && <p className="small muted">Sin dependencias: la evalúa el área completa.</p>}
                {deArea.map((d) => (
                  <div key={d.id} className="estructura-dependencia" data-activa={d.activa}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <strong>{d.nombre}</strong>
                      {!d.activa && <span className="pill pill-xs" data-estado="no_aplica" style={{ marginLeft: 6 }}>Inactiva</span>}
                      <div className="small muted">
                        Jefe: {d.jefes.map((j) => j.nombre_completo).join(', ') || 'sin asignar'} · {d.miembros.length} integrantes
                      </div>
                      {d.palabras_clave && (
                        <div className="small muted">Palabras clave: {d.palabras_clave.split('\n').filter(Boolean).join(', ')}</div>
                      )}
                    </div>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditando({ dependencia: d, tipo: d.tipo })}>
                      <Icono nombre="lapiz" tam={14} /> Editar
                    </button>
                  </div>
                ))}
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditando({ dependencia: null, tipo: a.tipo })}>
                  <Icono nombre="mas" tam={14} /> Agregar dependencia
                </button>
              </div>
            )
          })}
        </div>
      )}
      {editando && (
        <EditorDependencia
          inicial={editando.dependencia}
          tipo={editando.tipo}
          equipo={equipo}
          onCerrar={() => setEditando(null)}
          onGuardar={async (datos) => {
            if (editando.dependencia) await editarDependencia(editando.dependencia.id, datos, id)
            else await crearDependencia(datos, id)
            setEditando(null)
            onAviso('Estructura guardada')
            recargar()
          }}
        />
      )}
    </section>
  )
}

type Cargo = 'fuera' | 'integrante' | 'jefe'
const CARGOS: { valor: Cargo; nombre: string }[] = [
  { valor: 'fuera', nombre: 'No participa' },
  { valor: 'integrante', nombre: 'Integrante' },
  { valor: 'jefe', nombre: 'Jefe' },
]

function iniciales(nombre: string): string {
  return nombre
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('')
}

function EditorDependencia({
  inicial,
  tipo,
  equipo,
  onCerrar,
  onGuardar,
}: {
  inicial: Dependencia | null
  tipo: string
  equipo: MiembroCarga[]
  onCerrar: () => void
  onGuardar: (d: DependenciaIn) => Promise<void>
}) {
  const caja = useRef<HTMLDivElement>(null)
  useDialogo(caja)
  const [d, setD] = useState<DependenciaIn>({
    tipo,
    nombre: inicial?.nombre ?? '',
    palabras_clave: inicial?.palabras_clave ?? '',
    jefes: inicial?.jefes.map((j) => j.id) ?? [],
    miembros: inicial?.miembros.map((m) => m.id) ?? [],
    activa: inicial?.activa ?? true,
    orden: inicial?.orden ?? 0,
  })
  const [busqueda, setBusqueda] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)

  useEffect(() => {
    const tecla = (e: KeyboardEvent) => e.key === 'Escape' && onCerrar()
    window.addEventListener('keydown', tecla)
    return () => window.removeEventListener('keydown', tecla)
  }, [onCerrar])

  const cargo = (id: string): Cargo => (d.jefes.includes(id) ? 'jefe' : d.miembros.includes(id) ? 'integrante' : 'fuera')
  function asignar(id: string, nuevo: Cargo) {
    setD((x) => ({
      ...x,
      jefes: nuevo === 'jefe' ? [...x.jefes.filter((i) => i !== id), id] : x.jefes.filter((i) => i !== id),
      miembros: nuevo === 'integrante' ? [...x.miembros.filter((i) => i !== id), id] : x.miembros.filter((i) => i !== id),
    }))
  }

  // Los que ya están en la dependencia, primero; luego el resto por nombre.
  const personas = equipo
    .filter((m) => m.rol !== 'consulta')
    .filter((m) => {
      const q = busqueda.trim().toLowerCase()
      return !q || m.nombre_completo.toLowerCase().includes(q) || m.email.toLowerCase().includes(q)
    })
    .sort((a, b) => Number(cargo(b.id) !== 'fuera') - Number(cargo(a.id) !== 'fuera') || a.nombre_completo.localeCompare(b.nombre_completo))
  const nJefes = d.jefes.length
  const nIntegrantes = d.miembros.length

  return (
    <>
      <div className="overlay" style={{ zIndex: 60 }} onClick={onCerrar} />
      <div ref={caja} className="dialogo dialogo-ancho editor-dependencia" style={{ zIndex: 61 }} role="dialog" aria-modal="true" aria-labelledby="titulo-dependencia" tabIndex={-1}>
        <form
          onSubmit={async (e) => {
            e.preventDefault()
            setGuardando(true)
            setError(null)
            try {
              await onGuardar(d)
            } catch (err) {
              setError(mensajeDe(err))
              setGuardando(false)
            }
          }}
        >
          <div className="card-head">
            <div>
              <h2 id="titulo-dependencia">{inicial ? 'Editar dependencia' : 'Nueva dependencia'}</h2>
              <p>Quién la integra y quién la dirige. El jefe designa el comité de cada proceso de la dependencia y aprueba sus evaluaciones.</p>
            </div>
            <button className="btn btn-ghost btn-icon" type="button" onClick={onCerrar} aria-label="Cerrar">
              <Icono nombre="x" />
            </button>
          </div>
          {error && (
            <div className="callout callout-bad" role="alert">
              {error}
            </div>
          )}

          <div className="editor-dependencia-datos">
            <div className="field">
              <label htmlFor="dep-nombre">Nombre</label>
              <input id="dep-nombre" className="input" value={d.nombre} onChange={(e) => setD({ ...d, nombre: e.target.value })} placeholder="Ej.: Área de Concesiones" required />
            </div>
            <div className="field">
              <label htmlFor="dep-area">Evalúa el área</label>
              <select id="dep-area" className="select" value={d.tipo} onChange={(e) => setD({ ...d, tipo: e.target.value })}>
                {AREAS.map((a) => (
                  <option key={a.tipo} value={a.tipo}>
                    {a.nombre}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="field">
            <label htmlFor="dep-palabras">Palabras clave del objeto del contrato</label>
            <textarea
              id="dep-palabras"
              className="textarea"
              rows={2}
              value={d.palabras_clave}
              onChange={(e) => setD({ ...d, palabras_clave: e.target.value })}
              placeholder={'Una por línea, p. ej.:\nconcesión\nAPP'}
              aria-describedby="dep-palabras-ayuda"
            />
            <span id="dep-palabras-ayuda" className="small muted">
              Sirven para sugerir esta dependencia al crear un proceso. Opcional si el área tiene una sola dependencia.
            </span>
          </div>

          <div className="editor-dependencia-personas">
            <div className="editor-dependencia-personas-cabeza">
              <h3>Personas</h3>
              <span className="small muted">
                {nJefes} {nJefes === 1 ? 'jefe' : 'jefes'} · {nIntegrantes} {nIntegrantes === 1 ? 'integrante' : 'integrantes'}
              </span>
            </div>
            <div className="field" style={{ marginBottom: 8 }}>
              <label htmlFor="dep-buscar" className="sr-only">
                Buscar persona
              </label>
              <input id="dep-buscar" className="input" type="search" placeholder="Buscar por nombre o correo…" value={busqueda} onChange={(e) => setBusqueda(e.target.value)} />
            </div>
            <ul className="lista-personas">
              {personas.length === 0 && <li className="small muted lista-personas-vacio">Nadie coincide con la búsqueda.</li>}
              {personas.map((m) => {
                const actual = cargo(m.id)
                return (
                  <li key={m.id} className="persona-fila" data-cargo={actual}>
                    <span className="avatar" aria-hidden="true">
                      {iniciales(m.nombre_completo)}
                    </span>
                    <span className="persona-datos">
                      <strong>{m.nombre_completo}</strong>
                      <span className="small muted">
                        {m.email} · {m.rol_nombre}
                      </span>
                    </span>
                    <span className="segmented persona-cargo" role="group" aria-label={`Cargo de ${m.nombre_completo} en la dependencia`}>
                      {CARGOS.map((c) => (
                        <button key={c.valor} type="button" aria-pressed={actual === c.valor} onClick={() => asignar(m.id, c.valor)}>
                          {c.nombre}
                        </button>
                      ))}
                    </span>
                  </li>
                )
              })}
            </ul>
          </div>

          <div className="editor-dependencia-pie">
            <label className="check-linea">
              <input type="checkbox" checked={d.activa} onChange={(e) => setD({ ...d, activa: e.target.checked })} /> Activa: se puede elegir en procesos nuevos
            </label>
            <div className="acciones">
              <button type="button" className="btn btn-ghost" onClick={onCerrar}>
                Cancelar
              </button>
              <button type="submit" className="btn btn-primary" disabled={guardando}>
                {guardando ? <span className="spinner" /> : <Icono nombre="check" tam={16} />} Guardar
              </button>
            </div>
          </div>
        </form>
      </div>
    </>
  )
}
