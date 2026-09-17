/** Estado editable de los datos del proceso (objeto, lotes, garantía) y su
 * conversión al Documento Base que usa el motor. */
import { useCallback, useMemo, useState } from 'react'
import type { Lote, ProcesoDocumentoBase } from './api'
import type { BaseCalculo } from './components/PasoDatos'
import { addMonthsClamped } from './format'

export function useDatosProceso() {
  const [objetoGeneral, setObjetoGeneral] = useState('')
  const [lotes, setLotes] = useState<Lote[]>([])
  const [vigenciaMeses, setVigenciaMeses] = useState(3)
  const [porcentajePct, setPorcentajePct] = useState(10)
  const [baseCalculo, setBaseCalculo] = useState<BaseCalculo>('lote_mayor_valor')
  const [advertencias, setAdvertencias] = useState<string[]>([])

  const cargar = useCallback((proceso: ProcesoDocumentoBase) => {
    setObjetoGeneral(proceso.objeto_general)
    setLotes(proceso.lotes)
    setVigenciaMeses(proceso.garantia_seriedad.vigencia_meses)
    setPorcentajePct(Math.round(proceso.garantia_seriedad.porcentaje * 1000) / 10)
    setBaseCalculo(proceso.garantia_seriedad.base_calculo)
    setAdvertencias(proceso.advertencias)
  }, [])

  const derivados = useMemo(() => {
    const presupuestoTotal = lotes.reduce((s, l) => s + (Number(l.valor_presupuesto) || 0), 0)
    const loteMayor = lotes.reduce<Lote | null>(
      (max, l) => (!max || (Number(l.valor_presupuesto) || 0) > (Number(max.valor_presupuesto) || 0) ? l : max),
      null,
    )
    const valorBase = baseCalculo === 'lote_mayor_valor' && loteMayor ? Number(loteMayor.valor_presupuesto) || 0 : presupuestoTotal
    return {
      presupuestoTotal,
      loteMayorNumero: loteMayor?.numero ?? '',
      valorBase,
      valorAsegurado: Math.round(valorBase * (porcentajePct / 100) * 100) / 100,
    }
  }, [lotes, baseCalculo, porcentajePct])

  const construir = useCallback(
    (codigoProceso: string, fechaCierre: string): ProcesoDocumentoBase => ({
      codigo_proceso: codigoProceso.trim(),
      fecha_cierre: fechaCierre,
      objeto_general: objetoGeneral,
      lotes,
      lote_mayor_valor: derivados.loteMayorNumero,
      presupuesto_total: derivados.presupuestoTotal,
      garantia_seriedad: {
        vigencia_meses: vigenciaMeses,
        porcentaje: porcentajePct / 100,
        base_calculo: baseCalculo,
        lote_base: baseCalculo === 'lote_mayor_valor' ? derivados.loteMayorNumero : null,
        valor_base: derivados.valorBase,
        valor_asegurado: derivados.valorAsegurado,
        fecha_cierre: fechaCierre,
        fecha_vencimiento: fechaCierre ? addMonthsClamped(fechaCierre, vigenciaMeses) : '',
      },
      advertencias,
    }),
    [objetoGeneral, lotes, derivados, vigenciaMeses, porcentajePct, baseCalculo, advertencias],
  )

  return {
    objetoGeneral,
    lotes,
    vigenciaMeses,
    porcentajePct,
    baseCalculo,
    advertencias,
    derivados,
    cargar,
    construir,
    setObjetoGeneral,
    cambiarLote: (i: number, cambios: Partial<Lote>) => setLotes((prev) => prev.map((l, j) => (j === i ? { ...l, ...cambios } : l))),
    cambiarGarantia: (c: { vigenciaMeses?: number; porcentajePct?: number; baseCalculo?: BaseCalculo }) => {
      if (c.vigenciaMeses !== undefined) setVigenciaMeses(c.vigenciaMeses)
      if (c.porcentajePct !== undefined) setPorcentajePct(c.porcentajePct)
      if (c.baseCalculo !== undefined) setBaseCalculo(c.baseCalculo)
    },
  }
}

/** Props de PasoDatos que salen de este estado. */
export function propsDatos(d: ReturnType<typeof useDatosProceso>, fechaCierre: string) {
  return {
    objetoGeneral: d.objetoGeneral,
    lotes: d.lotes,
    vigenciaMeses: d.vigenciaMeses,
    porcentajePct: d.porcentajePct,
    baseCalculo: d.baseCalculo,
    advertencias: d.advertencias,
    derivados: { ...d.derivados, fechaVencimiento: fechaCierre ? addMonthsClamped(fechaCierre, d.vigenciaMeses) : '' },
    onCambiarObjeto: d.setObjetoGeneral,
    onCambiarLote: d.cambiarLote,
    onCambiarGarantia: d.cambiarGarantia,
  }
}
