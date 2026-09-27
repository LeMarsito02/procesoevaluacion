/** Banco de pruebas visual, solo en desarrollo (#/previsualizacion).
 *
 * Sirve para mirar los componentes de revisión con datos inventados sin tener
 * que crear un proceso ni iniciar sesión. Ningún dato aquí es real. */
import { useState } from 'react'
import type { ResultadoRequisito } from '../api'
import { requisitosOrdenados } from '../requisitos'
import DetalleFinanciero from '../components/DetalleFinanciero'
import PanelProponente from '../components/PanelProponente'
import PasoEvaluacion from '../components/PasoEvaluacion'
import PasoNuevo from '../components/PasoNuevo'
import VisorDocumento from '../components/VisorDocumento'
import Motivos from '../components/Motivos'
import DetalleTecnico from '../components/DetalleTecnico'
import QueFaltaRevisar from '../components/QueFaltaRevisar'

const BASE = {
  hoja: 'P-01',
  numero_orden: 1,
  nombre_proponente: 'CONSORCIO VÍAS DE EJEMPLO',
  cumple: false,
  archivo_evaluado: '13. Formato 3 - Experiencia.pdf',
  lotes_encontrados: ['LOTE 1'],
  numero_proceso_encontrado: true,
  objeto_relacionado: true,
  tipo_proponente: 'consorcio' as const,
  firma_detectada: true,
  representante_legal: 'ANA MARÍA PÉREZ',
  firma_nombre_certificado: null,
  firma_confirmada: null,
  matricula_profesional: null,
  profesion_certificada: null,
  copnia_vigente: null,
  copnia_sin_antecedentes: null,
  copnia_fecha_expedicion: null,
  error: null,
  archivos_disponibles: [],
  personas_antecedente: [],
}

const TECNICO: ResultadoRequisito = {
  ...BASE,
  requisito: 30,
  motivo:
    'contrato 2: no se encontró su acta o certificación entre los documentos de la oferta (3.5.6); verifica que el proponente la haya aportado; contrato 1: experiencia de un socio o accionista de INGENIERÍA DE EJEMPLO SAS (3.5.2 E): constituida el 18/11/2020, tiene más de tres años y conserva la experiencia; revisa el certificado de composición accionaria',
  detalle: {
    lote: 'LOTE 1',
    valor_a_certificar: 300.92,
    valor_certificado: 964.04,
    factor: 0.75,
    un_contrato_70: true,
    longitud: null,
    condiciones_plural: true,
    experiencia_acreditada: false,
    contratos: [
      {
        orden: 1,
        consecutivos: ['49'],
        contratante: 'INSTITUTO DE EJEMPLO',
        numero_contrato: '1122-11',
        objeto: 'INTERVENTORÍA TÉCNICA, ADMINISTRATIVA Y FINANCIERA AL MEJORAMIENTO DE LA VÍA ALFA - BETA',
        valor_smmlv: 601.4,
        participacion: 0.9,
        valor_aportado: 541.26,
        aportes: { 'INGENIERÍA DE EJEMPLO SAS': 541.26 },
        unspsc: true,
        de_un_socio: true,
        longitud_km: 12.4,
        soporte_longitud: 'Acta de recibo final.pdf',
        problemas: [],
      },
      {
        orden: 2,
        consecutivos: ['31'],
        contratante: 'MUNICIPIO DE EJEMPLO',
        numero_contrato: '4059-23',
        objeto: 'INTERVENTORÍA AL MANTENIMIENTO Y REHABILITACIÓN DE LA CARRETERA GAMMA',
        valor_smmlv: 469.75,
        participacion: 0.9,
        valor_aportado: 422.78,
        aportes: {},
        unspsc: true,
        de_un_socio: false,
        longitud_km: null,
        soporte_longitud: null,
        problemas: ['no se encontró su acta o certificación entre los documentos de la oferta (3.5.6)'],
      },
    ],
    revisiones: [
      {
        clave: 'soporte_contrato_2',
        ambito: 'oferta',
        que: 'el acta o certificación del contrato 2 (MUNICIPIO DE EJEMPLO, 4059-23)',
        donde: '',
      },
      {
        clave: 'socio_contrato_1',
        ambito: 'oferta',
        que: 'el certificado de composición accionaria de INGENIERÍA DE EJEMPLO SAS (3.5.2 E)',
        donde: '',
      },
      {
        clave: 'unspsc',
        ambito: 'proceso',
        que: 'los códigos UNSPSC que exige el pliego no se pudieron leer: confírmalos una vez en «Lo que se entendió del pliego»',
        donde: '',
      },
    ],
  } as never,
}

