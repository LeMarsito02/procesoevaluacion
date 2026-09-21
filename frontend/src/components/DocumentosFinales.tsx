import { useEffect, useState } from 'react'
import type { EvaluacionResumen } from '../evaluaciones'
import {
  descargarExpediente,
  descargarReporteWord,
  guardarArchivo,
  listarExpedientes,
  regenerarExpediente,
  type ExpedienteInfo,
} from '../historico'
import { mensajeDe } from '../http'
import Icono from './Icono'

const fecha = (iso: string) => new Date(iso).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' })
const megas = (b: number | null) => (b === null ? '' : `${(b / 1e6).toFixed(1)} MB`)

/** Reporte formal en Word y expediente permanente (.zip) de la evaluación. */
export default function DocumentosFinales({ resumen }: { resumen: EvaluacionResumen }) {
  const [expedientes, setExpedientes] = useState<ExpedienteInfo[]>([])
  const [ocupado, setOcupado] = useState<string | null>(null)
  const [regenerando, setRegenerando] = useState(false)
  const [cargados, setCargados] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const aprobada = resumen.estado === 'aprobada'
  const enCurso = expedientes.some((e) => e.estado === 'pendiente' || e.estado === 'generando')

  useEffect(() => {
    let vigente = true
    const cargar = () =>
      listarExpedientes(resumen.id)
        .then((l) => vigente && setExpedientes(l))
        .catch(() => undefined)
        .finally(() => vigente && setCargados(true))
    cargar()
    const t = enCurso || aprobada ? window.setInterval(cargar, 5000) : undefined
    return () => {
      vigente = false
      window.clearInterval(t)
    }
  }, [resumen.id, enCurso, aprobada])

  async function descargar(clave: string, f: () => Promise<{ blob: Blob; nombre: string | null }>, porDefecto: string) {
    setOcupado(clave)
    setError(null)
    try {
      const { blob, nombre } = await f()
      guardarArchivo(blob, nombre ?? porDefecto)
    } catch (e) {
      setError(mensajeDe(e))
    } finally {
      setOcupado(null)
    }
  }

  const vigente = expedientes.find((e) => e.estado === 'listo')

  return (
    <>
      <section className="card" style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
        <div className="dropzone-icon" style={{ background: 'var(--brand-soft)' }}>
          <Icono nombre="documento" tam={22} />
        </div>
        <div style={{ flex: 1 }}>
          <strong>Reporte formal de evaluación (.docx)</strong>
          <div className="small muted">
            Proceso, responsables, metodología y, por proponente, cada requisito: aprobado automáticamente por MiEvaluador o
            validado manualmente, con quién, cuándo y por qué.
            {!aprobada && ' Mientras no se apruebe, sale como borrador.'}
          </div>
        </div>
        <button
          className="btn btn-secondary btn-lg"
          type="button"
          disabled={ocupado !== null}
          onClick={() => descargar('word', () => descargarReporteWord(resumen.id), `REPORTE ${resumen.proceso_codigo}.docx`)}
        >
          {ocupado === 'word' ? <span className="spinner oscuro" /> : <Icono nombre="descargar" />} Descargar Word
        </button>
      </section>

      <section className="card">
        <div className="card-head">
          <div>
            <h2>Expediente del proceso (.zip)</h2>
            <p>
              Archivo histórico permanente: documentos con los que se verificó cada requisito, certificados aportados por el
              evaluador, informe Excel, reporte Word y registro con huellas de integridad. No se borra con la retención de
              documentos.
            </p>
          </div>
          <Icono nombre="escudo" tam={22} />
        </div>
        {!cargados ? (
          <p className="small muted" role="status" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="spinner oscuro" /> Cargando el expediente…
          </p>
        ) : !aprobada && expedientes.length === 0 ? (
          <p className="small muted">Se genera automáticamente cuando el jefe del área aprueba la evaluación.</p>
        ) : (
          <div className="lista-expedientes">
            {expedientes.map((e) => (
              <div key={e.id} className="plantilla-archivo">
                <Icono nombre={e.estado === 'listo' ? 'check' : e.estado === 'error' ? 'alerta' : 'reloj'} tam={16} />
                <span style={{ flex: 1 }} className="small">
                  <strong>Versión {e.version}</strong> · {fecha(e.creado_en)}
                  {e.estado === 'listo' && ` · ${megas(e.tamano)}`}
                  {e.estado === 'pendiente' && ' · en fila para generarse'}
                  {e.estado === 'generando' && ' · generando…'}
                  {e.estado === 'error' && <span style={{ color: 'var(--bad)' }}> · no se pudo generar: {e.avisos}</span>}
                  {e.estado === 'listo' && e.avisos && <span className="muted" title={e.avisos}> · con avisos</span>}
                  {e === vigente && e.sha256 && <div className="muted" style={{ fontSize: 11 }}>SHA-256 {e.sha256}</div>}
                </span>
                {e.estado === 'listo' && (
                  <button
                    type="button"
                    className={`btn btn-sm ${e === vigente ? 'btn-primary' : 'btn-ghost'}`}
                    disabled={ocupado !== null}
                    onClick={() => descargar(e.id, () => descargarExpediente(resumen.id, e.id), `EXPEDIENTE ${resumen.proceso_codigo} v${e.version}.zip`)}
                  >
                    {ocupado === e.id ? <span className="spinner" /> : <Icono nombre="descargar" tam={14} />} Descargar
                  </button>
                )}
              </div>
            ))}
            {aprobada && resumen.puede_gestionar && !enCurso && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                style={{ alignSelf: 'flex-start' }}
                disabled={regenerando}
                onClick={() => {
                  setRegenerando(true)
                  regenerarExpediente(resumen.id)
                    .then((nuevo) => setExpedientes((l) => [nuevo, ...l]))
                    .catch((err: unknown) => setError(mensajeDe(err)))
                    .finally(() => setRegenerando(false))
                }}
              >
                {regenerando ? <span className="spinner oscuro" /> : <Icono nombre="deshacer" tam={14} />} Generar una nueva versión
              </button>
            )}
          </div>
        )}
        {error && <p className="small" style={{ color: 'var(--bad)', marginTop: 8 }}>{error}</p>}
      </section>
    </>
  )
}
