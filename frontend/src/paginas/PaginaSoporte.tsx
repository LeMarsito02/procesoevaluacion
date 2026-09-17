import { useEffect, useState } from 'react'
import Icono from '../components/Icono'
import { accesosDisponibles, entrarComoSoporte, type Usuario } from '../cuentas'
import { mensajeDe } from '../http'
import { useSesion } from '../sesion'

const hora = (iso: string) => new Date(iso).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' })

/** Soporte de LeMarTek sin entidad elegida: solo ve las entidades que le dieron permiso. */
export default function PaginaSoporte({ onEntrar }: { onEntrar: (u: Usuario) => void }) {
  const { usuario } = useSesion()!
  const [accesos, setAccesos] = useState<Awaited<ReturnType<typeof accesosDisponibles>> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    accesosDisponibles()
      .then(setAccesos)
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [])

  return (
    <main className="page page-narrow">
      <div className="page-head">
        <div>
          <div className="eyebrow">Soporte LeMarTek</div>
          <h1>Hola, {usuario.nombre_completo.split(' ')[0]}</h1>
          <p>Solo puede ver una entidad si su administrador le dio acceso temporal. El acceso es de solo lectura y queda registrado.</p>
        </div>
      </div>
      {error && (
        <div className="callout callout-bad" role="alert">
          <Icono nombre="alerta" />
          <div>{error}</div>
        </div>
      )}
      {!accesos ? (
        <div className="vacio">
          <span className="spinner oscuro" />
        </div>
      ) : accesos.length === 0 ? (
        <div className="vacio card">
          <Icono nombre="escudo" tam={32} />
          <h3>Sin accesos vigentes</h3>
          <p>Cuando el administrador de una entidad le dé acceso, le llegará un correo y aparecerá aquí.</p>
        </div>
      ) : (
        <div className="tarjetas">
          {accesos.map((a) => (
            <article key={a.entidad.id} className="tarjeta-ev">
              <button
                type="button"
                className="tarjeta-ev-principal"
                onClick={() =>
                  entrarComoSoporte(a.entidad.id)
                    .then(onEntrar)
                    .catch((e: unknown) => setError(mensajeDe(e)))
                }
              >
                <h3>{a.entidad.nombre}</h3>
                <p className="small muted">{a.motivo}</p>
                <p className="small">
                  <Icono nombre="reloj" tam={13} /> Hasta {hora(a.expira_en)}
                </p>
              </button>
            </article>
          ))}
        </div>
      )}
    </main>
  )
}
