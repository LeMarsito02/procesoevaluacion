/** Personas verificadas, certificados aportados, reporte Word y expedientes. */
import { detalleError, enviarJson, ErrorApi, pedir, pedirJson } from './http'

export type RolPersona = 'proponente' | 'representante_legal' | 'suplente' | 'integrante'

export interface PersonaVerificada {
  id: string
  rol: RolPersona
  rol_nombre: string
  tipo: 'natural' | 'juridica'
  nombre: string
  documento: string
  fecha_expedicion_documento: string | null
  de_id: string | null
  /** La detectó el programa en la oferta; si no, la agregó el evaluador. */
  detectada: boolean
}

export type EstadoCertificado = 'cumple' | 'falta' | 'con_novedad' | 'vencido' | 'no_requerido'

export interface DocumentoAportado {
  id: string
  requisito: number
  persona_id: string | null
  fecha_expedicion: string
  nombre_original: string
  observacion: string
  subido_por: string | null
  subido_en: string
}

export interface Antecedentes {
  tipo_proponente: string | null
  representante_legal: string | null
  requisitos: { numero: number; corto: string; titulo: string; pistas: string[] }[]
  personas: PersonaVerificada[]
  aportados: DocumentoAportado[]
  encontrados: Record<string, string | null>
  /** Estado de cada certificado de cada persona: estados[persona_id][requisito]. */
  estados: Record<string, Record<string, { estado: EstadoCertificado; archivo: string | null }>>
}

export interface ExpedienteInfo {
  id: string
  version: number
  estado: 'pendiente' | 'generando' | 'listo' | 'error'
  tamano: number | null
  sha256: string
  avisos: string
  creado_en: string
  terminado_en: string | null
}

const base = (ev: string) => `/api/evaluaciones/${ev}`

export const obtenerAntecedentes = (ev: string, prop: string) => pedirJson<Antecedentes>(`${base(ev)}/proponentes/${prop}/antecedentes`)
export const agregarPersona = (
  ev: string,
  prop: string,
  datos: { rol: RolPersona; tipo: 'natural' | 'juridica'; nombre: string; documento: string; fecha_expedicion_documento: string | null; de_id: string | null },
) => enviarJson<PersonaVerificada>(`${base(ev)}/proponentes/${prop}/personas`, 'POST', datos)
export const quitarPersona = (ev: string, id: string) => enviarJson<void>(`${base(ev)}/personas/${id}`, 'DELETE')

export async function aportarDocumento(
  ev: string,
  prop: string,
  datos: { requisito: number; persona_id: string | null; fecha_expedicion: string; observacion: string; archivo: File },
): Promise<DocumentoAportado> {
  const cuerpo = new FormData()
  cuerpo.append('requisito', String(datos.requisito))
  if (datos.persona_id) cuerpo.append('persona_id', datos.persona_id)
  cuerpo.append('fecha_expedicion', datos.fecha_expedicion)
  cuerpo.append('observacion', datos.observacion)
  cuerpo.append('archivo', datos.archivo)
  const res = await pedir(`${base(ev)}/proponentes/${prop}/aportados`, { method: 'POST', body: cuerpo })
  if (!res.ok) throw new ErrorApi(res.status, await detalleError(res))
  return res.json()
}

export const quitarAportado = (ev: string, id: string) => enviarJson<void>(`${base(ev)}/aportados/${id}`, 'DELETE')

async function blob(ruta: string): Promise<{ blob: Blob; nombre: string | null }> {
  const res = await pedir(ruta)
  if (!res.ok) throw new ErrorApi(res.status, await detalleError(res))
  const nombre = /filename="?([^";]+)"?/.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ?? null
  return { blob: await res.blob(), nombre }
}

export const archivoAportado = (ev: string, id: string) => blob(`${base(ev)}/aportados/${id}/archivo`)
export const descargarReporteWord = (ev: string) => blob(`${base(ev)}/reporte`)
export const archivoPliego = (ev: string) => blob(`${base(ev)}/pliego`)
export const listarExpedientes = (ev: string) => pedirJson<ExpedienteInfo[]>(`${base(ev)}/expedientes`)
export const regenerarExpediente = (ev: string) => enviarJson<ExpedienteInfo>(`${base(ev)}/expedientes`, 'POST')
export const descargarExpediente = (ev: string, id: string) => blob(`${base(ev)}/expedientes/${id}/archivo`)

export function guardarArchivo(b: Blob, nombre: string) {
  const url = URL.createObjectURL(b)
  const a = document.createElement('a')
  a.href = url
  a.download = nombre
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** Fuente oficial donde se consulta cada antecedente (se reconoce por las pistas del requisito). */
export const FUENTES: { clave: string; nombre: string; url: string; pide: string }[] = [
  { clave: 'policia', nombre: 'Policía Nacional · antecedentes judiciales', url: 'https://antecedentes.policia.gov.co:7005/WebJudicial/', pide: 'cédula y fecha de expedición' },
  { clave: 'rnmc', nombre: 'Policía Nacional · medidas correctivas (RNMC)', url: 'https://srvpsi.policia.gov.co/PSC/frm_cnp_consulta.aspx', pide: 'cédula y fecha de expedición' },
  { clave: 'procuradur', nombre: 'Procuraduría General de la Nación', url: 'https://www.procuraduria.gov.co/CertWEB/Certificado.aspx?tpo=1', pide: 'cédula o NIT' },
  { clave: 'contralor', nombre: 'Contraloría General de la República', url: 'https://www.contraloria.gov.co/control-fiscal/responsabilidad-fiscal/certificado-de-antecedentes-fiscales', pide: 'cédula o NIT' },
  { clave: 'redam', nombre: 'REDAM · deudores alimentarios morosos', url: 'https://redam.sisben.gov.co/', pide: 'cédula' },
]

export function fuenteDe(pistas: string[]): (typeof FUENTES)[number] | null {
  return FUENTES.find((f) => pistas.some((p) => p.toLowerCase().includes(f.clave))) ?? null
}