const FINANCIERO: ResultadoRequisito = {
  ...BASE,
  requisito: 22,
  motivo: 'No se pudo calcular la capacidad residual: falta el saldo de los contratos en ejecución.',
  detalle: {
    financiera: {
      lote: 'LOTE 1',
      liquidez: 8.35,
      endeudamiento: 0.36,
      cobertura: 12.4,
      exigida: 1200000000,
      crp: null,
      integrantes: [
        {
          nombre: 'IES INGENIEROS DE EJEMPLO S.A.S',
          co: 32900045880,
          e: 60.36,
          puntos_e: 120,
          profesionales: 6,
          puntos_ct: 30,
          liquidez: 8.35,
          puntos_cf: 40,
          sce: null,
          crp: null,
        },
      ],
    },
    revisiones: [
      {
        clave: 'sce',
        ambito: 'oferta',
        que: 'el saldo de los contratos en ejecución no se pudo leer del Formato 5C',
        donde: '',
      },
    ],
  } as never,
}


const PROPONENTES = [
  { numero_orden: 1, hoja: 'P-01', nombre_proponente: 'CONSORCIO VÍAS DE EJEMPLO', nombre_archivo: 'p01.zip', drive_file_id: '1', advertencia: null },
  { numero_orden: 2, hoja: 'P-02', nombre_proponente: 'INGENIERÍA DE EJEMPLO S.A.S.', nombre_archivo: 'p02.zip', drive_file_id: '2', advertencia: null },
  { numero_orden: 3, hoja: 'P-03', nombre_proponente: 'UNIÓN TEMPORAL EJEMPLO 2026', nombre_archivo: 'p03.zip', drive_file_id: '3', advertencia: null },
  { numero_orden: 4, hoja: 'P-04', nombre_proponente: 'CONSTRUCTORA DE EJEMPLO LTDA', nombre_archivo: 'p04.zip', drive_file_id: '4', advertencia: 'El nombre del archivo no coincide con el del Formato 1' },
]

/** Un resultado por requisito, repartiendo estados para ver la matriz llena. */
function resultadosDe(hoja: string, semilla: number): ResultadoRequisito[] {
  return requisitosOrdenados().map((info, i) => {
    const suerte = (i * 7 + semilla * 3) % 10
    const cumple = suerte > 3
    return {
      ...BASE,
      hoja,
      numero_orden: semilla,
      nombre_proponente: PROPONENTES[semilla - 1].nombre_proponente,
      requisito: info.numero,
      cumple,
      motivo: cumple
        ? null
        : suerte === 0
          ? 'N.A. — el proponente no se presenta al lote 2. Según la carta de presentación se presenta al lote 1'
          : 'no se encontró el documento entre los archivos de la oferta; verifica que el proponente lo haya aportado',
    }
  })
}

const RESULTADOS: Record<string, ResultadoRequisito[]> = Object.fromEntries(
  PROPONENTES.map((pr, i) => [pr.hoja, resultadosDe(pr.hoja, i + 1)]),
)

