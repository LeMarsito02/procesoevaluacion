import { useEffect, useState } from 'react'
import {
  analizarDocumentoBase,
  analizarPliego,
  archivoDemoKit,
  consultarPliego,
  crearPreparacion,
  demoKit,
  eliminarPreparacion,
  listarPreparaciones,
  reintentarPreparacion,
  verPreparacion,
  type AnalisisPliego,
  type AnalisisResponse,
  type DecisionPliego,
  type Preparacion,
  type Proponente,
} from '../api'
import Icono from '../components/Icono'
import PasoDatos from '../components/PasoDatos'
import PasoLeyendo from '../components/PasoLeyendo'
import { useDialogos } from '../dialogos'
import PasoNuevo from '../components/PasoNuevo'
import PasoPliego from '../components/PasoPliego'
import Topbar from '../components/Topbar'
import { PASOS_NUEVO, type Paso } from '../pasos'
import { propsDatos, useDatosProceso } from '../datosProceso'
import { crearProceso, subirMatriz2 } from '../evaluaciones'
import { ErrorApi, mensajeDe } from '../http'
import { navegar } from '../rutas'
import { useSesion } from '../sesion'
import QuienEvalua from './QuienEvalua'
import { SELECCION_INICIAL, type SeleccionTipos } from './seleccionTipos'

/** Asistente: Documento Base y carpeta de Drive → datos del proceso → lo que exige el pliego → crear.
 *
 * Con `preparacionId` (ruta /procesos/nuevo/evaluacion/:id) es un proceso a
 * medio crear: el servidor lo está leyendo o ya lo leyó, y recargar la página
 * lo retoma donde iba. */
