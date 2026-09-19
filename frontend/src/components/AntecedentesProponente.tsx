import { useCallback, useEffect, useState } from 'react'
import {
  agregarPersona,
  fuenteDe,
  FUENTES,
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

async function copiar(texto: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(texto)
    return true
  } catch {
    return false
  }
}

const fecha = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString('es-CO', { dateStyle: 'medium' })

interface Props {
  evaluacionId: string
  proponenteId: string
  soloLectura: boolean
  onVerPdf: (blob: Blob, titulo: string) => void
  /** Requisito cuyo certificado se va a subir, pedido desde la tarjeta del requisito. */
  subirRequisito?: number | null
  onSubidaAtendida?: () => void
}

/** Personas cuyos antecedentes se verifican y certificados que el evaluador aportó. */
export default function AntecedentesProponente({ evaluacionId, proponenteId, soloLectura, onVerPdf, subirRequisito, onSubidaAtendida }: Props) {
  const [datos, setDatos] = useState<Antecedentes | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [agregando, setAgregando] = useState<{ de: PersonaVerificada | null } | null>(null)
  const [subiendo, setSubiendo] = useState<{ persona: PersonaVerificada | null; requisito: number } | null>(null)
  const [copiado, setCopiado] = useState<string | null>(null)

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

  // La subida puede venir de una casilla de la tabla o de la tarjeta del requisito.
  const subida = subiendo ?? (subirRequisito != null ? { persona: null, requisito: subirRequisito } : null)
  const raiz = datos.personas.filter((p) => !p.de_id)
  const hijos = (id: string) => datos.personas.filter((p) => p.de_id === id)
  const ordenadas = raiz.flatMap((p) => [p, ...hijos(p.id)])
  const aportado = (persona: string | null, req: number) => datos.aportados.filter((d) => d.persona_id === persona && d.requisito === req)
  const estado = (persona: string, req: number) => datos.estados[persona]?.[String(req)]
  const pendiente = (per: PersonaVerificada, req: number) => {
    if (aportado(per.id, req).length) return false
    const e = estado(per.id, req)?.estado
    return e ? e === 'falta' || e === 'con_novedad' || e === 'vencido' : !datos.encontrados[req]
  }
  const sinCertificado = ordenadas.reduce((n, per) => n + datos.requisitos.filter((r) => pendiente(per, r.numero)).length, 0)

  return (
    <section className="antecedentes">
      <div className="grupo-titulo">Personas verificadas y antecedentes</div>
      <p className="small muted">
        Las personas y empresas a las que la regla les exige antecedentes aparecen solas, con el estado de cada certificado.{' '}
        {AYUDA_TIPO[datos.tipo_proponente ?? ''] ?? ''} Si falta uno, consúltelo en la fuente oficial y súbalo: queda en el
        expediente y en el reporte.
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
                    {per.detectada && <span className="tag" style={{ marginLeft: 6 }}>de la oferta</span>}
                    <div className="small muted">
                      {per.rol_nombre}
                      {per.documento ? ` · ${per.tipo === 'juridica' ? 'NIT' : 'C.C.'} ${per.documento}` : ' · documento no leído'}
                      {per.fecha_expedicion_documento && ` · exp. ${fecha(per.fecha_expedicion_documento)}`}
                    </div>
                    {!soloLectura && (
                      <div className="acciones datos-consulta" style={{ marginTop: 4 }}>
                        <button
                          type="button"
                          className="enlace"
                          title="Copiar nombre, documento y fecha de expedición para consultarlos en las páginas oficiales"
                          onClick={async () =>
                            setCopiado(
                              (await copiar(
                                `${per.nombre} · ${per.tipo === 'juridica' ? 'NIT' : 'C.C.'} ${per.documento}${per.fecha_expedicion_documento ? ` · expedida el ${fecha(per.fecha_expedicion_documento)}` : ''}`,
                              ))
                                ? per.id
                                : null,
                            )
                          }
                        >
                          {copiado === per.id ? '¡copiado!' : 'copiar datos'}
                        </button>
                        {per.tipo === 'juridica' && (
                          <button type="button" className="enlace" onClick={() => setAgregando({ de: per })}>
                            + representante
                          </button>
                        )}
                        {!per.detectada && (
                          <button type="button" className="enlace" style={{ color: 'var(--ink-3)' }} onClick={() => accion(() => quitarPersona(evaluacionId, per.id))}>
                            quitar
                          </button>
                        )}
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
                        {docs.length === 0 && estado(per.id, r.numero)?.estado === 'cumple' && (
                          <span className="pill" data-estado="cumple" title={estado(per.id, r.numero)?.archivo ?? ''}>
                            <span className="dot" /> En la oferta
                          </span>
                        )}
                        {docs.length === 0 && estado(per.id, r.numero)?.estado === 'no_requerido' && (
                          <span className="small muted" title="La regla no le exige este certificado a esta persona">
                            No se exige
                          </span>
                        )}
                        {docs.length === 0 && estado(per.id, r.numero)?.estado === 'con_novedad' && (
                          <span className="pill" data-estado="error" title={estado(per.id, r.numero)?.archivo ?? ''}>
                            <span className="dot" /> Con novedad
                          </span>
                        )}
                        {docs.length === 0 && estado(per.id, r.numero)?.estado === 'vencido' && (
                          <span className="pill" data-estado="error" title={estado(per.id, r.numero)?.archivo ?? ''}>
                            <span className="dot" /> Vencido
                          </span>
                        )}
                        {docs.length === 0 && estado(per.id, r.numero)?.estado === 'falta' && (
                          <span className="pill" data-estado="revisar">
                            <span className="dot" /> Falta
                          </span>
                        )}
                        {docs.length === 0 &&
                          !['cumple', 'no_requerido'].includes(estado(per.id, r.numero)?.estado ?? '') &&
                          (soloLectura ? (
                            <span className="small muted">—</span>
                          ) : (
                            <div className="falta-certificado">
                              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSubiendo({ persona: per, requisito: r.numero })}>
                                <Icono nombre="subir" tam={13} /> Subir
                              </button>
                              {fuenteDe(r.pistas) && (
                                <a
                                  className="enlace"
                                  href={fuenteDe(r.pistas)!.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  title={`${fuenteDe(r.pistas)!.nombre} · pide ${fuenteDe(r.pistas)!.pide}`}
                                >
                                  consultar
                                </a>
                              )}
                            </div>
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
      {subida && (
        <FormularioCertificado
          titulo={`${datos.requisitos.find((r) => r.numero === subida.requisito)?.titulo ?? `Requisito ${subida.requisito}`}${subida.persona ? ` · ${subida.persona.nombre}` : ''}`}
          fuente={fuenteDe(datos.requisitos.find((r) => r.numero === subida.requisito)?.pistas ?? [])}
          personas={subida.persona ? null : ordenadas}
          onCerrar={() => {
            setSubiendo(null)
            onSubidaAtendida?.()
          }}
          onGuardar={(d, personaId) =>
            accion(async () => {
              await aportarDocumento(evaluacionId, proponenteId, {
                ...d,
                requisito: subida.requisito,
                persona_id: subida.persona?.id ?? personaId ?? null,
              })
              setSubiendo(null)
              onSubidaAtendida?.()
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
  fuente,
  personas,
  onCerrar,
  onGuardar,
}: {
  titulo: string
  /** Página oficial donde se consulta este antecedente, si la hay. */
  fuente?: (typeof FUENTES)[number] | null
  /** Personas entre las que elegir cuando la subida no viene de una casilla. */
  personas?: PersonaVerificada[] | null
  onCerrar: () => void
  onGuardar: (d: { fecha_expedicion: string; observacion: string; archivo: File }, personaId?: string | null) => void
}) {
  const [archivo, setArchivo] = useState<File | null>(null)
  const [expedicion, setExpedicion] = useState('')
  const [observacion, setObservacion] = useState('')
  const [persona, setPersona] = useState('')
  const faltaPersona = !!personas && personas.length > 0 && !persona
  return (
    <div className="formulario-inline">
      <strong className="small">Certificado consultado: {titulo}</strong>
      {fuente && (
        <p className="small muted" style={{ margin: 0 }}>
          Se consulta en{' '}
          <a className="enlace" href={fuente.url} target="_blank" rel="noopener noreferrer">
            {fuente.nombre}
          </a>{' '}
          (pide {fuente.pide}).
        </p>
      )}
      <div className="grid-persona">
        {personas && personas.length > 0 && (
          <label className="small muted" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            ¿De quién es el certificado?
            <select className="input select-sm" value={persona} onChange={(e) => setPersona(e.target.value)}>
              <option value="">Elegir persona…</option>
              {personas.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.nombre}
                </option>
              ))}
            </select>
          </label>
        )}
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
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={!archivo || !expedicion || faltaPersona}
          onClick={() => archivo && onGuardar({ fecha_expedicion: expedicion, observacion, archivo }, persona || null)}
        >
          Subir certificado
        </button>
      </div>
    </div>
  )
}
