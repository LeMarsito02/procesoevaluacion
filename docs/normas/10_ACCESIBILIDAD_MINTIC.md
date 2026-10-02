# Accesibilidad de MiEvaluador

**Código:** CAL-ACC-10 · **Versión:** 1.0 · **Fecha:** 2/10/2026
**Normas:** Resolución 1519 de 2020 de MinTIC, anexo 1 (accesibilidad web), que remite a **WCAG 2.1 nivel AA** · ISO/IEC 25010 (capacidad de interacción: inclusividad)

## 1. Por qué aplica
Las entidades públicas deben cumplir los estándares de accesibilidad de MinTIC en sus sedes electrónicas y sistemas. MiEvaluador lo usan servidores públicos, y cualquiera de ellos puede tener una discapacidad visual, motriz o cognitiva.

## 2. Auditoría automática
```
python Backend/scripts/auditar_accesibilidad.py --salida informe.json
```
Abre cada pantalla en Chromium, a tamaño de escritorio (1366 px) y de celular (390 px), y la revisa con **axe-core** contra las reglas de WCAG 2.0 y 2.1, niveles A y AA. Revisa las pantallas que no exigen sesión: el ingreso y el banco de previsualización, que muestra los componentes de revisión (panel del proponente, visor de documentos, detalle técnico y financiero) con datos inventados. Sale con error si hay infracciones graves o críticas.

**Resultado del 2/10/2026:** 0 infracciones en las 4 combinaciones (25 a 27 reglas aprobadas en cada una).

La revisión automática cubre más o menos un tercio de los criterios de WCAG. El resto se verifica a mano (sección 3).

## 3. Lista de verificación manual (WCAG 2.1 AA)

| Criterio | Qué se exige | Estado | Cómo se cumple |
|---|---|---|---|
| 1.1.1 Contenido no textual | Texto alternativo en imágenes | Cumple | Imágenes decorativas con `alt=""`; iconos de botones con `aria-label` |
| 1.3.1 Información y relaciones | Estructura semántica | Cumple | `main`, `header`, `nav`, encabezados y etiquetas en los formularios |
| 1.4.3 Contraste mínimo | 4,5:1 en texto | Cumple (automático) | axe-core sin infracciones de contraste |
| 1.4.4 Cambio de tamaño | Usable al 200 % | Por verificar | Diseño adaptable hasta 390 px de ancho |
| 1.4.10 Reflujo | Sin desplazamiento horizontal a 320 px | Por verificar | Revisado a 390 px (sin infracciones); falta verificar a 320 px |
| 1.4.11 Contraste de componentes | 3:1 en controles y foco | Cumple | Contorno de foco visible de 3 px |
| 2.1.1 Teclado | Todo se puede hacer con teclado | Cumple en lo revisado | Orden de tabulación lógico en el ingreso y la revisión |
| 2.1.2 Sin trampas de teclado | Se puede salir de cualquier diálogo | Cumple | Los diálogos retienen el foco mientras están abiertos y lo devuelven al cerrarse (`useDialogo`); el visor se cierra con Escape |
| 2.4.1 Evitar bloques | Saltar la navegación repetida | Cumple | Enlace «Saltar al contenido principal» (desde el 2/10/2026) |
| 2.4.2 Título de página | Título descriptivo | Cumple dentro de los procesos | El título dice el paso y el código del proceso (desde el 2/10/2026); en las demás pantallas, «MiEvaluador» |
| 2.4.3 Orden del foco | Orden lógico | Cumple en lo revisado | |
| 2.4.7 Foco visible | Se ve dónde está el foco | Cumple | `:focus-visible` en toda la interfaz |
| 3.1.1 Idioma de la página | Idioma declarado | Cumple | `<html lang="es">` |
| 3.3.1 y 3.3.2 Errores y etiquetas | Errores identificados, campos con etiqueta | Cumple | Mensajes en texto y `role="alert"` |
| 4.1.2 Nombre, función, valor | Controles accesibles a lectores de pantalla | Cumple en lo revisado | `aria-label`, `aria-expanded`, `aria-current` |
| 4.1.3 Mensajes de estado | Avisos anunciados | Cumple | Avisos y estados de carga con `role="status"` |

## 4. Pendientes
1. Recorrer las pantallas internas (lista de procesos, evaluación, informe) con un lector de pantalla (NVDA u Orca) y con zoom al 200 %.
2. Título propio en las pantallas fuera de un proceso (lista de procesos, equipo, configuración).
3. Extender la auditoría automática a las pantallas internas con una cuenta de prueba en un entorno de pruebas, sin saltarse el segundo factor.
