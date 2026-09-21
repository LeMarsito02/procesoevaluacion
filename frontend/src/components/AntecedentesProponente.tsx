import { Fragment, useCallback, useEffect, useState } from 'react'
import {
  agregarPersona,
  consultarEnLinea,
  fuenteDe,
  guardarFechaDocumento,
  verCedulaPersona,
  FUENTES,
  FUENTES_AUTOMATICAS,
  aportarDocumento,
  archivoAportado,
  obtenerAntecedentes,
  quitarAportado,
  quitarPersona,
  type Antecedentes,
  type PersonaVerificada,
  type RolPersona,
} from '../historico'
import { ErrorApi, mensajeDe } from '../http'
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
  /** Abre un documento de la oferta (o un certificado aportado) por su ruta. */
  onVerDocumento?: (archivo: string, requisito: number) => void
  /** Requisito cuyo certificado se va a subir, pedido desde la tarjeta del requisito. */
  subirRequisito?: number | null
  onSubidaAtendida?: () => void
  /** Casilla a la que se llegó desde la matriz: se marca y se pone a la vista. */
  foco?: { persona: string; requisito: number } | null
  /** Se adjuntó un certificado (subido o consultado): el requisito se vuelve a evaluar. */
  onCertificadoAdjunto?: () => void
  /** Cambia cuando llegan resultados nuevos del proponente: la tabla se recarga. */
  marca?: unknown
}

