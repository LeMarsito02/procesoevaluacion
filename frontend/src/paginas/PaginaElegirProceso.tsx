import { useEffect, useState } from 'react'
import Icono from '../components/Icono'
import { listarOps } from '../ops'
import { navegar } from '../rutas'

/** Primer paso al crear: qué se va a hacer. La evaluación de un proceso de
 * selección y la prestación de servicios son trabajos distintos, cada uno
 * con su propio recorrido. */
export default function PaginaElegirProceso() {
  // null: aún no se sabe si la entidad tiene el módulo de prestación de servicios.
  const [licenciado, setLicenciado] = useState<boolean | null>(null)

  useEffect(() => {
    document.title = 'Nuevo · MiEvaluador'
    listarOps()
      .then((r) => setLicenciado(r.licenciado))
      .catch(() => setLicenciado(false))
  }, [])

  return (
    <main className="page elegir">
      <div className="elegir-cabecera">
        <div className="eyebrow">Nuevo</div>
        <h1>¿Qué va a hacer?</h1>
        <p>Elija el tipo de trabajo. Cada uno tiene su propio recorrido.</p>
      </div>

      <div className="elegir-tarjetas">
        <button type="button" className="elegir-tarjeta" data-tono="evaluacion" onClick={() => navegar('/procesos/nuevo/evaluacion')}>
          <span className="elegir-icono">
            <Icono nombre="balanza" tam={34} grosor={1.8} />
          </span>
          <span className="elegir-etiqueta">Proceso de selección</span>
          <strong>Evaluación</strong>
          <span className="elegir-texto">
            Licitaciones, concursos de méritos y selecciones abreviadas. Compara las ofertas de varios proponentes contra el
            pliego.
          </span>
          <ul>
            <li>Evaluación jurídica, técnica y financiera</li>
            <li>Comité evaluador e informe consolidado</li>
            <li>Requisitos tomados del pliego</li>
          </ul>
          <span className="elegir-accion">
            Crear evaluación <Icono nombre="flecha" tam={17} />
          </span>
        </button>

        <button
          type="button"
          className="elegir-tarjeta"
          data-tono="ops"
          data-bloqueada={licenciado === false}
          aria-disabled={licenciado === false}
          onClick={() => licenciado && navegar('/ops/nueva')}
        >
          {licenciado === false && (
            <span className="elegir-candado">
              <Candado /> Módulo no incluido
            </span>
          )}
          <span className="elegir-icono">
            <Icono nombre="usuarios" tam={34} grosor={1.8} />
          </span>
          <span className="elegir-etiqueta">Contratación directa</span>
          <strong>OPS</strong>
          <span className="elegir-texto">
            Prestación de servicios profesionales y de apoyo a la gestión. Verifica a una persona frente al perfil del
            estudio previo.
          </span>
          <ul>
            <li>Experiencia sin traslapes y franja de honorarios</li>
            <li>Lista de verificación de documentos</li>
            <li>Certificado de idoneidad en Word</li>
          </ul>
          {licenciado === false ? (
            <span className="elegir-accion elegir-accion-bloqueada">
              Este módulo tiene licencia aparte. Pídalo a LeMarTek para activarlo en su entidad.
            </span>
          ) : (
            <span className="elegir-accion">
              {licenciado === null ? <span className="spinner oscuro" /> : null} Crear OPS <Icono nombre="flecha" tam={17} />
            </span>
          )}
        </button>
      </div>

      <button type="button" className="enlace elegir-volver" onClick={() => navegar('/')}>
        Volver al inicio
      </button>
    </main>
  )
}

function Candado() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="4" y="11" width="16" height="10" rx="2.5" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  )
}
