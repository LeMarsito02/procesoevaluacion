import { Fragment, type ReactNode } from 'react'

/** Las siglas y los términos del oficio, explicados al pasar el cursor.
 *
 * Quien revisa es abogado: conoce el pliego, pero los textos del motor están
 * llenos de siglas de la fórmula financiera ("CRP", "SCE", "CO") y de unidades
 * del documento tipo ("SMMLV", "UNSPSC") que no tiene por qué saberse de
 * memoria. Esto no cambia el texto —sigue siendo el mismo, verificable contra
 * el documento—, solo lo anota.
 *
 * A propósito NO se explican los numerales del pliego ("3.5.6", "literal D"):
 * cambian de un proceso a otro y decir lo que creemos que significan sería
 * ponerle al abogado una regla que quizá ese pliego no tiene. */
export const TERMINOS: Record<string, string> = {
  SMMLV: 'Salarios mínimos mensuales legales vigentes: la unidad en que el pliego mide el valor de la experiencia.',
  RUP: 'Registro Único de Proponentes: el certificado de la cámara de comercio donde están inscritos los contratos que el proponente ya ejecutó.',
  UNSPSC:
    'El clasificador de bienes y servicios con el que se codifica cada contrato del RUP. El pliego exige unos códigos determinados.',
  CRP: 'Capacidad residual del proponente: el margen de contratación que le queda después de descontar lo que ya tiene en ejecución.',
  SCE: 'Saldo de los contratos que el proponente tiene en ejecución. Se resta de su capacidad.',
  CO: 'Capacidad de organización: el mayor ingreso operacional de los años que pide el pliego.',
  CT: 'Capacidad técnica: el número de profesionales de planta del proponente.',
  CF: 'Capacidad financiera: se mide con el índice de liquidez.',
  MIPYME: 'Micro, pequeña o mediana empresa. Algunos pliegos les piden indicadores financieros menos exigentes.',
  COPNIA: 'Consejo Profesional Nacional de Ingeniería: expide la tarjeta profesional y el certificado de antecedentes.',
  RNMC: 'Registro Nacional de Medidas Correctivas de la Policía Nacional.',
  REDAM: 'Registro de Deudores Alimentarios Morosos.',
  NIT: 'Número de identificación tributaria de la empresa.',
  'Formato 3': 'El formato donde el proponente lista los contratos con los que acredita su experiencia.',
  'Formato 5C': 'El formato donde el proponente declara los contratos que tiene en ejecución.',
  'Formato 2': 'El formato donde se conforma el consorcio o la unión temporal, con el porcentaje de cada integrante.',
  'Formato 1': 'La carta de presentación de la oferta.',
  'capacidad residual': 'El margen de contratación que le queda al proponente después de lo que ya tiene en ejecución.',
  'capital de trabajo': 'Activo corriente menos pasivo corriente: con cuánto cuenta la empresa para operar.',
  'cobertura de intereses': 'Cuántas veces la utilidad operacional alcanza a pagar los intereses de la deuda.',
  endeudamiento: 'Qué parte del activo está financiada con deuda.',
  liquidez: 'Cuántas veces el activo corriente cubre el pasivo corriente.',
  'unión temporal': 'Dos o más proponentes que se presentan juntos; responden según su participación en la ejecución.',
  consorcio: 'Dos o más proponentes que se presentan juntos y responden solidariamente por toda la oferta.',
  'proponente plural': 'Un consorcio o una unión temporal, frente a un proponente que se presenta solo.',
  subsanable: 'El pliego permite pedirlo después del cierre sin rechazar la oferta.',
}

// Se ordenan de más largo a más corto para que "Formato 5C" gane sobre
// "Formato 5" y "capacidad residual" sobre "capacidad".
const CLAVES = Object.keys(TERMINOS).sort((a, b) => b.length - a.length)
const escapar = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
// Las siglas se buscan como palabra entera para no marcar "CO" dentro de
// "CONTRATO"; los términos en minúscula, sin distinguir mayúsculas.
const PATRON = new RegExp(`(${CLAVES.map(escapar).join('|')})(?![A-Za-zÁÉÍÓÚÑáéíóúñ])`, 'g')

function definicionDe(fragmento: string): string | undefined {
  return TERMINOS[fragmento] ?? TERMINOS[fragmento.toLowerCase()]
}

/** El mismo texto, con los términos del oficio anotados. */
export function conGlosario(texto: string | null | undefined): ReactNode {
  if (!texto) return texto ?? null
  const partes: ReactNode[] = []
  let ultimo = 0
  for (const encontrado of texto.matchAll(PATRON)) {
    const inicio = encontrado.index ?? 0
    const fragmento = encontrado[0]
    const definicion = definicionDe(fragmento)
    if (!definicion) continue
    // Una sigla pegada a una letra ("PROPONENTES") no es la sigla.
    if (inicio > 0 && /[A-Za-zÁÉÍÓÚÑáéíóúñ]/.test(texto[inicio - 1])) continue
    if (inicio > ultimo) partes.push(texto.slice(ultimo, inicio))
    partes.push(
      <abbr key={`${inicio}-${fragmento}`} className="termino" title={definicion}>
        {fragmento}
      </abbr>,
    )
    ultimo = inicio + fragmento.length
  }
  if (partes.length === 0) return texto
  if (ultimo < texto.length) partes.push(texto.slice(ultimo))
  return <>{partes.map((p, i) => (typeof p === 'string' ? <Fragment key={i}>{p}</Fragment> : p))}</>
}

/** Los motivos del motor vienen en una sola línea separados por "; ". Con tres
 * o cuatro problemas eso es un muro de texto: se leen mucho mejor en lista.
 *
 * Pero no todo "; " separa dos motivos. El motor escribe el problema y, pegada,
 * la instrucción de qué hacer ("...no se encontró su acta (3.5.6); verifica que
 * el proponente la haya aportado"). Esa instrucción es del motivo anterior y
 * como viñeta suelta se lee como si fuera otro problema más, así que se vuelve
 * a pegar. */
const CONTINUACION = /^(verifica|revisa|confirma|confírma|comprueba|mira|pide|ten en cuenta|no se lo pidas|se asume|úsalo|tenlo)/i

export function partirMotivos(motivo: string | null | undefined): string[] {
  if (!motivo) return []
  const trozos = motivo
    .split(/;\s+/)
    .map((m) => m.trim())
    .filter(Boolean)
  const motivos: string[] = []
  for (const trozo of trozos) {
    if (motivos.length > 0 && CONTINUACION.test(trozo)) motivos[motivos.length - 1] += `; ${trozo}`
    else motivos.push(trozo)
  }
  return motivos
}
