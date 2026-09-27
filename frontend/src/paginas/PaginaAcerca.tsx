/** Ficha de transparencia algorítmica (Directiva Conjunta 007 de 2025): qué es
 * MiEvaluador, qué hace y qué no, con qué modelos y bajo qué controles. Se arma
 * con la configuración real del servidor. */
import { useEffect, useState } from 'react'
import Icono from '../components/Icono'
import { descargarFicha, verFicha, type FichaTransparencia } from '../evaluaciones'
import { mensajeDe } from '../http'

function Lista({ items }: { items: string[] }) {
  return (
    <ul style={{ margin: '8px 0 0', paddingLeft: 20, lineHeight: 1.6 }}>
      {items.map((x) => (
        <li key={x}>{x}</li>
      ))}
    </ul>
  )
}

export default function PaginaAcerca() {
  const [ficha, setFicha] = useState<FichaTransparencia | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    verFicha()
      .then(setFicha)
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [])

  if (error)
    return (
      <main className="page page-narrow">
        <div className="vacio">
          <h3>No se pudo cargar la ficha</h3>
          <p>{error}</p>
        </div>
      </main>
    )
  if (!ficha)
    return (
      <main className="page page-narrow">
        <div className="cargando-pagina" role="status">
          <span className="spinner oscuro" /> Cargando…
        </div>
      </main>
    )

  const m = ficha.medicion
  return (
    <main className="page page-narrow">
      <div className="page-head">
        <div>
          <div className="eyebrow">Transparencia algorítmica</div>
          <h1>Acerca de MiEvaluador</h1>
          <p>
            {ficha.responsable} · versión {ficha.version}
          </p>
        </div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() =>
            descargarFicha()
              .then(({ blob, nombre }) => {
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a')
                a.href = url
                a.download = nombre ?? 'FICHA TRANSPARENCIA MIEVALUADOR.docx'
                a.click()
                URL.revokeObjectURL(url)
              })
              .catch((e: unknown) => setError(mensajeDe(e)))
          }
        >
          <Icono nombre="descargar" /> Descargar ficha
        </button>
      </div>

      <section className="card">
        <h2>Finalidad</h2>
        <p>{ficha.finalidad}</p>
      </section>
      <section className="card" style={{ marginTop: 16 }}>
        <h2>Qué hace</h2>
        <Lista items={ficha.que_hace} />
        <h2 style={{ marginTop: 16 }}>Qué no hace</h2>
        <Lista items={ficha.que_no_hace} />
      </section>
      <section className="card" style={{ marginTop: 16 }}>
        <h2>Cómo decide el sistema</h2>
        <p>{ficha.como_decide_el_sistema}</p>
        <h2 style={{ marginTop: 16 }}>Control humano</h2>
        <Lista items={ficha.control_humano} />
      </section>
      <section className="card" style={{ marginTop: 16 }}>
        <h2>Modelos de inteligencia artificial</h2>
        <div className="tabla-wrap" style={{ marginTop: 8 }}>
          <table className="tabla">
            <thead>
              <tr>
                <th>Uso</th>
                <th>Modelo</th>
                <th>Licencia</th>
                <th>Dónde se ejecuta</th>
              </tr>
            </thead>
            <tbody>
              {ficha.modelos.map((x) => (
                <tr key={x.modelo + x.uso}>
                  <td>{x.uso}</td>
                  <td>{x.modelo}</td>
                  <td>{x.licencia}</td>
                  <td>{x.donde_se_ejecuta}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {ficha.atribucion && (
          <p className="small" style={{ marginTop: 8 }}>
            <strong>{ficha.atribucion}</strong>
          </p>
        )}
      </section>
      <section className="card" style={{ marginTop: 16 }}>
        <h2>Datos que trata</h2>
        <p>{ficha.datos_tratados}</p>
        {m && (
          <>
            <h2 style={{ marginTop: 16 }}>Desempeño medido</h2>
            <p>
              Medición del {m.fecha.slice(0, 10)} contra evaluaciones reales: {m.proponentes} proponentes, {m.decisiones} decisiones,{' '}
              {m.verificadas_por_el_sistema} verificadas por el sistema y {m.verificaciones_contradichas_por_el_evaluador} contradichas por
              el evaluador
              {m.limite_superior_de_error_95 !== null && ` (límite superior de error del ${(m.limite_superior_de_error_95 * 100).toFixed(2)} % con 95 % de confianza)`}.
            </p>
          </>
        )}
        <h2 style={{ marginTop: 16 }}>Cómo pedir explicaciones</h2>
        <p>{ficha.como_pedir_explicaciones}</p>
        <h2 style={{ marginTop: 16 }}>Marco de referencia</h2>
        <Lista items={ficha.marco} />
      </section>
    </main>
  )
}
