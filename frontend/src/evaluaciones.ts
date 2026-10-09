/** API de procesos y evaluaciones guardados en el servidor. */
import type { AnalisisResponse, DecisionPliego, HallazgoPliego, ProcesoDocumentoBase, Proponente, ResultadoRequisito } from './api'
import type { InfoRequisito } from './requisitos'
import { detalleError, enviarJson, ErrorApi, pedir, pedirJson } from './http'

export type EstadoEvaluacion = 'sin_asignar' | 'asignada' | 'evaluando' | 'en_revision' | 'aprobada'

export interface Persona {
  id: string
  nombre_completo: string
  email: string
}

export interface Avance {
  proponentes: number
  evaluados: number
  con_error: number
  pendientes: number
  revisados: number
  en_fila: number
  procesando: number
}

export interface Fila {
  en_fila: number
  procesando: number
  por_delante: number
  capacidad: number
  segundos_por_proponente: number
  eta_segundos: number | null
}

export interface EvaluacionResumen {
  id: string
  tipo: string
  tipo_nombre: string
  estado: EstadoEvaluacion
  estado_nombre: string
  responsable: Persona | null
  avance: Avance
  entidad_id: string
  entidad_nombre: string
  proceso_id: string
  proceso_codigo: string
  proceso_objeto: string
  fecha_cierre: string
  actualizada_en: string
  aprobada_en: string | null
  puede_trabajar: boolean
  puede_gestionar: boolean
  tipo_disponible: boolean
  plantilla_version: number | null
  plantilla_nombre: string
  plantilla_desactualizada: boolean
  fila: Fila | null
  /** Dependencia que evalúa y comité designado (el primero coordina). */
  dependencia: { id: string; nombre: string } | null
  comite: Persona[]
}

export interface ProcesoResumen {
  id: string
  codigo: string
  objeto: string
  fecha_cierre: string
  creado_en: string
  creado_por: Persona
  proponentes: number
  evaluaciones: EvaluacionResumen[]
  /** Archivar: quien puede eliminarlo, aunque ya tenga expediente (entonces no se elimina). */
  puede_archivar?: boolean
  archivado_en?: string | null
  /** Quien lo ve puede eliminarlo (administrador o quien lo creó, y sin evaluaciones aprobadas). */
  puede_eliminar: boolean
}

export interface ProponenteGuardado extends Proponente {
  id: string
}

export interface RevisionGuardada {
  proponente_id: string
  hoja: string
  requisito: number
  cumple: boolean
  nota: string
  usuario: string
  fecha: string
}

export interface EvaluacionDetalle {
  evaluacion: EvaluacionResumen
  documento_base: ProcesoDocumentoBase
  carpeta_drive: string
  proponentes_no_reconocidos: string[]
  proponentes: ProponenteGuardado[]
  resultados: ResultadoRequisito[]
  revisiones: RevisionGuardada[]
  catalogo: InfoRequisito[]
  pliego: PliegoProceso | null
  /** Otras áreas del proceso que este usuario puede poner a evaluar ahora. */
  otras_por_evaluar: { id: string; tipo_nombre: string }[]
}

/** Decisión tomada al crear el proceso sobre un hallazgo del pliego. */
export interface AjustePliego {
  id: string
  decision: 'aceptado' | 'rechazado'
  nota: string
  por: string
  en: string
  hallazgo: HallazgoPliego
}

export interface PliegoProceso {
  nombre_archivo: string
  paginas: number
  documento_tipo: string
  ajustes: AjustePliego[]
  aclaraciones: HallazgoPliego[]
  obligaciones: HallazgoPliego[]
}

export const urlPliego = (evaluacionId: string) => `/api/evaluaciones/${evaluacionId}/pliego`

export interface MiembroCarga extends Persona {
  rol: string
  rol_nombre: string
  areas: string[]
  evaluaciones_activas: number
  pendientes: number
}

export const listarProcesos = (archivados = false) =>
  pedirJson<ProcesoResumen[]>(`/api/evaluaciones/procesos${archivados ? '?archivados=true' : ''}`)
/** Archiva (o desarchiva) un proceso: se conserva con todo, pero sale de las listas. */
export const archivarProceso = (id: string, archivar = true) =>
  enviarJson<void>(`/api/evaluaciones/procesos/${id}/archivar${archivar ? '' : '?archivar=false'}`, 'POST')
/** Elimina el proceso con todo lo suyo. `confirmacion` = su código, escrito a mano. */
export const eliminarProceso = (id: string, confirmacion: string) =>
  enviarJson<void>(`/api/evaluaciones/procesos/${id}`, 'DELETE', { confirmacion })
