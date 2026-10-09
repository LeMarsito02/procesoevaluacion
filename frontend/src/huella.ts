/** Huella rápida de un archivo para reconocer una carga que ya está en el
 * servidor y no volver a subirla (pueden ser 10 GB). Mismos tramos que
 * `huella_rapida` en Backend/evaluaciones/subidas.py: el principio, ocho
 * muestras repartidas y los últimos 8 MB —ahí está el índice del zip, con el
 * CRC de cada archivo de adentro—, más el tamaño.
 *
 * SHA-256 propio porque crypto.subtle solo existe en páginas seguras (HTTPS o
 * localhost), y en la red local se entra por http://192.168.x.x. */

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
])

/** SHA-256 por partes (no hace falta tener todo en memoria). */
export class Sha256 {
  private h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19])
  private bloque = new Uint8Array(64)
  private ocupado = 0
  private largo = 0
  private w = new Uint32Array(64)

  update(datos: Uint8Array): this {
    this.largo += datos.length
    let i = 0
    while (i < datos.length) {
      const n = Math.min(64 - this.ocupado, datos.length - i)
      this.bloque.set(datos.subarray(i, i + n), this.ocupado)
      this.ocupado += n
      i += n
      if (this.ocupado === 64) {
        this.procesar(this.bloque)
        this.ocupado = 0
      }
    }
    return this
  }

  hex(): string {
    const bits = this.largo * 8
    const relleno = new Uint8Array(this.ocupado < 56 ? 64 - this.ocupado : 128 - this.ocupado)
    relleno[0] = 0x80
    const vista = new DataView(relleno.buffer)
    vista.setUint32(relleno.length - 8, Math.floor(bits / 2 ** 32))
    vista.setUint32(relleno.length - 4, bits >>> 0)
    const largo = this.largo
    this.update(relleno)
    this.largo = largo
    return Array.from(this.h, (x) => x.toString(16).padStart(8, '0')).join('')
  }

  private procesar(b: Uint8Array) {
    const w = this.w
    for (let t = 0; t < 16; t++) w[t] = (b[t * 4] << 24) | (b[t * 4 + 1] << 16) | (b[t * 4 + 2] << 8) | b[t * 4 + 3]
    for (let t = 16; t < 64; t++) {
      const s0 = ((w[t - 15] >>> 7) | (w[t - 15] << 25)) ^ ((w[t - 15] >>> 18) | (w[t - 15] << 14)) ^ (w[t - 15] >>> 3)
      const s1 = ((w[t - 2] >>> 17) | (w[t - 2] << 15)) ^ ((w[t - 2] >>> 19) | (w[t - 2] << 13)) ^ (w[t - 2] >>> 10)
      w[t] = (w[t - 16] + s0 + w[t - 7] + s1) | 0
    }
    let [a, bb, c, d, e, f, g, h] = this.h
    for (let t = 0; t < 64; t++) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7))
      const ch = (e & f) ^ (~e & g)
      const t1 = (h + S1 + ch + K[t] + w[t]) | 0
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10))
      const maj = (a & bb) ^ (a & c) ^ (bb & c)
      const t2 = (S0 + maj) | 0
      h = g
      g = f
      f = e
      e = (d + t1) | 0
      d = c
      c = bb
      bb = a
      a = (t1 + t2) | 0
    }
    const nuevos = [a, bb, c, d, e, f, g, h]
    for (let i = 0; i < 8; i++) this.h[i] = (this.h[i] + nuevos[i]) | 0
  }
}

const INICIO = 1024 * 1024
const FINAL = 8 * 1024 * 1024
const MUESTRA = 256 * 1024
const MUESTRAS = 8

function tramos(tamano: number): [number, number][] {
  const salida: [number, number][] = [[0, Math.min(INICIO, tamano)]]
  for (let i = 1; i <= MUESTRAS; i++) {
    const desde = Math.floor((tamano * i) / (MUESTRAS + 1))
    salida.push([desde, Math.min(tamano, desde + MUESTRA)])
  }
  salida.push([Math.max(0, tamano - FINAL), tamano])
  return salida
}

export async function huellaRapida(archivo: File): Promise<string> {
  const h = new Sha256().update(new TextEncoder().encode(`mievaluador-huella-v1|${archivo.size}|`))
  for (const [desde, hasta] of tramos(archivo.size)) {
    h.update(new Uint8Array(await archivo.slice(desde, hasta).arrayBuffer()))
  }
  return h.hex()
}
