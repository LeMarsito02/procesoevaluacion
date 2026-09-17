/** Catálogo de requisitos tal como los lee el evaluador: nombre corto, qué se
 * verificó y a qué grupo pertenece.
 *
 * Cada entidad define sus propios requisitos (plantilla de evaluación), así que
 * el catálogo lo manda el servidor con cada evaluación y se instala con
 * `establecerCatalogo`. Los valores de abajo son la base del sistema (jurídica
 * de referencia, sin RUT) y sirven mientras no haya otro. */

export type GrupoRequisito = 'oferta' | 'camara' | 'antecedentes' | 'adicionales'

export interface InfoRequisito {
  numero: number
  corto: string
  titulo: string
  verifica: string
  grupo: GrupoRequisito
  pistas?: string[]
  personalizado?: boolean
}

export const GRUPOS: Record<GrupoRequisito, string> = {
  oferta: 'Documentos de la oferta',
  camara: 'Cámara de Comercio',
  antecedentes: 'Antecedentes',
  adicionales: 'Requisitos adicionales',
}

export const ORDEN_GRUPOS: GrupoRequisito[] = ['oferta', 'camara', 'antecedentes', 'adicionales']

export const REQUISITOS: InfoRequisito[] = [
  {
    numero: 1,
    corto: 'Carta',
    titulo: 'Carta de presentación de la oferta',
    verifica: 'Formato 1 firmado por el representante legal, con el número del proceso, el objeto y los lotes.',
    grupo: 'oferta',
  },
  {
    numero: 2,
    corto: 'Aval ing.',
    titulo: 'Suscrita o avalada por ingeniero',
    verifica: 'Firma o aval de un ingeniero con matrícula vigente (COPNIA de máximo 3 meses al cierre).',
    grupo: 'oferta',
  },
  {
    numero: 3,
    corto: 'COPNIA',
    titulo: 'Antecedentes disciplinarios del ingeniero',
    verifica: 'El COPNIA del ingeniero certifica que no tiene antecedentes disciplinarios.',
    grupo: 'oferta',
  },
  {
    numero: 4,
    corto: 'Plural',
    titulo: 'Conformación de proponente plural',
    verifica: 'Formato 2 con integrantes, porcentajes que suman 100% y representante designado.',
    grupo: 'oferta',
  },
  {
    numero: 11,
    corto: 'Póliza',
    titulo: 'Garantía de seriedad de la oferta',
    verifica: 'Beneficiario la entidad, vigencia hasta la fecha mínima y valor asegurado de al menos el porcentaje exigido del lote más caro al que se presenta.',
    grupo: 'oferta',
  },
  {
    numero: 12,
    corto: 'Seg. social',
    titulo: 'Pago de seguridad social y aportes',
    verifica: 'Formato 5 firmado por el representante legal o revisor fiscal (uno por integrante si es plural).',
    grupo: 'oferta',
  },
  {
    numero: 6,
    corto: 'Existencia',
    titulo: 'Certificado de existencia y representación legal',
    verifica: 'Expedido máximo 1 mes antes de la fecha de cierre.',
    grupo: 'camara',
  },
  {
    numero: 7,
    corto: 'Objeto',
    titulo: 'Objeto social',
    verifica: 'El objeto social se relaciona con el objeto del proceso.',
    grupo: 'camara',
  },
  {
    numero: 8,
    corto: 'Facultades',
    titulo: 'Facultades del representante legal',
    verifica: 'Sin límites de cuantía ni autorizaciones pendientes para contratar.',
    grupo: 'camara',
  },
  {
    numero: 9,
    corto: 'RUP',
    titulo: 'Registro Único de Proponentes (RUP)',
    verifica: 'Expedido máximo 1 mes antes de la fecha de cierre.',
    grupo: 'camara',
  },
  {
    numero: 10,
    corto: 'Sanciones',
    titulo: 'Multas y sanciones en el RUP',
    verifica: 'El RUP no reporta multas ni sanciones en firme.',
    grupo: 'camara',
  },
  {
    numero: 18,
    corto: 'Rev. fiscal',
    titulo: 'Certificado de revisor fiscal',
    verifica: 'Aplica solo a sociedades anónimas: indica si es abierta o cerrada.',
    grupo: 'camara',
  },
  {
    numero: 5,
    corto: 'REDAM',
    titulo: 'Deudores alimentarios morosos (REDAM)',
    verifica: 'El representante legal no está inscrito en el REDAM.',
    grupo: 'antecedentes',
  },
  {
    numero: 14,
    corto: 'Contraloría',
    titulo: 'Responsabilidad fiscal (Contraloría)',
    verifica: 'No reportado en el Boletín de Responsables Fiscales.',
    grupo: 'antecedentes',
  },
  {
    numero: 15,
    corto: 'Procuraduría',
    titulo: 'Antecedentes disciplinarios (Procuraduría)',
    verifica: 'No registra sanciones ni inhabilidades vigentes.',
    grupo: 'antecedentes',
  },
  {
    numero: 16,
    corto: 'Policía',
    titulo: 'Antecedentes judiciales (Policía)',
    verifica: 'No tiene asuntos pendientes con las autoridades judiciales.',
    grupo: 'antecedentes',
  },
  {
    numero: 17,
    corto: 'RNMC',
    titulo: 'Medidas correctivas (RNMC)',
    verifica: 'No tiene medidas correctivas pendientes por cumplir.',
    grupo: 'antecedentes',
  },
]