/** Personas cuyos antecedentes se verifican y certificados que el evaluador aportó. */
export default function AntecedentesProponente({ evaluacionId, proponenteId, soloLectura, onVerPdf, onVerDocumento, subirRequisito, onSubidaAtendida, foco, onCertificadoAdjunto, marca }: Props) {
  const [datos, setDatos] = useState<Antecedentes | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [agregando, setAgregando] = useState<{ de: PersonaVerificada | null } | null>(null)
  const [subiendo, setSubiendo] = useState<{ persona: PersonaVerificada | null; requisito: number } | null>(null)
  const [copiado, setCopiado] = useState<string | null>(null)
  // Consulta en curso: "<persona>|<requisito>".
  const [consultando, setConsultando] = useState<string | null>(null)
  // Cuando el RNMC pide la fecha de expedición de la cédula y no la tenemos.
  const [pideFecha, setPideFecha] = useState<{ persona: PersonaVerificada; requisito: number; motivo: string; hayCedula: boolean } | null>(null)
  const [fechaEscrita, setFechaEscrita] = useState('')
  // La cédula abierta al lado del campo, para leer la fecha con los ojos.
  const [cedulaALaVista, setCedulaALaVista] = useState<{ url: string; archivo: string | null } | null>(null)
  const [abriendoCedula, setAbriendoCedula] = useState(false)

  async function mostrarCedula(persona: PersonaVerificada) {
    setAbriendoCedula(true)
    try {
      const { blob, sugerida, archivo } = await verCedulaPersona(evaluacionId, proponenteId, persona.id)
      setCedulaALaVista({ url: URL.createObjectURL(blob), archivo })
      if (sugerida && !fechaEscrita) setFechaEscrita(sugerida)
      setError(null)
    } catch (e) {
      setError(mensajeDe(e))
    } finally {
      setAbriendoCedula(false)
    }
  }

  function cerrarFecha() {
    if (cedulaALaVista) URL.revokeObjectURL(cedulaALaVista.url)
    setCedulaALaVista(null)
    setPideFecha(null)
    setFechaEscrita('')
    setError(null)
  }
  // Persona cuya fecha de expedición se está escribiendo en su ficha.
  const [editandoFecha, setEditandoFecha] = useState<string | null>(null)
  // Cédula abierta debajo de la fila de la persona, para leer y guardar la fecha.
  const [cedulaDe, setCedulaDe] = useState<{ persona: PersonaVerificada; url: string; archivo: string | null; fecha: string } | null>(null)
  const [abriendoDe, setAbriendoDe] = useState<string | null>(null)
  const [abriendoAportado, setAbriendoAportado] = useState<string | null>(null)

  async function abrirCedula(persona: PersonaVerificada) {
    if (cedulaDe?.persona.id === persona.id) return cerrarCedula()
    setAbriendoDe(persona.id)
    try {
      const { blob, sugerida, archivo } = await verCedulaPersona(evaluacionId, proponenteId, persona.id)
      if (cedulaDe) URL.revokeObjectURL(cedulaDe.url)
      setCedulaDe({ persona, url: URL.createObjectURL(blob), archivo, fecha: persona.fecha_expedicion_documento ?? sugerida ?? '' })
      setError(null)
    } catch (e) {
      setError(mensajeDe(e))
    } finally {
      setAbriendoDe(null)
    }
  }

  function cerrarCedula() {
    if (cedulaDe) URL.revokeObjectURL(cedulaDe.url)
    setCedulaDe(null)
  }

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
  }, [recargar, marca])

  async function consultar(persona: PersonaVerificada, requisito: number, fecha?: string) {
    setConsultando(`${persona.id}|${requisito}`)
    try {
      await consultarEnLinea(evaluacionId, proponenteId, {
        requisito,
        persona_id: persona.id,
        ...(fecha ? { fecha_expedicion_documento: fecha } : {}),
      })
      cerrarFecha()
      recargar()
      onCertificadoAdjunto?.()
      setError(null)
    } catch (e) {
      const mensaje = mensajeDe(e)
      // La página oficial necesita ese dato: se pide aquí mismo, con la
      // cédula a la vista si vino en la oferta.
      // Solo un 400 es un problema de los datos; un 503 es la página oficial
      // que falló, y ahí no hay que pedir ni cambiar nada.
      if (e instanceof ErrorApi && e.status === 400 && /fecha de expedici/i.test(mensaje)) {
        setPideFecha({ persona, requisito, motivo: mensaje, hayCedula: !/no se encontró la copia de su cédula/i.test(mensaje) })
        setError(null)
      } else {
        setError(mensaje)
      }
    } finally {
      setConsultando(null)
    }
  }


  // Algo se está guardando: los botones que escriben quedan quietos y con
  // indicador hasta que responda el servidor.
  const [trabajando, setTrabajando] = useState(false)

  async function accion(f: () => Promise<unknown>) {
    setTrabajando(true)
    try {
      await f()
      recargar()
    } catch (e) {
      setError(mensajeDe(e))
    } finally {
      setTrabajando(false)
    }
  }

  if (!datos)
    return error ? (
      <p className="small" style={{ color: 'var(--bad)' }}>{error}</p>
    ) : (
      <p className="small muted" role="status" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className="spinner oscuro" /> Cargando las personas y sus antecedentes…
      </p>
    )
  if (datos.requisitos.length === 0) return null

  // La subida puede venir de una casilla de la tabla o de la tarjeta del requisito.
  const subida = subiendo ?? (subirRequisito != null ? { persona: null, requisito: subirRequisito } : null)
  const raiz = datos.personas.filter((p) => !p.de_id)
  const hijos = (id: string) => datos.personas.filter((p) => p.de_id === id)
  const ordenadas = raiz.flatMap((p) => [p, ...hijos(p.id)])
  const aportado = (persona: string | null, req: number) => datos.aportados.filter((d) => d.persona_id === persona && d.requisito === req)
  // La casilla que se tocó en la matriz (se reconoce por documento o nombre).
  const esElFoco = (per: PersonaVerificada, req: number) =>
    !!foco && foco.requisito === req && (foco.persona === per.documento || foco.persona === per.nombre.toUpperCase())
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
        // Una ficha por persona: sus datos y, debajo, una casilla por
        // antecedente que se acomoda al ancho (sin desplazarse a la derecha).
        <div className="antecedentes-personas">
              {ordenadas.map((per) => (
                <Fragment key={per.id}>
                <div className="persona-ant" data-representante={!!per.de_id}>
                  <div className="persona-ant-datos">
                    <strong className="small">{per.nombre}</strong>
                    {per.detectada && <span className="tag" style={{ marginLeft: 6 }}>de la oferta</span>}
                    <div className="small muted">
                      {per.rol_nombre}
                      {per.documento ? ` · ${per.tipo === 'juridica' ? 'NIT' : 'C.C.'} ${per.documento}` : ' · documento no leído'}
                      {per.fecha_expedicion_documento && ` · expedida el ${fecha(per.fecha_expedicion_documento)}`}
                    </div>
                    {!soloLectura && per.tipo !== 'juridica' && (
                      // Las páginas de consulta (RNMC, antecedentes judiciales) piden
                      // la fecha de expedición del documento además de la cédula.
                      editandoFecha === per.id ? (
                        <div className="acciones" style={{ marginTop: 4 }}>
                          <input
                            className="input select-sm"
                            type="date"
                            defaultValue={per.fecha_expedicion_documento ?? ''}
                            disabled={trabajando}
                            style={{ width: 150 }}
                            onChange={(e) =>
                              accion(async () => {
                                if (e.target.value) await guardarFechaDocumento(evaluacionId, per.id, e.target.value)
                                setEditandoFecha(null)
                              })
                            }
                          />
                          {trabajando ? (
                            <span className="spinner oscuro" aria-label="Guardando" />
                          ) : (
                            <button type="button" className="enlace" onClick={() => setEditandoFecha(null)}>
                              cancelar
                            </button>
                          )}
                        </div>
                      ) : (
                        <button
                          type="button"
                          className="enlace small"
                          onClick={() => setEditandoFecha(per.id)}
                          title="La piden el RNMC y los antecedentes judiciales"
                        >
                          {per.fecha_expedicion_documento ? 'cambiar la fecha de expedición' : 'falta la fecha de expedición de la cédula'}
                        </button>
                      )
                    )}
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
                        {per.tipo !== 'juridica' && (
                          <button
                            type="button"
                            className="enlace"
                            title="Abrir la copia de su cédula que vino en la oferta"
                            disabled={abriendoDe === per.id}
                            onClick={() => void abrirCedula(per)}
                          >
                            {abriendoDe === per.id ? 'abriendo…' : cedulaDe?.persona.id === per.id ? 'cerrar cédula' : 'ver cédula'}
                          </button>
                        )}
                        {per.tipo === 'juridica' && (
                          <button type="button" className="enlace" onClick={() => setAgregando({ de: per })}>
                            + representante
                          </button>
                        )}
                        {!per.detectada && (
                          <button type="button" className="enlace" style={{ color: 'var(--ink-3)' }} disabled={trabajando} onClick={() => accion(() => quitarPersona(evaluacionId, per.id))}>
                            quitar
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="persona-ant-reqs">
                  {datos.requisitos.map((r) => {
                    const docs = aportado(per.id, r.numero)
                    return (
                      <div
                        key={r.numero}
                        className={`celda-antecedente${esElFoco(per, r.numero) ? ' celda-foco' : ''}`}
                        ref={
                          esElFoco(per, r.numero)
                            ? (nodo) => nodo?.scrollIntoView({ block: 'center', behavior: 'smooth' })
                            : undefined
                        }
                      >
                        <div className="celda-antecedente-titulo" title={r.titulo}>
                          {r.corto}
                        </div>
                        {docs.map((d) => (
                          <div key={d.id} className="aportado">
                            <button
                              type="button"
                              className="enlace"
                              title={`Aportado por ${d.subido_por ?? 'el evaluador'}${d.observacion ? ` · ${d.observacion}` : ''}`}
                              disabled={abriendoAportado === d.id}
                              onClick={() => {
                                setAbriendoAportado(d.id)
                                archivoAportado(evaluacionId, d.id)
                                  .then(({ blob }) => onVerPdf(blob, `${r.titulo} · ${per.nombre}`))
                                  .catch((e: unknown) => setError(mensajeDe(e)))
                                  .finally(() => setAbriendoAportado(null))
                              }}
                            >
                              {abriendoAportado === d.id ? <span className="spinner oscuro" /> : <Icono nombre="check" tam={12} grosor={3} />} {fecha(d.fecha_expedicion)}
                            </button>
                            {!soloLectura && (
                              <button type="button" className="enlace" aria-label="Quitar certificado" disabled={trabajando} onClick={() => accion(() => quitarAportado(evaluacionId, d.id))}>
                                <Icono nombre="x" tam={11} />
                              </button>
                            )}
                          </div>
                        ))}
                        {docs.length === 0 && estado(per.id, r.numero)?.estado === 'cumple' && (
                          // El documento con el que se dio por cumplido: de la oferta o el que se aportó.
                          <button
                            type="button"
                            className="pill"
                            data-estado="cumple"
                            title={`${estado(per.id, r.numero)?.archivo ?? ''} — clic para verlo`}
                            disabled={!estado(per.id, r.numero)?.archivo || !onVerDocumento}
                            onClick={() => onVerDocumento?.(estado(per.id, r.numero)!.archivo!, r.numero)}
                          >
                            <Icono nombre="ojo" tam={12} /> Cumple
                          </button>
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
                              {FUENTES_AUTOMATICAS.includes(fuenteDe(r.pistas)?.clave ?? '') ? (
                                // Esta página no pide captcha: el programa trae el certificado y lo adjunta.
                                <button
                                  type="button"
                                  className="btn btn-secondary btn-sm"
                                  disabled={consultando !== null}
                                  onClick={() => void consultar(per, r.numero)}
                                  title={`Consulta en ${fuenteDe(r.pistas)!.nombre} y lo adjunta al expediente`}
                                >
                                  {consultando === `${per.id}|${r.numero}` ? <span className="spinner oscuro" /> : <Icono nombre="descargar" tam={13} />}
                                  Consultar
                                </button>
                              ) : null}
                              {
                                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSubiendo({ persona: per, requisito: r.numero })}>
                                  <Icono nombre="subir" tam={13} /> Subir
                                </button>
                              }
                              {fuenteDe(r.pistas) && (
                                <a
                                  className="enlace"
                                  href={fuenteDe(r.pistas)!.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  title={`${fuenteDe(r.pistas)!.nombre} · pide ${fuenteDe(r.pistas)!.pide}`}
                                >
                                  {FUENTES_AUTOMATICAS.includes(fuenteDe(r.pistas)?.clave ?? '') ? 'ver página' : 'consultar'}
                                </a>
                              )}
                            </div>
                          ))}
                      </div>
                    )
                  })}
                  </div>
                </div>
                {cedulaDe?.persona.id === per.id && (
                  <div className="persona-ant-cedula">
                      <div className="formulario-inline" style={{ margin: 0 }}>
                        <div className="acciones" style={{ justifyContent: 'space-between' }}>
                          <strong className="small">
                            Cédula de {per.nombre}
                            {cedulaDe.archivo && <span className="muted" style={{ fontWeight: 400 }}> · {cedulaDe.archivo}</span>}
                          </strong>
                          <button type="button" className="enlace" onClick={cerrarCedula}>
                            cerrar
                          </button>
                        </div>
                        <iframe
                          title={`Cédula de ${per.nombre}`}
                          src={cedulaDe.url}
                          style={{ width: '100%', height: 460, border: '1px solid var(--line)', borderRadius: 8 }}
                        />
                        {!soloLectura && (
                          <div className="acciones" style={{ alignItems: 'flex-end' }}>
                            <label className="small muted" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                              Fecha de expedición (reverso, junto a «FECHA Y LUGAR DE EXPEDICIÓN»)
                              <input
                                className="input select-sm"
                                type="date"
                                value={cedulaDe.fecha}
                                style={{ width: 170 }}
                                onChange={(e) => setCedulaDe({ ...cedulaDe, fecha: e.target.value })}
                              />
                            </label>
                            {cedulaDe.fecha && cedulaDe.fecha !== per.fecha_expedicion_documento && !per.fecha_expedicion_documento && (
                              <span className="small muted">sugerida por el programa: revísala antes de guardar</span>
                            )}
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              disabled={trabajando || !cedulaDe.fecha || cedulaDe.fecha === per.fecha_expedicion_documento}
                              onClick={() =>
                                accion(async () => {
                                  await guardarFechaDocumento(evaluacionId, per.id, cedulaDe.fecha)
                                  cerrarCedula()
                                })
                              }
                            >
                              {trabajando ? <span className="spinner" /> : null} Guardar fecha
                            </button>
                          </div>
                        )}
                      </div>
                  </div>
                )}
                </Fragment>
              ))}
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
          ocupado={trabajando}
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
      {pideFecha && (
        <div className="formulario-inline">
          <strong className="small">
            Escriba la fecha de expedición de la cédula de {pideFecha.persona.nombre}
          </strong>
          <p className="small muted" style={{ margin: 0 }}>
            {pideFecha.hayCedula
              ? 'La página de la Policía la pide junto con el número de cédula, y aquí no se pudo leer con seguridad. Ábrala para verla con sus propios ojos: está en el reverso, junto a «FECHA Y LUGAR DE EXPEDICIÓN».'
              : 'La página de la Policía la pide junto con el número de cédula, y la copia de su cédula no vino en la oferta. Tómela del documento que tenga a la mano.'}
          </p>
          <div className="acciones">
            <label className="small muted" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              Fecha de expedición
              <input className="input select-sm" type="date" value={fechaEscrita} onChange={(e) => setFechaEscrita(e.target.value)} />
            </label>
            {!cedulaALaVista && pideFecha.hayCedula && (
              <button type="button" className="btn btn-secondary btn-sm" disabled={abriendoCedula} onClick={() => void mostrarCedula(pideFecha.persona)}>
                {abriendoCedula ? <span className="spinner oscuro" /> : <Icono nombre="ojo" tam={14} />} Ver su cédula aquí
              </button>
            )}
          </div>
          {cedulaALaVista && (
            <div style={{ marginTop: 8 }}>
              <div className="small muted">{cedulaALaVista.archivo}</div>
              <iframe
                title={`Cédula de ${pideFecha.persona.nombre}`}
                src={cedulaALaVista.url}
                style={{ width: '100%', height: 420, border: '1px solid var(--line)', borderRadius: 8 }}
              />
            </div>
          )}
          <div className="acciones" style={{ justifyContent: 'flex-end' }}>
            <button type="button" className="btn btn-ghost btn-sm" onClick={cerrarFecha}>
              Cancelar
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={!fechaEscrita || consultando !== null}
              onClick={() => void consultar(pideFecha.persona, pideFecha.requisito, fechaEscrita)}
            >
              {consultando ? <span className="spinner" /> : null} Consultar con esta fecha
            </button>
          </div>
        </div>
      )}
      {subida && (
        <FormularioCertificado
          ocupado={trabajando}
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
              onCertificadoAdjunto?.()
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
  ocupado = false,
}: {
  ocupado?: boolean
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
          disabled={ocupado || nombre.trim().length < 3 || documento.trim().length < 4}
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
          {ocupado ? <span className="spinner" /> : null} Agregar
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
  ocupado = false,
}: {
  ocupado?: boolean
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
          disabled={ocupado || !archivo || !expedicion || faltaPersona}
          onClick={() => archivo && onGuardar({ fecha_expedicion: expedicion, observacion, archivo }, persona || null)}
        >
          {ocupado ? <span className="spinner" /> : null} {ocupado ? 'Subiendo…' : 'Subir certificado'}
        </button>
      </div>
    </div>
  )
}
