/** '' = sin asignar; 'yo' = quien crea; otro valor = id de la persona. */
export type Eleccion = '' | 'yo' | string

/** dependencia: '' = la que sugiera el objeto del contrato; otro valor = id de la dependencia. */
/** comite: más integrantes del comité (ids), además del responsable, que lo coordina. */
export type SeleccionTipos = Record<string, { incluir: boolean; eleccion: Eleccion; dependencia?: string; comite?: string[] }>

export const SELECCION_INICIAL: SeleccionTipos = {
  juridica: { incluir: true, eleccion: '' },
  tecnica: { incluir: false, eleccion: '' },
  financiera: { incluir: false, eleccion: '' },
}
