import { useCallback, useEffect, useState } from 'react'
import {
  agregarPersona,
  aportarDocumento,
  archivoAportado,
  obtenerAntecedentes,
  quitarAportado,
  quitarPersona,
  type Antecedentes,
  type PersonaVerificada,
  type RolPersona,
} from '../historico'
import { mensajeDe } from '../http'
import Icono from './Icono'

const AYUDA_TIPO: Record<string, string> = {
  persona_natural: 'Persona natural: registre al proponente con su cédula.',
  persona_juridica: 'Persona jurídica: registre la empresa (NIT) y su representante legal; el suplente solo si lo tiene.',
  consorcio: 'Consorcio: registre cada integrante (persona natural o jurídica) con sus representantes, y el representante del consorcio.',
  union_temporal: 'Unión temporal: registre cada integrante (persona natural o jurídica) con sus representantes, y el representante de la unión temporal.',
}

const fecha = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString('es-CO', { dateStyle: 'medium' })

interface Props {
  evaluacionId: string
  proponenteId: string
  soloLectura: boolean
  onVerPdf: (blob: Blob, titulo: string) => void
}

/** Personas cuyos antecedentes se verifican y certificados que el evaluador aportó. */
export default function AntecedentesProponente({ evaluacionId, proponenteId, soloLectura, onVerPdf }: Props) {
  const [datos, setDatos] = useState<Antecedentes | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [agregando, setAgregando] = useState<{ de: PersonaVerificada | null } | null>(null)
  const [subiendo, setSubiendo] = useState<{ persona: PersonaVerificada | null; requisito: number } | null>(null)

  const recargar = useCallback(() => {
    obtenerAntecedentes(evaluacionId, proponenteId)
      .then((d) => {
        setDatos(d)
        setError(null)
      })
      .catch((e: unknown) => setError(mensajeDe(e)))
  }, [evaluacionId, proponenteId])

  useEffect(() => {
    recargar()
  }, [recargar])

  async function accion(f: () => Promise<unknown>) {
    try {
      await f()
      recargar()
    } catch (e) {
      setError(mensajeDe(e))
    }
  }

  if (!datos) return error ? <p className="small" style={{ color: 'var(--bad)' }}>{error}</p> : null
  if (datos.requisitos.length === 0) return null

  const raiz = datos.personas.filter((p) => !p.de_id)
  const hijos = (id: string) => datos.personas.filter((p) => p.de_id === id)
  const ordenadas = raiz.flatMap((p) => [p, ...hijos(p.id)])
  const aportado = (persona: string | null, req: number) => datos.aportados.filter((d) => d.persona_id === persona && d.requisito === req)
  const sinCertificado = ordenadas.reduce(
    (n, per) => n + datos.requisitos.filter((r) => aportado(per.id, r.numero).length === 0 && !datos.encontrados[r.numero]).length,
    0,
  )

  return (
    <section className="antecedentes">
      <div className="grupo-titulo">Personas verificadas y antecedentes</div>
      <p className="small muted">
        {AYUDA_TIPO[datos.tipo_proponente ?? ''] ?? 'Registre las personas cuyos antecedentes se verifican.'} Si la oferta no trae un
        certificado, consúltelo en la fuente oficial y súbalo: queda en el expediente y en el reporte.
      </p>
      {error && <p className="small" style={{ color: 'var(--bad)' }}>{error}</p>}

      {ordenadas.length > 0 && (
        <div className="tabla-wrap" style={{ marginTop: 8 }}>
          <table className="tabla tabla-antecedentes">
            <thead>
              <tr>
                <th>Persona</th>
                {datos.requisitos.map((r) => (
                  <th key={r.numero} title={r.titulo}>
                    {r.corto}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ordenadas.map((per) => (
                <tr key={per.id}>
                  <td style={{ paddingLeft: per.de_id ? 26 : undefined }}>
                    <strong className="small">{per.nombre}</strong>
                    <div className="small muted">
                      {per.rol_nombre} · {per.tipo === 'juridica' ? 'NIT' : 'C.C.'} {per.documento}
                      {per.fecha_expedicion_documento && ` · exp. ${fecha(per.fecha_expedicion_documento)}`}
                    </div>
                    {!soloLectura && (
                      <div className="acciones" style={{ marginTop: 4 }}>
                        {per.tipo === 'juridica' && (
                          <button type="button" className="enlace" onClick={() => setAgregando({ de: per })}>
                            + representante
                          </button>
                        )}
                        <button type="button" className="enlace" style={{ color: 'var(--ink-3)' }} onClick={() => accion(() => quitarPersona(evaluacionId, per.id))}>
                          quitar
                        </button>
                      </div>
                    )}
                  </td>
                  {datos.requisitos.map((r) => {
                    const docs = aportado(per.id, r.numero)
                    return (
                      <td key={r.numero} className="celda-antecedente">
                        {docs.map((d) => (
                          <div key={d.id} className="aportado">
                            <button
                              type="button"
                              className="enlace"
                              title={`Aportado por ${d.subido_por ?? 'el evaluador'}${d.observacion ? ` · ${d.observacion}` : ''}`}
                              onClick={() =>
                                archivoAportado(evaluacionId, d.id)
                                  .then(({ blob }) => onVerPdf(blob, `${r.titulo} · ${per.nombre}`))
                                  .catch((e: unknown) => setError(mensajeDe(e)))
                              }
                            >
                              <Icono nombre="check" tam={12} grosor={3} /> {fecha(d.fecha_expedicion)}
                            </button>
                            {!soloLectura && (
                              <button type="button" className="enlace" aria-label="Quitar certificado" onClick={() => accion(() => quitarAportado(evaluacionId, d.id))}>
                                <Icono nombre="x" tam={11} />
                              </button>
                            )}
                          </div>
                        ))}
                        {docs.length === 0 &&
                          (soloLectura ? (
                            <span className="small muted">—</span>
                          ) : (
                            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSubiendo({ persona: per, requisito: r.numero })}>
                              <Icono nombre="subir" tam={13} /> Subir
                            </button>
                          ))}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="small muted" style={{ marginTop: 6 }}>
        En la oferta:{' '}
        {datos.requisitos.map((r, i) => (
          <span key={r.numero}>
            {i > 0 && ' · '}
            {r.corto} {datos.encontrados[r.numero] ? '✓' : '✗'}
          </span>
        ))}
        {ordenadas.length > 0 && sinCertificado > 0 && ` · ${sinCertificado} certificados por persona sin soporte`}
      </p>

      {!soloLectura && (
        <div className="acciones" style={{ marginTop: 8 }}>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAgregando({ de: null })}>
            <Icono nombre="mas" tam={14} /> Agregar persona
          </button>
        </div>
      )}

      {agregando && (
        <FormularioPersona
          de={agregando.de}
          sugerido={agregando.de ? null : datos.representante_legal}
          tipoProponente={datos.tipo_proponente}
          onCerrar={() => setAgregando(null)}
          onGuardar={(d) =>
            accion(async () => {
              await agregarPersona(evaluacionId, proponenteId, { ...d, de_id: agregando.de?.id ?? null })
              setAgregando(null)
            })
          }
        />
      )}
      {subiendo && (
        <FormularioCertificado
          titulo={`${datos.requisitos.find((r) => r.numero === subiendo.requisito)?.titulo} · ${subiendo.persona?.nombre ?? ''}`}
          onCerrar={() => setSubiendo(null)}
          onGuardar={(d) =>
            accion(async () => {
              await aportarDocumento(evaluacionId, proponenteId, { ...d, requisito: subiendo.requisito, persona_id: subiendo.persona?.id ?? null })
              setSubiendo(null)
            })
          }
        />
      )}
    </section>
  )
}

function FormularioPersona({
  de,
  sugerido,
  tipoProponente,
  onCerrar,
  onGuardar,
}: {
  de: PersonaVerificada | null
  sugerido: string | null
  tipoProponente: string | null
  onCerrar: () => void
  onGuardar: (d: { rol: RolPersona; tipo: 'natural' | 'juridica'; nombre: string; documento: string; fecha_expedicion_documento: string | null }) => void
}) {
  const plural = tipoProponente === 'consorcio' || tipoProponente === 'union_temporal'
  const [rol, setRol] = useState<RolPersona>(de ? 'representante_legal' : plural ? 'integrante' : tipoProponente === 'persona_natural' ? 'proponente' : 'representante_legal')
  const [tipo, setTipo] = useState<'natural' | 'juridica'>(de ? 'natural' : 'natural')
  const [nombre, setNombre] = useState(de ? '' : (sugerido ?? ''))
  const [documento, setDocumento] = useState('')
  const [expedicion, setExpedicion] = useState('')
  const esRepresentante = rol === 'representante_legal' || rol === 'suplente'

  return (
    <div className="formulario-inline">
      <strong className="small">{de ? `Representante de ${de.nombre}` : 'Nueva persona'}</strong>
      <div className="grid-persona">
        <select className="select select-sm" value={rol} onChange={(e) => setRol(e.target.value as RolPersona)} aria-label="Rol">
          {!de && <option value="proponente">Proponente</option>}
          {!de && <option value="integrante">Integrante (consorcio/UT)</option>}
          <option value="representante_legal">Representante legal</option>
          <option value="suplente">Representante legal suplente</option>
        </select>
        <select
          className="select select-sm"
          value={esRepresentante ? 'natural' : tipo}
          disabled={esRepresentante}
          onChange={(e) => setTipo(e.target.value as 'natural' | 'juridica')}
          aria-label="Tipo de persona"
        >
          <option value="natural">Persona natural</option>
          <option value="juridica">Persona jurídica</option>
        </select>
        <input className="input select-sm" placeholder={tipo === 'juridica' && !esRepresentante ? 'Razón social' : 'Nombre completo'} value={nombre} onChange={(e) => setNombre(e.target.value)} />
        <input className="input select-sm" placeholder={tipo === 'juridica' && !esRepresentante ? 'NIT' : 'Cédula'} value={documento} onChange={(e) => setDocumento(e.target.value)} />
        {(tipo === 'natural' || esRepresentante) && (
          <label className="small muted" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            Expedición de la cédula
            <input className="input select-sm" type="date" value={expedicion} onChange={(e) => setExpedicion(e.target.value)} />
          </label>
        )}
      </div>
      <div className="acciones" style={{ justifyContent: 'flex-end' }}>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCerrar}>
          Cancelar
        </button>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={nombre.trim().length < 3 || documento.trim().length < 4}
          onClick={() =>
            onGuardar({
              rol,
              tipo: esRepresentante ? 'natural' : tipo,
              nombre,
              documento,
              fecha_expedicion_documento: expedicion || null,
            })
          }
        >
          Agregar
        </button>
      </div>
    </div>
  )
}

function FormularioCertificado({
  titulo,
  onCerrar,
  onGuardar,
}: {
  titulo: string
  onCerrar: () => void
  onGuardar: (d: { fecha_expedicion: string; observacion: string; archivo: File }) => void
}) {
  const [archivo, setArchivo] = useState<File | null>(null)
  const [expedicion, setExpedicion] = useState('')
  const [observacion, setObservacion] = useState('')
  return (
    <div className="formulario-inline">
      <strong className="small">Certificado consultado: {titulo}</strong>
      <div className="grid-persona">
        <label className="small muted" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          PDF del certificado
          <input type="file" accept="application/pdf" onChange={(e) => setArchivo(e.target.files?.[0] ?? null)} />
        </label>
        <label className="small muted" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          Fecha de expedición del certificado
          <input className="input select-sm" type="date" value={expedicion} onChange={(e) => setExpedicion(e.target.value)} />
        </label>
        <input className="input select-sm" placeholder="Observación (opcional)" value={observacion} onChange={(e) => setObservacion(e.target.value)} />
      </div>
      <div className="acciones" style={{ justifyContent: 'flex-end' }}>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCerrar}>
          Cancelar
        </button>
        <button type="button" className="btn btn-primary btn-sm" disabled={!archivo || !expedicion} onClick={() => archivo && onGuardar({ fecha_expedicion: expedicion, observacion, archivo })}>
          Subir certificado
        </button>
      </div>
    </div>
  )
}
