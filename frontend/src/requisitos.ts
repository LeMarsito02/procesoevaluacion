/** Catálogo de requisitos jurídicos tal como los lee un abogado: nombre
 * corto, qué se verificó y a qué grupo de documentos pertenece. El RUT
 * (Requisito 13) se omite por decisión del abogado. */

export type GrupoRequisito = 'oferta' | 'camara' | 'antecedentes'

export interface InfoRequisito {
  numero: number
  corto: string
  titulo: string
  verifica: string
  grupo: GrupoRequisito
}

export const GRUPOS: Record<GrupoRequisito, string> = {
  oferta: 'Documentos de la oferta',
  camara: 'Cámara de Comercio',
  antecedentes: 'Antecedentes',
}

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
    verifica: 'Beneficiario ICCU, vigencia hasta la fecha mínima y valor asegurado suficiente.',
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

export const REQUISITO_POR_NUMERO: Record<number, InfoRequisito> = Object.fromEntries(
  REQUISITOS.map((r) => [r.numero, r]),
)

/** Requisitos que la interfaz muestra y cuenta (sin el RUT). */
export const NUMEROS_VISIBLES = new Set(REQUISITOS.map((r) => r.numero))
