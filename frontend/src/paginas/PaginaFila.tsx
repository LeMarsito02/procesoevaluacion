import { useEffect, useState } from 'react'
import Icono from '../components/Icono'
import { estadoDeLaFila, type EstadoFilaGlobal } from '../evaluaciones'
import { formatDuracion } from '../format'
import { mensajeDe } from '../http'
import { useSesion } from '../sesion'
import TarjetaEvaluacion from './TarjetaEvaluacion'

export default function PaginaFila() {
  const { usuario } = useSesion()!
  const esSuper = usuario.rol === 'superadmin'
  const [estado, setEstado] = useState<EstadoFilaGlobal | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let vigente = true
    const cargar = () =>
      estadoDeLaFila()
        .then((e) => {
          if (!vigente) return
          setEstado(e)
          setError(null)
        })
        .catch((e: unknown) => vigente && setError(mensajeDe(e)))
    cargar()
    const t = window.setInterval(cargar, 5000)
    return () => {
      vigente = false
      window.clearInterval(t)
    }
  }, [])

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">{esSuper ? 'Plataforma' : usuario.entidad?.nombre}</div>
          <h1>Fila de evaluación</h1>
          <p>Lo que se está evaluando y lo que espera turno. Se actualiza cada 5 segundos.</p>
        </div>
      </div>
      {error && (
        <div className="callout callout-bad" style={{ marginBottom: 16 }} role="alert">
          <Icono nombre="alerta" />
          <div>{error}</div>
        </div>
      )}
      {!estado ? (
        <div className="vacio">
          <span className="spinner oscuro" />
        </div>
      ) : (
        <>
          {estado.capacidad_activa === 0 && (
            <div className="callout callout-warn" style={{ marginBottom: 16 }}>
              <Icono nombre="alerta" />
              <div>
                <strong>El servicio de evaluación no está activo.</strong> Las evaluaciones quedan en fila y empiezan en cuanto
                se reanude.
              </div>
            </div>
          )}
          <div className="kpis">
            <div className="kpi">
              <div className="kpi-label">Evaluando ahora</div>
              <div className="kpi-value">{estado.total_procesando}</div>
              <div className="kpi-sub">proponentes</div>
            </div>
            <div className="kpi" data-tone={estado.total_en_fila ? 'warn' : undefined}>
              <div className="kpi-label">En fila</div>
              <div className="kpi-value">{estado.total_en_fila}</div>
              <div className="kpi-sub">proponentes esperando turno</div>
            </div>
            <div className="kpi">
              <div className="kpi-label">Capacidad activa</div>
              <div className="kpi-value">{estado.capacidad_activa}</div>
              <div className="kpi-sub">proponentes a la vez</div>
            </div>
            <div className="kpi">
              <div className="kpi-label">Tiempo por proponente</div>
              <div className="kpi-value">{formatDuracion(estado.segundos_por_proponente * 1000)}</div>
              <div className="kpi-sub">promedio reciente</div>
            </div>
          </div>

          {esSuper && (
            <section className="seccion">
              <h2 className="seccion-titulo" style={{ color: 'var(--ink)' }}>
                Trabajadores
              </h2>
              <div className="tabla-wrap">
                <table className="tabla">
                  <thead>
                    <tr>
                      <th>Trabajador</th>
                      <th>Capacidad</th>
                      <th>Desde</th>
                      <th>Último latido</th>
                      <th>Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {estado.trabajadores.map((t) => (
                      <tr key={t.id}>
                        <td className="num small">{t.id}</td>
                        <td className="num">{t.capacidad}</td>
                        <td className="small muted">{new Date(t.iniciado_en).toLocaleString('es-CO')}</td>
                        <td className="small muted">{new Date(t.latido).toLocaleTimeString('es-CO')}</td>
                        <td>
                          <span className="pill" data-estado={t.activo ? 'cumple' : 'error'}>
                            <span className="dot" /> {t.activo ? 'Activo' : 'Sin respuesta'}
                          </span>
                        </td>
                      </tr>
                    ))}
                    {estado.trabajadores.length === 0 && (
                      <tr>
                        <td colSpan={5} className="vacio">
                          No hay trabajadores registrados.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section className="seccion">
            <h2 className="seccion-titulo" style={{ color: 'var(--ink)' }}>
              Evaluaciones en curso
            </h2>
            {estado.evaluaciones.length === 0 ? (
              <div className="vacio card">
                <h3>La fila está vacía</h3>
                <p>No hay evaluaciones esperando ni en proceso.</p>
              </div>
            ) : (
              <div className="tarjetas">
                {estado.evaluaciones.map((e) => (
                  <TarjetaEvaluacion key={e.id} e={e} mostrarEntidad={esSuper} />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </main>
  )
}
