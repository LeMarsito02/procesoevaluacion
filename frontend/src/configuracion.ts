/** API de configuración por entidad (plantillas de informe). */
import { detalleError, enviarJson, ErrorApi, pedir, pedirJson } from './http'

export interface MapeoPlantilla {
  prefijo_codigo: string
  titulo: string
  hoja_proponente_patron: string
  hoja_modelo: string | null
  celda_titulo: string | null
  celda_objeto: string | null
  celda_nombre_proponente: string | null
  columna_resultado: string
  columna_detalle: string
  filas_por_requisito: Record<string, number>
  hoja_resumen: string | null
  celda_resumen: string | null
  texto_cumple: string
  texto_no_cumple: string
  texto_revisar: string
  agregar_hoja_datos: boolean
}

export interface InspeccionPlantilla {
  valida: boolean
  problemas: string[]
  hojas: string[]
  hojas_proponente: number
  filas: Record<string, string>
}

export interface Plantilla {
  id: string
  tipo: string
  nombre_original: string
  subida_en: string
  subida_por: string | null
  activa: boolean
  mapeo: MapeoPlantilla
  inspeccion: InspeccionPlantilla
}

export interface PlantillasTipo {
  tipo: string
  tipo_nombre: string
  motor_disponible: boolean
  activa: Plantilla | null
  usa_plantilla_del_sistema: boolean
  historial: Plantilla[]
}

const q = (entidadId?: string | null) => (entidadId ? `?entidad_id=${entidadId}` : '')

export const listarPlantillas = (entidadId?: string | null) => pedirJson<PlantillasTipo[]>(`/api/configuracion/plantillas${q(entidadId)}`)

export async function subirPlantilla(tipo: string, archivo: File, entidadId?: string | null): Promise<Plantilla> {
  const datos = new FormData()
  datos.append('tipo', tipo)
  datos.append('archivo', archivo)
  const res = await pedir(`/api/configuracion/plantillas${q(entidadId)}`, { method: 'POST', body: datos })
  if (!res.ok) throw new ErrorApi(res.status, await detalleError(res))
  return res.json()
}

export const ajustarMapeo = (id: string, mapeo: MapeoPlantilla) =>
  enviarJson<Plantilla>(`/api/configuracion/plantillas/${id}/mapeo`, 'PUT', { mapeo })
export const activarPlantilla = (id: string) => enviarJson<Plantilla>(`/api/configuracion/plantillas/${id}/activar`, 'POST')
export const borrarPlantilla = (id: string) => enviarJson<void>(`/api/configuracion/plantillas/${id}`, 'DELETE')

export async function descargarPlantilla(p: Plantilla) {
  const res = await pedir(`/api/configuracion/plantillas/${p.id}/archivo`)
  if (!res.ok) throw new ErrorApi(res.status, await detalleError(res))
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = p.nombre_original
  a.click()
  URL.revokeObjectURL(url)
}