export const misEvaluaciones = () => pedirJson<EvaluacionResumen[]>('/api/evaluaciones/mias')
export const cargaEquipo = (entidadId?: string | null) =>
  pedirJson<MiembroCarga[]>(`/api/evaluaciones/equipo${entidadId ? `?entidad_id=${entidadId}` : ''}`)
export const obtenerEvaluacion = (id: string) => pedirJson<EvaluacionDetalle>(`/api/evaluaciones/${id}`)

export const crearProceso = (datos: {
  documento_base: ProcesoDocumentoBase
  carpeta_drive: string
  proponentes: Proponente[]
  proponentes_no_reconocidos: string[]
  tipos: string[]
  entidad_id?: string | null
  dependencias?: Record<string, string | undefined>
  /** La preparación (proceso a medio crear) de la que sale: el servidor la borra al crearlo. */
  preparacion_id?: string | null
  /** Más integrantes del comité por tipo, además del responsable. */
  comites?: Record<string, string[]>
  responsable_id?: string | null
  sin_responsable?: boolean
  responsables?: Record<string, string | null>
  analisis_pliego_id?: string | null
  decisiones_pliego?: Record<string, DecisionPliego>
}) => enviarJson<EvaluacionResumen[]>('/api/evaluaciones/procesos', 'POST', datos)

export const guardarDocumentoBase = (id: string, doc: ProcesoDocumentoBase) =>
  enviarJson<ProcesoDocumentoBase>(`/api/evaluaciones/${id}/documento-base`, 'PUT', doc)
export const asignarEvaluacion = (id: string, responsableId: string | null) =>
  enviarJson<EvaluacionResumen>(`/api/evaluaciones/${id}/asignar`, 'POST', { responsable_id: responsableId })
export const aprobarEvaluacion = (id: string) => enviarJson<EvaluacionResumen>(`/api/evaluaciones/${id}/aprobar`, 'POST')
export const reabrirEvaluacion = (id: string) => enviarJson<EvaluacionResumen>(`/api/evaluaciones/${id}/reabrir`, 'POST')
export const guardarRevision = (id: string, proponenteId: string, requisito: number, cumple: boolean | null, nota = '') =>
  enviarJson<RevisionGuardada | null>(`/api/evaluaciones/${id}/revisiones`, 'PUT', {
    proponente_id: proponenteId,
    requisito,
    cumple,
    nota,
  })

export const encolarEvaluacion = (id: string, proponenteIds?: string[]) =>
  enviarJson<EvaluacionResumen>(`/api/evaluaciones/${id}/evaluar`, 'POST', { proponente_ids: proponenteIds ?? null })
export const pausarEvaluacion = (id: string) => enviarJson<EvaluacionResumen>(`/api/evaluaciones/${id}/pausar`, 'POST')
export const novedadesEvaluacion = (id: string, desde: string | null) =>
  pedirJson<{ evaluacion: EvaluacionResumen; resultados: ResultadoRequisito[]; hasta: string; bloqueos: Bloqueo[] }>(
    `/api/evaluaciones/${id}/novedades${desde ? `?desde=${encodeURIComponent(desde)}` : ''}`,
  )

async function descargarBlob(ruta: string): Promise<{ blob: Blob; nombre: string | null }> {
  const res = await pedir(ruta)
  if (!res.ok) throw new ErrorApi(res.status, await detalleError(res))
  const disposicion = res.headers.get('Content-Disposition') ?? ''
  const nombre = /filename="([^"]+)"/.exec(disposicion)?.[1] ?? null
  return { blob: await res.blob(), nombre }
}

/** El informe en Excel (la plantilla oficial) o en PDF, y los resultados en CSV (RF-22). */
export type FormatoInforme = 'xlsx' | 'pdf' | 'csv'
export const descargarInforme = (id: string, formato: FormatoInforme = 'xlsx') =>
  descargarBlob(formato === 'csv' ? `/api/evaluaciones/${id}/resultados.csv` : `/api/evaluaciones/${id}/informe?formato=${formato}`)
/** Las tres áreas del proceso en un archivo, con puntaje y orden de elegibilidad. */
export const descargarConsolidado = (id: string, formato: 'xlsx' | 'pdf' = 'xlsx') => descargarBlob(`/api/evaluaciones/${id}/consolidado?formato=${formato}`)
export const verDocumentoProponente = (id: string, proponenteId: string, archivo: string) =>
  descargarBlob(`/api/evaluaciones/${id}/proponentes/${proponenteId}/documento?archivo=${encodeURIComponent(archivo)}`).then((r) => r.blob)

