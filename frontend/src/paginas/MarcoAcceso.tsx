import type { ReactNode } from 'react'

/** Diseño de las pantallas sin sesión: marca a la izquierda, formulario a la derecha. */
export default function MarcoAcceso({ children }: { children: ReactNode }) {
  return (
    <div className="acceso">
      <aside className="acceso-marca">
        <div className="acceso-centro">
          <img src="/logo-mievaluador.png" alt="MiEvaluador by LeMarTek" className="acceso-logo" />
          <h2>Evaluaciones de proponentes, claras y trazables.</h2>
          <p>Requisitos habilitantes jurídicos, técnicos y financieros revisados en minutos, con cada decisión respaldada en el documento.</p>
        </div>
        <span className="acceso-pie">
          © {new Date().getFullYear()} LeMarTek Labs S.A.S. · NIT 902069061-9
        </span>
      </aside>
      <main className="acceso-panel">
        <div className="acceso-caja">{children}</div>
      </main>
    </div>
  )
}
