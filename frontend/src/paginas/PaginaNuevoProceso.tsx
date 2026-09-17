import { useState } from 'react'
import { analizarDocumentoBase, type Proponente } from '../api'
import PasoDatos from '../components/PasoDatos'
import PasoNuevo from '../components/PasoNuevo'
import Topbar from '../components/Topbar'
import { PASOS_NUEVO, type Paso } from '../pasos'
import { propsDatos, useDatosProceso } from '../datosProceso'
import { crearProceso } from '../evaluaciones'
import { mensajeDe } from '../http'
import { navegar } from '../rutas'
import { useSesion } from '../sesion'
import QuienEvalua from './QuienEvalua'
import { SELECCION_INICIAL, type SeleccionTipos } from './seleccionTipos'

/** Asistente: Documento Base y carpeta de Drive → datos del proceso → crear. */
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
  const datos = useDatosProceso()
  const { usuario } = useSesion()!
  const esSuper = usuario.rol === 'superadmin'
  const [entidadId, setEntidadId] = useState<string | null>(esSuper ? null : (usuario.entidad?.id ?? null))
  const [seleccion, setSeleccion] = useState<SeleccionTipos>(SELECCION_INICIAL)
  const tiposElegidos = Object.entries(seleccion).filter(([, s]) => s.incluir)

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
      setPaso('datos')
    } catch (err) {
      setError(mensajeDe(err, 'No se pudo leer el Documento Base. Verifique que sea el PDF correcto.'))
    } finally {
      setAnalizando(false)
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
            textoAccion={`Crear proceso con ${proponentes.length} proponentes`}
            ocupado={creando}
            deshabilitado={(esSuper && !entidadId) || tiposElegidos.length === 0}
            antesDeAcciones={<QuienEvalua entidadId={entidadId} seleccion={seleccion} onEntidad={setEntidadId} onSeleccion={setSeleccion} />}
            onVolver={() => setPaso('nuevo')}
            onEvaluar={crear}
          />
        </>
      )}
    </>
  )
}
