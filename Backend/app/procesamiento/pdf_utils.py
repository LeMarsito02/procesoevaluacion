from __future__ import annotations

import io

import pdfplumber


def extraer_texto(contenido: bytes, max_paginas: int | None = None) -> str:
    """Extrae el texto de un PDF liberando el caché pesado de cada página
    (curvas, rects, layout) apenas se usa, con `page.flush_cache()`.

    Sin esto, pdfplumber puede consumir cientos de MB extra en documentos
    con muchas páginas y gráficos vectoriales — muy común en certificados
    oficiales con marca de agua/fondo de seguridad (RUP, Cámara de
    Comercio, pólizas). Se confirmó con un RUP real de 52 páginas: sin
    `flush_cache()` el proceso subía +255MB solo por ese documento; con
    `flush_cache()` por página, +110MB — y esa memoria nunca se libera
    sola porque los workers se reutilizan entre peticiones, así que con
    varios proponentes grandes en la misma corrida el ahorro se
    multiplica en vez de perderse."""
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        paginas = pdf.pages[:max_paginas] if max_paginas is not None else pdf.pages
        partes = []
        for page in paginas:
            partes.append(page.extract_text() or "")
            page.flush_cache()
        return "\n".join(partes)


def buscar_pagina(contenido: bytes, coincide, max_paginas: int = 6) -> str | None:
    """Recorre las primeras páginas del PDF y devuelve el texto leído hasta
    la primera página en la que se cumple `coincide(texto)`, o None.

    Va página por página y corta apenas encuentra, en vez de leer todo el
    documento de una: así el caso común (el título en la página 1) sigue
    costando lo mismo que antes, pero se alcanzan también los documentos que
    traen una carátula con el membrete de la empresa antes del certificado
    —se confirmó con proponentes reales cuyo Certificado de Existencia
    empieza en la página 2 y antes quedaban como "no encontrado".

    La condición se evalúa sobre el texto ACUMULADO de las páginas leídas
    hasta ese momento, no sobre cada página suelta: hay certificados (RUP de
    Bucaramanga) con el título en la carátula y la fecha de expedición en la
    página siguiente."""
    partes: list[str] = []
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for page in pdf.pages[:max_paginas]:
            partes.append(page.extract_text() or "")
            page.flush_cache()
            acumulado = "\n".join(partes)
            if coincide(acumulado):
                return acumulado
    return None
