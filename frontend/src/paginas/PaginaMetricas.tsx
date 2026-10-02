import { useEffect, useState } from 'react'
import Icono from '../components/Icono'
import { mensajeDe, pedirJson } from '../http'
import { useSesion } from '../sesion'

/** Métricas de uso de la entidad (administrador de la entidad y
 * superadministrador). Definiciones en Backend/evaluaciones/metricas.py. */

interface Area {
  clave: string
  nombre: string
  evaluaciones: number
  evaluadas: number
  aprobadas: number
  ofertas: number
  verificaciones: number
  verificadas_sistema: number
  porcentaje_sistema: number | null
  revisadas_personas: number
  correcciones: number
  pendientes: number
  segundos_por_oferta: number | null
  horas_ahorradas: number
}

interface Metricas {
  periodo: { anio: number | null; mes: number | null; anios_disponibles: number[] }
  entidad_id: string | null
  entidades?: { id: string; nombre: string }[]
  procesos: { creados: number; evaluados: number; aprobados: number }
  modalidades: { clave: string; nombre: string; procesos: number; ofertas: number; promedio_ofertas: number | null }[]
  areas: Area[]
  totales: {
    ofertas: number
    evaluaciones_de_oferta: number
    verificaciones: number
    verificadas_sistema: number
    porcentaje_sistema: number | null
    revisadas_personas: number
    correcciones: number
    pendientes: number
    documentos_soporte: number
    documentos_aportados: number
    horas_ahorradas: number
  }
  tiempos: { segundos_por_oferta: number | null; ofertas_medidas: number; dias_hasta_aprobar: number | null }
  control: { muestras: number; verificaciones_revisadas: number; conformes: number; hallazgos: number; porcentaje_conforme: number | null }
  mensual: { mes: number; procesos: number; ofertas: number }[]
  causas_revision: { area: string; requisito: number; titulo: string; casos: number }[]
  minutos_por_verificacion: Record<string, number>
}

const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
const entero = (n: number | null | undefined) => (n == null ? '—' : n.toLocaleString('es-CO', { maximumFractionDigits: 0 }))
const pct = (n: number | null | undefined) => (n == null ? '—' : `${(n * 100).toLocaleString('es-CO', { maximumFractionDigits: 0 })} %`)
function duracion(segundos: number | null | undefined): string {
  if (segundos == null) return '—'
  if (segundos < 60) return `${Math.round(segundos)} s`
  const m = Math.floor(segundos / 60)
  const s = Math.round(segundos % 60)
  return s ? `${m} min ${s} s` : `${m} min`
}

function Kpi({ etiqueta, valor, detalle, tono }: { etiqueta: string; valor: string; detalle?: string; tono?: 'ok' | 'warn' }) {
  return (
    <div className="kpi" data-tone={tono}>
      <div className="kpi-label">{etiqueta}</div>
      <div className="kpi-value">{valor}</div>
      {detalle && <div className="kpi-sub">{detalle}</div>}
    </div>
  )
}

