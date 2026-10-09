export function formatPesos(value: number): string {
  if (Number.isNaN(value)) return ''
  return new Intl.NumberFormat('es-CO', {
    style: 'currency',
    currency: 'COP',
    // Sin redondear: un valor asegurado de $1.106.861.272,8 no es $1.106.861.273.
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value)
}

export function formatFechaCorta(iso: string): string {
  if (!iso) return ''
  const [y, m, d] = iso.split('-').map(Number)
  if (!y || !m || !d) return iso
  return `${String(d).padStart(2, '0')}/${String(m).padStart(2, '0')}/${y}`
}

export function formatDuracion(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  const totalSegundos = Math.round(ms / 1000)
  const minutos = Math.floor(totalSegundos / 60)
  const segundos = totalSegundos % 60
  if (minutos === 0) return `${segundos}s`
  if (minutos >= 60) return `${Math.floor(minutos / 60)} h ${String(minutos % 60).padStart(2, '0')} min`
  return `${minutos}m ${String(segundos).padStart(2, '0')}s`
}

/** Adds `months` to an ISO date (yyyy-mm-dd), clamping the day to the target
 * month's length, matching Python's dateutil.relativedelta behaviour. */
export function addMonthsClamped(iso: string, months: number): string {
  const [y, m, d] = iso.split('-').map(Number)
  if (!y || !m || !d) return iso
  const totalMonths = m - 1 + months
  const targetYear = y + Math.floor(totalMonths / 12)
  const targetMonthIdx = ((totalMonths % 12) + 12) % 12
  const daysInTargetMonth = new Date(Date.UTC(targetYear, targetMonthIdx + 1, 0)).getUTCDate()
  const targetDay = Math.min(d, daysInTargetMonth)
  const result = new Date(Date.UTC(targetYear, targetMonthIdx, targetDay))
  return result.toISOString().slice(0, 10)
}

/** El NIT con su dígito de verificación («901.869.180-7»). El programa guarda
 * los nueve dígitos; el de verificación se calcula con la regla de la DIAN. Si
 * ya vienen diez dígitos, el último se toma como el de verificación. */
export function nitConDv(nit: string | null | undefined): string {
  let digitos = (nit ?? '').replace(/\D/g, '')
  let dv: string
  if (digitos.length === 10) {
    dv = digitos[9]
    digitos = digitos.slice(0, 9)
  } else if (digitos.length >= 6 && digitos.length <= 9) {
    const pesos = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]
    const resto = [...digitos].reverse().reduce((suma, d, i) => suma + Number(d) * pesos[i], 0) % 11
    dv = String(resto < 2 ? resto : 11 - resto)
  } else {
    return nit ?? ''
  }
  return `${Number(digitos).toLocaleString('es-CO')}-${dv}`
}

/** Copia un texto al portapapeles. `navigator.clipboard` solo existe en páginas
 * seguras (HTTPS o localhost): entrando por la red local (http://192.168.x.x) no
 * está, y el botón de copiar no hacía nada. Ahí se usa el método antiguo. */
export async function copiarAlPortapapeles(texto: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(texto)
      return true
    }
  } catch {
    // se intenta por el otro camino
  }
  const area = document.createElement('textarea')
  area.value = texto
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  area.setSelectionRange(0, texto.length)
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    document.body.removeChild(area)
  }
}

/** El NIT como lo piden las páginas oficiales: los nueve dígitos y el de verificación, sin puntos ni guion. */
export function nitParaConsulta(nit: string | null | undefined): string {
  return nitConDv(nit).replace(/\D/g, '')
}
