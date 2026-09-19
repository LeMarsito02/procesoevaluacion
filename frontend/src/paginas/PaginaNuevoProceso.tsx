import { useEffect, useState } from 'react'
import { analizarDocumentoBase, analizarPliego, consultarPliego, type AnalisisPliego, type DecisionPliego, type Proponente } from '../api'
import PasoDatos from '../components/PasoDatos'
import PasoNuevo from '../components/PasoNuevo'
import PasoPliego from '../components/PasoPliego'
import Topbar from '../components/Topbar'
import { PASOS_NUEVO, type Paso } from '../pasos'
import { propsDatos, useDatosProceso } from '../datosProceso'
import { crearProceso } from '../evaluaciones'
import { mensajeDe } from '../http'
import { navegar } from '../rutas'
import { useSesion } from '../sesion'
import QuienEvalua from './QuienEvalua'
import { SELECCION_INICIAL, type SeleccionTipos } from './seleccionTipos'

/** Asistente: Documento Base y carpeta de Drive → datos del proceso → lo que exige el pliego → crear. */
export default function PaginaNuevoProceso() {
  const [paso, setPaso] = useState<Paso>('nuevo')
  const [codigoProceso, setCodigoProceso] = useState('')
  const [fechaCierre, setFechaCierre] = useState('')
  const [carpetaDrive, setCarpetaDrive] = useState('')
  const [archivo, setArchivo] = useState<File | null>(null)
  const [analizando, setAnalizando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [proponentes, setProponentes] = useState<Proponente[]>([])
  const [noReconocidos, setNoReconocidos] = useState<string[]>([])
  const [driveError, setDriveError] = useState<string | null>(null)
  const [creando, setCreando] = useState(false)
  const [errorCrear, setErrorCrear] = useState<string | null>(null)
  // Análisis del pliego contra la plantilla de la entidad (para el superadmin
  // se hace cuando ya eligió la entidad) y la decisión sobre cada hallazgo.
  const [pliego, setPliego] = useState<AnalisisPliego | null>(null)
  const [pliegoEntidad, setPliegoEntidad] = useState<string | null>(null)
  const [pliegoError, setPliegoError] = useState<string | null>(null)
  const [analizandoPliego, setAnalizandoPliego] = useState(false)
  const [decisiones, setDecisiones] = useState<Record<string, DecisionPliego>>({})
  const [sinPliego, setSinPliego] = useState(false)
  const datos = useDatosProceso()
  const { usuario } = useSesion()!
  const esSuper = usuario.rol === 'superadmin'
  const [entidadId, setEntidadId] = useState<string | null>(esSuper ? null : (usuario.entidad?.id ?? null))
  const [seleccion, setSeleccion] = useState<SeleccionTipos>(SELECCION_INICIAL)
  const tiposElegidos = Object.entries(seleccion).filter(([, s]) => s.incluir)

  // Mientras la IA lee el pliego completo, se consulta su avance; al terminar
  // llegan los hallazgos nuevos (las decisiones ya tomadas se conservan).
  const pliegoLeyendo = pliego != null && ['pendiente', 'leyendo'].includes(pliego.lectura_ia.estado)
  const pliegoId = pliego?.id
  useEffect(() => {
    if (!pliegoLeyendo || !pliegoId) return
    let vivo = true
    const id = pliegoId
    const t = window.setInterval(async () => {
      try {
        const nuevo = await consultarPliego(id, esSuper ? pliegoEntidad : null)
        if (vivo) setPliego((actual) => (actual && actual.id === id ? { ...nuevo, reutilizado: actual.reutilizado } : actual))
      } catch {
        // Un fallo de red momentáneo no detiene la consulta.
      }
    }, 4000)
    return () => {
      vivo = false
      window.clearInterval(t)
    }
  }, [pliegoLeyendo, pliegoId, esSuper, pliegoEntidad])

  async function analizar() {
    if (!archivo) return
    setAnalizando(true)
    setError(null)
    try {
      const r = await analizarDocumentoBase(codigoProceso.trim(), fechaCierre, archivo, carpetaDrive)
      datos.cargar(r.documento_base)
      setProponentes(r.proponentes)
      setNoReconocidos(r.proponentes_no_reconocidos)
      setDriveError(r.drive_error)
      setPliego(r.pliego)
      setPliegoEntidad(r.pliego ? entidadId : null)
      setPliegoError(r.pliego_error)
      setDecisiones({})
      setSinPliego(false)
      setPaso('datos')
    } catch (err) {
      setError(mensajeDe(err, 'No se pudo leer el Documento Base. Verifique que sea el PDF correcto.'))
    } finally {
      setAnalizando(false)
    }
  }

  async function irAlPliego() {
    setPaso('pliego')
    // El superadmin eligió la entidad después de leer el documento: se compara con la suya.
    if (archivo && (!pliego || pliegoEntidad !== entidadId)) {
      setAnalizandoPliego(true)
      setPliegoError(null)
      try {
        setPliego(await analizarPliego(archivo, esSuper ? entidadId : null))
        setPliegoEntidad(entidadId)
        setDecisiones({})
      } catch (err) {
        setPliego(null)
        setPliegoError(mensajeDe(err, 'No se pudo leer el pliego.'))
      } finally {
        setAnalizandoPliego(false)
      }
    }
  }

  async function crear() {
    setCreando(true)
    setErrorCrear(null)
    try {
      const creadas = await crearProceso({
        documento_base: datos.construir(codigoProceso, fechaCierre),
        carpeta_drive: carpetaDrive,
        proponentes,
        proponentes_no_reconocidos: noReconocidos,
        tipos: tiposElegidos.map(([clave]) => clave),
        entidad_id: esSuper ? entidadId : null,
        analisis_pliego_id: pliego?.id ?? null,
        decisiones_pliego: pliego ? decisiones : {},
        // El evaluador queda a cargo de lo que crea; los demás eligen por tipo.
        ...(usuario.rol === 'evaluador'
          ? {}
          : {
              responsables: Object.fromEntries(
                tiposElegidos.map(([clave, s]) => [clave, s.eleccion === '' ? null : s.eleccion === 'yo' ? usuario.id : s.eleccion]),
              ),
            }),
      })
      // Se abre la primera evaluación que ya tiene motor automático.
      const destino = creadas.find((e) => e.tipo_disponible) ?? creadas[0]
      navegar(`/evaluaciones/${destino.id}`, true)
    } catch (err) {
      setErrorCrear(mensajeDe(err, 'No se pudo crear el proceso.'))
      setCreando(false)
    }
  }

  const disponibles = new Set<Paso>(['nuevo'])
  if (proponentes.length || datos.lotes.length) disponibles.add('datos')
  if (paso === 'pliego') disponibles.add('pliego')

  return (
    <>
      <Topbar
        codigoProceso={paso === 'nuevo' ? null : codigoProceso}
        pasos={{ lista: PASOS_NUEVO, paso, pasosDisponibles: disponibles, onIr: setPaso }}
      />
      {paso === 'nuevo' ? (
        <PasoNuevo
          codigoProceso={codigoProceso}
          fechaCierre={fechaCierre}
          carpetaDrive={carpetaDrive}
          archivo={archivo}
          analizando={analizando}
          error={error}
          onCambiar={(c) => {
            if (c.codigoProceso !== undefined) setCodigoProceso(c.codigoProceso)
            if (c.fechaCierre !== undefined) setFechaCierre(c.fechaCierre)
            if (c.carpetaDrive !== undefined) setCarpetaDrive(c.carpetaDrive)
            if (c.archivo !== undefined) setArchivo(c.archivo)
          }}
          onAnalizar={analizar}
          onCancelar={() => navegar('/')}
        />
      ) : paso === 'pliego' ? (
        <>
          {errorCrear && (
            <div className="page" style={{ paddingBottom: 0 }}>
              <div className="callout callout-bad" role="alert">
                {errorCrear}
              </div>
            </div>
          )}
          <PasoPliego
            pliego={pliego}
            cargando={analizandoPliego}
            error={pliegoError}
            decisiones={decisiones}
            onDecidir={(id, d) => setDecisiones((prev) => ({ ...prev, [id]: d }))}
            onReintentar={() => {
              setPliego(null)
              setPliegoEntidad(null)
              void irAlPliego()
            }}
            sinPliegoConfirmado={sinPliego}
            onConfirmarSinPliego={setSinPliego}
            ocupado={creando}
            textoAccion={`Crear proceso con ${proponentes.length} proponentes`}
            onVolver={() => setPaso('datos')}
            onCrear={crear}
          />
        </>
      ) : (
        <>
          {errorCrear && (
            <div className="page" style={{ paddingBottom: 0 }}>
              <div className="callout callout-bad" role="alert">
                {errorCrear}
              </div>
            </div>
          )}
          <PasoDatos
            codigoProceso={codigoProceso}
            fechaCierre={fechaCierre}
            {...propsDatos(datos, fechaCierre)}
            proponentes={proponentes}
            noReconocidos={noReconocidos}
            driveError={driveError}
            hayResultados={false}
            textoAccion="Continuar: lo que exige el pliego"
            ocupado={analizandoPliego}
            deshabilitado={(esSuper && !entidadId) || tiposElegidos.length === 0}
            antesDeAcciones={<QuienEvalua entidadId={entidadId} seleccion={seleccion} onEntidad={setEntidadId} onSeleccion={setSeleccion} />}
            onVolver={() => setPaso('nuevo')}
            onEvaluar={irAlPliego}
          />
        </>
      )}
    </>
  )
}
