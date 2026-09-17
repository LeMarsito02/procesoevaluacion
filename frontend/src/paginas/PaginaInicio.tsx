import { useEffect, useMemo, useState } from 'react'
import Icono from '../components/Icono'
import { asignarEvaluacion, cargaEquipo, misEvaluaciones, type EvaluacionResumen, type MiembroCarga } from '../evaluaciones'
import { mensajeDe } from '../http'
import { navegar } from '../rutas'
import { useSesion } from '../sesion'
import TarjetaEvaluacion from './TarjetaEvaluacion'

type Filtro = 'activas' | 'por_revisar' | 'aprobadas' | 'todas'

export default function PaginaInicio() {
  const { usuario } = useSesion()!
  const [evaluaciones, setEvaluaciones] = useState<EvaluacionResumen[] | null>(null)
  const [equipo, setEquipo] = useState<MiembroCarga[]>([])
  const [error, setError] = useState<string | null>(null)
  const [filtro, setFiltro] = useState<Filtro>('activas')
  const [busqueda, setBusqueda] = useState('')
  const [aviso, setAviso] = useState<string | null>(null)

  const gestiona = usuario.rol === 'admin_entidad' || usuario.rol === 'jefe_area'
  const puedeCrear = usuario.rol !== 'consulta' && usuario.rol !== 'superadmin'

  useEffect(() => {
    let vigente = true
    const cargar = () =>
      misEvaluaciones()
        .then((l) => vigente && setEvaluaciones(l))
        .catch((e: unknown) => vigente && setError(mensajeDe(e)))
    cargar()
    // Refresco periódico: el avance cambia mientras otros evalúan.
    const t = window.setInterval(cargar, 15000)
    return () => {
      vigente = false
      window.clearInterval(t)
    }
  }, [])

  useEffect(() => {
    if (!gestiona) return
    cargaEquipo()
      .then(setEquipo)
      .catch(() => setEquipo([]))
  }, [gestiona])

  useEffect(() => {
    if (!aviso) return
    const t = window.setTimeout(() => setAviso(null), 3000)
    return () => window.clearTimeout(t)
  }, [aviso])

  const porAsignar = (evaluaciones ?? []).filter((e) => e.estado === 'sin_asignar' && e.puede_gestionar)
  const mias = useMemo(() => {
    const q = busqueda.trim().toLowerCase()
    return (evaluaciones ?? [])
      .filter((e) => e.estado !== 'sin_asignar' || !e.puede_gestionar)
      .filter((e) => !q || `${e.proceso_codigo} ${e.proceso_objeto} ${e.responsable?.nombre_completo ?? ''}`.toLowerCase().includes(q))
      .filter((e) => {
        if (filtro === 'activas') return e.estado !== 'aprobada'
        if (filtro === 'por_revisar') return e.avance.pendientes > 0
        if (filtro === 'aprobadas') return e.estado === 'aprobada'
        return true
      })
  }, [evaluaciones, filtro, busqueda])

  const totales = useMemo(() => {
    const l = evaluaciones ?? []
    return {
      activas: l.filter((e) => e.estado !== 'aprobada').length,
      pendientes: l.reduce((s, e) => s + e.avance.pendientes, 0),
      porAsignar: porAsignar.length,
      aprobadas: l.filter((e) => e.estado === 'aprobada').length,
    }
  }, [evaluaciones, porAsignar.length])

  async function asignar(e: EvaluacionResumen, responsableId: string) {
    try {
      const nueva = await asignarEvaluacion(e.id, responsableId)
      setEvaluaciones((l) => l?.map((x) => (x.id === e.id ? nueva : x)) ?? null)
      setAviso(`Asignada a ${nueva.responsable?.nombre_completo}`)
      cargaEquipo().then(setEquipo).catch(() => undefined)
    } catch (err) {
      setAviso(mensajeDe(err))
    }
  }

  const primerNombre = usuario.nombre_completo.split(' ')[0]

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">{usuario.entidad?.nombre ?? 'MiEvaluador'}</div>
          <h1>Hola, {primerNombre}</h1>
          <p>{gestiona ? 'Evaluaciones de su equipo y las que tiene a cargo.' : 'Las evaluaciones que tiene a cargo.'}</p>
        </div>
        {puedeCrear && (
          <button className="btn btn-primary btn-lg" type="button" onClick={() => navegar('/procesos/nuevo')}>
            <Icono nombre="mas" /> Nuevo proceso
          </button>
        )}
      </div>

      {error && (
        <div className="callout callout-bad" style={{ marginBottom: 16 }} role="alert">
          <Icono nombre="alerta" />
          <div>{error}</div>
        </div>
      )}

      <div className="kpis">
        <div className="kpi">
          <div className="kpi-label">En curso</div>
          <div className="kpi-value">{totales.activas}</div>
          <div className="kpi-sub">evaluaciones sin aprobar</div>
        </div>
        <div className="kpi" data-tone={totales.pendientes ? 'warn' : undefined}>
          <div className="kpi-label">Por revisar</div>
          <div className="kpi-value">{totales.pendientes}</div>
          <div className="kpi-sub">requisitos que necesitan una decisión</div>
        </div>
        {gestiona ? (
          <div className="kpi" data-tone={totales.porAsignar ? 'warn' : undefined}>
            <div className="kpi-label">Por asignar</div>
            <div className="kpi-value">{totales.porAsignar}</div>
            <div className="kpi-sub">evaluaciones sin responsable</div>
          </div>
        ) : (
          <div className="kpi">
            <div className="kpi-label">Asignadas</div>
            <div className="kpi-value">{(evaluaciones ?? []).length}</div>
            <div className="kpi-sub">en total</div>
          </div>
        )}
        <div className="kpi" data-tone="ok">
          <div className="kpi-label">Aprobadas</div>
          <div className="kpi-value">{totales.aprobadas}</div>
          <div className="kpi-sub">con informe definitivo</div>
        </div>
      </div>

      {porAsignar.length > 0 && (
        <section className="seccion">
          <h2 className="seccion-titulo">
            <Icono nombre="alerta" tam={16} /> Por asignar
          </h2>
          <div className="tarjetas">
            {porAsignar.map((e) => {
              const candidatos = equipo.filter((m) => m.areas.includes(e.tipo))
              return (
                <TarjetaEvaluacion
                  key={e.id}
                  e={e}
                  accion={
                    <select className="select select-sm" value="" onChange={(ev) => ev.target.value && asignar(e, ev.target.value)} aria-label="Asignar a">
                      <option value="">Asignar a…</option>
                      {candidatos.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.nombre_completo} · {m.evaluaciones_activas} activas · {m.pendientes} por revisar
                        </option>
                      ))}
                    </select>
                  }
                />
              )
            })}
          </div>
        </section>
      )}

      <section className="seccion">
        <div className="toolbar">
          <div className="segmented" role="group" aria-label="Filtrar evaluaciones">
            {(
              [
                ['activas', 'En curso'],
                ['por_revisar', 'Con pendientes'],
                ['aprobadas', 'Aprobadas'],
                ['todas', 'Todas'],
              ] as [Filtro, string][]
            ).map(([id, nombre]) => (
              <button key={id} type="button" aria-pressed={filtro === id} onClick={() => setFiltro(id)}>
                {nombre}
              </button>
            ))}
          </div>
          <div className="input-group search" style={{ marginLeft: 'auto' }}>
            <Icono nombre="buscar" tam={16} />
            <input className="input" placeholder="Buscar proceso o responsable" value={busqueda} onChange={(e) => setBusqueda(e.target.value)} />
          </div>
        </div>

        {evaluaciones === null ? (
          <div className="vacio">
            <span className="spinner oscuro" />
          </div>
        ) : mias.length === 0 ? (
          <div className="vacio card">
            <h3>{evaluaciones.length === 0 ? 'Aún no tiene evaluaciones' : 'Nada con este filtro'}</h3>
            <p>
              {evaluaciones.length === 0
                ? puedeCrear
                  ? 'Cree un proceso o espere a que el jefe de su área le asigne una evaluación.'
                  : 'Cuando haya evaluaciones de su entidad las verá en "Procesos".'
                : 'Pruebe con otro filtro o búsqueda.'}
            </p>
          </div>
        ) : (
          <div className="tarjetas">
            {mias.map((e) => (
              <TarjetaEvaluacion key={e.id} e={e} />
            ))}
          </div>
        )}
      </section>
      {aviso && <div className="toast">{aviso}</div>}
    </main>
  )
}
