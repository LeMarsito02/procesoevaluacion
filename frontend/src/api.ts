import { huellaRapida } from './huella'
import { detalleError, enviarJson, pedir, pedirJson, subirConAvance, type AvanceSubida } from './http'

export interface Lote {
  numero: string
  objeto: string
  plazo_meses: number
  valor_presupuesto: number
  lugar_ejecucion: string | null
}

export interface GarantiaSeriedad {
  vigencia_meses: number
  porcentaje: number
  base_calculo: 'lote_mayor_valor' | 'presupuesto_total'
  lote_base: string | null
  valor_base: number
  valor_asegurado: number
  fecha_cierre: string
  fecha_vencimiento: string
}

export interface ProcesoDocumentoBase {
  codigo_proceso: string
  fecha_cierre: string
  objeto_general: string
  lotes: Lote[]
  lote_mayor_valor: string
  presupuesto_total: number
  garantia_seriedad: GarantiaSeriedad
  advertencias: string[]
  /** Páginas del pliego donde está cada dato, para abrirlo ahí y comprobarlo. */
  pagina_objeto?: number | null
  pagina_garantia?: number | null
}

export interface Proponente {
  numero_orden: number
  hoja: string
  nombre_proponente: string
  nombre_archivo: string
  drive_file_id: string
  advertencia: string | null
}

export interface AnalisisResponse {
  documento_base: ProcesoDocumentoBase
  proponentes: Proponente[]
  proponentes_no_reconocidos: string[]
  drive_error: string | null
  pliego: AnalisisPliego | null
  pliego_error: string | null
}

export type TipoHallazgo =
  | 'ajuste_parametro'
  | 'requisito_nuevo'
  | 'requisito_no_exigido'
  | 'aclaracion'
  | 'informativo'
  | 'fuera_de_alcance'
  | 'obligacion'

/** Algo que dice el pliego frente a la forma de evaluar de la entidad, con su prueba literal. */
export interface HallazgoPliego {
  id: string
  tipo: TipoHallazgo
  titulo: string
  detalle: string
  seccion: string
  pagina: number
  cita: string
  verificacion: string | null
  parametro: string | null
  valor_plantilla: string | number | string[] | null
  valor_pliego: string | number | string[] | null
  valor_pliego_texto: string | null
  requiere_decision: boolean
}

export interface SeccionPliego {
  numero: string
  titulo: string
  pagina: number
  ambito: string
  verificaciones: string[]
  /** Qué hacer con la sección cuando no tiene una verificación propia (o es parcial). */
  nota?: string | null
}

/** Lectura profunda del pliego con la IA local (corre en el trabajador). */
export interface LecturaIA {
  estado: 'pendiente' | 'leyendo' | 'listo' | 'error' | 'no_disponible'
  progreso: number
  modelo: string
  requisitos: number
  error: string
}

/** Un requisito jurídico que exige el pliego y cómo se verificará. */
export interface RequisitoDelPliego {
  id: string
  requisito: string
  documento: string | null
  expide: string | null
  aplica_a: string[]
  vigencia_dias: number | null
  vigencia_meses: number | null
  condiciones: string[]
  cita: string
  seccion: string
  pagina: number
  verificacion: string | null
  como: string
  estado: 'motor' | 'motor_nuevo' | 'documento' | 'revision' | 'condicional' | 'extranjeros'
  parametros: Record<string, number>
}

export interface AnalisisPliego {
  id: string
  nombre_archivo: string
  paginas: number
  documento_tipo: string
  reutilizado: boolean
  hallazgos: HallazgoPliego[]
  secciones: SeccionPliego[]
  lectura_ia: LecturaIA
  requisitos: RequisitoDelPliego[]
}

export interface DecisionPliego {
  decision: 'aceptado' | 'rechazado'
  nota: string
}

/** Una persona o empresa a la que un requisito de antecedentes le exige certificado. */
export interface PersonaAntecedente {
  nombre: string
  documento: string | null
  tipo: 'natural' | 'juridica'
  rol: 'representante_legal' | 'suplente' | 'integrante' | 'proponente'
  estado: 'cumple' | 'falta' | 'con_novedad' | 'vencido'
  archivo: string | null
}

