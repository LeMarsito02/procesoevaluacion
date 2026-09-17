"""Criterios de evaluación configurables por entidad.

Una *definición de evaluación* dice qué requisitos se piden, con qué número y
nombre, con qué verificación del motor (o con qué bloques, si es un requisito
nuevo) y con qué parámetros (vigencias, beneficiario, sigla…). Los valores por
defecto reproducen exactamente la evaluación jurídica del ICCU con la que se
midió el acierto del programa.

Los evaluadores leen los parámetros con `valor(...)`; el orquestador los fija
con `usar(...)` antes de evaluar cada proponente (cada worker evalúa uno a la
vez, así que el contexto no se mezcla entre proponentes).
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# --- Parámetros ---
@dataclass(frozen=True)
class Parametro:
    clave: str
    nombre: str
    descripcion: str
    defecto: Any
    tipo: Literal["entero", "texto", "lista_texto"]
    minimo: int | None = None
    maximo: int | None = None
    unidad: str = ""
    requisitos: tuple[str, ...] = field(default_factory=tuple)


PARAMETROS: dict[str, Parametro] = {
    p.clave: p
    for p in (
        Parametro(
            "copnia_meses",
            "Antigüedad máxima del COPNIA",
            "Meses contados hacia atrás desde la fecha de cierre.",
            3,
            "entero",
            1,
            24,
            "meses",
            ("juridica.aval_ingeniero", "juridica.copnia_antecedentes"),
        ),
        Parametro(
            "camara_meses",
            "Vigencia máxima de los certificados de Cámara de Comercio",
            "Certificado de existencia y RUP: meses de expedición antes del cierre.",
            1,
            "entero",
            1,
            12,
            "meses",
            ("juridica.existencia", "juridica.rup"),
        ),
        Parametro(
            "prefijo_codigo",
            "Sigla de la entidad en el código del proceso",
            "Se acepta el código con o sin esta sigla (ej. ICCU-CM-037-2026 o CM-037-2026).",
            "ICCU",
            "texto",
            requisitos=("juridica.carta",),
        ),
        Parametro(
            "beneficiario_claves",
            "Beneficiario de la póliza",
            "Siglas o nombres de la entidad que deben aparecer como beneficiario de la garantía.",
            ["ICCU", "INSTITUTO DE CAMINOS"],
            "lista_texto",
            requisitos=("juridica.garantia",),
        ),
    )
}

_ACTUALES: dict[str, Any] = {}


def valor(clave: str) -> Any:
    """Valor vigente del parámetro (el de la entidad o el por defecto)."""
    return _ACTUALES.get(clave, PARAMETROS[clave].defecto)


@contextmanager
def usar(parametros: dict[str, Any] | None) -> Iterator[None]:
    global _ACTUALES
    anteriores = _ACTUALES
    _ACTUALES = {k: v for k, v in (parametros or {}).items() if k in PARAMETROS}
    try:
        yield
    finally:
        _ACTUALES = anteriores


def huella_parametros() -> str | None:
    """Para la clave de caché: None si todo está en su valor por defecto (así
    los resultados ya calculados con los criterios del ICCU siguen sirviendo)."""
    distintos = {k: v for k, v in _ACTUALES.items() if v != PARAMETROS[k].defecto}
    if not distintos:
        return None
    return hashlib.sha256(json.dumps(distintos, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


# --- Verificaciones del motor ---
GRUPOS: dict[str, str] = {
    "oferta": "Documentos de la oferta",
    "camara": "Cámara de Comercio",
    "antecedentes": "Antecedentes",
    "adicionales": "Requisitos adicionales",
}


@dataclass(frozen=True)
class Verificacion:
    clave: str
    tipo: str
    numero_interno: int
    corto: str
    titulo: str
    verifica: str
    grupo: str
    pistas: tuple[str, ...] = ()


VERIFICACIONES: dict[str, Verificacion] = {
    v.clave: v
    for v in (
        Verificacion("juridica.carta", "juridica", 1, "Carta", "Carta de presentación de la oferta",
                     "Formato 1 firmado por el representante legal, con el número del proceso, el objeto y los lotes.",
                     "oferta", ("carta", "formato 1", "presentac")),
        Verificacion("juridica.aval_ingeniero", "juridica", 2, "Aval ing.", "Suscrita o avalada por ingeniero",
                     "Firma o aval de un ingeniero con matrícula vigente (COPNIA dentro de la antigüedad máxima).",
                     "oferta", ("copnia", "matricula", "tarjeta", "aval", "vigencia")),
        Verificacion("juridica.copnia_antecedentes", "juridica", 3, "COPNIA", "Antecedentes disciplinarios del ingeniero",
                     "El COPNIA del ingeniero certifica que no tiene antecedentes disciplinarios.",
                     "oferta", ("copnia", "antecedentes", "vigencia")),
        Verificacion("juridica.plural", "juridica", 4, "Plural", "Conformación de proponente plural",
                     "Formato 2 con integrantes, porcentajes que suman 100% y representante designado.",
                     "oferta", ("formato 2", "consorci", "union temporal", "conformac")),
        Verificacion("juridica.redam", "juridica", 5, "REDAM", "Deudores alimentarios morosos (REDAM)",
                     "El representante legal no está inscrito en el REDAM.",
                     "antecedentes", ("redam", "deudor", "alimentari")),
        Verificacion("juridica.existencia", "juridica", 6, "Existencia", "Certificado de existencia y representación legal",
                     "Expedido dentro de la vigencia máxima antes de la fecha de cierre.",
                     "camara", ("existencia", "camara", "rep legal", "representacion")),
        Verificacion("juridica.objeto_social", "juridica", 7, "Objeto", "Objeto social",
                     "El objeto social se relaciona con el objeto del proceso.",
                     "camara", ("existencia", "camara", "representacion")),
        Verificacion("juridica.facultades", "juridica", 8, "Facultades", "Facultades del representante legal",
                     "Sin límites de cuantía ni autorizaciones pendientes para contratar.",
                     "camara", ("existencia", "camara", "representacion", "acta", "autoriza")),
        Verificacion("juridica.rup", "juridica", 9, "RUP", "Registro Único de Proponentes (RUP)",
                     "Expedido dentro de la vigencia máxima antes de la fecha de cierre.",
                     "camara", ("rup", "proponente")),
        Verificacion("juridica.sanciones_rup", "juridica", 10, "Sanciones", "Multas y sanciones en el RUP",
                     "El RUP no reporta multas ni sanciones en firme.",
                     "camara", ("rup", "proponente")),
        Verificacion("juridica.garantia", "juridica", 11, "Póliza", "Garantía de seriedad de la oferta",
                     "Beneficiario la entidad, vigencia hasta la fecha mínima y valor asegurado según el lote más caro al que se presenta.",
                     "oferta", ("poliza", "póliza", "garantia", "garantía", "seriedad", "seguro")),
        Verificacion("juridica.seguridad_social", "juridica", 12, "Seg. social", "Pago de seguridad social y aportes",
                     "Formato firmado por el representante legal o revisor fiscal (uno por integrante si es plural).",
                     "oferta", ("formato 5", "seguridad social", "parafiscal", "aportes")),
        Verificacion("juridica.contraloria", "juridica", 14, "Contraloría", "Responsabilidad fiscal (Contraloría)",
                     "No reportado en el Boletín de Responsables Fiscales.",
                     "antecedentes", ("contralor", "fiscal")),
        Verificacion("juridica.procuraduria", "juridica", 15, "Procuraduría", "Antecedentes disciplinarios (Procuraduría)",
                     "No registra sanciones ni inhabilidades vigentes.",
                     "antecedentes", ("procuradur", "disciplinari")),
        Verificacion("juridica.policia", "juridica", 16, "Policía", "Antecedentes judiciales (Policía)",
                     "No tiene asuntos pendientes con las autoridades judiciales.",
                     "antecedentes", ("policia", "policía", "judicial", "penal")),
        Verificacion("juridica.rnmc", "juridica", 17, "RNMC", "Medidas correctivas (RNMC)",
                     "No tiene medidas correctivas pendientes por cumplir.",
                     "antecedentes", ("rnmc", "medidas correctivas", "correctiva")),
        Verificacion("juridica.revisor_fiscal", "juridica", 18, "Rev. fiscal", "Certificado de revisor fiscal",
                     "Aplica solo a sociedades anónimas: indica si es abierta o cerrada.",
                     "camara", ("revisor", "existencia")),
    )
}

VERIFICACION_POR_NUMERO_INTERNO = {v.numero_interno: v for v in VERIFICACIONES.values()}
PERSONALIZADO = "personalizado"


# --- Requisitos nuevos armados con bloques ---
TIPOS_PROPONENTE = ("persona_natural", "persona_juridica", "consorcio", "union_temporal")


class Bloque(BaseModel):
    """Una comprobación sobre el documento encontrado."""

    tipo: Literal["vigencia_maxima", "contiene", "no_contiene", "menciona_representante", "menciona_proponente"]
    meses: int | None = Field(None, ge=1, le=120)
    frases: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coherente(self) -> "Bloque":
        if self.tipo == "vigencia_maxima" and not self.meses:
            raise ValueError("La vigencia máxima necesita el número de meses.")
        if self.tipo in ("contiene", "no_contiene"):
            self.frases = [f.strip() for f in self.frases if f and f.strip()]
            if not self.frases:
                raise ValueError("Indique al menos una frase a buscar.")
        return self


class ConfigPersonalizado(BaseModel):
    # El documento se reconoce si en sus primeras páginas aparece alguna de estas frases.
    frases_documento: list[str] = Field(min_length=1)
    paginas: int = Field(3, ge=1, le=20)
    bloques: list[Bloque] = Field(default_factory=list)
    # Vacío = aplica a todos los proponentes.
    aplica_a: list[Literal["persona_natural", "persona_juridica", "consorcio", "union_temporal"]] = Field(default_factory=list)

    @field_validator("frases_documento")
    @classmethod
    def _limpiar(cls, v: list[str]) -> list[str]:
        limpias = [f.strip() for f in v if f and f.strip()]
        if not limpias:
            raise ValueError("Indique al menos una frase que identifique el documento.")
        return limpias


class RequisitoDefinicion(BaseModel):
    numero: int = Field(ge=1, le=999)
    titulo: str = Field(min_length=3, max_length=200)
    corto: str = Field(min_length=1, max_length=20)
    grupo: str = "adicionales"
    verificacion: str
    verifica: str = ""
    # Fila del Excel donde va este requisito (si no, se usa el mapeo de la plantilla).
    fila_excel: int | None = Field(None, ge=1, le=10000)
    config: ConfigPersonalizado | None = None

    @model_validator(mode="after")
    def _verificacion_valida(self) -> "RequisitoDefinicion":
        if self.verificacion == PERSONALIZADO:
            if self.config is None:
                raise ValueError(f"El requisito {self.numero} necesita su configuración de bloques.")
        elif self.verificacion not in VERIFICACIONES:
            raise ValueError(f"Verificación desconocida: {self.verificacion}")
        if self.grupo not in GRUPOS:
            self.grupo = "adicionales"
        return self


class DefinicionEvaluacion(BaseModel):
    parametros: dict[str, Any] = Field(default_factory=dict)
    requisitos: list[RequisitoDefinicion] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validar(self) -> "DefinicionEvaluacion":
        numeros = [r.numero for r in self.requisitos]
        repetidos = sorted({n for n in numeros if numeros.count(n) > 1})
        if repetidos:
            raise ValueError(f"Números de requisito repetidos: {', '.join(map(str, repetidos))}.")
        limpios: dict[str, Any] = {}
        for clave, v in self.parametros.items():
            p = PARAMETROS.get(clave)
            if p is None:
                continue
            if p.tipo == "entero":
                if not isinstance(v, int) or isinstance(v, bool) or (p.minimo is not None and v < p.minimo) or (p.maximo is not None and v > p.maximo):
                    raise ValueError(f"«{p.nombre}» debe ser un número entre {p.minimo} y {p.maximo}.")
            elif p.tipo == "texto":
                if not isinstance(v, str):
                    raise ValueError(f"«{p.nombre}» debe ser texto.")
                v = v.strip()
            elif p.tipo == "lista_texto":
                if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                    raise ValueError(f"«{p.nombre}» debe ser una lista de textos.")
                v = [x.strip() for x in v if x.strip()]
                if not v:
                    raise ValueError(f"«{p.nombre}» no puede quedar vacío.")
            limpios[clave] = v
        self.parametros = limpios
        return self


def definicion_sistema(tipo: str) -> DefinicionEvaluacion:
    """Definición base del sistema: la evaluación jurídica del ICCU (sin RUT),
    con el mismo orden y numeración de su plantilla de Excel."""
    if tipo != "juridica":
        return DefinicionEvaluacion()
    requisitos = [
        RequisitoDefinicion(
            numero=v.numero_interno,
            titulo=v.titulo,
            corto=v.corto,
            grupo=v.grupo,
            verificacion=v.clave,
            verifica=v.verifica,
        )
        for v in VERIFICACIONES.values()
        if v.tipo == "juridica"
    ]
    return DefinicionEvaluacion(parametros={}, requisitos=requisitos)
