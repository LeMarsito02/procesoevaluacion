"""Periodos de experiencia leídos de las certificaciones del contratista.

Cada entidad y cada empresa certifica a su manera, y el contratista entrega
todo junto, a veces con páginas repetidas, escaneadas o en desorden. En vez
de esperar un formato, se leen todas las fechas del documento y se mira qué
dice el texto justo antes de cada una:

- de inicio: «fecha de inicio:», «desde el», «a partir del»;
- de terminación: «fecha de terminación:», «hasta el», «al», «terminación
  anticipada»;
- una fecha seguida de «hasta…» o «al…» también es de inicio («del 26 de
  agosto de 2016 hasta el 25 de diciembre de 2016»).

Con eso se arman los periodos. Lo dudoso queda marcado para que lo revise una
persona, y nunca se inventa una fecha:

- sin fecha de terminación, si el contrato estaba en ejecución o la persona
  seguía activa, se cuenta hasta la fecha de expedición (`abierto`);
- una terminación sin inicio a la vista toma la fecha anterior del mismo
  párrafo («nombrado mediante decreto del 20 de mayo de 1993… hasta el 30 de
  diciembre de 1994») y se avisa (`nota`);
- una terminación posterior a la fecha de referencia se recorta a esa fecha.

Las certificaciones repetidas no hacen daño: al poner la experiencia en línea
el tiempo se cuenta una sola vez.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date

from motor.ops.experiencia import Periodo
from motor.ops.texto import en_una_linea, plano, sin_marcas
from motor.ops.tiempo import MESES, fechas_con_tramo

_M = "|".join(MESES)
_ANIO = r"(\d{4})"
# Lo que puede haber entre la palabra clave y la fecha: «:», guiones de una
# tabla y el número en letras («el dieciocho (18) de…»).
_RELLENO = r"\s*:?[\s|_-]*(?:[A-Z]+\s*)?$"
_ANTES_INICIO_RE = re.compile(
    r"(?:\bDESDE(?:\s+EL)?(?:\s+DIA)?|\bA\s+PARTIR\s+DEL?(?:\s+DIA)?|FECHA\s+(?:DE\s+)?(?:INICIO|INICIACION|INGRESO)[^\n\d:]{0,25}?)" + _RELLENO
)
_ANTES_FIN_ROTULO_RE = re.compile(r"FECHA\s+(?:DE\s+)?(?:TERMINACION|FINALIZACION|RETIRO)[^\n\d:]{0,25}?" + _RELLENO)
_ANTES_HASTA_RE = re.compile(r"\bHASTA(?:\s+EL)?(?:\s+DIA)?(?:\s+LA\s+FECHA)?" + _RELLENO)
_ANTES_AL_RE = re.compile(r"\bAL(?:\s+DIA)?" + _RELLENO)
# «prórroga de seis meses a partir del…», «se aceptó su renuncia a partir del…»: no empieza un periodo.
_NO_EMPIEZA_RE = re.compile(r"PRORROGA|ADICION|RENUNCIA|RETIRO|DESVINCUL|INSUBSISTEN")
_ANTES_ANTICIPADA_RE = re.compile(r"TERMINACION\s+(?:ANTICIPADA|BILATERAL)[^\n\d:]{0,12}?" + _RELLENO)
_ANTES_SUSCRIPCION_RE = re.compile(r"FECHA\s+(?:DE\s+)?(?:SUSCRIPCION|(?:DEL\s+)?CONTRATO)[^\n\d:]{0,12}?" + _RELLENO)
_ANTES_EXPEDICION_RE = re.compile(r"(?:SE\s+EXPIDE|EXPEDID[AO]|SE\s+OTORGA|DAD[AO]\s+EN|SE\s+FIRMA|FECHA\s*:)[^\n]{0,90}(?:\n[^\n]{0,60})?$")
# Tras una fecha: lo que sigue la convierte en fecha de inicio.
_SIGUE_FIN_RE = re.compile(r"\s*,?\s*(?:Y\s+)?(?:HASTA|AL)\b")
# «2 de enero al 30 de enero de 2004», «del 8 al 30 de junio de 2023»: la primera fecha no trae año.
_RANGO_SIN_ANIO_RE = re.compile(rf"\b(\d{{1,2}})(?:\s+DE\s+({_M}))?\s+(?:AL|HASTA\s+EL)\s+(\d{{1,2}})\s+DE\s+({_M})\s+DEL?\s+{_ANIO}")
# «SUSPENSION NO 1: 20 DE JUNIO AL 03 DE JULIO DE 2025»
_SUSPENSION_RE = re.compile(
    rf"SUSPENSION[^\n:]{{0,20}}:\s*(\d{{1,2}})\s+DE\s+({_M})(?:\s+DE\s+(\d{{4}}))?\s+(?:AL|HASTA\s+EL)\s+(\d{{1,2}})\s+DE\s+({_M})\s+DE\s+(\d{{4}})"
)
# Tabla con las fechas arriba y los rótulos debajo.
_ROTULOS_DEBAJO_RE = re.compile(r"FECHA\s+DE\s+INICIO\s*\n\s*FECHA\s+DE\s+TERMINACION")
_VENTANA_ROTULOS = 260
_ABIERTO_RE = re.compile(
    r"EN\s+EJECUCION|SE\s+ENCUENTRA\s+ACTIV[OA]|ACTUALMENTE\s+(?:SE\s+DESEMPENA|LABORA|VINCULAD|PRESTA)|HASTA\s+LA\s+FECHA(?!\s*\(?\d)|A\s+LA\s+FECHA\s+SE\s+ENCUENTRA"
)
_REFERENCIA_RE = re.compile(
    r"(?:NO\.?\s*(?:DE\s+)?CONTRATO|CONTRATO(?:\s+(?:NO|NUMERO)\.?)?)\s*:?\s*((?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{2,})"
    r"|((?:CONTRATO|ORDEN)\s+DE\s+(?:PRESTACION\s+DE\s+)?SERVICIOS(?:\s+PROFESIONALES)?\s+(?:NO\.?\s*)?\d+\s+DE\s+\d{4})"
)
_CARGO_RE = re.compile(r"\bCARGO\s+(?:DE|COMO)\s+([A-Z][A-Z ]{3,60}?)(?=\s*[,.;\n]|\s+CODIGO|\s+GRADO|\s+EN\s+|\s+DE\s+LA\b|\s+DEL\b|$)")
_ENTIDAD_RE = re.compile(
    r"\b(?:INSTITUTO|CORPORACION|DEPARTAMENTO|GOBERNACION|MUNICIPIO|ALCALDIA|MINISTERIO|UNIVERSIDAD|EMPRESAS?|FUNDACION|AGENCIA|"
    r"UNIDAD\s+(?:DE|ADMINISTRATIVA)|CONSORCIO|UNION\s+TEMPORAL|COOPERATIVA|HOSPITAL|CONSTRUCTORA|GRUPO)\s[^\n]{3,90}"
)
_SOCIEDAD_RE = re.compile(r"^[^\n:]{3,70}\b(?:S\.?A\.?S|LTDA|S\.A|E\.S\.P|& ?CIA)\b\.?[ \t]*$", re.M)
# Donde deja de ser el nombre de la entidad.
_FIN_ENTIDAD_RE = re.compile(r"[,;(:]|\.\s|\s-\s|\s(?:DESDE|HASTA|MEDIANTE|IDENTIFICAD|CON\s+NIT|NIT\b|EN\s+EL\s+CARGO|SUSCRIB|CERTIFICA|HACE\s+CONSTAR|Y\s+EL\s+SE)")
# Cuánto texto antes del inicio se mira para saber si la certificación es abierta.
_VENTANA_ABIERTO = 1500
# Una terminación sin inicio busca la fecha anterior hasta esta distancia.
_VENTANA_INICIO_INFERIDO = 420
# Más lejos que esto, una terminación ya no es del inicio que quedó pendiente.
_VENTANA_PERIODO = 2600
# Un «hasta» en prosa solo cierra un inicio que esté a esta distancia.
_VENTANA_HASTA = 450


@dataclass
class Lectura:
    periodos: list[Periodo] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


@dataclass
class _Pendiente:
    inicio: date
    pos: int
    fines: list[date] = field(default_factory=list)
    anticipadas: list[date] = field(default_factory=list)
    suspensiones: list[tuple[date, date]] = field(default_factory=list)


def _fecha(dia: str, mes: str, anio: str | int) -> date | None:
    try:
        return date(int(anio), MESES[mes], int(dia))
    except (ValueError, KeyError):
        return None


def _suspension(m: re.Match[str]) -> tuple[date, date] | None:
    d1, mes1, a1, d2, mes2, a2 = m.groups()
    hasta = _fecha(d2, mes2, a2)
    if hasta is None:
        return None
    desde = _fecha(d1, mes1, a1 or hasta.year - (1 if MESES[mes1] > MESES[mes2] else 0))
    return (desde, hasta) if desde else None


def leer_periodos(paginas: list[str], archivo: str = "", hasta: date | None = None) -> Lectura:
    """Periodos de experiencia que certifican las páginas de un documento.
    `hasta` es la fecha de referencia: nada cuenta después de ella."""
    originales = [sin_marcas(p) for p in paginas]
    textos = [plano(o) for o in originales]
    comienzos, pos = [], 0
    for t in textos:
        comienzos.append(pos)
        pos += len(t) + 1
    texto, original = "\n".join(textos), "\n".join(originales)
    lectura = Lectura()

    def pagina_de(posicion: int) -> int:
        return max(bisect_right(comienzos, posicion) - 1, 0)

    def donde(posicion: int) -> str:
        return f"página {pagina_de(posicion) + 1}" + (f" de {archivo}" if archivo else "")

    def referencia_de(posicion: int) -> str:
        """El contrato nombrado en la misma página o, en una certificación
        laboral, el cargo; si no, el contrato de la página anterior (más atrás
        no: con páginas en desorden sería de otro contrato)."""
        p = pagina_de(posicion)

        def contrato(pagina: int, ultimo: bool) -> str:
            halladas = list(_REFERENCIA_RE.finditer(textos[pagina]))
            if not halladas:
                return ""
            m = halladas[-1] if ultimo else halladas[0]
            grupo = 1 if m.group(1) else 2
            return en_una_linea(originales[pagina][m.start(grupo):m.end(grupo)])

        if ref := contrato(p, False):
            return ref
        if m := _CARGO_RE.search(textos[p]):
            return en_una_linea(originales[p][m.start(1):m.end(1)]).title()
        return contrato(p - 1, True) if p > 0 else ""

    def entidad_de(posicion: int) -> str:
        """Quien certifica: la primera entidad nombrada en la página con
        mayúscula inicial (un «instituto» en medio de una frase no lo es)."""
        p = pagina_de(posicion)
        t, o = textos[p], originales[p]
        candidatas = [(m.start(), m.end()) for m in _ENTIDAD_RE.finditer(t) if o[m.start()].isupper()]
        candidatas += [(m.start(), m.end()) for m in _SOCIEDAD_RE.finditer(t) if sum(c.isupper() for c in o[m.start():m.end()]) > 5]
        if not candidatas:
            return ""
        inicio, fin = min(candidatas)
        corte = _FIN_ENTIDAD_RE.search(t, inicio + 6, fin)
        return en_una_linea(o[inicio:corte.start() if corte else fin]).strip(" .-_|")

    def agregar(inicio: date, fin: date, posicion: int, **datos) -> None:
        nota = datos.pop("nota", "")
        if hasta and inicio > hasta:
            return
        if hasta and fin > hasta:
            fin, datos["abierto"] = hasta, True
            nota = (nota + " " if nota else "") + f"Termina después del {hasta:%d/%m/%Y}: se contó hasta esa fecha."
        p = pagina_de(posicion)
        lectura.periodos.append(Periodo(
            inicio, fin, entidad=entidad_de(posicion), referencia=datos.pop("referencia", None) or referencia_de(posicion),
            archivo=archivo, pagina=p + 1, texto="\n".join(textos[p:p + 2]), nota=nota, **datos,
        ))

    # Lo que no sigue la forma general se lee aparte y sus fechas ya no se vuelven a mirar.
    ocupado: list[tuple[int, int]] = []
    suspensiones: list[tuple[int, tuple[date, date]]] = []
    for m in _SUSPENSION_RE.finditer(texto):
        if s := _suspension(m):
            suspensiones.append((m.start(), s))
            ocupado.append(m.span())
    for m in _RANGO_SIN_ANIO_RE.finditer(texto):
        if any(a <= m.start() < b for a, b in ocupado):
            continue
        d1, mes1, d2, mes2, anio = m.groups()
        fin = _fecha(d2, mes2, anio)
        inicio = _fecha(d1, mes1 or mes2, anio)
        if inicio and fin and inicio <= fin:
            agregar(inicio, fin, m.start())
            ocupado.append(m.span())

    fechas = [f for f in fechas_con_tramo(texto) if not any(a <= f[0] < b for a, b in ocupado)]
    for i in range(len(fechas) - 1):
        rotulos = _ROTULOS_DEBAJO_RE.search(texto, fechas[i + 1][1], fechas[i + 1][1] + _VENTANA_ROTULOS)
        seguidas = "\n" in texto[fechas[i][1]:fechas[i + 1][0]] and fechas[i + 1][0] - fechas[i][1] < 12
        sin_otra = i + 2 >= len(fechas) or (rotulos and fechas[i + 2][0] > rotulos.start())
        if rotulos and seguidas and sin_otra and fechas[i][2] <= fechas[i + 1][2]:
            agregar(fechas[i][2], fechas[i + 1][2], fechas[i][0])
            ocupado.extend([(fechas[i][0], fechas[i][1]), (fechas[i + 1][0], fechas[i + 1][1])])
    fechas = [f for f in fechas if not any(a <= f[0] < b for a, b in ocupado)]

    pendiente: _Pendiente | None = None
    suscripcion: tuple[int, date] | None = None
    usadas: set[int] = set()

    def cerrar(limite: int) -> None:
        nonlocal pendiente
        if pendiente is None:
            return
        p, pendiente = pendiente, None
        propias = [s for posicion, s in suspensiones if p.pos <= posicion < limite]
        if p.anticipadas or p.fines:
            fin = min(p.anticipadas) if p.anticipadas else max(p.fines)
            if fin >= p.inicio:
                nota = "Terminó antes de lo pactado (terminación anticipada)." if p.anticipadas and p.fines and fin < max(p.fines) else ""
                agregar(p.inicio, fin, p.pos, suspensiones=propias, nota=nota)
            else:
                lectura.avisos.append(
                    f"Una certificación ({donde(p.pos)}) tiene una fecha mal leída: empieza el {p.inicio:%d/%m/%Y} y termina el {fin:%d/%m/%Y}. "
                    "Agregue el periodo a mano."
                )
            return
        abierta = _ABIERTO_RE.search(texto, max(0, p.pos - _VENTANA_ABIERTO), limite)
        expedicion = next(
            (f for ini, _, f in fechas if p.pos < ini < limite and f >= p.inicio and _ANTES_EXPEDICION_RE.search(texto, max(0, ini - 170), ini)),
            None,
        )
        if abierta and (expedicion or hasta):
            agregar(p.inicio, expedicion or hasta, p.pos, suspensiones=propias, abierto=True)
        else:
            nombre = referencia_de(p.pos) or "Una certificación"
            lectura.avisos.append(f"{nombre} ({donde(p.pos)}) empieza el {p.inicio:%d/%m/%Y} y no se leyó la fecha de terminación.")

    for i, (ini, fin_tramo, fecha) in enumerate(fechas):
        antes = texto[max(0, ini - 60):ini]
        rotulo_fin, hasta_, al = _ANTES_FIN_ROTULO_RE.search(antes), _ANTES_HASTA_RE.search(antes), _ANTES_AL_RE.search(antes)
        es_anticipada = bool(_ANTES_ANTICIPADA_RE.search(antes))
        es_fin = bool(rotulo_fin or hasta_ or al)
        inicio_escrito = _ANTES_INICIO_RE.search(antes)
        if inicio_escrito and "PARTIR" in inicio_escrito.group() and _NO_EMPIEZA_RE.search(texto, max(0, ini - 130), ini):
            usadas.add(i)
            continue
        es_inicio = bool(inicio_escrito) or (not es_fin and not es_anticipada and bool(_SIGUE_FIN_RE.match(texto, fin_tramo)))
        if _ANTES_SUSCRIPCION_RE.search(antes):
            suscripcion = (ini, fecha)
        if es_inicio:
            cerrar(ini)
            pendiente = _Pendiente(fecha, ini)
            usadas.add(i)
            continue
        if not (es_fin or es_anticipada):
            continue
        usadas.add(i)
        if pendiente and suscripcion and suscripcion[0] > pendiente.pos:
            # Después del inicio pendiente empezó otro contrato (trae su fecha de suscripción).
            cerrar(suscripcion[0])
        cerca = pendiente is not None and pagina_de(ini) - pagina_de(pendiente.pos) <= 1
        if es_anticipada:
            if cerca and ini - pendiente.pos < _VENTANA_PERIODO:
                pendiente.anticipadas.append(fecha)
            continue
        # Un «hasta» en prosa cierra el inicio que tiene al lado; los rótulos
        # («fecha de terminación inicial», «…final») pueden ser varios.
        if cerca and (ini - pendiente.pos < _VENTANA_PERIODO if rotulo_fin else not pendiente.fines and ini - pendiente.pos < _VENTANA_HASTA):
            pendiente.fines.append(fecha)
            continue
        if suscripcion and rotulo_fin and ini - suscripcion[0] < 700 and suscripcion[1] <= fecha:
            agregar(suscripcion[1], fecha, suscripcion[0], nota="No trae fecha de inicio: se tomó la de suscripción del contrato.")
            suscripcion = None
            continue
        if not hasta_:
            continue
        # «Hasta» sin inicio a la vista: la fecha anterior del mismo párrafo.
        anterior = next(
            (fechas[j] for j in range(i - 1, -1, -1)
             if j not in usadas and ini - fechas[j][0] < _VENTANA_INICIO_INFERIDO and fechas[j][2] <= fecha
             and "\n\n" not in texto[fechas[j][1]:ini]),
            None,
        )
        if anterior:
            agregar(anterior[2], fecha, anterior[0], nota=f"El inicio ({anterior[2]:%d/%m/%Y}) se dedujo del texto: confírmelo.")
        else:
            lectura.avisos.append(f"Una certificación ({donde(ini)}) termina el {fecha:%d/%m/%Y} y no se leyó la fecha de inicio.")
    cerrar(len(texto))

    lectura.periodos = _sin_repetidos(lectura.periodos)
    # Un inicio sin terminación ya no es problema si el mismo periodo se leyó completo en otra parte.
    inicios = {f"empieza el {p.inicio:%d/%m/%Y}" for p in lectura.periodos}
    lectura.avisos = list(dict.fromkeys(a for a in lectura.avisos if not any(i in a for i in inicios)))
    if not lectura.periodos and not lectura.avisos:
        lectura.avisos.append("No se encontró ningún periodo de experiencia" + (f" en {archivo}." if archivo else "."))
    return lectura


def _sin_repetidos(periodos: list[Periodo]) -> list[Periodo]:
    """Una certificación repetida (o la versión abierta o deducida de un
    periodo que también se leyó completo) se deja una sola vez."""
    firmes = {p.inicio for p in periodos if not p.abierto and not p.nota}
    vistos: set[tuple[date, date]] = set()
    unicos: list[Periodo] = []
    for p in sorted(periodos, key=lambda p: (p.inicio, p.abierto, bool(p.nota), not p.referencia)):
        if (p.inicio, p.fin) in vistos or ((p.abierto or p.nota) and p.inicio in firmes):
            continue
        vistos.add((p.inicio, p.fin))
        unicos.append(p)
    return unicos