export interface ResultadoRequisito {
  hoja: string
  numero_orden: number
  nombre_proponente: string
  requisito: number
  cumple: boolean | null
  motivo: string | null
  archivo_evaluado: string | null
  /** Otros documentos que sostienen el resultado (los que nombra el motivo, el acta, el de cada integrante). */
  archivos_soporte?: string[]
  /** Documentos de la carpeta que quien revisa asoció a mano a este requisito. */
  archivos_asociados?: string[]
  /** Documentos que el programa relacionó y quien revisa quitó porque no corresponden. */
  archivos_excluidos?: string[]
  lotes_encontrados: string[]
  numero_proceso_encontrado: boolean
  objeto_relacionado: boolean | null
  tipo_proponente: 'persona_natural' | 'persona_juridica' | 'consorcio' | 'union_temporal' | 'otro' | null
  firma_detectada: boolean
  representante_legal: string | null
  firma_nombre_certificado: string | null
  firma_confirmada: boolean | null
  matricula_profesional: string | null
  profesion_certificada: string | null
  copnia_vigente: boolean | null
  copnia_sin_antecedentes: boolean | null
  copnia_fecha_expedicion: string | null
  error: string | null
  archivos_disponibles: string[]
  /** A quién se le exigió el certificado en este requisito y cómo le fue. */
  personas_antecedente: PersonaAntecedente[]
  /** Evaluación técnica: contratos del lote o puntaje del factor. */
  detalle?: DetalleTecnico | null
  /** La muestra de control encontró un error en este requisito: pasa a revisión humana. */
  revision_forzada?: string | null
}

export interface ContratoTecnico {
  orden: number
  consecutivos: string[]
  contratante: string
  numero_contrato: string
  objeto: string
  valor_smmlv: number | null
  participacion: number | null
  valor_aportado: number | null
  aportes: Record<string, number>
  unspsc: boolean | null
  de_un_socio: boolean
  longitud_km: number | null
  soporte_longitud: string | null
  area_m2?: number | null
  soporte_area?: string | null
  problemas: string[]
}

export interface IntegranteFinanciero {
  nombre: string
  nit: string | null
  participacion: number | null
  rup: string | null
  financiera: {
    fecha_corte: string | null
    activo_corriente: number | null
    activo_total: number | null
    pasivo_corriente: number | null
    pasivo_total: number | null
    patrimonio: number | null
    utilidad_operacional: number | null
    gastos_intereses: number | null
  } | null
}

export interface ResidualIntegrante {
  nombre: string
  co: number | null
  e: number | null
  puntos_e: number | null
  profesionales: number | null
  puntos_ct: number | null
  liquidez: number | null
  puntos_cf: number | null
  sce: number | null
  crp: number | null
}

export interface DetalleFinanciero {
  no_aplica?: boolean
  compartido?: boolean
  lote?: string
  liquidez?: number | null
  endeudamiento?: number | null
  cobertura?: number | null
  roa?: number | null
  roe?: number | null
  capital_de_trabajo?: number
  demandado?: number | null
  exigida?: number
  crp?: number
  lotes_cubiertos?: string[]
  integrantes?: ResidualIntegrante[]
  patrimonio?: number | null
  /** Validez: por integrante, sus estados financieros y el estado del certificado de cada tarjeta profesional. */
  validez?: Record<string, { estados: string[]; tarjetas: Record<string, string> }>
}

/** Una cosa concreta por revisar. El ámbito es lo que dice cuánto cuesta:
 * "proceso" sale del pliego y se resuelve una vez para todos los proponentes,
 * "oferta" hay que mirarlo en esta oferta. */
export interface PuntoDeRevision {
  clave: string
  ambito: 'proceso' | 'oferta'
  que: string
  donde: string
}