/** Una página del documento como imagen (para los equipos que no muestran un PDF
 * dentro de la página). Devuelve la imagen y cuántas páginas tiene el documento. */
export async function paginaDelDocumento(
  id: string, proponenteId: string, archivo: string, n: number, resolucion: number,
): Promise<{ blob: Blob; paginas: number }> {
  const res = await pedir(
    `/api/evaluaciones/${id}/proponentes/${proponenteId}/documento/pagina?archivo=${encodeURIComponent(archivo)}&n=${n}&resolucion=${resolucion}`,
  )
  if (!res.ok) throw new ErrorApi(res.status, await detalleError(res))
  return { blob: await res.blob(), paginas: Number(res.headers.get('X-Paginas') ?? '1') || 1 }
}

/** Dónde aparece un texto dentro de un documento de la oferta (con el texto
 * leído por OCR: el buscador del navegador no ve nada en un escaneo). */
export const buscarEnDocumento = (id: string, proponenteId: string, archivo: string, q: string) =>
  pedirJson<{ pagina: number; fragmento: string }[]>(
    `/api/evaluaciones/${id}/proponentes/${proponenteId}/documento/buscar?archivo=${encodeURIComponent(archivo)}&q=${encodeURIComponent(q)}`,
  )

/** Sube la Matriz 2 del proceso (PDF, Word o Excel): de ella salen los umbrales
 * de los indicadores financieros. Los proponentes ya evaluados vuelven a la fila. */
export async function subirMatriz2(id: string, archivo: File): Promise<{ avisos: string[]; reevaluados: number }> {
  const cuerpo = new FormData()
  cuerpo.append('archivo', archivo)
  const res = await pedir(`/api/evaluaciones/${id}/matriz2`, { method: 'POST', body: cuerpo })
  if (!res.ok) throw new ErrorApi(res.status, await detalleError(res))
  return res.json()
}

/** Deja `archivos` como los documentos asociados a mano a un requisito (reemplaza
 * la lista anterior). Devuelve el resultado ya actualizado. */
export const asociarDocumentos = (id: string, proponenteId: string, requisito: number, archivos: string[], excluidos: string[]) =>
  enviarJson<ResultadoRequisito>(`/api/evaluaciones/${id}/proponentes/${proponenteId}/requisitos/${requisito}/documentos`, 'PUT', { archivos, excluidos })

/** Todos los documentos de la oferta del proponente, para mirar la carpeta y
 * buscar a mano el que el motor no encontró. */
export const archivosDelProponente = (id: string, proponenteId: string) =>
  pedirJson<{ archivos: string[]; aportados: string[] }>(
    `/api/evaluaciones/${id}/proponentes/${proponenteId}/archivos`,
  )

export type { AnalisisResponse }

// --- Muestra de control (expediente LEG-004, numerales 3 y 3.1) ---
export interface ItemMuestra {
  id: number
  proponente_id: string
  hoja: string
  proponente: string
  requisito: number
  usa_ia: boolean
  resultado: 'conforme' | 'no_conforme' | null
  nota: string
  soporte_visto: boolean
  /** La decisión sale del pliego (N.A.): su soporte es el pliego, no la oferta. */
  soporte_pliego: boolean
  usuario: string | null
  fecha: string | null
}

export interface Muestra {
  id: string
  estado: 'en_curso' | 'con_hallazgos' | 'cerrada' | 'anulada'
  estado_nombre: string
  semilla: string
  parametros: { verificaciones?: number; universo_ofertas?: number; universo_verificaciones?: number }
  ofertas_sorteadas: string[]
  requisitos_ampliados: number[]
  creada_por: string
  creada_en: string
  cerrada_por: string | null
  cerrada_en: string | null
  items: ItemMuestra[]
}

export interface EstadoMuestra {
  muestra: Muestra | null
  motivo_para_no_aprobar: string | null
  verificaciones_por_muestra: number
}

export const verMuestra = (id: string) => pedirJson<EstadoMuestra>(`/api/evaluaciones/${id}/muestra`)
export const crearMuestra = (id: string) => enviarJson<EstadoMuestra>(`/api/evaluaciones/${id}/muestra`, 'POST')
export const revisarItemMuestra = (id: string, itemId: number, conforme: boolean, nota = '') =>
  enviarJson<EstadoMuestra>(`/api/evaluaciones/${id}/muestra/items/${itemId}`, 'PUT', { conforme, nota })
export const cerrarMuestra = (id: string) => enviarJson<EstadoMuestra>(`/api/evaluaciones/${id}/muestra/cerrar`, 'POST')
export const descargarActaMuestra = (id: string) => descargarBlob(`/api/evaluaciones/${id}/muestra/acta`)