export default function PaginaMetricas() {
  const { usuario } = useSesion()!
  const esSuper = usuario.rol === 'superadmin'
  const [anio, setAnio] = useState<number | null>(new Date().getFullYear())
  const [mes, setMes] = useState<number | null>(null)
  const [entidad, setEntidad] = useState<string>('')
  const [datos, setDatos] = useState<Metricas | null>(null)
  const [error, setError] = useState<string | null>(null)
  const consulta = new URLSearchParams({
    ...(anio ? { anio: String(anio) } : {}),
    ...(anio && mes ? { mes: String(mes) } : {}),
    ...(esSuper && entidad ? { entidad_id: entidad } : {}),
  }).toString()
  // La consulta cuyos datos se ven: si no es la actual, se está cargando.
  const [cargada, setCargada] = useState<string | null>(null)
  const cargando = cargada !== consulta

  useEffect(() => {
    let vivo = true
    pedirJson<Metricas>(`/api/metricas?${consulta}`)
      .then((d) => vivo && (setDatos(d), setError(null)))
      .catch((e: unknown) => vivo && setError(mensajeDe(e)))
      .finally(() => vivo && setCargada(consulta))
    return () => {
      vivo = false
    }
  }, [consulta])

  const t = datos?.totales
  const anios = datos?.periodo.anios_disponibles ?? []
  const nombreEntidad = esSuper
    ? (datos?.entidades?.find((e) => e.id === entidad)?.nombre ?? 'Todas las entidades')
    : (usuario.entidad?.nombre ?? '')
  const periodo = !anio ? 'Todo el tiempo' : mes ? `${MESES[mes - 1]} de ${anio}` : `Año ${anio}`
  const maxMes = Math.max(1, ...(datos?.mensual.map((m) => m.ofertas) ?? [1]))

  return (
    <main className="page metricas">
      <div className="page-head">
        <div>
          <div className="eyebrow">Métricas · {nombreEntidad}</div>
          <h1>Uso y rendimiento de MiEvaluador</h1>
          <p>
            {periodo}. Procesos según su fecha de creación en la plataforma. Cifras agregadas: no incluyen proponentes ni
            códigos de proceso.
          </p>
        </div>
        <div className="page-head-acciones no-imprimir">
          <button className="btn btn-secondary" type="button" onClick={() => window.print()} disabled={!datos}>
            <Icono nombre="descargar" tam={16} /> Exportar
          </button>
        </div>
      </div>

      <section className="metricas-filtros card no-imprimir" aria-label="Filtros">
        {esSuper && (
          <div className="field">
            <label htmlFor="m-entidad">Entidad</label>
            <select id="m-entidad" className="select" value={entidad} onChange={(e) => setEntidad(e.target.value)}>
              <option value="">Todas las entidades</option>
              {datos?.entidades?.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.nombre}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label htmlFor="m-anio">Año</label>
          <select
            id="m-anio"
            className="select"
            value={anio ?? ''}
            onChange={(e) => {
              setAnio(e.target.value ? Number(e.target.value) : null)
              if (!e.target.value) setMes(null)
            }}
          >
            <option value="">Todo el tiempo</option>
            {[...new Set([new Date().getFullYear(), ...anios])].sort((a, b) => b - a).map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="m-mes">Mes</label>
          <select id="m-mes" className="select" value={mes ?? ''} disabled={!anio} onChange={(e) => setMes(e.target.value ? Number(e.target.value) : null)}>
            <option value="">Todo el año</option>
            {MESES.map((m, i) => (
              <option key={m} value={i + 1}>
                {m}
              </option>
            ))}
          </select>
        </div>
        {cargando && <span className="spinner oscuro" role="status" aria-label="Cargando métricas" />}
      </section>

      {error && (
        <div className="callout callout-bad" role="alert">
          {error}
        </div>
      )}

      {datos && t && (
        <>
          <section className="kpis" aria-label="Resumen">
            <Kpi etiqueta="Procesos evaluados" valor={entero(datos.procesos.evaluados)} detalle={`de ${entero(datos.procesos.creados)} creados · ${entero(datos.procesos.aprobados)} con área aprobada`} />
            <Kpi etiqueta="Ofertas evaluadas" valor={entero(t.ofertas)} detalle={`${entero(t.evaluaciones_de_oferta)} evaluaciones entre las tres áreas`} />
            <Kpi
              etiqueta="Verificadas por el sistema"
              valor={pct(t.porcentaje_sistema)}
              detalle={`${entero(t.verificadas_sistema)} de ${entero(t.verificaciones)} verificaciones, con su soporte`}
              tono="ok"
            />
            <Kpi
              etiqueta="Tiempo por oferta"
              valor={duracion(datos.tiempos.segundos_por_oferta)}
              detalle={datos.tiempos.ofertas_medidas ? `promedio de máquina en ${entero(datos.tiempos.ofertas_medidas)} evaluaciones` : 'sin evaluaciones medidas en el periodo'}
            />
            <Kpi etiqueta="Documentos revisados" valor={entero(t.documentos_soporte + t.documentos_aportados)} detalle={`${entero(t.documentos_soporte)} de las ofertas · ${entero(t.documentos_aportados)} consultados o aportados`} />
            <Kpi etiqueta="Revisadas por personas" valor={entero(t.revisadas_personas)} detalle={`${entero(t.correcciones)} cambiaron la decisión del sistema`} />
            <Kpi etiqueta="Pendientes de revisión" valor={entero(t.pendientes)} detalle="verificaciones que esperan a una persona" tono={t.pendientes ? 'warn' : undefined} />
            <Kpi etiqueta="Horas de trabajo ahorradas" valor={entero(t.horas_ahorradas)} detalle="estimación con el tiempo manual de cada verificación" />
          </section>

          <section className="card metricas-bloque">
            <h2>Ofertas por proceso</h2>
            <p className="small muted">Promedio de proponentes en los procesos evaluados, según la modalidad.</p>
            <div className="metricas-modalidades">
              {datos.modalidades
                .filter((m) => m.procesos || m.clave !== 'otra')
                .map((m) => (
                  <div key={m.clave} className="metricas-modalidad">
                    <div className="kpi-label">{m.nombre}</div>
                    <div className="kpi-value">{m.promedio_ofertas == null ? '—' : m.promedio_ofertas.toLocaleString('es-CO')}</div>
                    <div className="kpi-sub">
                      ofertas por proceso · {entero(m.procesos)} {m.procesos === 1 ? 'proceso' : 'procesos'}, {entero(m.ofertas)} ofertas
                    </div>
                  </div>
                ))}
            </div>
          </section>

          <section className="card metricas-bloque">
            <h2>Por área de evaluación</h2>
            <div className="tabla-wrap">
              <table className="tabla">
                <thead>
                  <tr>
                    <th scope="col">Área</th>
                    <th scope="col">Evaluaciones</th>
                    <th scope="col">Ofertas</th>
                    <th scope="col">Verificaciones</th>
                    <th scope="col">Verificadas por el sistema</th>
                    <th scope="col">Revisadas por personas</th>
                    <th scope="col">Pendientes</th>
                    <th scope="col">Tiempo por oferta</th>
                  </tr>
                </thead>
                <tbody>
                  {datos.areas.map((a) => (
                    <tr key={a.clave}>
                      <th scope="row">{a.nombre}</th>
                      <td>
                        {entero(a.evaluadas)}
                        <span className="small muted"> · {entero(a.aprobadas)} aprobadas</span>
                      </td>
                      <td>{entero(a.ofertas)}</td>
                      <td>{entero(a.verificaciones)}</td>
                      <td>
                        <div className="metricas-barra" title={`${entero(a.verificadas_sistema)} de ${entero(a.verificaciones)}`}>
                          <span style={{ width: `${(a.porcentaje_sistema ?? 0) * 100}%` }} />
                        </div>
                        <strong>{pct(a.porcentaje_sistema)}</strong>
                      </td>
                      <td>
                        {entero(a.revisadas_personas)}
                        {a.correcciones > 0 && <span className="small muted"> · {entero(a.correcciones)} corregidas</span>}
                      </td>
                      <td>{entero(a.pendientes)}</td>
                      <td>{duracion(a.segundos_por_oferta)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {anio && !mes && (
            <section className="card metricas-bloque">
              <h2>Ofertas evaluadas mes a mes · {anio}</h2>
              <div className="metricas-meses" role="list" aria-label={`Ofertas por mes en ${anio}`}>
                {datos.mensual.map((m) => (
                  <div
                    key={m.mes}
                    role="listitem"
                    className="metricas-mes"
                    aria-label={`${MESES[m.mes - 1]}: ${m.ofertas} ofertas en ${m.procesos} procesos`}
                    title={`${MESES[m.mes - 1]}: ${m.ofertas} ofertas en ${m.procesos} procesos`}
                  >
                    <span className="metricas-mes-valor" aria-hidden="true">
                      {m.ofertas || ''}
                    </span>
                    <span className="metricas-mes-barra" style={{ height: `${(m.ofertas / maxMes) * 100}%` }} aria-hidden="true" />
                    <span className="metricas-mes-nombre" aria-hidden="true">
                      {MESES[m.mes - 1].slice(0, 3)}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}

          <div className="metricas-dos">
            <section className="card metricas-bloque">
              <h2>Control de la verificación</h2>
              <dl className="metricas-lista">
                <div>
                  <dt>Muestras de control</dt>
                  <dd>{entero(datos.control.muestras)}</dd>
                </div>
                <div>
                  <dt>Verificaciones revisadas en las muestras</dt>
                  <dd>{entero(datos.control.verificaciones_revisadas)}</dd>
                </div>
                <div>
                  <dt>Conformes</dt>
                  <dd>{pct(datos.control.porcentaje_conforme)}</dd>
                </div>
                <div>
                  <dt>Hallazgos (pasaron a revisión en todo el proceso)</dt>
                  <dd>{entero(datos.control.hallazgos)}</dd>
                </div>
                <div>
                  <dt>Días promedio hasta aprobar un área</dt>
                  <dd>{datos.tiempos.dias_hasta_aprobar == null ? '—' : datos.tiempos.dias_hasta_aprobar.toLocaleString('es-CO', { maximumFractionDigits: 1 })}</dd>
                </div>
              </dl>
            </section>

            <section className="card metricas-bloque">
              <h2>Lo que más pasa a revisión</h2>
              {datos.causas_revision.length === 0 ? (
                <p className="small muted">Nada pendiente en el periodo.</p>
              ) : (
                <ol className="metricas-causas">
                  {datos.causas_revision.map((c) => (
                    <li key={`${c.area}-${c.requisito}`}>
                      <span>
                        <strong>{c.titulo}</strong>
                        <span className="small muted"> · {c.area}</span>
                      </span>
                      <span className="metricas-causa-n">{entero(c.casos)}</span>
                    </li>
                  ))}
                </ol>
              )}
              <p className="small muted" style={{ marginTop: 8 }}>
                Requisitos que el sistema no pudo confirmar solo y mandó a una persona. Son los candidatos a automatizar.
              </p>
            </section>
          </div>
          <p className="small muted">
            Tiempo por oferta: tiempo de máquina, sin los procesos de demostración. Horas ahorradas: estimación con{' '}
            {datos.minutos_por_verificacion.juridica} min por verificación jurídica, {datos.minutos_por_verificacion.tecnica} técnica y{' '}
            {datos.minutos_por_verificacion.financiera} financiera.
          </p>
        </>
      )}
    </main>
  )
}
