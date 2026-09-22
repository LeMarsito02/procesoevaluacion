import { useEffect, useMemo, useState } from 'react'
import Icono from '../components/Icono'
import { mensajeDe, pedirJson } from '../http'

/** Tablero comercial de rendimiento: el programa contra evaluaciones reales ya
 * hechas por entidades (manage.py medir_rendimiento). Se exporta a PDF con la
 * impresión del navegador. */

interface Estadisticas {
  decisiones: number
  automaticas: number
  automatizacion: number | null
  indebidas: number
  precision: number | null
  techo_error: number | null
  revision: number
  revision_justificada: number
}

interface ResumenPrueba extends Estadisticas {
  clave: string
  area: Area
  nombre: string
  a_ciegas: boolean
  nota: string
  proponentes: number
  proponentes_resueltos_solos: number
  proponentes_resueltos_solos_mal: number
  segundos_por_proponente: number | null
  segundos_mediana: number | null
  por_requisito: (Estadisticas & { requisito: string; titulo: string })[]
}

interface Global {
  pruebas: number
  proponentes: number
  decisiones: number
  automaticas: number
  automatizacion: number | null
  indebidas: number
  techo_error: number | null
  horas_ahorradas: number
  minutos_manuales: Record<string, number>
}

interface Rendimiento {
  foto: { global: Global; global_a_ciegas: Global; pruebas: ResumenPrueba[]; confianza: number } | null
  creada_en: string | null
  nota: string
  proponentes_evaluados: number
  segundos_por_proponente: number | null
}

const pct = (v: number | null | undefined, dec = 1) =>
  v == null ? '—' : `${(v * 100).toLocaleString('es-CO', { minimumFractionDigits: dec, maximumFractionDigits: dec })} %`
const entero = (v: number) => v.toLocaleString('es-CO')
const AREA = { juridica: 'Jurídica', tecnica: 'Técnica', financiera: 'Financiera' } as const
type Area = keyof typeof AREA
const AREAS = Object.keys(AREA) as Area[]

function duracion(segundos: number | null | undefined): string {
  if (segundos == null) return '—'
  if (segundos < 90) return `${Math.round(segundos)} s`
  return `${(segundos / 60).toLocaleString('es-CO', { maximumFractionDigits: 1 })} min`
}

function Tile({ etiqueta, valor, detalle }: { etiqueta: string; valor: string; detalle?: string }) {
  return (
    <div className="rend-tile">
      <div className="rend-tile-etiqueta">{etiqueta}</div>
      <div className="rend-tile-valor">{valor}</div>
      {detalle && <div className="rend-tile-detalle">{detalle}</div>}
    </div>
  )
}

