"""Documentos de las ofertas del proceso de demostración.

Todo es inventado: entidad, proponentes, personas, cédulas (series 9990…),
NIT (serie 9991…), matrículas, pólizas y certificados. Cada documento lleva
la marca «DOCUMENTO DE DEMOSTRACIÓN · DATOS FICTICIOS · SIN VALIDEZ», y
ninguno usa escudos ni logos oficiales: sirven para mostrar el programa, no
pueden pasar por un certificado real.

Los textos siguen la estructura de los documentos reales (los títulos y las
frases estándar que el motor reconoce), para que el motor los evalúe de
verdad y la demostración sea honesta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

MARCA = "DOCUMENTO DE DEMOSTRACIÓN · DATOS FICTICIOS · SIN VALIDEZ"

ENTIDAD = "INSTITUTO DE INFRAESTRUCTURA VIAL DEMO – IIVD"
ENTIDAD_NIT = "999.000.001-1"
CODIGO = "DEMO-CM-001-2026"
CIERRE = date(2026, 9, 15)
OBJETO = (
    "CONTRATAR LA INTERVENTORÍA TÉCNICA, ADMINISTRATIVA, FINANCIERA, JURÍDICA, SOCIAL Y AMBIENTAL PARA EL "
    "MEJORAMIENTO Y REHABILITACIÓN DE VÍAS TERCIARIAS EN EL DEPARTAMENTO DEMO"
)
LOTES = [
    ("LOTE 1", "INTERVENTORÍA TÉCNICA, ADMINISTRATIVA, FINANCIERA, JURÍDICA, SOCIAL Y AMBIENTAL AL PROYECTO "
               "\"MEJORAMIENTO Y REHABILITACIÓN DE LA VÍA SAN ALEJO – LA ESPERANZA\"", 1_200_000_000.0, 10, "Municipio de San Alejo"),
    ("LOTE 2", "INTERVENTORÍA TÉCNICA, ADMINISTRATIVA, FINANCIERA, JURÍDICA, SOCIAL Y AMBIENTAL AL PROYECTO "
               "\"MEJORAMIENTO Y REHABILITACIÓN DE LA VÍA EL ROBLE – VILLA CLARA\"", 900_000_000.0, 8, "Municipio de Villa Clara"),
]

MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE",
         "NOVIEMBRE", "DICIEMBRE"]
MESES_CEDULA = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]


@dataclass
class Persona:
    nombre: str  # NOMBRES APELLIDOS
    apellidos: str
    nombres: str
    cedula: str  # sin puntos
    expedicion: date
    nacimiento: date
    ciudad: str = "BOGOTÁ D.C."
    matricula: str | None = None  # si es ingeniero(a)
    # Fechas de sus certificados de antecedentes (para mostrar uno vencido).
    rnmc: date = date(2026, 9, 1)

    @property
    def cedula_puntos(self) -> str:
        c = self.cedula
        return f"{int(c):,}".replace(",", ".")


@dataclass
class Empresa:
    razon: str
    nit: str  # 9 dígitos
    dv: str
    gerente: Persona
    suplente: Persona | None = None
    anonima: bool = False
    revisor_fiscal: str | None = None
    revisor_cedula: str | None = None
    # Multas y sanciones que su RUP reporta (para mostrar el art. 58 de la
    # Ley 2195 de 2022 y el art. 90 de la Ley 1474 de 2011).
    sanciones: list["SancionDemo"] = field(default_factory=list)

    @property
    def nit_puntos(self) -> str:
        return f"{self.nit[:3]}.{self.nit[3:6]}.{self.nit[6:]}-{self.dv}"


@dataclass
class SancionDemo:
    """Una multa o declaratoria como la reporta el RUP de verdad."""

    tipo: str  # MULTA | DECLARATORIA DE INCUMPLIMIENTO
    entidad: str
    contrato: str
    descripcion: str
    ejecutoria: date
    valor: str = ""
    es_incumplimiento: bool = False


@dataclass
class Proponente:
    hoja: str
    nombre: str
    tipo: str  # consorcio | union_temporal | persona_juridica
    representante: Persona
    suplente: Persona | None
    integrantes: list[tuple[Empresa, int]] = field(default_factory=list)
    empresa: Empresa | None = None  # persona jurídica individual
    valor_poliza: float = 120_000_000.0
    copnia: date = date(2026, 8, 20)


def fecha_larga(f: date) -> str:
    return f"{f.day} DE {MESES[f.month - 1]} DE {f.year}"


def fecha_cedula(f: date) -> str:
    return f"{f.day:02d}-{MESES_CEDULA[f.month - 1]}-{f.year}"


# --- Estilos y piezas comunes -------------------------------------------------
ESTILO = """
<style>
  @page { size: Letter; margin: 22mm 20mm 26mm 20mm; }
  body { font-family: 'DejaVu Sans', Arial, sans-serif; font-size: 10.5pt; line-height: 1.38; color: #111; }
  h1 { font-size: 13pt; text-align: center; margin: 0 0 8px; }
  h2 { font-size: 11pt; margin: 14px 0 6px; }
  .centro { text-align: center; }
  table { border-collapse: collapse; width: 100%; margin: 6px 0; }
  td, th { border: 1px solid #444; padding: 4px 6px; font-size: 9.5pt; }
  .firma { margin-top: 40px; }
  .firma img { height: 52px; }
  .salto { page-break-before: always; }
</style>
"""

# Una firma inventada (un trazo), como imagen: el motor revisa que el documento
# esté firmado buscando la imagen en la parte de abajo de la página.
FIRMA_PNG = "data:image/png;base64,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"


PIE_PAGINA = (
    "<div style='width:100%;text-align:center;font-size:8px;color:#b00020;font-family:Arial'>"
    f"{MARCA} · página <span class='pageNumber'></span> de <span class='totalPages'></span></div>"
)


def html(cuerpo: str, titulo: str = "") -> str:
    return f"<html><head><meta charset='utf-8'><title>{titulo}</title>{ESTILO}</head><body>{cuerpo}</body></html>"


def firma(nombre: str, cargo: str, entidad: str = "") -> str:
    return (
        f"<div class='firma'><img src=\"{FIRMA_PNG}\"><br>"
        f"________________________________________<br><b>{nombre}</b><br>{cargo}<br>{entidad}</div>"
    )


# --- Formato 1: carta de presentación (cláusulas del formato oficial CCE) ----
CLAUSULAS_FORMATO1 = [
    "Estoy autorizado para suscribir y presentar la oferta y para suscribir el contrato si resulto adjudicatario del proceso de contratación de la referencia.",
    "En caso de que la oferta le sea adjudicada al proponente suscribiré el contrato objeto del proceso de contratación en la fecha prevista para el efecto en el cronograma contenido en los documentos del proceso.",
    "Conozco los Documentos del Proceso, incluyendo Adendas y acepto los requisitos en ellos contenido. Dentro de los documentos presentados a la Entidad conozco los ítems, la descripción, las unidades y cantidades establecidas en el Formulario 1 – Propuesta económica.",
    "Conozco las leyes de la República de Colombia que rigen el proceso de contratación.",
    "El proponente conoce las especificaciones técnicas y el alcance de la obra objeto de interventoría, así como las disposiciones establecidas en el Anexo 1 – Anexo Técnico.",
    "Conozco el sitio donde se ejecutará el contrato y asumo los riesgos previsibles inherentes al mismo, así como aquellos asignados en el pliego de condiciones.",
    "La información contenida en todos los documentos de la oferta es veraz y el proponente asume total responsabilidad frente a la entidad cuando los datos suministrados sean falsos o contrarios a la realidad, sin perjuicio de lo dispuesto en el Código Penal y demás normas concordantes.",
    "La información diligenciada en el “Formato 8 - Aceptación y cumplimiento de la formación académica y la experiencia del Personal Clave Evaluable” es real y verificable con los soportes de formación académica y experiencia que entregaré a la Entidad en el momento dispuesto en el numeral 9.1 del Documento Base. En el caso que la Entidad encuentre que la información del Formato no es verídica, soy consciente de las sanciones penales en que puedo incurrir, tales como falsedad en documento público.",
    "Conozco y cuento con los profesionales ofertados en el equipo de trabajo y los pondré a disposición de la Entidad para el cumplimiento del objeto de la interventoría en los plazos dispuestos en el numeral 9.1 del Documento Base.",
    "Ni los integrantes del Proponente Plural, ni los socios de la persona jurídica que represento (se exceptúan las sociedades anónimas abiertas), ni yo nos hallamos incursos en causal alguna de Conflicto de Interés, inhabilidad o incompatibilidad de las señaladas en la Constitución y en la ley.",
    "Ni los integrantes del Proponente Plural, ni los socios de la persona jurídica que represento (se exceptúan las sociedades anónimas abiertas), ni yo nos encontramos en ninguno de los eventos de prohibiciones especiales para contratar, ni nos hallamos incursos en ninguno de los conflictos de intereses para participar establecidos en la ley.",
    "En caso de conocer que los integrantes del Proponente Plural, los socios de la persona jurídica que represento (se exceptúan las sociedades anónimas abiertas) o yo nos encontremos incursos en alguna inhabilidad o Conflicto de Interés sobreviniente, contemplados en la normativa vigente, nos comprometemos a informar de manera inmediata tal circunstancia a la Entidad, para que tome las medidas pertinentes. Este compromiso lo adquirimos en total independencia de la etapa en que se encuentre el Proceso de Contratación (precontractual, contractual y/o post contractual).",
    "Ni los integrantes del Proponente Plural, ni los socios de la persona jurídica que represento (se exceptúan las sociedades anónimas abiertas), ni a mí, se nos ha declarado responsables judicialmente por actos de corrupción, la comisión de delitos de peculado, concusión, cohecho, prevaricato en cualquiera de sus modalidades, soborno trasnacional, lavado de activos, enriquecimiento ilícito, entre otros, de conformidad con la ley penal colombiana y los tratados internacionales sobre la materia, así como sus equivalentes en otras jurisdicciones.",
    "Ni los integrantes del Proponente Plural, ni los socios de la persona jurídica que represento (se exceptúan las sociedades anónimas abiertas), ni yo estamos incursos en la situación descrita en el numeral 1° del artículo 38 de la Ley 1116 de 2006.",
    "No soy responsable fiscal por actividades ejercidas en Colombia en el pasado y no tengo sanciones vigentes en Colombia que impliquen inhabilidad, incompatibilidad o prohibición para contratar con Entidad Estatal alguna.",
    "Conozco el Anexo 4 denominado “Pacto de Transparencia” relacionado en el Pliego de Condiciones y me comprometo a darle estricto cumplimiento.",
    "Los recursos destinados al proyecto son de origen lícito y no hemos participado en actividades delictivas, así como no hemos recibido recursos o facilitado actividades contrarias a la ley.",
    "Al momento de la presentación de la oferta ni mis representados ni yo nos encontramos incursos en alguna de las causales de rechazo señaladas en la sección 1.15 del Documento Base.",
    "Si se adjudica el contrato me comprometo a constituir las Garantías requeridas y a suscribir estas y aquel dentro de los términos señalados para ello.",
    "La oferta está constituida por todos los Formatos, Formularios, Anexos y Matrices requeridos en los Documentos del Proceso aplicables al Proponente y documentos de soporte presentados.",
    "La oferta fue elaborada teniendo en cuenta todos los gastos, costos, derechos, impuestos, tasas y demás contribuciones que se causen con ocasión de su presentación y suscripción del contrato y que en consecuencia no haré reclamos con ocasión del pago de tales gastos.",
    "Declaro que me informaré de todas las etapas y decisiones del Proceso de Contratación, consultando el Sistema Electrónico para la Contratación Pública (SECOP); y en caso de que me deban comunicar o notificar alguna decisión, autorizo a la Entidad para que lo haga al correo electrónico indicado al final de este documento. Acepto que se comuniquen y notifiquen las decisiones surgidas en el Proceso de Contratación a través del usuario del SECOP II, de acuerdo con el Manual de Uso y Condiciones de la plataforma del SECOP II y el artículo 56 de la Ley 1437 de 2011.",
]


def encabezado_proceso() -> str:
    lotes = " ".join(f"{n}: {o}." for n, o, *_ in LOTES)
    return (
        f"<p>Señores<br><b>{ENTIDAD}</b><br>Ciudad Demo</p>"
        f"<p><b>REFERENCIA:</b> Proceso de Contratación {CODIGO}, en adelante el proceso.</p>"
        f"<p><b>Objeto:</b> {OBJETO}. {lotes}</p><p><b>LOTE: 1 Y 2.</b></p>"
    )


def carta(p: Proponente) -> str:
    marcas = {"persona_juridica": "Persona jurídica nacional", "consorcio": "Consorcio", "union_temporal": "Unión temporal"}
    tipos = ["Persona natural", "Persona jurídica nacional", "Persona jurídica extranjera sin sucursal en Colombia",
             "Sucursal de sociedad extranjera", "Unión temporal", "Consorcio", "Otro"]
    tipo = "".join(f"{t} {'_X__' if t == marcas[p.tipo] else '___'}<br>" for t in tipos)
    clausulas = "".join(f"<p>{i}. {c}</p>" for i, c in enumerate(CLAUSULAS_FORMATO1, 1))
    empresas = [e for e, _ in p.integrantes] or [p.empresa]
    composicion = "".join(
        f"<p><b>{e.razon}</b></p><table><tr><th>Porcentaje participación</th><th>Documento de identificación</th>"
        f"<th>Nombre o razón social del accionista</th></tr>"
        f"<tr><td>60%</td><td>{e.gerente.cedula_puntos}</td><td>{e.gerente.nombre.title()}</td></tr>"
        f"<tr><td>40%</td><td>1.999.009.{e.nit[-3:]}</td><td>Socio Demostración {e.nit[-2:]}</td></tr></table>"
        for e in empresas if not e.anonima
    )
    r = p.representante
    cuerpo = f"""
<h1>FORMATO 1 – CARTA DE PRESENTACIÓN DE LA OFERTA</h1>
<p class='centro'>INTERVENTORÍA DE OBRA PÚBLICA DE INFRAESTRUCTURA DE TRANSPORTE – VERSIÓN 3<br>{CODIGO} FORMATO 1</p>
{encabezado_proceso()}
<p>Estimados señores:</p>
<p>{r.nombre}, en mi calidad de representante legal de {p.nombre}, en adelante el “proponente”, manifiesto, bajo la gravedad del juramento que:</p>
{clausulas}
<p>23. Declaro que: [Marque con una X la característica aplica al proponente]</p>
<p>El proponente es:<br>{tipo}</p>
<p>El proponente o alguno de los miembros del proponente plural pertenece a un grupo empresarial: sí__ no_X__</p>
<p>El proponente cotiza en bolsa: sí___ no__X__</p>
<p>Composición accionaria del proponente o de las personas jurídicas que lo integran (lo anterior no aplica para las sociedades anónimas abiertas):</p>
{composicion or '<p>No aplica: sociedad anónima.</p>'}
<p>24. Autorizo que la entidad consulte la información comercial o financiera pertinente para el proceso de contratación, bajo el entendido que la entidad debe guardar confidencialidad sobre la información sujeta a reserva.</p>
<p>26. Recibiré notificaciones del contrato en: Persona de contacto {r.nombre.title()} · Dirección Calle Ficticia 123 · Ciudad Demo · Correo electrónico contacto@demo.invalid</p>
<p>27. He leído y acepto lo establecido en el Manual de Uso y Condiciones de la plataforma del SECOP II.</p>
<p>28. Me comprometo a cumplir todos los ítems relacionados con el “Formulario 1 – Presupuesto oficial” en caso de resultar adjudicatario.</p>
<p>Atentamente,</p>
<p>Nombre del Proponente {p.nombre}<br>Nombre del Representante Legal {r.nombre}<br>
C. C. No. {r.cedula_puntos} de {r.ciudad}<br>M.P. {r.matricula}<br>Ciudad Demo</p>
{firma(r.nombre, 'REPRESENTANTE LEGAL', p.nombre)}
"""
    return html(cuerpo, "Formato 1")


def copnia(persona: Persona, expedido: date) -> str:
    numeros = ["", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce",
               "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno",
               "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho",
               "veintinueve", "treinta", "treinta y uno"]
    cuerpo = f"""
<h1>Certificado de vigencia y antecedentes disciplinarios</h1>
<p class='centro'>CVAD-2026-DEMO{persona.cedula[-4:]}<br>CONSEJO PROFESIONAL NACIONAL DE INGENIERÍA<br>COPNIA<br>EL DIRECTOR GENERAL<br>CERTIFICA:</p>
<p>1. Que {persona.nombre}, identificado(a) con CEDULA DE CIUDADANIA {persona.cedula}, se encuentra inscrito(a) en el Registro Profesional Nacional que lleva esta entidad, en la profesión de INGENIERIA CIVIL con MATRICULA PROFESIONAL {persona.matricula} desde el 15 de Marzo de 2010, otorgado(a) mediante Resolución Nacional 9999.</p>
<p>2. Que el(la) MATRICULA PROFESIONAL es la autorización que expide el Estado para que el titular ejerza su profesión en todo el territorio de la República de Colombia, de conformidad con lo dispuesto en la Ley 842 de 2003.</p>
<p>3. Que el(la) referido(a) MATRICULA PROFESIONAL se encuentra VIGENTE</p>
<p>4. Que el profesional no tiene antecedentes disciplinarios ético-profesionales.</p>
<p>5. Que la presente certificación se expide en Bogotá, D.C., a los {numeros[expedido.day]} ({expedido.day}) días del mes de {MESES[expedido.month - 1].title()} del año dos mil veintiseis ({expedido.year}).</p>
<p>Funcionario de Demostración<br>Firma del titular (*)</p>
<div class='salto'></div>
<h1>TARJETA PROFESIONAL</h1>
<p class='centro'>MATRÍCULA PROFESIONAL DE INGENIERÍA</p>
<p>INGENIERO CIVIL<br>{persona.nombre}<br>C.C. {persona.cedula_puntos}<br>MATRÍCULA PROFESIONAL No. {persona.matricula}<br>FECHA DE EXPEDICIÓN: 15 DE MARZO DE 2010</p>
"""
    return html(cuerpo, "COPNIA")


def formato2(p: Proponente) -> str:
    clase = "CONSORCIO" if p.tipo == "consorcio" else "UNIÓN TEMPORAL"
    sub = "2A — DOCUMENTO DE CONFORMACIÓN DE CONSORCIO" if p.tipo == "consorcio" else "2B — DOCUMENTO DE CONFORMACIÓN DE UNIÓN TEMPORAL"
    filas = "".join(f"<tr><td>{e.razon}</td><td>{pct}%</td></tr>" for e, pct in p.integrantes)
    firmantes = " y ".join(f"{e.razon} NIT {e.nit_puntos}" for e, _ in p.integrantes)
    r, s = p.representante, p.suplente
    cuerpo = f"""
<h1>FORMATO 2 — CONFORMACIÓN DE PROPONENTE PLURAL</h1>
<p class='centro'>FORMATO {sub}<br>{CODIGO}</p>
{encabezado_proceso()}
<p>Estimados señores:</p>
<p>Los suscritos, debidamente autorizados para actuar en nombre y representación de {firmantes} respectivamente, manifestamos por medio de este documento que hemos convenido asociarnos en {clase.title()} para participar en el Proceso de Contratación y, por lo tanto, expresamos lo siguiente:</p>
<p>1. El {clase.title()} está integrado por los siguientes miembros:</p>
<table><tr><th>Nombre del integrante</th><th>Compromiso (%) (1)</th></tr>{filas}</table>
<p>2. El {clase.title()} se denomina {p.nombre}</p>
<p>3. El objeto del {clase.title()} es {OBJETO}.</p>
<p>4. La duración de este {clase.title()} es la duración del contrato y un año más.</p>
<p>5. EL REPRESENTANTE DEL {clase} ES {r.nombre} IDENTIFICADO CON CEDULA DE CIUDADANIA {r.cedula_puntos} DE {r.ciudad}, quien está expresamente facultado para firmar, presentar la propuesta y, en caso de salir favorecidos con la adjudicación del contrato, firmarlo y tomar todas las determinaciones que fueren necesarias respecto de su ejecución y liquidación, con amplias y suficientes facultades.</p>
<p>6. EL REPRESENTANTE SUPLENTE DEL {clase} ES {s.nombre} IDENTIFICADO CON CEDULA DE CIUDADANIA {s.cedula_puntos} DE {s.ciudad}, quien está expresamente facultado para firmar, presentar la propuesta y, en caso de salir favorecidos con la adjudicación del contrato, firmarlo.</p>
<p>7. En caso de resultar adjudicatario, la facturación la realizará: {p.nombre}</p>
<p>8. El domicilio del {clase.title()} es: Calle Ficticia 123 · Ciudad Demo · contacto@demo.invalid</p>
{firma(r.nombre, 'REPRESENTANTE LEGAL', p.nombre)}
"""
    return html(cuerpo, "Formato 2")


def existencia(e: Empresa, expedido: date) -> str:
    tipo_sociedad = "SOCIEDAD ANÓNIMA" if e.anonima else "SOCIEDAD POR ACCIONES SIMPLIFICADA"
    suplente = (
        f"<p>SUPLENTE DEL GERENTE {e.suplente.apellidos} {e.suplente.nombres} C.C. {int(e.suplente.cedula):015d}</p>"
        if e.suplente else ""
    )
    revisor = (
        f"<p>CERTIFICA:<br>** REVISORÍA FISCAL **<br>QUE POR ACTA DE ASAMBLEA DE ACCIONISTAS FUE NOMBRADO:<br>"
        f"REVISOR FISCAL {e.revisor_fiscal} C.C. {e.revisor_cedula}</p>"
        if e.revisor_fiscal else ""
    )
    cuerpo = f"""
<p>CAMARA DE COMERCIO DE CIUDAD DEMO<br>SEDE VIRTUAL<br>CÓDIGO VERIFICACIÓN: DEMO{e.nit[-6:]}<br>{fecha_larga(expedido)} HORA 08:30:00</p>
<p>ESTE CERTIFICADO FUE GENERADO ELECTRÓNICAMENTE PARA UNA DEMOSTRACIÓN Y NO PUEDE SER VALIDADO.</p>
<h1>CERTIFICADO DE EXISTENCIA Y REPRESENTACION LEGAL O INSCRIPCION DE DOCUMENTOS.</h1>
<p>LA CAMARA DE COMERCIO DE CIUDAD DEMO, CON FUNDAMENTO EN LAS MATRICULAS E INSCRIPCIONES DEL REGISTRO MERCANTIL</p>
<p>CERTIFICA:<br>RAZON SOCIAL : {e.razon} NIT : {e.nit} {e.dv}<br>DOMICILIO : CIUDAD DEMO</p>
<p>CERTIFICA:<br>MATRICULA NO: 0999{e.nit[-4:]} DEL 3 DE MARZO DE 2012</p>
<p>CERTIFICA:<br>RENOVACION DE LA MATRICULA : 28 DE MARZO DE 2026<br>ULTIMO AÑO RENOVADO : 2026</p>
<p>CERTIFICA:<br>CONSTITUCION: QUE POR DOCUMENTO PRIVADO DEL 3 DE MARZO DE 2012 SE CONSTITUYO LA {tipo_sociedad} DENOMINADA {e.razon}.</p>
<p>CERTIFICA:<br>VIGENCIA: QUE EL TERMINO DE DURACION DE LA SOCIEDAD ES INDEFINIDO</p>
<p>CERTIFICA:<br>OBJETO SOCIAL: LA SOCIEDAD TENDRA COMO OBJETO PRINCIPAL LA INTERVENTORIA, CONSULTORIA, DISEÑO, CONSTRUCCION, MEJORAMIENTO, REHABILITACION Y MANTENIMIENTO DE OBRAS CIVILES, VIAS, CARRETERAS, PUENTES Y OBRAS DE INFRAESTRUCTURA DE TRANSPORTE, ASI COMO LA INTERVENTORIA TECNICA, ADMINISTRATIVA, FINANCIERA, JURIDICA, SOCIAL Y AMBIENTAL DE PROYECTOS DE INGENIERIA CIVIL.</p>
<p>CERTIFICA:<br>ACTIVIDAD PRINCIPAL:<br>7112 (ACTIVIDADES DE INGENIERÍA Y OTRAS ACTIVIDADES CONEXAS DE CONSULTORÍA TÉCNICA)</p>
<p>CERTIFICA:<br>REPRESENTACION LEGAL: LA SOCIEDAD TENDRÁ UN GERENTE QUE SERÁ EL REPRESENTANTE LEGAL DE LA MISMA. EL GERENTE TENDRÁ UN (1) SUPLENTE QUIEN LO REEMPLAZARÁ EN SUS FALTAS ABSOLUTAS O ACCIDENTALES.</p>
<p>CERTIFICA:<br>** NOMBRAMIENTOS **<br>NOMBRE IDENTIFICACION<br>GERENTE<br>{e.gerente.apellidos} {e.gerente.nombres} C.C. {int(e.gerente.cedula):015d}</p>
{suplente}
{revisor}
<p>CERTIFICA:<br>FACULTADES DEL REPRESENTANTE LEGAL: EL GERENTE PODRÁ CELEBRAR Y EJECUTAR TODOS LOS ACTOS Y CONTRATOS COMPRENDIDOS EN EL OBJETO SOCIAL SIN NINGÚN TIPO DE LIMITACIÓN POR RAZÓN DE LA NATURALEZA NI DE LA CUANTÍA DE LOS ACTOS QUE CELEBRE.</p>
<p>* * * EL PRESENTE CERTIFICADO NO CONSTITUYE PERMISO DE FUNCIONAMIENTO EN NINGUN CASO * * *</p>
<p>** ESTE CERTIFICADO REFLEJA LA SITUACION JURIDICA DE LA SOCIEDAD HASTA LA FECHA Y HORA DE SU EXPEDICION. **</p>
"""
    return html(cuerpo, "Existencia")


def rup(e: Empresa, expedido: date) -> str:
    cuerpo = f"""
<p>CAMARA DE COMERCIO DE CIUDAD DEMO<br>SEDE VIRTUAL<br>CÓDIGO VERIFICACIÓN: DEMORUP{e.nit[-5:]}<br>{fecha_larga(expedido)} HORA 08:31:00</p>
<h1>CERTIFICADO DE INSCRIPCION Y CLASIFICACION REGISTRO UNICO DE PROPONENTES</h1>
<p>CERTIFICA:<br>LA CAMARA DE COMERCIO DE CIUDAD DEMO, CON FUNDAMENTO EN LO DISPUESTO EN EL ARTICULO 6.1 DE LA LEY 1150 DE 2007, REGLAMENTADA POR DECRETO 1082 DE 2015.</p>
<p>CERTIFICA:<br>IDENTIFICACION<br>QUE: {e.razon}<br>NIT: {e.nit} {e.dv}<br>NUMERO DEL PROPONENTE EN LA CAMARA DE COMERCIO: 0009{e.nit[-4:]}</p>
<p>CERTIFICA:<br>QUE LA INSCRIPCION SE ENCUENTRA VIGENTE Y EN FIRME.</p>
<p>CERTIFICA:<br>CLASIFICACION: 721410 SERVICIOS DE INTERVENTORIA DE OBRAS CIVILES · 811015 INGENIERIA CIVIL</p>
<div class='salto'></div>
<p>CERTIFICA:<br>REPORTE DE LAS ENTIDADES ESTATALES SOBRE CONTRATOS, MULTAS, SANCIONES E INHABILIDADES EN FIRME</p>
{_sanciones_rup(e)}
"""
    return html(cuerpo, "RUP")


def _sanciones_rup(e: Empresa) -> str:
    """El bloque de multas del RUP, con la misma forma que el de la Cámara de
    Comercio: una ficha por sanción con entidad, contrato, descripción y
    fecha de ejecutoria."""
    if not e.sanciones:
        return "<p>A LA FECHA DE EXPEDICION DE ESTE CERTIFICADO NO APARECEN REPORTES DE CONTRATOS, MULTAS, SANCIONES NI INHABILIDADES.</p>"
    partes = ["<p>LA INFORMACION REPORTADA POR LAS ENTIDADES ESTATALES EN RELACION CON LAS SANCIONES EN FIRME ES LA SIGUIENTE:</p>"]
    for s in e.sanciones:
        partes.append(f"""<p><b>SANCIONES</b><br>
ENTIDAD QUE REPORTO LA {s.tipo}: {s.entidad}<br>
NUMERO DE REGISTRO: {s.ejecutoria.year}-{s.contrato}<br>
CONTRATO AFECTADO: {s.contrato}<br>
DESCRIPCION DE LA SANCION: {s.descripcion}<br>
LA SANCION ES INCUMPLIMIENTO (SI O NO): {"SI" if s.es_incumplimiento else "NO"}<br>
VALOR DE LA MULTA EN PESOS: {s.valor or "0"}<br>
FECHA DEL ACTO ADMINISTRATIVO QUE LA IMPUSO: {s.ejecutoria:%Y/%m/%d}<br>
FECHA DE EJECUTORIA: {s.ejecutoria:%Y/%m/%d}</p>""")
    return "\n".join(partes)


def poliza(p: Proponente, expedida: date, hasta: date) -> str:
    cuerpo = f"""
<h1>POLIZA DE SEGURO DE CUMPLIMIENTO ENTIDAD ESTATAL</h1>
<p class='centro'>DECRETO 1082 DE 2015 · ASEGURADORA DEMOSTRACIÓN S.A. · PÓLIZA No. DEMO-{p.hoja}-2026</p>
<p>FECHA EXPEDICIÓN {expedida:%d/%m/%Y}</p>
<p><b>DATOS DEL TOMADOR / GARANTIZADO</b><br>NOMBRE O RAZON SOCIAL {p.nombre}</p>
<p><b>DATOS DEL ASEGURADO / BENEFICIARIO</b><br>BENEFICIARIO: {ENTIDAD} IDENTIFICACIÓN NIT: {ENTIDAD_NIT}</p>
<p><b>OBJETO DEL SEGURO:</b> GARANTIZAR LA SERIEDAD DE LA OFERTA PRESENTADA EN EL PROCESO {CODIGO}, LOTE 1 Y LOTE 2, CUYO OBJETO ES {OBJETO}.</p>
<table><tr><th>AMPARO</th><th>VIGENCIA DESDE</th><th>VIGENCIA HASTA</th><th>VALOR ASEGURADO</th></tr>
<tr><td>SERIEDAD DE LA OFERTA</td><td>{CIERRE:%d/%m/%Y}</td><td>{hasta:%d/%m/%Y}</td><td>${p.valor_poliza:,.2f}</td></tr></table>
{firma('Firma autorizada · Aseguradora Demostración', 'FIRMA AUTORIZADA')}
"""
    return html(cuerpo, "Póliza")


def seguridad_social(e: Empresa) -> str:
    firmante = e.revisor_fiscal or e.gerente.nombre
    cargo = "REVISOR FISCAL" if e.revisor_fiscal else "REPRESENTANTE LEGAL"
    cuerpo = f"""
<h1>FORMATO 5 – PAGOS AL SISTEMA DE SEGURIDAD SOCIAL Y APORTES LEGALES</h1>
<p class='centro'>ARTÍCULO 50 LEY 789 DE 2002 (PERSONAS JURÍDICAS)<br>{CODIGO}</p>
<p>{firmante}, identificado con C.C. {e.revisor_cedula or e.gerente.cedula_puntos} en mi condición de {cargo.lower()} de {e.razon} identificada con NIT {e.nit_puntos}, bajo la gravedad de juramento, certifico el pago de los aportes de salud, riesgos profesionales, pensiones y aportes a las Cajas de Compensación Familiar, al Instituto Colombiano de Bienestar Familiar y al Servicio Nacional de Aprendizaje, pagados por la compañía durante los últimos seis (6) meses contados a partir de la fecha de cierre del presente proceso de selección. Lo anterior, en cumplimiento de lo dispuesto en el artículo 50 de la Ley 789 de 2002.</p>
<p>En constancia, se firma en Ciudad Demo a los 5 días del mes de septiembre de 2026</p>
{firma(firmante, cargo, e.razon)}
"""
    return html(cuerpo, "Seguridad social")


def revisor_abierta_cerrada(e: Empresa) -> str:
    cuerpo = f"""
<h1>CERTIFICACIÓN DEL REVISOR FISCAL</h1>
<p>El suscrito revisor fiscal de {e.razon}, identificada con NIT {e.nit_puntos}, certifica que LA EMPRESA {e.razon} ES UNA SOCIEDAD ANONIMA CERRADA, de conformidad con sus estatutos y el Código de Comercio.</p>
<p>Se expide en Ciudad Demo el 5 de septiembre de 2026.</p>
{firma(e.revisor_fiscal, 'REVISOR FISCAL', e.razon)}
"""
    return html(cuerpo, "Revisor fiscal")


# --- Antecedentes (frases estándar de cada certificado) ----------------------
def redam(persona: Persona, expedido: date) -> str:
    hasta = date(expedido.year + (expedido.month + 3 > 12), (expedido.month + 2) % 12 + 1, min(expedido.day, 28))
    return html(f"""
<h1>CERTIFICADO REDAM</h1>
<p>CERTIFICA QUE</p>
<p>Una vez consultada la base de datos de deudores alimentarios morosos REDAM, el(la) ciudadano(a) con número de identificación CC {persona.cedula} NO SE ENCUENTRA INSCRITO EN EL REGISTRO DE DEUDORES ALIMENTARIOS MOROSOS</p>
<p>Se expide en Bogotá el {expedido:%d/%m/%Y} 09:41 AM<br>Código Verificación: DEMO{persona.cedula[-6:]}<br>Válida hasta: {hasta:%d/%m/%Y}</p>
""", "REDAM")


def contraloria(nombre: str, documento: str, tipo: str, expedido: date) -> str:
    return html(f"""
<h1>CERTIFICADO DE ANTECEDENTES FISCALES</h1>
<p>LA CONTRALORÍA DELEGADA PARA RESPONSABILIDAD FISCAL, INTERVENCIÓN JUDICIAL Y COBRO COACTIVO</p>
<p>CERTIFICA:</p>
<p>Que una vez consultado el Sistema de Información del Boletín de Responsables Fiscales 'SIBOR', el {fecha_larga(expedido).lower()}, el número de identificación{' de la persona jurídica' if tipo == 'NIT' else ''}, relacionado a continuación, NO SE ENCUENTRA REPORTADO COMO RESPONSABLE FISCAL.</p>
<p>Tipo Documento {tipo}<br>No. Identificación {documento}<br>Nombre {nombre}<br>Código de Verificación DEMO{documento[-6:]}</p>
""", "Contraloría")


def procuraduria(nombre: str, documento: str, tipo: str, expedido: date) -> str:
    return html(f"""
<h1>CERTIFICADO DE ANTECEDENTES</h1>
<p>CERTIFICADO ORDINARIO No. DEMO{documento[-6:]}</p>
<p>Ciudad Demo, {fecha_larga(expedido).lower()}</p>
<p>La PROCURADURIA GENERAL DE LA NACIÓN certifica que una vez consultado el Sistema de Información de Registro de Sanciones e Inhabilidades (SIRI), el(la) señor(a) {nombre} identificado(a) con {tipo} número {documento}:</p>
<p><b>NO REGISTRA SANCIONES NI INHABILIDADES VIGENTES</b></p>
<p>Funcionario de Demostración</p>
""", "Procuraduría")


def policia(persona: Persona, expedido: date) -> str:
    return html(f"""
<h1>Consulta en línea de Antecedentes Penales y Requerimientos Judiciales</h1>
<p>La Policía Nacional de Colombia informa:</p>
<p>Que siendo las 10:01:56 AM horas del {expedido:%d/%m/%Y}, el ciudadano identificado con:<br>Cédula de Ciudadanía Nº {persona.cedula}<br>Apellidos y Nombres: {persona.apellidos} {persona.nombres}</p>
<p><b>NO TIENE ASUNTOS PENDIENTES CON LAS AUTORIDADES JUDICIALES</b></p>
<p>de conformidad con lo establecido en el artículo 248 de la Constitución Política de Colombia.</p>
""", "Policía")


def rnmc(persona: Persona) -> str:
    return html(f"""
<h1>Sistema Registro Nacional de Medidas Correctivas RNMC</h1>
<p>Consulta Ciudadano</p>
<p>La Policía Nacional de Colombia informa:</p>
<p>Que a la fecha, {persona.rnmc:%d/%m/%Y} 10:00:15 a. m. el ciudadano con Cédula de Ciudadanía Nº. {persona.cedula} y Nombre: {persona.nombre}.</p>
<p><b>NO TIENE MEDIDAS CORRECTIVAS PENDIENTES POR CUMPLIR.</b></p>
<p>De conformidad con la Ley 1801 de 2016. Registro interno de validación No. DEMO{persona.cedula[-6:]}.</p>
""", "RNMC")


def cedula(persona: Persona) -> str:
    return html(f"""
<h1>REPUBLICA DE COLOMBIA</h1>
<p class='centro'>IDENTIFICACION PERSONAL<br>CEDULA DE CIUDADANIA</p>
<p>NUMERO {persona.cedula_puntos}<br>{persona.apellidos}<br>APELLIDOS<br>{persona.nombres}<br>NOMBRES</p>
<div class='salto'></div>
<p>FECHA DE NACIMIENTO {fecha_cedula(persona.nacimiento)}<br>{persona.ciudad}<br>LUGAR DE NACIMIENTO<br>1.70 O+ M<br>ESTATURA G.S. RH SEXO</p>
<p>{fecha_cedula(persona.expedicion)} {persona.ciudad} FECHA Y LUGAR DE EXPEDICION</p>
<p>INDICE DERECHO<br>REGISTRADOR NACIONAL · FUNCIONARIO DE DEMOSTRACIÓN<br>A-0000000-00000000-M-{int(persona.cedula):010d}-{persona.expedicion:%Y%m%d}</p>
""", "Cédula")
