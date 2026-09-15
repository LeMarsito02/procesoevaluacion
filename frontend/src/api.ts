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
}

export interface ResultadoRequisito {
  hoja: string
  numero_orden: number
  nombre_proponente: string
  requisito: number
  cumple: boolean | null
  motivo: string | null
  archivo_evaluado: string | null
  lotes_encontrados: string[]
  numero_proceso_encontrado: boolean
  objeto_relacionado: boolean | null
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
}

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export async function analizarDocumentoBase(
  codigoProceso: string,
  fechaCierre: string,
  archivo: File,
  carpetaDrive: string,
): Promise<AnalisisResponse> {
  const formData = new FormData()
  formData.append('codigo_proceso', codigoProceso)
  formData.append('fecha_cierre', fechaCierre)
  formData.append('archivo', archivo)
  if (carpetaDrive.trim()) {
    formData.append('carpeta_drive', carpetaDrive.trim())
  }

  const res = await fetch(`${API_URL}/api/procesos/analizar`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const detail = await extractErrorDetail(res)
    throw new Error(detail)
  }

  return res.json()
}

export async function generarExcel(
  proceso: ProcesoDocumentoBase,
  proponentes: Proponente[],
  resultados: ResultadoRequisito[],
): Promise<Blob> {
  const res = await fetch(`${API_URL}/api/procesos/generar-excel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      documento_base: proceso,
      proponentes,
      resultados,
    }),
  })

  if (!res.ok) {
    const detail = await extractErrorDetail(res)
    throw new Error(detail)
  }

  return res.blob()
}

export async function verDocumento(driveFileId: string, archivoEvaluado: string): Promise<Blob> {
  const res = await fetch(`${API_URL}/api/procesos/proponentes/documento`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ drive_file_id: driveFileId, archivo_evaluado: archivoEvaluado }),
  })

  if (!res.ok) {
    const detail = await extractErrorDetail(res)
    throw new Error(detail)
  }

  return res.blob()
}

function resultadoVacio(requisito: number, proponente: Proponente, error: string): ResultadoRequisito {
  return {
    hoja: proponente.hoja,
    numero_orden: proponente.numero_orden,
    nombre_proponente: proponente.nombre_proponente,
    requisito,
    cumple: null,
    motivo: null,
    archivo_evaluado: null,
    lotes_encontrados: [],
    numero_proceso_encontrado: false,
    objeto_relacionado: null,
    firma_detectada: false,
    representante_legal: null,
    firma_nombre_certificado: null,
    firma_confirmada: null,
    matricula_profesional: null,
    profesion_certificada: null,
    copnia_vigente: null,
    copnia_sin_antecedentes: null,
    copnia_fecha_expedicion: null,
    error,
    archivos_disponibles: [],
  }
}

async function evaluarUnProponente(
  requisito: number,
  proceso: ProcesoDocumentoBase,
  proponente: Proponente,
): Promise<ResultadoRequisito> {
  const res = await fetch(`${API_URL}/api/procesos/evaluar-requisito-${requisito}/proponente`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ documento_base: proceso, proponente }),
  })

  if (!res.ok) {
    const detail = await extractErrorDetail(res)
    return resultadoVacio(requisito, proponente, detail)
  }

  return res.json()
}

// Limitado para no saturar la RAM: cada evaluación puede tener en memoria un
// zip de proponente de hasta ~200 MB, así que muchas en paralelo pueden
// colgar una máquina de escritorio normal.
const CONCURRENCIA_EVALUACION = 4

/** Evalúa los proponentes uno por uno (con varios en paralelo) para poder
 * reportar avance en tiempo real en vez de esperar en silencio una sola
 * petición larga. Sirve para cualquier número de requisito: agregar uno
 * nuevo del lado del backend no requiere tocar esta función. */
export async function evaluarRequisito(
  requisito: number,
  proceso: ProcesoDocumentoBase,
  proponentes: Proponente[],
  onProgreso?: (completados: number, total: number, ultimoResultado: ResultadoRequisito) => void,
): Promise<ResultadoRequisito[]> {
  const resultados: ResultadoRequisito[] = new Array(proponentes.length)
  let siguiente = 0
  let completados = 0

  async function trabajador() {
    while (siguiente < proponentes.length) {
      const indice = siguiente++
      const resultado = await evaluarUnProponente(requisito, proceso, proponentes[indice])
      resultados[indice] = resultado
      completados++
      onProgreso?.(completados, proponentes.length, resultado)
    }
  }

  const trabajadores = Array.from({ length: Math.min(CONCURRENCIA_EVALUACION, proponentes.length) }, trabajador)
  await Promise.all(trabajadores)
  return resultados
}

async function extractErrorDetail(res: Response): Promise<string> {
  try {
    const data = await res.json()
    if (typeof data?.detail === 'string') return data.detail
    return JSON.stringify(data?.detail ?? data)
  } catch {
    return `Error ${res.status}: ${res.statusText}`
  }
}