export default function PaginaRendimiento() {
  const [datos, setDatos] = useState<Rendimiento | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [minutos, setMinutos] = useState<Record<string, number>>({ juridica: 6, tecnica: 10, financiera: 15 })
  const [area, setArea] = useState<Area>('juridica')

  useEffect(() => {
    pedirJson<Rendimiento>('/api/plataforma/rendimiento')
      .then((d) => {
        setDatos(d)
        if (d.foto) setMinutos((m) => ({ ...m, ...d.foto!.global.minutos_manuales }))
      })
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [])

  const pruebas = datos?.foto?.pruebas ?? []
  const horas = useMemo(
    () => pruebas.reduce((s, p) => s + (p.automaticas * (minutos[p.area] ?? 0)) / 60, 0),
    [pruebas, minutos],
  )
  // Por requisito: todas las pruebas del área juntas.
  const requisitos = useMemo(() => {
    const suma = new Map<string, { titulo: string; automaticas: number; decisiones: number; indebidas: number }>()
    for (const p of pruebas.filter((x) => x.area === area)) {
      for (const r of p.por_requisito) {
        const a = suma.get(r.titulo) ?? { titulo: r.titulo, automaticas: 0, decisiones: 0, indebidas: 0 }
        a.automaticas += r.automaticas
        a.decisiones += r.decisiones
        a.indebidas += r.indebidas
        suma.set(r.titulo, a)
      }
    }
    return [...suma.values()].sort((a, b) => b.automaticas / b.decisiones - a.automaticas / a.decisiones)
  }, [pruebas, area])

  if (error)
    return (
      <main className="page">
        <div className="callout callout-bad" role="alert">
          <Icono nombre="alerta" />
          <div>{error}</div>
        </div>
      </main>
    )
  if (!datos)
    return (
      <main className="page">
        <div className="vacio">
          <span className="spinner oscuro" />
        </div>
      </main>
    )
  const foto = datos.foto
  const g = foto?.global
  const ciegas = foto?.global_a_ciegas

  return (
    <main className="page rendimiento">
      <div className="page-head">
        <div>
          <div className="eyebrow">MiEvaluador · rendimiento comprobado</div>
          <h1>Resultados contra evaluaciones reales</h1>
          <p>
            Cada cifra compara lo que el programa decidió solo con lo que decidió el abogado o el técnico de la entidad en su
            informe oficial, requisito por requisito.
          </p>
        </div>
        <div className="page-head-acciones no-imprimir">
          <button className="btn btn-primary" type="button" onClick={() => window.print()} disabled={!foto}>
            <Icono nombre="descargar" tam={16} /> Exportar informe
          </button>
        </div>
      </div>

      {!foto || !g ? (
        <div className="callout callout-warn">
          <Icono nombre="info" />
          <div>
            Todavía no hay mediciones. Se generan con <code>manage.py medir_rendimiento</code> después de medir contra
            procesos reales.
          </div>
        </div>
      ) : (
        <>
          <section className="rend-hero card">
            <div className="rend-hero-cifra">{entero(g.indebidas)}</div>
            <div className="rend-hero-texto">
              <strong>{g.indebidas === 1 ? 'aprobación indebida' : 'aprobaciones indebidas'}</strong> en{' '}
              {entero(g.automaticas)} decisiones que el programa tomó solo.
              <span>
                Con {pct(foto.confianza, 0)} de confianza, el error está por debajo de <strong>{pct(g.techo_error, 2)}</strong>.
                Lo que el programa no puede confirmar lo manda a revisión: nunca lo aprueba.
              </span>
            </div>
          </section>

          <section className="rend-tiles">
            <Tile etiqueta="Procesos reales medidos" valor={entero(g.pruebas)} detalle={`${entero(g.proponentes)} ofertas evaluadas`} />
            <Tile
              etiqueta="Resuelto sin intervención"
              valor={pct(g.automatizacion, 0)}
              detalle={`${entero(g.automaticas)} de ${entero(g.decisiones)} verificaciones`}
            />
            <Tile
              etiqueta="Precisión de lo automático"
              valor={pct(g.automaticas ? 1 - g.indebidas / g.automaticas : null, 2)}
              detalle="coincide con el evaluador"
            />
            <Tile
              etiqueta="Tiempo por oferta"
              valor={duracion(
                pruebas.reduce((s, p) => s + (p.segundos_por_proponente ?? 0) * p.proponentes, 0) /
                  Math.max(1, pruebas.reduce((s, p) => s + (p.segundos_por_proponente != null ? p.proponentes : 0), 0)),
              )}
              detalle="en promedio, todos los requisitos"
            />
            <Tile
              etiqueta="Horas de trabajo ahorradas"
              valor={horas.toLocaleString('es-CO', { maximumFractionDigits: 0 })}
              detalle={`con ${minutos.juridica} min por requisito jurídico, ${minutos.tecnica} técnico y ${minutos.financiera} financiero`}
            />
          </section>

          <div className="rend-minutos no-imprimir">
            <span className="small muted">Minutos que tarda una persona por requisito:</span>
            {AREAS.filter((a) => pruebas.some((p) => p.area === a)).map((a) => (
              <label key={a} className="small">
                {AREA[a]}{' '}
                <input
                  className="input select-sm"
                  type="number"
                  min={1}
                  max={120}
                  value={minutos[a]}
                  onChange={(e) => setMinutos((m) => ({ ...m, [a]: Math.max(1, Number(e.target.value) || 1) }))}
                  style={{ width: 70 }}
                />
              </label>
            ))}
          </div>

          <section className="card rend-seccion">
            <h2>Por proceso</h2>
            <div className="rend-tabla-envoltura">
              <table className="rend-tabla">
                <thead>
                  <tr>
                    <th>Proceso</th>
                    <th>Área</th>
                    <th className="num">Ofertas</th>
                    <th className="num">Resuelto solo</th>
                    <th className="num">Aprobaciones indebidas</th>
                    <th className="num">Error máximo (95 %)</th>
                    <th className="num">Tiempo por oferta</th>
                  </tr>
                </thead>
                <tbody>
                  {pruebas.map((p) => (
                    <tr key={p.clave}>
                      <td>
                        {p.nombre}
                        {p.nota && <div className="small muted">{p.nota}</div>}
                      </td>
                      <td>{AREA[p.area]}</td>
                      <td className="num">{entero(p.proponentes)}</td>
                      <td className="num">{pct(p.automatizacion, 1)}</td>
                      <td className="num">{entero(p.indebidas)}</td>
                      <td className="num">{pct(p.techo_error, 2)}</td>
                      <td className="num">{duracion(p.segundos_mediana ?? p.segundos_por_proponente)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {ciegas && ciegas.pruebas > 0 && (
              <p className="small muted" style={{ marginTop: 10 }}>
                Medición a ciegas (ofertas que no se usaron para desarrollar el programa): {entero(ciegas.indebidas)} aprobaciones
                indebidas en {entero(ciegas.automaticas)} decisiones automáticas; error máximo {pct(ciegas.techo_error, 2)}.
              </p>
            )}
          </section>

          <section className="card rend-seccion">
            <div className="rend-seccion-cabeza">
              <h2>Qué resuelve solo, requisito por requisito</h2>
              <div className="segmentado no-imprimir" role="tablist">
                {AREAS.filter((a) => pruebas.some((p) => p.area === a)).map((a) => (
                  <button key={a} type="button" role="tab" aria-selected={area === a} onClick={() => setArea(a)}>
                    {AREA[a]}
                  </button>
                ))}
              </div>
            </div>
            <p className="small muted">
              Porcentaje de verificaciones que el programa resolvió sin intervención. El resto quedó para revisión con el motivo
              y el documento señalado.
            </p>
            <div className="rend-barras" role="table" aria-label={`Automatización por requisito, área ${AREA[area]}`}>
              {requisitos.map((r) => {
                const valor = r.decisiones ? r.automaticas / r.decisiones : 0
                return (
                  <div
                    className="rend-barra"
                    role="row"
                    key={r.titulo}
                    title={`${r.titulo}: ${pct(valor)} (${entero(r.automaticas)} de ${entero(r.decisiones)}) · ${entero(r.indebidas)} indebidas`}
                  >
                    <span className="rend-barra-nombre" role="cell">{r.titulo}</span>
                    <span className="rend-barra-pista" role="cell">
                      <span className="rend-barra-relleno" style={{ width: `${valor * 100}%` }} />
                    </span>
                    <span className="rend-barra-valor" role="cell">{pct(valor, 0)}</span>
                  </div>
                )
              })}
              {requisitos.length === 0 && <p className="small muted">Sin mediciones de esta área.</p>}
            </div>
          </section>

          <section className="card rend-seccion rend-metodo">
            <h2>Cómo se mide</h2>
            <ul>
              <li>
                Se toman procesos de contratación reales ya evaluados por una entidad pública, con su informe oficial de
                evaluación, y el programa los evalúa desde cero con los mismos documentos de las ofertas.
              </li>
              <li>
                <strong>Aprobación indebida:</strong> el programa aprobó solo un requisito que el evaluador rechazó. Es el único
                error que llegaría al informe sin que nadie lo viera.
              </li>
              <li>
                <strong>Error máximo:</strong> cota superior exacta (binomial) de la tasa de aprobaciones indebidas con{' '}
                {pct(foto.confianza, 0)} de confianza.
              </li>
              <li>
                Todo lo que el programa no puede confirmar va a revisión con el motivo; la decisión final siempre es de una persona
                y queda registrada.
              </li>
              <li>La inteligencia artificial corre en los servidores del programa: ningún documento sale a servicios externos.</li>
            </ul>
            <p className="small muted">
              Medición del {datos.creada_en ? new Date(datos.creada_en).toLocaleDateString('es-CO', { dateStyle: 'long' }) : '—'}.
              Horas ahorradas: verificaciones resueltas solas × minutos que tarda una persona por requisito.
            </p>
          </section>
        </>
      )}
    </main>
  )
}