export default function Previsualizacion() {
  const [ancho, setAncho] = useState(760)
  // El panel lateral tapa el resto: se abre solo si se pide.
  const [verPanel, setVerPanel] = useState(window.location.hash.includes('panel'))
  const [verVisor, setVerVisor] = useState(window.location.hash.includes('visor'))
  return (
    <div style={{ maxWidth: 1320, margin: '0 auto', padding: 28, display: 'flex', flexDirection: 'column', gap: 24 }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        <h1 className="serif" style={{ fontSize: 26 }}>
          Banco de pruebas visual
        </h1>
        <span className="small muted">Datos inventados · solo en desarrollo</span>
        <label className="small muted" style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          Ancho del panel
          <input type="range" min={360} max={1100} value={ancho} onChange={(e) => setAncho(Number(e.target.value))} />
          {ancho}px
        </label>
      </header>

      <section style={{ width: `min(${ancho}px, 100%)`, display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <h2 style={{ fontSize: 16 }}>Experiencia del lote 1 — técnico</h2>
          <Motivos motivo={TECNICO.motivo} tono="warn" />
          <DetalleTecnico detalle={TECNICO.detalle as never} />
          <QueFaltaRevisar
            revisiones={(TECNICO.detalle as never as { revisiones: never[] }).revisiones}
            acreditada={false}
          />
        </div>

        <div className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <h2 style={{ fontSize: 16 }}>Capacidad residual — financiero</h2>
          <Motivos motivo={FINANCIERO.motivo} tono="warn" />
          <DetalleFinanciero detalle={FINANCIERO.detalle as never} />
          <QueFaltaRevisar
            revisiones={(FINANCIERO.detalle as never as { revisiones: never[] }).revisiones}
            acreditada={false}
          />
        </div>
      </section>

      <section style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'flex-start' }}>
        <h2 style={{ fontSize: 18 }}>Ver un documento y decidir</h2>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setVerVisor((v) => !v)}>
          {verVisor ? 'Cerrar el visor' : 'Abrir el visor de documentos'}
        </button>
        {verVisor && (
          <VisorDocumento
            url="about:blank"
            archivo="oferta/13. Formato 3 - Experiencia.pdf"
            resultado={TECNICO}
            revisiones={{}}
            onRevisar={() => {}}
            onCerrar={() => setVerVisor(false)}
          />
        )}
      </section>

      <section>
        <h2 style={{ fontSize: 18, marginBottom: 12 }}>Crear un proceso</h2>
        <PasoNuevo
          codigoProceso="ICCU-CM-037-2026"
          fechaCierre=""
          carpetaDrive=""
          archivo={null}
          ofertas={[]}
          analizando={false}
          error={null}
          onCambiar={() => {}}
          onAnalizar={() => {}}
          onCancelar={() => {}}
        />
      </section>

      <section>
        <h2 style={{ fontSize: 18, marginBottom: 12 }}>Pantalla de evaluación y revisión</h2>
        <PasoEvaluacion
          proponentes={PROPONENTES}
          resultados={RESULTADOS}
          revisiones={{}}
          progreso={{ enFila: 2, procesando: 1, porDelante: 0, capacidad: 2, etaSegundos: 180 }}
          ocupado={false}
          hojaActiva={null}
          puedeEvaluar
          onDetener={() => {}}
          onContinuar={() => {}}
          onAbrir={() => {}}
          onSiguientePendiente={() => {}}
          onIrInforme={() => {}}
        />
      </section>

      <section style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h2 style={{ fontSize: 18 }}>Panel de un proponente</h2>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setVerPanel((v) => !v)}>
          {verPanel ? 'Cerrar el panel' : 'Abrir el panel de un proponente'}
        </button>
        {verPanel && (
          <PanelProponente
            proponente={PROPONENTES[0]}
            evaluacionId="demo"
            proponenteId="demo"
            resultados={[TECNICO, FINANCIERO, ...RESULTADOS['P-01'].slice(0, 8)]}
            revisiones={{}}
            requisitoDestacado={30}
            abriendoDocumento={null}
            onRevisar={() => {}}
            onVerDocumento={() => {}}
            onAnterior={null}
            onSiguiente={() => {}}
            onSiguientePendiente={() => {}}
            onSubirCertificado={() => {}}
            onConsultarCopnia={null}
            consultandoCopnia={null}
            onCerrar={() => setVerPanel(false)}
          />
        )}
      </section>
    </div>
  )
}