export default function PaginaNuevoProceso({ preparacionId = null }: { preparacionId?: string | null }) {
  const [paso, setPaso] = useState<Paso>('nuevo')
  const { confirmar } = useDialogos()
  const [preparacion, setPreparacion] = useState<Preparacion | null>(null)
  const [errorPreparacion, setErrorPreparacion] = useState<string | null>(null)
  const [ocupadoPreparacion, setOcupadoPreparacion] = useState(false)
  // Cambia al reintentar: vuelve a arrancar la consulta del avance.
  const [vuelta, setVuelta] = useState(0)
  // Procesos que la persona dejó a medio crear: se ofrecen al empezar uno nuevo.
  const [pendientes, setPendientes] = useState<Preparacion[]>([])
  const [codigoProceso, setCodigoProceso] = useState('')
  const [fechaCierre, setFechaCierre] = useState('')
  const [carpetaDrive, setCarpetaDrive] = useState('')
  // Las ofertas subidas a mano, cuando no están en una carpeta compartida.
  const [ofertas, setOfertas] = useState<File[]>([])
  const [archivo, setArchivo] = useState<File | null>(null)
  const [analizando, setAnalizando] = useState(false)
  // Avance de la subida de los archivos al crear el proceso.
  const [subida, setSubida] = useState<{ cargado: number; total: number; inicio: number; ahora: number; reutilizadas?: string[] } | null>(null)
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
  // La Matriz 2 se pide al incluir la financiera y se carga apenas existe el proceso.
  const [matriz2, setMatriz2] = useState<File | null>(null)

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

  // Demostración: con un código «DEMO-…» el formulario se llena solo con el kit
  // de este equipo (Documento Base, ofertas y fecha de cierre). Donde no hay
  // kit, la consulta dice que no está disponible y no cambia nada.
  const [kitCargado, setKitCargado] = useState(false)
  useEffect(() => {
    if (kitCargado || !/^DEMO-/i.test(codigoProceso.trim()) || archivo || ofertas.length) return
    let vivo = true
    const t = window.setTimeout(async () => {
      try {
        const kit = await demoKit()
        if (!vivo || !kit.disponible) return
        const [pliegoKit, ...ofertasKit] = await Promise.all([
          archivoDemoKit('pliego.pdf'),
          ...(kit.ofertas ?? []).map((nombre) => archivoDemoKit(nombre)),
        ])
        if (!vivo) return
        if (kit.fecha_cierre) setFechaCierre((actual) => actual || kit.fecha_cierre!)
        setArchivo(pliegoKit)
        setOfertas(ofertasKit)
        setKitCargado(true)
      } catch {
        // Sin kit en este equipo: el formulario sigue como siempre.
      }
    }, 400)
    return () => {
      vivo = false
      window.clearTimeout(t)
    }
  }, [codigoProceso, kitCargado, archivo, ofertas.length])

  function cargarResultado(r: AnalisisResponse, entidad: string | null) {
    datos.cargar(r.documento_base)
    setProponentes(r.proponentes)
    setNoReconocidos(r.proponentes_no_reconocidos)
    setDriveError(r.drive_error)
    setPliego(r.pliego)
    setPliegoEntidad(r.pliego ? entidad : null)
    setPliegoError(r.pliego_error)
    setDecisiones({})
    setSinPliego(false)
    setPaso('datos')
  }

  // Sin preparación: los procesos a medio crear que quedaron.
  useEffect(() => {
    if (preparacionId) return
    listarPreparaciones()
      .then(setPendientes)
      .catch(() => setPendientes([]))
  }, [preparacionId])

  // Con preparación: se consulta hasta que esté lista; entonces se cargan sus
  // datos. Nunca se deja de consultar por un fallo pasajero (wifi, servidor
  // reiniciando): se reintenta y se dice; solo para si la preparación ya no existe.
  const [sinConexion, setSinConexion] = useState(false)
  useEffect(() => {
    if (!preparacionId) return
    let vivo = true
    let t: number | undefined
    let fallos = 0
    let listo = false
    const consultar = async () => {
      window.clearTimeout(t)
      if (!vivo || listo) return
      try {
        const p = await verPreparacion(preparacionId)
        if (!vivo) return
        fallos = 0
        setSinConexion(false)
        setPreparacion(p)
        setErrorPreparacion(null)
        if (p.estado === 'lista' && p.resultado) {
          listo = true
          setCodigoProceso(p.codigo)
          setFechaCierre(p.fecha_cierre)
          setCarpetaDrive(p.carpeta_drive)
          cargarResultado(p.resultado, p.entidad_id)
          return
        }
        if (p.estado !== 'error') t = window.setTimeout(consultar, 2000)
      } catch (err) {
        if (!vivo) return
        if (err instanceof ErrorApi && err.status === 404) {
          setErrorPreparacion(mensajeDe(err, 'No se encontró ese proceso a medio crear: puede que ya se haya creado o eliminado.'))
          return
        }
        fallos += 1
        setSinConexion(true)
        t = window.setTimeout(consultar, Math.min(15000, 2000 * 2 ** Math.min(fallos, 3)))
      }
    }
    // Al volver a la pestaña o recuperar la red, se consulta de una vez.
    const ya = () => {
      if (document.visibilityState === 'visible') void consultar()
    }
    window.addEventListener('online', ya)
    window.addEventListener('focus', ya)
    document.addEventListener('visibilitychange', ya)
    void consultar()
    return () => {
      vivo = false
      window.clearTimeout(t)
      window.removeEventListener('online', ya)
      window.removeEventListener('focus', ya)
      document.removeEventListener('visibilitychange', ya)
    }
    // cargarResultado usa setters estables; solo cambia con la preparación.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preparacionId, vuelta])

  async function eliminarPreparacionActual(id: string, preguntar = true) {
    if (
      preguntar &&
      !(await confirmar({
        titulo: '¿Eliminar este proceso a medio crear?',
        mensaje: 'Se borran el Documento Base y lo leído. Las ofertas de la carpeta compartida no se tocan.',
        aceptar: 'Eliminar',
        cancelar: 'Conservar',
        peligro: true,
      }))
    )
      return false
    setOcupadoPreparacion(true)
    try {
      await eliminarPreparacion(id)
      setPendientes((lista) => lista.filter((x) => x.id !== id))
      return true
    } catch (err) {
      setErrorPreparacion(mensajeDe(err, 'No se pudo eliminar.'))
      return false
    } finally {
      setOcupadoPreparacion(false)
    }
  }

  async function analizar() {
    if (!archivo) return
    setAnalizando(true)
    setError(null)
    try {
      // El superadministrador elige la entidad después de leer: lectura directa.
      if (!esSuper || entidadId) {
        const inicio = Date.now()
        setSubida({ cargado: 0, total: archivo.size + ofertas.reduce((t, o) => t + o.size, 0), inicio, ahora: inicio, reutilizadas: [] })
        const p = await crearPreparacion(
          codigoProceso.trim(),
          fechaCierre,
          archivo,
          carpetaDrive,
          esSuper ? entidadId : null,
          ofertas,
          (a) => setSubida((s) => ({ cargado: a.cargado, total: a.total, inicio, ahora: Date.now(), reutilizadas: s?.reutilizadas ?? [] })),
          (nombre) => setSubida((s) => (s ? { ...s, reutilizadas: [...(s.reutilizadas ?? []), nombre] } : s)),
        )
        navegar(`/procesos/nuevo/evaluacion/${p.id}`)
        return
      }
      const r = await analizarDocumentoBase(codigoProceso.trim(), fechaCierre, archivo, carpetaDrive, null, ofertas)
      cargarResultado(r, entidadId)
    } catch (err) {
      setError(mensajeDe(err, 'No se pudo leer el Documento Base. Verifique que sea el PDF correcto.'))
    } finally {
      setAnalizando(false)
      setSubida(null)
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
        // Dependencia elegida por área; si no se eligió, el servidor usa la sugerida.
        dependencias: Object.fromEntries(tiposElegidos.filter(([, s]) => s.dependencia).map(([clave, s]) => [clave, s.dependencia])),
        decisiones_pliego: pliego ? decisiones : {},
        preparacion_id: preparacionId,
        // Más integrantes del comité por evaluación (el responsable lo coordina).
        comites: Object.fromEntries(tiposElegidos.filter(([, s]) => s.eleccion !== '' && (s.comite ?? []).length > 0).map(([clave, s]) => [clave, s.comite ?? []])),
        // El evaluador queda a cargo de lo que crea; los demás eligen por tipo.
        ...(usuario.rol === 'evaluador'
          ? {}
          : {
              responsables: Object.fromEntries(
                tiposElegidos.map(([clave, s]) => [clave, s.eleccion === '' ? null : s.eleccion === 'yo' ? usuario.id : s.eleccion]),
              ),
            }),
      })
      const financiera = creadas.find((e) => e.tipo === 'financiera')
      if (matriz2 && financiera) {
        try {
          await subirMatriz2(financiera.id, matriz2)
        } catch (err) {
          // El proceso ya existe: se avisa y se sigue; la matriz se puede subir después.
          window.alert(
            `El proceso se creó, pero no se pudo cargar la Matriz 2: ${mensajeDe(err)}\n\nSúbala después en la evaluación financiera, en «Parámetros financieros».`,
          )
        }
      }
      // Se abre la primera evaluación que ya tiene motor automático.
      const destino = creadas.find((e) => e.tipo_disponible) ?? creadas[0]
      navegar(`/evaluaciones/${destino.id}`, true)
    } catch (err) {
      setErrorCrear(mensajeDe(err, 'No se pudo crear el proceso.'))
      setCreando(false)
    }
  }

  if (preparacionId && paso === 'nuevo') {
    // Leyendo (o con error): la barra de avance, que sobrevive a recargar.
    return (
      <>
        <Topbar codigoProceso={preparacion?.codigo ?? null} pasos={{ lista: PASOS_NUEVO, paso, pasosDisponibles: new Set<Paso>(), onIr: setPaso }} />
        {errorPreparacion && !preparacion ? (
          <main className="page page-narrow">
            <div className="callout callout-bad" role="alert">
              <Icono nombre="alerta" />
              <div>{errorPreparacion}</div>
            </div>
            <button className="btn btn-primary" type="button" style={{ marginTop: 16 }} onClick={() => navegar('/procesos/nuevo/evaluacion', true)}>
              Empezar un proceso nuevo
            </button>
          </main>
        ) : preparacion ? (
          <PasoLeyendo
            preparacion={preparacion}
            sinConexion={sinConexion}
            ocupado={ocupadoPreparacion}
            onEliminar={async () => {
              if (await eliminarPreparacionActual(preparacion.id)) navegar('/procesos/nuevo/evaluacion', true)
            }}
            onReintentar={async () => {
              setOcupadoPreparacion(true)
              try {
                setPreparacion(await reintentarPreparacion(preparacion.id))
                setVuelta((v) => v + 1)
              } catch (err) {
                setErrorPreparacion(mensajeDe(err, 'No se pudo reintentar.'))
              } finally {
                setOcupadoPreparacion(false)
              }
            }}
          />
        ) : (
          <main className="page page-narrow">
            <div className="vacio">
              <span className="spinner oscuro" />
            </div>
          </main>
        )}
      </>
    )
  }

  // Leído por el servidor, volver al formulario no tiene sentido: se descarta desde «Volver».
  const disponibles = new Set<Paso>(preparacionId ? [] : ['nuevo'])
  if (proponentes.length || datos.lotes.length) disponibles.add('datos')
  if (paso === 'pliego') disponibles.add('pliego')

  return (
    <>
      <Topbar
        codigoProceso={paso === 'nuevo' ? null : codigoProceso}
        pasos={{ lista: PASOS_NUEVO, paso, pasosDisponibles: disponibles, onIr: setPaso }}
      />
      {paso === 'nuevo' ? (
        <>
        {pendientes.length > 0 && (
          <div className="page page-narrow" style={{ paddingBottom: 0 }}>
            <section className="card a-medio-crear">
              <strong>Procesos a medio crear</strong>
              <ul>
                {pendientes.map((x) => (
                  <li key={x.id}>
                    <span>
                      <strong>{x.codigo}</strong>
                      <span className="small muted">
                        {' '}
                        · {x.estado === 'lista' ? 'Listo para revisar' : x.estado === 'error' ? 'Con error' : x.etapa || 'En fila'}
                      </span>
                    </span>
                    <span className="acciones">
                      <button className="btn btn-sm btn-secondary" type="button" onClick={() => navegar(`/procesos/nuevo/evaluacion/${x.id}`)}>
                        Continuar
                      </button>
                      <button className="btn btn-sm btn-ghost" type="button" disabled={ocupadoPreparacion} onClick={() => void eliminarPreparacionActual(x.id)}>
                        Eliminar
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
        <PasoNuevo
          codigoProceso={codigoProceso}
          fechaCierre={fechaCierre}
          carpetaDrive={carpetaDrive}
          ofertas={ofertas}
          archivo={archivo}
          analizando={analizando}
          subida={subida}
          error={error}
          onCambiar={(c) => {
            if (c.codigoProceso !== undefined) setCodigoProceso(c.codigoProceso)
            if (c.fechaCierre !== undefined) setFechaCierre(c.fechaCierre)
            if (c.carpetaDrive !== undefined) setCarpetaDrive(c.carpetaDrive)
            if (c.ofertas !== undefined) setOfertas(c.ofertas)
            if (c.archivo !== undefined) setArchivo(c.archivo)
          }}
          onAnalizar={analizar}
          onCancelar={() => navegar('/procesos/nuevo')}
        />
        </>
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
            pliego={
              pliego
                ? {
                    url: `/api/procesos/pliego/${pliego.id}/archivo${esSuper && entidadId ? `?entidad_id=${entidadId}` : ''}`,
                    nombre: pliego.nombre_archivo,
                    paginaObjeto: datos.paginas.objeto,
                    paginaGarantia: datos.paginas.garantia,
                  }
                : null
            }
            proponentes={proponentes}
            noReconocidos={noReconocidos}
            driveError={driveError}
            hayResultados={false}
            textoAccion="Continuar: lo que exige el pliego"
            ocupado={analizandoPliego}
            deshabilitado={(esSuper && !entidadId) || tiposElegidos.length === 0}
            antesDeAcciones={<QuienEvalua entidadId={entidadId} seleccion={seleccion} onEntidad={setEntidadId} onSeleccion={setSeleccion} objeto={datos.objetoGeneral} matriz2={matriz2} onMatriz2={setMatriz2} />}
            onVolver={
              preparacionId
                ? async () => {
                    if (await eliminarPreparacionActual(preparacionId)) navegar('/procesos/nuevo/evaluacion', true)
                  }
                : () => setPaso('nuevo')
            }
            onCambiarFecha={setFechaCierre}
            onEvaluar={irAlPliego}
          />
        </>
      )}
    </>
  )
}
