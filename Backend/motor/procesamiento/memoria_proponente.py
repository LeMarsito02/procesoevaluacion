"""Memoria de trabajo de UN proponente dentro de un worker.

Evaluar los 18 requisitos de un proponente implica descomprimir su zip y
leer sus PDF. Antes cada requisito lo hacía desde cero (18 veces el mismo
zip, las mismas páginas, la misma búsqueda del Formato 1...). Aquí se guarda
lo ya calculado mientras se sigue trabajando con el mismo proponente, y se
libera apenas se pasa al siguiente, para no acumular memoria en el worker."""
from __future__ import annotations

import functools
from collections.abc import Callable
from typing import TypeVar

R = TypeVar("R")


class PdfsProponente(dict):
    """dict {ruta_en_zip: bytes_del_pdf} que además lleva la memoria de las
    búsquedas ya hechas sobre esos mismos PDF (ver `memo_por_pdfs`)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.memo: dict = {}


def memo_por_pdfs(func: Callable[..., R]) -> Callable[..., R]:
    """Memoriza `func(pdfs, *args)` dentro del PdfsProponente recibido. Si
    `pdfs` es un dict normal (ej. en pruebas) simplemente llama a la función.
    Solo para funciones puras sobre los PDF cuyo resultado no se modifica
    después: el mismo objeto se devuelve a todos los requisitos."""

    @functools.wraps(func)
    def envoltura(pdfs, *args):
        memo = getattr(pdfs, "memo", None)
        if memo is None:
            return func(pdfs, *args)
        clave = (func.__module__, func.__qualname__, args)
        if clave not in memo:
            memo[clave] = func(pdfs, *args)
        return memo[clave]

    return envoltura
