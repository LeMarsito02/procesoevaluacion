"""Coincidencias entre las ofertas de un mismo proceso (RF-14): insumo para
prevenir prácticas colusorias, no una decisión.

Señales:
- documentos idénticos (mismo contenido byte a byte) en ofertas distintas;
- la misma persona (por cédula, o por nombre completo) en ofertas distintas:
  representantes, suplentes, integrantes;
- el mismo NIT de una empresa integrante en dos ofertas;
- el mismo profesional (matrícula) propuesto por dos oferentes;
- el mismo correo, teléfono o dirección de notificación.

Un documento idéntico en casi todas las ofertas suele ser un formato en blanco
del pliego: se informa aparte y no cuenta como alerta.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class DatosOferta:
    clave: str  # identificador del proponente
    nombre: str
    archivos: dict[str, bytes] = field(default_factory=dict)  # ruta → contenido
    personas: list[tuple[str, str | None, str]] = field(default_factory=list)  # (nombre, documento, rol)
    empresas: list[tuple[str, str]] = field(default_factory=list)  # (nombre, NIT)
    matriculas: list[tuple[str, str]] = field(default_factory=list)  # (nombre, matrícula)
    texto_contacto: str = ""  # carta de presentación: correos, teléfonos, direcciones


@dataclass
class Coincidencia:
    tipo: str  # documento · persona · empresa · profesional · correo · telefono · direccion
    valor: str
    ofertas: list[str]
    detalle: str = ""


@dataclass
class Resultado:
    coincidencias: list[Coincidencia] = field(default_factory=list)
    # Documentos que comparten casi todas las ofertas (formatos del pliego).
    comunes: list[Coincidencia] = field(default_factory=list)


def _plano(t: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().upper()).strip()


def _digitos(t: str | None) -> str:
    return re.sub(r"\D", "", t or "")


_CORREO_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_TELEFONO_RE = re.compile(r"(?<!\d)(?:\+?57[\s-]?)?((?:3\d{2}|60\d)[\s.-]?\d{3}[\s.-]?\d{4})(?!\d)")
_DIRECCION_RE = re.compile(
    r"\b(?:CALLE|CL|CARRERA|CRA|KR|KRA|CARR|AVENIDA|AV|AK|AC|DIAGONAL|DG|TRANSVERSAL|TV)\.?\s*(\d{1,3}\s?[A-Z]?)\s*(?:BIS\s*)?(?:N[O°º.]*|#)\s*(\d{1,3}\s?[A-Z]?)\s*-\s*(\d{1,3})"
)
_TIPO_VIA = {"CL": "CALLE", "CRA": "CARRERA", "KR": "CARRERA", "KRA": "CARRERA", "CARR": "CARRERA", "AV": "AVENIDA", "DG": "DIAGONAL", "TV": "TRANSVERSAL"}
# Correos genéricos de servicios que no identifican a nadie.
_CORREOS_COMUNES = re.compile(r"@(?:secop|colombiacompra|iccu|cundinamarca)\.", re.I)


def contactos(texto: str) -> dict[str, set[str]]:
    t = _plano(texto)
    correos = {c.lower() for c in _CORREO_RE.findall(texto or "") if not _CORREOS_COMUNES.search(c)}
    telefonos = {_digitos(m)[-10:] for m in _TELEFONO_RE.findall(t)}
    direcciones = set()
    for m in _DIRECCION_RE.finditer(t):
        via = m.group(0).split()[0].rstrip(".")
        direcciones.add(f"{_TIPO_VIA.get(via, via)} {m.group(1).replace(' ', '')} # {m.group(2).replace(' ', '')}-{m.group(3)}")
    return {"correo": correos, "telefono": telefonos, "direccion": direcciones}


def buscar(ofertas: list[DatosOferta]) -> Resultado:
    r = Resultado()
    if len(ofertas) < 2:
        return r
    nombre = {o.clave: o.nombre for o in ofertas}

    def agrupar(tipo: str, pares: dict[str, set[str]], detalle: dict[str, str] | None = None) -> None:
        for valor, claves in pares.items():
            if len(claves) > 1:
                r.coincidencias.append(Coincidencia(tipo, valor, sorted(claves, key=list(nombre).index), (detalle or {}).get(valor, "")))

    # Documentos idénticos.
    por_huella: dict[str, set[str]] = defaultdict(set)
    nombres_archivo: dict[str, set[str]] = defaultdict(set)
    for o in ofertas:
        for ruta, contenido in o.archivos.items():
            if len(contenido) < 2048:
                continue  # archivos casi vacíos no dicen nada
            h = hashlib.sha256(contenido).hexdigest()
            por_huella[h].add(o.clave)
            nombres_archivo[h].add(ruta.rsplit("/", 1)[-1])
    umbral_comun = max(3, int(len(ofertas) * 0.6 + 0.999))
    for h, claves in por_huella.items():
        if len(claves) < 2:
            continue
        c = Coincidencia("documento", h[:12], sorted(claves, key=list(nombre).index), " · ".join(sorted(nombres_archivo[h]))[:300])
        (r.comunes if len(claves) >= umbral_comun and len(ofertas) > 2 else r.coincidencias).append(c)

    personas_doc: dict[str, set[str]] = defaultdict(set)
    personas_nombre: dict[str, set[str]] = defaultdict(set)
    detalle_persona: dict[str, str] = {}
    for o in ofertas:
        for nombre_p, documento, rol in o.personas:
            d = _digitos(documento)
            if len(d) >= 6:
                personas_doc[d].add(o.clave)
                detalle_persona[d] = f"{nombre_p} ({rol})"
            n = _plano(nombre_p)
            if len(n.split()) >= 3:
                personas_nombre[n].add(o.clave)
    agrupar("persona", personas_doc, detalle_persona)
    # Por nombre solo si no se cruzó ya por cédula.
    ya = {frozenset(c.ofertas) for c in r.coincidencias if c.tipo == "persona"}
    agrupar("persona", {n: c for n, c in personas_nombre.items() if frozenset(c) not in ya}, {n: "Mismo nombre completo" for n in personas_nombre})

    empresas: dict[str, set[str]] = defaultdict(set)
    detalle_empresa: dict[str, str] = {}
    for o in ofertas:
        for nombre_e, nit in o.empresas:
            d = _digitos(nit)[:9]
            if len(d) >= 8:
                empresas[d].add(o.clave)
                detalle_empresa[d] = nombre_e
    agrupar("empresa", empresas, detalle_empresa)

    matriculas: dict[str, set[str]] = defaultdict(set)
    detalle_mat: dict[str, str] = {}
    for o in ofertas:
        for nombre_p, matricula in o.matriculas:
            m = re.sub(r"[^0-9A-Z]", "", (matricula or "").upper())
            if len(m) >= 5:
                matriculas[m].add(o.clave)
                detalle_mat[m] = nombre_p
    agrupar("profesional", matriculas, detalle_mat)

    for tipo in ("correo", "telefono", "direccion"):
        pares: dict[str, set[str]] = defaultdict(set)
        for o in ofertas:
            for valor in contactos(o.texto_contacto)[tipo]:
                pares[valor].add(o.clave)
        agrupar(tipo, pares)
    return r
