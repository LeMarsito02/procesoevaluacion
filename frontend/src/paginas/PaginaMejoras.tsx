import { useEffect, useMemo, useState } from 'react'
import Icono from '../components/Icono'
import {
  causasDeRevision,
  requisitosNoAutomatizados,
  type CausaDeRevision,
  type RequisitoNoAutomatizado,
} from '../evaluaciones'
import { mensajeDe } from '../http'

const CLASES: Record<string, string> = {
  exclusion: 'el pliego dice qué NO sirve',
  exigencia: 'el pliego pide algo',
  regla_lectura: 'cómo contar o leer',
}

/** Qué programar primero, sacado de los pliegos que ya se evaluaron.
 *
 * Hay dos razones por las que una persona tiene que mirar una oferta, y se
 * arreglan de forma distinta: o el pliego exige algo que el programa no sabe
 * verificar (hay que programar la verificación), o el programa sí sabe y la
 * lectura falló en esa oferta (hay que mejorar la lectura). Por eso van en dos
 * listas, y cada una se ordena por el trabajo humano que ahorraría resolverla.
 *
 * Nada de esto cambia una evaluación: es la hoja de ruta. */
export default function PaginaMejoras() {
  const [requisitos, setRequisitos] = useState<RequisitoNoAutomatizado[] | undefined>()
  const [causas, setCausas] = useState<CausaDeRevision[] | undefined>()
  const [error, setError] = useState<string | null>(null)
  const [soloExclusiones, setSoloExclusiones] = useState(false)
  const [area, setArea] = useState<string>('')

  useEffect(() => {
    requisitosNoAutomatizados()
      .then(setRequisitos)
      .catch((e) => setError(mensajeDe(e, 'No se pudo leer el registro de requisitos.')))
    causasDeRevision()
      .then(setCausas)
      .catch((e) => setError(mensajeDe(e, 'No se pudieron leer las causas de revisión.')))
  }, [])

  const visibles = useMemo(() => {
    let lista = requisitos ?? []
    if (soloExclusiones) lista = lista.filter((r) => r.clase === 'exclusion')
    if (area) lista = lista.filter((r) => r.area === area)
    return lista
  }, [requisitos, soloExclusiones, area])

  const exclusiones = (requisitos ?? []).filter((r) => r.clase === 'exclusion').length
  const asumidos = (requisitos ?? []).filter((r) => r.veces_asumido > 0).length

  return (
    <main className="pagina">
      <header className="pagina-head">
        <div>
          <h1>Qué falta automatizar</h1>
          <p>
            Sale de los pliegos que ya se evaluaron, no de suposiciones. Se llena solo con cada proceso y no cambia
            ninguna evaluación: un requisito anotado aquí sigue mandando su lote a revisión hasta que alguien lo mire.
          </p>
        </div>
      </header>

      {error && <div className="callout callout-bad">{error}</div>}

      <section className="card">
        <div className="card-head">
          <div>
            <h2>Requisitos que los pliegos exigen y el programa no verifica</h2>
            <p>
              Esto se arregla programando una verificación nueva. Ordenados por las veces que una persona tuvo que
              asumirlos, que es el trabajo que ya se hizo y se repetirá en el próximo proceso.
            </p>
          </div>
        </div>
        <div className="acciones" style={{ marginBottom: 12 }}>
          <span className="small muted">
            {(requisitos ?? []).length} requisitos · {exclusiones} exclusiones · {asumidos} ya asumidos por alguien
          </span>
          <label className="small">
            <input type="checkbox" checked={soloExclusiones} onChange={(e) => setSoloExclusiones(e.target.checked)} />{' '}
            solo exclusiones
          </label>
          <select value={area} onChange={(e) => setArea(e.target.value)} aria-label="Área">
            <option value="">todas las áreas</option>
            <option value="tecnica">técnica</option>
            <option value="financiera">financiera</option>
          </select>
        </div>
        {soloExclusiones && (
          <div className="callout callout-warn" style={{ marginBottom: 12 }}>
            <Icono nombre="alerta" />
            <div>
              Las exclusiones son las de más riesgo: el pliego dice qué no sirve, así que si nadie las mira se podría
              contar un contrato que no debía contar.
            </div>
          </div>
        )}
        <div className="tabla-wrap">
          <table className="tabla">
            <thead>
              <tr>
                <th>Asumido</th>
                <th>Procesos</th>
                <th>Qué es</th>
                <th>Requisito</th>
                <th>Lo que dice el pliego</th>
              </tr>
            </thead>
            <tbody>
              {visibles.map((r) => (
                <tr key={r.clave} data-problema={r.clase === 'exclusion'}>
                  <td>{r.veces_asumido || '—'}</td>
                  <td>
                    {r.veces}
                    {r.procesos.length > 0 && <div className="small muted">{r.procesos.slice(-3).join(', ')}</div>}
                  </td>
                  <td className="small">{CLASES[r.clase] ?? r.clase}</td>
                  <td>{r.requisito}</td>
                  <td className="small muted">{r.cita ? `«${r.cita}»` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {requisitos !== undefined && visibles.length === 0 && (
          <p className="small muted">Nada por aquí con ese filtro.</p>
        )}
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="card-head">
          <div>
            <h2>Lecturas que sí sabemos hacer y fallaron</h2>
            <p>
              Esto se arregla mejorando una lectura que ya existe. Se cuenta por oferta, porque eso es la revisión
              humana: una lectura que falla en 48 de 98 ofertas cuesta 48 revisiones.
            </p>
          </div>
        </div>
        <div className="tabla-wrap">
          <table className="tabla">
            <thead>
              <tr>
                <th>Ofertas</th>
                <th>Área</th>
                <th>Ámbito</th>
                <th>Causa</th>
                <th>Un ejemplo real</th>
              </tr>
            </thead>
            <tbody>
              {(causas ?? []).map((c) => (
                <tr key={`${c.area}-${c.clave}`}>
                  <td>{c.ofertas}</td>
                  <td className="small">{c.area}</td>
                  <td className="small">{c.ambito === 'proceso' ? 'del pliego' : 'de la oferta'}</td>
                  <td>{c.clave}</td>
                  <td className="small muted">
                    {c.ejemplo}
                    {c.procesos.length > 0 && <div className="small muted">{c.procesos.slice(-3).join(', ')}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {causas !== undefined && causas.length === 0 && (
          <p className="small muted">Todavía no se ha evaluado ninguna oferta que haya ido a revisión.</p>
        )}
      </section>
    </main>
  )
}