export interface DetalleTecnico {
  lote?: string
  valor_a_certificar?: number | null
  factor?: number | null
  valor_certificado?: number
  un_contrato_70?: boolean | null
  longitud?: boolean | null
  longitud_minima_km?: number | null
  condiciones_plural?: boolean | null
  aporte_por_integrante?: Record<string, number>
  contratos?: ContratoTecnico[]
  integrantes?: { nombre: string; nit: string | null; participacion: number | null; rup: string | null; tamano: string | null }[]
  formato3?: string | null
  /** Evaluación financiera: indicadores, capital de trabajo o capacidad residual. */
  financiera?: DetalleFinanciero
  integrantes_financieros?: IntegranteFinanciero[]
  factor_clave?: string
  puntaje_maximo?: number
  puntaje?: number | null
  /** Lo que falta por mirar, punto por punto. */
  revisiones?: PuntoDeRevision[]
  /** La experiencia quedó acreditada con lo aportado: si el lote aún no cumple,
   * lo que falta sale del pliego y se resuelve una vez, no oferta por oferta. */
  experiencia_acreditada?: boolean
}


/** Un proceso a medio crear: el servidor lee el Documento Base, las ofertas y
 * el pliego en segundo plano y lo guarda; recargar la página no lo pierde. */
export interface Preparacion {
  id: string
  codigo: string
  fecha_cierre: string
  carpeta_drive: string
  nombre_archivo: string
  ofertas_subidas: boolean
  estado: 'pendiente' | 'leyendo' | 'lista' | 'error'
  etapa: string
  progreso: number
  error: string
  creada_en: string
  iniciada_en: string | null
  entidad_id: string
  resultado?: AnalisisResponse | null
}

export async function crearPreparacion(
  codigoProceso: string,
  fechaCierre: string,
  archivo: File,
  carpetaDrive: string,
  entidadId: string | null,
  ofertas: File[],
  onAvance: (a: AvanceSubida) => void = () => {},
  onReutilizada: (nombre: string) => void = () => {},
): Promise<Preparacion> {
  const formData = new FormData()
  formData.append('codigo_proceso', codigoProceso)
  formData.append('fecha_cierre', fechaCierre)
  formData.append('archivo', archivo)
  if (entidadId) formData.append('entidad_id', entidadId)
  if (ofertas.length > 0) {
    // Primero las ofertas, por pedazos (pueden ser varios GB); luego el Documento Base.
    const total = ofertas.reduce((s, f) => s + f.size, 0) + archivo.size
    const ids = await subirOfertasPorPedazos(ofertas, (a) => onAvance({ cargado: a.cargado, total }), onReutilizada)
    for (const id of ids) formData.append('subidas', id)
    const pesoOfertas = total - archivo.size
    const p = await subirConAvance<Preparacion>('/api/procesos/preparaciones', formData, (a) =>
      onAvance({ cargado: pesoOfertas + Math.min(a.cargado, archivo.size), total }),
    )
    olvidarSubidas(ofertas)
    return p
  }
  if (carpetaDrive.trim()) formData.append('carpeta_drive', carpetaDrive.trim())
  return subirConAvance<Preparacion>('/api/procesos/preparaciones', formData, onAvance)
}
/** Subida de ofertas por pedazos: cada archivo (hasta 10 GB) sube en trozos
 * de 32 MB que el servidor va pegando en disco; si se corta, se sigue desde lo
 * que llegó. Devuelve los identificadores de las subidas, en el mismo orden. */
const PEDAZO = 32 * 1024 * 1024
interface EstadoSubida {
  id: string
  recibido: number
  tamano: number
  completa: boolean
  /** El archivo ya estaba en el servidor (misma huella): no se sube. */
  reutilizada?: boolean
}
const claveSubida = (f: File) => `mievaluador-subida:${f.name}:${f.size}:${f.lastModified}`

