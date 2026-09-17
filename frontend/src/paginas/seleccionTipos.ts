/** '' = sin asignar; 'yo' = quien crea; otro valor = id de la persona. */
export type Eleccion = '' | 'yo' | string

export type SeleccionTipos = Record<string, { incluir: boolean; eleccion: Eleccion }>

export const SELECCION_INICIAL: SeleccionTipos = {
  juridica: { incluir: true, eleccion: '' },
  tecnica: { incluir: false, eleccion: '' },
  financiera: { incluir: false, eleccion: '' },
}
