"""Auditoría de accesibilidad de MiEvaluador para personas con discapacidad
(Resolución 1519 de 2020 de MinTIC, anexo 1 → WCAG 2.1 nivel AA; también se
reporta WCAG 2.2, sin bloquear).

    python scripts/auditar_accesibilidad.py [--url http://localhost:5173] [--salida informe.json] [--internas]

Por cada pantalla revisa:

- **Ceguera (lector de pantalla):** reglas WCAG de axe-core (nombres
  accesibles, estructura, formularios, ARIA) y el árbol de accesibilidad que
  anuncia un lector de pantalla, guardado como evidencia.
- **Baja visión:** contraste (axe-core); ampliación al 200 % y reflujo a
  320 px sin desplazamiento horizontal (1.4.4 y 1.4.10); espaciado de texto
  aumentado sin que se corte (1.4.12).
- **Daltonismo:** contraste y que el estado no dependa solo del color (axe).
- **Discapacidad motriz (solo teclado):** que cada elemento enfocable muestre
  dónde está el foco (2.4.7) y tamaño mínimo de los objetivos (2.5.8, WCAG 2.2).
- **Sensibilidad al movimiento y discapacidad cognitiva:** que la interfaz
  respete «reducir movimiento» del sistema (2.3.3).

Sin `--internas` revisa las pantallas sin sesión (ingreso y el banco de
previsualización). Con `--internas` (solo en desarrollo) entra también a las
pantallas internas con una cuenta propia de la auditoría: rol «Consulta»
(solo lectura), en la entidad de demostración, con una contraseña aleatoria
nueva en cada corrida que no se imprime. Ese rol no exige segundo factor en
desarrollo, así que no se salta ningún control.

Sale con código 1 si hay infracciones graves o críticas de WCAG 2.1 AA o
fallas de reflujo, ampliación o foco visible.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BACKEND = Path(__file__).resolve().parents[1]
AXE = BACKEND.parent / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
WCAG21 = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]
WCAG22 = ["wcag22aa"]
BLOQUEANTES = {"serious", "critical"}
CORREO_AUDITORIA = "auditoria-accesibilidad@lemartek.local"
CAPTURAS: Path | None = None

PUBLICAS = {"Ingreso": "/", "Previsualización de la revisión": "/#/previsualizacion"}

# Movimiento: si la interfaz anima algo con «reducir movimiento» activo.
JS_ANIMACIONES = """() => [...document.querySelectorAll('*')].filter(e => {
  const s = getComputedStyle(e);
  return (parseFloat(s.animationDuration) > 0.01 && s.animationName !== 'none' && s.animationIterationCount === 'infinite')
}).length"""

# Texto con el espaciado aumentado de WCAG 1.4.12: ¿algún texto queda cortado?
CSS_ESPACIADO = """* { line-height: 1.5 !important; letter-spacing: 0.12em !important;
  word-spacing: 0.16em !important; } p { margin-bottom: 2em !important; }"""
JS_CORTADOS = """() => [...document.querySelectorAll('button, a, label, th, td, h1, h2, h3, p, span')]
  .filter(e => e.offsetParent && getComputedStyle(e).overflow === 'hidden' && e.scrollHeight > e.clientHeight + 2
               && !getComputedStyle(e).textOverflow.includes('ellipsis') && e.innerText.trim())
  .slice(0, 5).map(e => e.innerText.trim().slice(0, 40))"""


def _axe(pagina: Page, etiquetas: list[str]) -> list[dict]:
    pagina.add_script_tag(path=str(AXE))
    resultado = pagina.evaluate(
        "async (e) => await axe.run(document, {runOnly: {type: 'tag', values: e}})", etiquetas
    )
    return [
        {
            "regla": v["id"],
            "impacto": v["impact"],
            "descripcion": v["help"],
            "elementos": [n["target"][0] for n in v["nodes"]][:5],
            "ocurrencias": len(v["nodes"]),
        }
        for v in resultado["violations"]
    ]


def _desborda(pagina: Page) -> int:
    return pagina.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")


# Los elementos más externos que se salen por la derecha (para saber qué arreglar).
JS_QUE_DESBORDA = """() => { const w = document.documentElement.clientWidth;
  const fuera = [...document.querySelectorAll('body *')].filter(e => { const r = e.getBoundingClientRect();
    return r.width && r.right > w + 1 && getComputedStyle(e).position !== 'fixed' });
  const externos = fuera.filter(e => !fuera.includes(e.parentElement));
  const nombre = e => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\\s+/).join('.') : '');
  return externos.slice(0, 4).map(e => nombre(e.parentElement) + ' > ' + nombre(e) + (e.innerText ? ' «' + e.innerText.trim().slice(0, 25) + '»' : '')
    + ' (' + Math.round(e.getBoundingClientRect().right - w) + ' px)') }"""


def _foco_invisible(pagina: Page, maximo: int = 40) -> list[str]:
    """Recorre la pantalla con el tabulador y devuelve los elementos que,
    con el foco puesto, no muestran ningún indicador (contorno ni sombra)."""
    invisibles: list[str] = []
    pagina.evaluate("() => { document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0) }")
    vistos = set()
    for _ in range(maximo):
        pagina.keyboard.press("Tab")
        info = pagina.evaluate(
            """() => { const e = document.activeElement; if (!e || e === document.body) return null;
              const s = getComputedStyle(e);
              const visible = (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || (s.boxShadow && s.boxShadow !== 'none');
              return {id: e.tagName + ':' + (e.innerText || e.getAttribute('aria-label') || e.name || '').trim().slice(0, 30), visible} }"""
        )
        if not info or info["id"] in vistos:
            if info:
                break
            continue
        vistos.add(info["id"])
        # El foco dentro de un iframe de otro origen (reCAPTCHA de Google) no se puede medir desde la página.
        if not info["visible"] and not info["id"].startswith("IFRAME:"):
            invisibles.append(info["id"])
    return invisibles


def revisar(navegador, url: str, nombre: str, preparar=None, contexto=None, arbol: Path | None = None) -> dict:
    ctx = contexto or navegador.new_context()
    datos: dict = {}
    for etiqueta, ancho in (("escritorio", 1366), ("ampliado 200 %", 683), ("reflujo 320 px", 320)):
        pagina = ctx.new_page()
        pagina.set_viewport_size({"width": ancho, "height": 800})
        pagina.emulate_media(reduced_motion="reduce")
        pagina.goto(url, wait_until="networkidle")
        pagina.wait_for_timeout(700)
        if preparar:
            try:
                preparar(pagina)
            except Exception as exc:  # noqa: BLE001 — no poder operar la pantalla ES una falla de accesibilidad
                datos[f"bloqueo_{etiqueta}"] = str(exc).splitlines()[0][:200]
                if CAPTURAS:
                    pagina.screenshot(path=str(CAPTURAS / f"bloqueo_{len(list(CAPTURAS.glob('*.png'))):02d}.png"))
                pagina.close()
                continue
            pagina.wait_for_timeout(700)
        if etiqueta == "escritorio":
            datos["wcag21"] = _axe(pagina, WCAG21)
            datos["wcag22_informativo"] = _axe(pagina, WCAG22)
            datos["foco_invisible"] = _foco_invisible(pagina)
            datos["animaciones_con_movimiento_reducido"] = pagina.evaluate(JS_ANIMACIONES)
            if arbol:
                arbol.write_text(pagina.locator("body").aria_snapshot(), encoding="utf-8")
            pagina.add_style_tag(content=CSS_ESPACIADO)
            pagina.wait_for_timeout(300)
            datos["texto_cortado_con_espaciado"] = pagina.evaluate(JS_CORTADOS)
        else:
            datos[f"desborde_{etiqueta}"] = _desborda(pagina)
            if CAPTURAS and etiqueta.startswith("reflujo"):
                nombre_archivo = "".join(c if c.isalnum() else "_" for c in nombre)[:60]
                pagina.screenshot(path=str(CAPTURAS / f"320px_{nombre_archivo}.png"))
            if datos[f"desborde_{etiqueta}"] > 0:
                datos[f"que_desborda_{etiqueta}"] = pagina.evaluate(JS_QUE_DESBORDA)
        pagina.close()
    if contexto is None:
        ctx.close()
    return datos


def _cuenta_de_auditoria() -> tuple[str, str, str]:
    """Cuenta «Consulta» de la auditoría (solo desarrollo) y la evaluación a revisar."""
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.conf import settings

    if not settings.DEBUG:
        raise SystemExit("Las pantallas internas solo se auditan en desarrollo (DEBUG).")
    from cuentas.aislamiento import SISTEMA, fijar_entidad
    from cuentas.models import Rol, Usuario
    from evaluaciones.models import Evaluacion

    fijar_entidad(SISTEMA)
    demos = Evaluacion.objects.filter(proceso__codigo__istartswith="DEMO-", tipo="juridica", resultados__isnull=False)
    # El respaldo de la entidad de demostración, si existe (preparar_demo_en_vivo).
    evaluacion = (demos.filter(proceso__codigo="DEMO-CM-043-2026", entidad__nit="999000001").first()
                  or demos.select_related("proceso").distinct().first())
    if evaluacion is None:
        raise SystemExit("No hay un proceso DEMO- evaluado: corra manage.py preparar_demo_en_vivo.")
    clave = secrets.token_urlsafe(24)
    usuario = Usuario.objects.filter(email=CORREO_AUDITORIA).first()
    if usuario is None:
        usuario = Usuario.objects.create_user(
            CORREO_AUDITORIA, clave, nombre_completo="Auditoría de accesibilidad (automática)",
            entidad_id=evaluacion.entidad_id, rol=Rol.CONSULTA,
        )
    else:
        usuario.set_password(clave)
        usuario.is_active = True
        usuario.entidad_id = evaluacion.entidad_id
        usuario.save()
    return clave, str(evaluacion.id), evaluacion.proceso.codigo


@contextlib.contextmanager
def instancia_de_auditoria():
    """Backend (8011) y frontend (5180) propios de la auditoría, solo en esta
    máquina, sin reCAPTCHA —como las pruebas automáticas—: el reCAPTCHA de la
    instancia principal frena, con razón, a un navegador automático. La
    principal sigue protegida. Se apagan al terminar."""
    import subprocess
    import time
    import urllib.request

    entorno = {**os.environ, "RECAPTCHA_PROJECT_ID": "", "RECAPTCHA_API_KEY": "", "DJANGO_DEBUG": "1",
               "CORS_ORIGENES": "http://127.0.0.1:5180"}
    uvicorn = BACKEND / "venv" / "bin" / "uvicorn"
    procesos = [
        subprocess.Popen([str(uvicorn), "config.asgi:application", "--host", "127.0.0.1", "--port", "8011"],
                         cwd=BACKEND, env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
        subprocess.Popen(["npx", "vite", "--host", "127.0.0.1", "--port", "5180", "--strictPort"],
                         cwd=BACKEND.parent / "frontend", env={**entorno, "API_DESTINO": "http://127.0.0.1:8011"},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
    ]
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen("http://127.0.0.1:5180/api/auth/csrf", timeout=2)  # nosec B310 (URL local fija)
                break
            except OSError:
                time.sleep(1)
        else:
            raise SystemExit("La instancia de auditoría no arrancó (puertos 8011 y 5180).")
        yield "http://127.0.0.1:5180"
    finally:
        for proceso in procesos:
            proceso.terminate()
        for proceso in procesos:
            try:
                proceso.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proceso.kill()


def _entrar(contexto, url: str, clave: str) -> None:
    pagina = contexto.new_page()
    pagina.goto(url, wait_until="networkidle")
    pagina.get_by_label("Correo electrónico").fill(CORREO_AUDITORIA)
    pagina.get_by_label("Contraseña", exact=True).fill(clave)
    pagina.get_by_role("button", name="Entrar").click()
    pagina.wait_for_load_state("networkidle")
    pagina.wait_for_timeout(1000)
    if pagina.get_by_label("Correo electrónico").count():
        aviso = pagina.locator("[role=alert]").all_inner_texts()
        raise SystemExit(f"No se pudo entrar con la cuenta de la auditoría: {' '.join(aviso) or pagina.url}")
    pagina.close()


def _paso(nombre: str):
    def ir(pagina: Page) -> None:
        boton = pagina.get_by_role("button", name=nombre).first  # el nombre accesible incluye el del paso
        if boton.is_enabled():  # el paso actual está deshabilitado: ya se está en él
            boton.click()
    return ir


def _abrir_proponente(pagina: Page) -> None:
    _paso("Evaluación y revisión")(pagina)
    pagina.wait_for_timeout(800)
    pagina.get_by_text("P-01", exact=True).first.click()


def auditar(url: str, internas: bool, carpeta_arboles: Path | None, url_internas: str = "") -> dict:
    informe: dict = {"norma": "WCAG 2.1 AA (Res. 1519 de 2020)", "pantallas": {}}
    # Antes de abrir el navegador: Playwright corre su propio bucle asíncrono y
    # Django no deja consultar la base desde ahí.
    cuenta = _cuenta_de_auditoria() if internas else None
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        for nombre, ruta in PUBLICAS.items():
            informe["pantallas"][nombre] = revisar(navegador, url + ruta, nombre)
        if cuenta:
            clave, evaluacion_id, codigo = cuenta
            cuenta = None
            url = url_internas
            contexto = navegador.new_context()
            _entrar(contexto, url, clave)
            del clave
            ev = f"{url}/evaluaciones/{evaluacion_id}"
            internas_ = {
                "Mis evaluaciones": (url + "/", None),
                "Procesos": (url + "/procesos", None),
                "Acerca del sistema": (url + "/acerca", None),
                f"{codigo} · Datos del proceso": (ev, _paso("Datos del proceso")),
                f"{codigo} · Evaluación y revisión": (ev, _paso("Evaluación y revisión")),
                f"{codigo} · Panel de un proponente": (ev, _abrir_proponente),
                f"{codigo} · Control de la verificación": (ev, _paso("Control de la verificación")),
                f"{codigo} · Informe": (ev, _paso("Informe")),
            }
            for nombre, (destino, preparar) in internas_.items():
                arbol = carpeta_arboles / f"lector_{len(informe['pantallas']):02d}.txt" if carpeta_arboles else None
                informe["pantallas"][nombre] = revisar(navegador, destino, nombre, preparar, contexto, arbol)
            contexto.close()
        navegador.close()
    return informe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:5173")
    parser.add_argument("--salida")
    parser.add_argument("--internas", action="store_true", help="Auditar también las pantallas con sesión (solo desarrollo)")
    args = parser.parse_args()
    global CAPTURAS
    arboles = Path(args.salida).parent / "lector_de_pantalla" if args.salida else None
    if arboles:
        arboles.mkdir(parents=True, exist_ok=True)
        CAPTURAS = Path(args.salida).parent / "capturas"
        CAPTURAS.mkdir(exist_ok=True)
    if args.internas:
        with instancia_de_auditoria() as url_internas:
            informe = auditar(args.url.rstrip("/"), True, arboles, url_internas)
    else:
        informe = auditar(args.url.rstrip("/"), False, arboles)

    fallas = 0
    for pantalla, d in informe["pantallas"].items():
        graves = [v for v in d.get("wcag21", []) if v["impacto"] in BLOQUEANTES]
        desbordes = {k: v for k, v in d.items() if k.startswith("desborde_") and v > 0}
        bloqueos = {k: v for k, v in d.items() if k.startswith("bloqueo_")}
        fallas += len(graves) + len(desbordes) + len(d.get("foco_invisible", [])) + len(bloqueos)
        estado = "OK" if not (graves or desbordes or d.get("foco_invisible") or bloqueos) else "FALLAS"
        print(f"\n{pantalla}: {estado}")
        for v in d.get("wcag21", []):
            print(f"  [WCAG 2.1 {v['impacto']}] {v['regla']} ({v['ocurrencias']}): {v['descripcion']} — {', '.join(v['elementos'])}")
        for v in d.get("wcag22_informativo", []):
            print(f"  [WCAG 2.2, informativo] {v['regla']} ({v['ocurrencias']}): {v['descripcion']}")
        for k, v in bloqueos.items():
            print(f"  [baja visión / motriz] no se pudo operar la pantalla ({k.replace('bloqueo_', '')}): {v}")
        for k, v in desbordes.items():
            print(f"  [baja visión] {k.replace('desborde_', '')}: {v} px de desplazamiento horizontal "
                  f"— {', '.join(d.get('que_' + k.replace('desborde_', 'desborda_'), []))}")
        if d.get("foco_invisible"):
            print(f"  [teclado] foco invisible en: {', '.join(d['foco_invisible'][:5])}")
        if d.get("texto_cortado_con_espaciado"):
            print(f"  [baja visión, revisar] texto cortado con espaciado aumentado: {d['texto_cortado_con_espaciado']}")
        if d.get("animaciones_con_movimiento_reducido"):
            print(f"  [movimiento] {d['animaciones_con_movimiento_reducido']} animaciones continuas con «reducir movimiento»")
    if args.salida:
        Path(args.salida).write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFallas bloqueantes: {fallas}")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