// --- Puntaje técnico: lo adopta una persona, en un solo acto ---
export interface PuntajeProponente {
  proponente_id: string
  hoja: string
  nombre: string
  puntaje: number | null
  resuelto: boolean
  detalle: Record<string, number | string>
  adoptado: boolean
  adoptado_por: string | null
  adoptado_en: string | null
  adopcion_desactualizada: boolean
}

export const verPuntajes = (id: string) => pedirJson<PuntajeProponente[]>(`/api/evaluaciones/${id}/puntajes`)
export const adoptarPuntajes = (id: string, nota = '') =>
  enviarJson<PuntajeProponente[]>(`/api/evaluaciones/${id}/puntajes/adoptar`, 'POST', { nota })

// --- Ficha de transparencia algorítmica (Directiva Conjunta 007 de 2025) ---
export interface FichaTransparencia {
  sistema: string
  responsable: string
  version: string
  generada_en: string
  finalidad: string
  que_hace: string[]
  que_no_hace: string[]
  como_decide_el_sistema: string
  control_humano: string[]
  datos_tratados: string
  modelos: { uso: string; modelo: string; licencia: string; donde_se_ejecuta: string }[]
  atribucion: string | null
  medicion: {
    fecha: string
    proponentes: number
    decisiones: number
    verificadas_por_el_sistema: number
    verificaciones_contradichas_por_el_evaluador: number
    limite_superior_de_error_95: number | null
  } | null
  aviso: string
  como_pedir_explicaciones: string
  marco: string[]
}

export const verFicha = () => pedirJson<FichaTransparencia>('/api/acerca')
export const descargarFicha = () => descargarBlob('/api/acerca/ficha')

export interface TrabajadorFila {
  id: string
  capacidad: number
  iniciado_en: string
  latido: string
  activo: boolean
}

export interface EstadoFilaGlobal {
  capacidad_activa: number
  segundos_por_proponente: number
  total_en_fila: number
  total_procesando: number
  trabajadores: TrabajadorFila[]
  evaluaciones: EvaluacionResumen[]
}

export const estadoDeLaFila = () => pedirJson<EstadoFilaGlobal>('/api/evaluaciones/fila/estado')

export interface TipoEvaluacion {
  clave: 'juridica' | 'tecnica' | 'financiera'
  nombre: string
  descripcion: string
  disponible: boolean
}

export interface LoteFinanciero {
  nombre: string
  presupuesto: number | null
  plazo_meses: number | null
  anticipo: number | null
  capital_de_trabajo_demandado: number | null
  capacidad_residual_del_proceso: number | null
}

export interface UmbralesFinancieros {
  liquidez_min: number | null
  endeudamiento_max: number | null
  cobertura_min: number | null
  roa_min: number | null
  roe_min: number | null
  fuente: string
}

export interface ParametrosFinancieros {
  smmlv: number
  lotes: LoteFinanciero[]
  umbrales: UmbralesFinancieros
  /** Los que la Matriz 2 reserva a los proponentes que acrediten ser Mipyme:
   * más laxos, y se aplican solo a quien lo acredite con su RUP. */
  umbrales_mipyme?: UmbralesFinancieros | null
  umbrales_completos: boolean
  patrimonio_aplica: boolean
  avisos: string[]
}

export const parametrosFinancieros = (id: string) =>
  pedirJson<ParametrosFinancieros | null>(`/api/evaluaciones/${id}/parametros-financieros`)
export const registrarUmbrales = (id: string, u: Omit<UmbralesFinancieros, 'fuente'>) =>
  enviarJson<ParametrosFinancieros>(`/api/evaluaciones/${id}/umbrales-financieros`, 'PUT', u)
/** Un parámetro que el programa leyó del pliego, con la frase que lo respalda. */
export interface ParametroPliego {
  campo: string
  valor_reglas: unknown
  valor_ia: unknown
  /** regla · regla+ia · ia · conflicto · persona */
  origen: string
  en_firme: boolean
  confirmado: unknown
  cita: string
  seccion: string
}

export const parametrosPliego = (id: string) =>
  pedirJson<ParametroPliego[]>(`/api/evaluaciones/${id}/parametros-pliego`)
export const confirmarParametrosPliego = (id: string, valores: Record<string, unknown>) =>
  enviarJson<{ confirmados: Record<string, unknown>; reevaluados: number }>(
    `/api/evaluaciones/${id}/parametros-pliego`, 'PUT', valores)

export interface RequisitoPliego {
  clave: string
  requisito: string
  cita: string
  asumido: boolean
}

