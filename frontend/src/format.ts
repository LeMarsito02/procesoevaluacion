export function formatPesos(value: number): string {
  if (Number.isNaN(value)) return ''
  return new Intl.NumberFormat('es-CO', {
    style: 'currency',
    currency: 'COP',
    maximumFractionDigits: 0,
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