async function retomarOcrear(f: File): Promise<EstadoSubida> {
  // 1) ¿Ya está en el servidor? Se pregunta antes que nada: si está, no se sube
  //    (y una subida vieja a medias del mismo archivo sobra: se elimina).
  let huella: string | null = null
  try {
    huella = await huellaRapida(f)
  } catch {
    // Sin huella se sube normal.
  }
  let guardada: string | null = null
  try {
    guardada = localStorage.getItem(claveSubida(f))
  } catch {
    // Sin almacenamiento local: no hay subida que retomar.
  }
  if (huella) {
    const s = await enviarJson<EstadoSubida>('/api/procesos/subidas', 'POST', { nombre: f.name, tamano: f.size, huella })
    if (s.reutilizada) {
      if (guardada) {
        await pedir(`/api/procesos/subidas/${guardada}`, { method: 'DELETE' }).catch(() => undefined)
        try {
          localStorage.removeItem(claveSubida(f))
        } catch {
          // Nada que olvidar.
        }
      }
      return s
    }
    // No está: si había una subida a medias se retoma y la recién creada sobra.
    if (guardada) {
      try {
        const vieja = await pedirJson<EstadoSubida>(`/api/procesos/subidas/${guardada}`)
        if (vieja.tamano === f.size && !vieja.reutilizada) {
          await pedir(`/api/procesos/subidas/${s.id}`, { method: 'DELETE' }).catch(() => undefined)
          return vieja
        }
      } catch {
        // Vencida o de otra sesión: se sigue con la nueva.
      }
    }
    try {
      localStorage.setItem(claveSubida(f), s.id)
    } catch {
      // Sin almacenamiento local la subida funciona igual; solo no se retoma tras recargar.
    }
    return s
  }
  // 2) Sin huella: retomar la subida a medias o empezar una nueva.
  if (guardada) {
    try {
      const vieja = await pedirJson<EstadoSubida>(`/api/procesos/subidas/${guardada}`)
      if (vieja.tamano === f.size) return vieja
    } catch {
      // Vencida o de otra sesión: se empieza de nuevo.
    }
  }
  const s = await enviarJson<EstadoSubida>('/api/procesos/subidas', 'POST', { nombre: f.name, tamano: f.size, huella: null })
  try {
    localStorage.setItem(claveSubida(f), s.id)
  } catch {
    // Sin almacenamiento local la subida funciona igual; solo no se retoma tras recargar.
  }
  return s
}

const esperar = (ms: number) => new Promise((r) => window.setTimeout(r, ms))

export async function subirOfertasPorPedazos(
  ofertas: File[],
  onAvance: (a: AvanceSubida) => void,
  onReutilizada: (nombre: string) => void = () => {},
): Promise<string[]> {
  const total = ofertas.reduce((t, f) => t + f.size, 0)
  let previos = 0
  const ids: string[] = []
  for (const f of ofertas) {
    let s = await retomarOcrear(f)
    if (s.reutilizada) onReutilizada(f.name)
    let fallos = 0
    while (!s.completa) {
      const desde = s.recibido
      const trozo = f.slice(desde, Math.min(f.size, desde + PEDAZO))
      try {
        s = await subirConAvance<EstadoSubida>(
          `/api/procesos/subidas/${s.id}?desde=${desde}`,
          trozo,
          (a) => onAvance({ cargado: previos + desde + a.cargado, total }),
          true,
          'PUT',
        )
        fallos = 0
      } catch (err) {
        // 409: el servidor ya tenía más (un reintento que sí había llegado): se sigue desde ahí.
        // Red caída: se reintenta con espera creciente; tras varios intentos, se avisa.
        fallos += 1
        if (fallos > 8) throw err
        await esperar(Math.min(30000, 1000 * 2 ** fallos))
        s = await pedirJson<EstadoSubida>(`/api/procesos/subidas/${s.id}`)
      }
      onAvance({ cargado: previos + s.recibido, total })
    }
    previos += f.size
    ids.push(s.id)
  }
  return ids
}

/** Olvida en este navegador las subidas ya usadas (la preparación las reparte y borra). */
export function olvidarSubidas(ofertas: File[]) {
  try {
    for (const f of ofertas) localStorage.removeItem(claveSubida(f))
  } catch {
    // Nada que olvidar.
  }
}

/** Ofertas subidas desde el equipo que quedaron guardadas en el servidor: se
 * reutilizan si se vuelve a elegir el mismo archivo, y se pueden eliminar. */