export const requisitosPliego = (id: string) =>
  pedirJson<RequisitoPliego[]>(`/api/evaluaciones/${id}/requisitos-pliego`)
export const asumirRequisitosPliego = (id: string, claves: string[]) =>
  enviarJson<{ asumidos: number; reevaluados: number }>(
    `/api/evaluaciones/${id}/requisitos-pliego`, 'POST', { claves })

export interface RequisitoNoAutomatizado {
  clave: string
  requisito: string
  cita: string
  clase: string
  area: string
  veces: number
  veces_asumido: number
  procesos: string[]
  entidades: number
  primera_vez: string
  ultima_vez: string
}

export interface CausaDeRevision {
  clave: string
  ambito: string
  area: string
  ejemplo: string
  ofertas: number
  veces: number
  procesos: string[]
  primera_vez: string
  ultima_vez: string
  nota: string
}

export const requisitosNoAutomatizados = () =>
  pedirJson<RequisitoNoAutomatizado[]>('/api/evaluaciones/requisitos-no-automatizados')
export const causasDeRevision = () => pedirJson<CausaDeRevision[]>('/api/evaluaciones/causas-de-revision')

export const listarTipos = () => pedirJson<TipoEvaluacion[]>('/api/evaluaciones/tipos')

export const actualizarPlantillaEvaluacion = (id: string) =>
  enviarJson<EvaluacionResumen>(`/api/evaluaciones/${id}/actualizar-plantilla`, 'POST')

/** La explicación en palabras llanas de un resultado, redactada por el modelo
 * local. `texto` viene en null cuando el modelo no está disponible o no se pudo
 * verificar lo que respondió: la pantalla se queda con el detalle técnico. */
export const explicacionDelResultado = (evaluacionId: string, proponenteId: string, requisito: number, soloGuardada = false) =>
  pedirJson<{ texto: string | null }>(
    `/api/evaluaciones/${evaluacionId}/proponentes/${proponenteId}/explicacion/${requisito}${soloGuardada ? '?guardada=true' : ''}`,
  )


// --- Comité evaluador y colaboración en tiempo real ---
/** Quién está revisando un proponente ahora mismo. */
export interface Bloqueo {
  hoja: string
  nombre: string
  propio: boolean
}

export interface Designacion {
  id: number
  consecutivo: string
  version: number
  dependencia: string
  miembros: { nombre: string; email: string; coordinador: boolean }[]
  designado_por: string
  designado_en: string
  sha256: string
}

export interface Comite {
  dependencia: { id: string; nombre: string } | null
  miembros: Persona[]
  designaciones: Designacion[]
}

export const verComite = (id: string) => pedirJson<Comite>(`/api/evaluaciones/${id}/comite`)
export const designarComite = (id: string, miembros: string[], dependenciaId: string | null) =>
  enviarJson<Comite>(`/api/evaluaciones/${id}/comite`, 'PUT', { miembros, dependencia_id: dependenciaId })
export const urlDesignacion = (id: string, designacionId: number) => `/api/evaluaciones/${id}/designaciones/${designacionId}/documento`
export const tomarBloqueo = (id: string, proponenteId: string) =>
  enviarJson<{ propio: boolean; nombre: string | null; solo_lectura: boolean }>(
    `/api/evaluaciones/${id}/proponentes/${proponenteId}/bloqueo`,
    'POST',
  )
export const soltarBloqueo = (id: string, proponenteId: string) =>
  pedir(`/api/evaluaciones/${id}/proponentes/${proponenteId}/bloqueo`, { method: 'DELETE' }).catch(() => undefined)

// --- Acta de revisión cruzada de los comités (por proceso) ---
export interface ActaRevisionCruzada {
  id: number
  consecutivo: string
  version: number
  generada_por: string
  generada_en: string
  sha256: string
  todas_aprobadas: boolean
  pendientes: number
}
export interface ActasRevisionCruzada {
  puede_generar: boolean
  actas: ActaRevisionCruzada[]
}
export const verActasRevisionCruzada = (procesoId: string) =>
  pedirJson<ActasRevisionCruzada>(`/api/evaluaciones/procesos/${procesoId}/revision-cruzada`)
export const generarActaRevisionCruzada = (procesoId: string) =>
  enviarJson<ActasRevisionCruzada>(`/api/evaluaciones/procesos/${procesoId}/revision-cruzada`, 'POST')
export const urlActaRevisionCruzada = (procesoId: string, actaId: number) =>
  `/api/evaluaciones/procesos/${procesoId}/revision-cruzada/${actaId}/documento`
