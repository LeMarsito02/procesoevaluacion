/** Pasos del asistente de proceso y de la evaluación (barra superior). */
export type Paso = 'nuevo' | 'datos' | 'pliego' | 'evaluacion' | 'control' | 'informe'

export const PASOS_NUEVO: { id: Paso; nombre: string }[] = [
  { id: 'nuevo', nombre: 'Documento y ofertas' },
  { id: 'datos', nombre: 'Datos del proceso' },
  { id: 'pliego', nombre: 'Lo que exige el pliego' },
]

export const PASOS_EVALUACION: { id: Paso; nombre: string }[] = [
  { id: 'datos', nombre: 'Datos del proceso' },
  { id: 'evaluacion', nombre: 'Evaluación y revisión' },
  // La muestra de control va antes del informe, y como paso propio: es la
  // adopción humana de lo que el sistema verificó, no un detalle del informe.
  { id: 'control', nombre: 'Control de la verificación' },
  { id: 'informe', nombre: 'Informe' },
]