export const REQUISITO_POR_NUMERO: Record<number, InfoRequisito> = Object.fromEntries(REQUISITOS.map((r) => [r.numero, r]))

/** Palabras en el nombre del archivo que sugieren el documento de cada
 * requisito: se usan para ordenar la lista cuando el sistema no encontró el
 * documento y el abogado debe buscarlo. */
const PISTAS_ARCHIVO: Record<number, string[]> = {
  1: ['carta', 'formato 1', 'presentac'],
  2: ['copnia', 'matricula', 'tarjeta', 'aval', 'vigencia'],
  3: ['copnia', 'antecedentes', 'vigencia'],
  4: ['formato 2', 'consorci', 'union temporal', 'conformac'],
  5: ['redam', 'deudor', 'alimentari'],
  6: ['existencia', 'camara', 'rep legal', 'representacion'],
  7: ['existencia', 'camara', 'representacion'],
  8: ['existencia', 'camara', 'representacion', 'acta', 'autoriza'],
  9: ['rup', 'proponente'],
  10: ['rup', 'proponente'],
  11: ['poliza', 'póliza', 'garantia', 'garantía', 'seriedad', 'seguro'],
  12: ['formato 5', 'seguridad social', 'parafiscal', 'aportes'],
  14: ['contralor', 'fiscal'],
  15: ['procuradur', 'disciplinari'],
  16: ['policia', 'policía', 'judicial', 'penal'],
  17: ['rnmc', 'medidas correctivas', 'correctiva'],
  18: ['revisor', 'existencia'],
}

export function ordenarArchivosPorRequisito(requisito: number, archivos: string[]): string[] {
  const pistas = REQUISITO_POR_NUMERO[requisito]?.pistas ?? PISTAS_ARCHIVO[requisito] ?? []
  const puntaje = (ruta: string) => {
    const nombre = (ruta.split('/').pop() ?? ruta).toLowerCase()
    return pistas.some((p) => nombre.includes(p)) ? 0 : 1
  }
  return [...archivos].sort((a, b) => puntaje(a) - puntaje(b))
}

/** Requisitos que la interfaz muestra y cuenta. */
export const NUMEROS_VISIBLES = new Set(REQUISITOS.map((r) => r.numero))

/** Instala el catálogo de la evaluación abierta (plantilla de la entidad). */
export function establecerCatalogo(lista: InfoRequisito[]) {
  REQUISITOS.splice(0, REQUISITOS.length, ...lista.map((r) => ({ ...r, grupo: ORDEN_GRUPOS.includes(r.grupo) ? r.grupo : 'adicionales' })))
  for (const k of Object.keys(REQUISITO_POR_NUMERO)) delete REQUISITO_POR_NUMERO[Number(k)]
  for (const r of REQUISITOS) REQUISITO_POR_NUMERO[r.numero] = r
  NUMEROS_VISIBLES.clear()
  for (const r of REQUISITOS) NUMEROS_VISIBLES.add(r.numero)
}

/** Requisitos agrupados en el orden de la matriz. */
export function requisitosOrdenados(): InfoRequisito[] {
  return ORDEN_GRUPOS.flatMap((g) => REQUISITOS.filter((r) => r.grupo === g))
}