export interface CargaGuardada {
  huella: string
  nombre: string
  tamano: number
  ofertas: number
  registrada: number | null
  completa: boolean
}
export const listarCargas = () => pedirJson<CargaGuardada[]>('/api/procesos/cargas')
export const verCarga = (huella: string, tamano: number) =>
  pedirJson<{ guardada: boolean; ofertas: number }>(`/api/procesos/cargas/${huella}?tamano=${tamano}`)
export const eliminarCarga = (huella: string) => pedirJson<{ ofertas_borradas: number }>(`/api/procesos/cargas/${huella}`, { method: 'DELETE' })

export const listarPreparaciones = () => pedirJson<Preparacion[]>('/api/procesos/preparaciones')
export const verPreparacion = (id: string) => pedirJson<Preparacion>(`/api/procesos/preparaciones/${id}`)
export const reintentarPreparacion = (id: string) => enviarJson<Preparacion>(`/api/procesos/preparaciones/${id}/reintentar`, 'POST')
export async function eliminarPreparacion(id: string): Promise<void> {
  const res = await pedir(`/api/procesos/preparaciones/${id}`, { method: 'DELETE' })
  if (!res.ok && res.status !== 404) throw new Error(await extractErrorDetail(res))
}

export async function analizarDocumentoBase(
  codigoProceso: string,
  fechaCierre: string,
  archivo: File,
  carpetaDrive: string,
  entidadId?: string | null,
  /** Las ofertas subidas a mano, cuando no están en una carpeta compartida. */
  ofertas?: File[] | null,
): Promise<AnalisisResponse> {
  const formData = new FormData()
  formData.append('codigo_proceso', codigoProceso)
  formData.append('fecha_cierre', fechaCierre)
  formData.append('archivo', archivo)
  if (ofertas && ofertas.length > 0) {
    for (const oferta of ofertas) formData.append('ofertas', oferta)
  } else if (carpetaDrive.trim()) {
    formData.append('carpeta_drive', carpetaDrive.trim())
  }
  if (entidadId) formData.append('entidad_id', entidadId)

  const res = await pedir(`/api/procesos/analizar`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const detail = await extractErrorDetail(res)
    throw new Error(detail)
  }

  return res.json()
}

const extractErrorDetail = detalleError

/** Solo el pliego, cuando la entidad se elige después (superadministrador). */
/** El análisis del pliego con el avance de la lectura con IA. */
export async function consultarPliego(id: string, entidadId: string | null): Promise<AnalisisPliego> {
  const q = entidadId ? `?entidad_id=${encodeURIComponent(entidadId)}` : ''
  const res = await pedir(`/api/procesos/pliego/${id}${q}`)
  if (!res.ok) throw new Error(await extractErrorDetail(res))
  return res.json()
}

export async function analizarPliego(archivo: File, entidadId: string | null): Promise<AnalisisPliego> {
  const formData = new FormData()
  formData.append('archivo', archivo)
  if (entidadId) formData.append('entidad_id', entidadId)
  const res = await pedir('/api/procesos/pliego', { method: 'POST', body: formData })
  if (!res.ok) throw new Error(await extractErrorDetail(res))
  return res.json()
}

// --- Kit de demostración ---
// En el equipo de la presentación, un código «DEMO-…» en «Crear proceso» llena el
// formulario solo con el Documento Base, las ofertas y la fecha de cierre.
export interface KitDemo {
  disponible: boolean
  fecha_cierre?: string | null
  ofertas?: string[]
}

export const demoKit = () => pedirJson<KitDemo>('/api/procesos/demo-kit')

export async function archivoDemoKit(nombre: string): Promise<File> {
  const res = await pedir(`/api/procesos/demo-kit/archivo?nombre=${encodeURIComponent(nombre)}`)
  if (!res.ok) throw new Error(await detalleError(res))
  const tipo = nombre.toLowerCase().endsWith('.pdf') ? 'application/pdf' : 'application/zip'
  return new File([await res.blob()], nombre, { type: tipo })
}

