# Accesibilidad de MiEvaluador para personas con discapacidad

**Código:** CAL-ACC-10 · **Versión:** 1.1 · **Fecha:** 2/10/2026
**Normas:** Resolución 1519 de 2020 de MinTIC, anexo 1 (accesibilidad web), que remite a **WCAG 2.1 nivel AA** · se reporta también WCAG 2.2 · ISO/IEC 25010 (capacidad de interacción: inclusividad)

## 1. Por qué aplica
Las entidades públicas deben cumplir los estándares de accesibilidad de MinTIC en sus sedes electrónicas y sistemas. MiEvaluador lo usan servidores públicos, y cualquiera puede tener una discapacidad visual, motriz, auditiva o cognitiva.

## 2. Cómo se audita
```
python Backend/scripts/auditar_accesibilidad.py --internas --salida evidencias/AAAA-MM-DD/accesibilidad/informe.json
```
(Lo corre también `Backend/scripts/auditar_calidad.sh`.)

- **Pantallas revisadas (10):** ingreso, banco de previsualización, Mis evaluaciones, Procesos, Acerca del sistema y, en un proceso real de demostración, Datos del proceso, Evaluación y revisión, Panel de un proponente, Control de la verificación e Informe.
- **Tamaños:** escritorio (1366 px), ampliación al 200 % (683 px) y reflujo a 320 px (una pantalla de 1280 px al 400 %).
- **Cómo entra a las pantallas internas sin saltarse controles:**
  - usa su propia cuenta de solo lectura (rol «Consulta»), con una contraseña aleatoria nueva en cada corrida que no se imprime;
  - corre en una instancia aparte, solo en esta máquina y solo en desarrollo, sin reCAPTCHA, como las pruebas automáticas;
  - la instancia principal sigue protegida.
- **Evidencia:**
  - el informe JSON;
  - el árbol de accesibilidad de cada pantalla (lo que anuncia un lector de pantalla), en `lector_de_pantalla/`;
  - capturas a 320 px, en `capturas/`.

## 3. Resultado por tipo de discapacidad (2/10/2026)

| Discapacidad | Qué se verifica | Criterios | Resultado |
|---|---|---|---|
| **Ceguera** (lector de pantalla) | Nombres accesibles de botones, enlaces y campos; estructura (encabezados, regiones, tablas); ARIA válido; avisos anunciados; enlace para saltar la navegación; título de cada pantalla | 1.1.1, 1.3.1, 2.4.1, 2.4.2, 4.1.2, 4.1.3 | **Cumple** en las 10 pantallas. Corregido: los pasos de la barra se anunciaban «3» en vez de «Paso 3: Control de la verificación»; el menú del usuario leía las iniciales del avatar |
| **Baja visión** | Contraste de texto y componentes; uso al 200 %; reflujo a 320 px sin desplazamiento horizontal; espaciado de texto aumentado sin cortes | 1.4.3, 1.4.4, 1.4.10, 1.4.11, 1.4.12 | **Cumple** en las 10 pantallas. Corregido: contraste de las etiquetas «Cumple» (4,35 → 5,2:1) y «No aplica» (3,7 → 5,3:1); desbordamiento a 320 px en 6 pantallas; a 320 px el avatar tapaba los pasos y no se podían pulsar |
| **Daltonismo** | Contraste suficiente; el estado no depende solo del color | 1.4.1, 1.4.3 | **Cumple:** cada estado lleva texto («Cumple», «Revisar», «No cumple») además del color |
| **Discapacidad motriz** (solo teclado) | Todo operable con teclado; foco siempre visible; sin trampas de teclado; orden lógico; tamaño mínimo de los objetivos (WCAG 2.2) | 2.1.1, 2.1.2, 2.4.3, 2.4.7, 2.5.8 | **Cumple:** foco visible en todos los elementos recorridos (el iframe de reCAPTCHA es de Google y no se puede medir); diálogos que retienen y devuelven el foco; atajos de teclado para pasar de un proponente a otro |
| **Sensibilidad al movimiento** | Respeta «reducir movimiento» del sistema | 2.3.3 | **Cumple:** con esa preferencia no hay animaciones ni transiciones |
| **Discapacidad cognitiva** | Lenguaje claro, flujo por pasos, errores explicados, sin límites de tiempo en las tareas | 2.2.1, 3.2.3, 3.3.1, 3.3.2, 3.3.3 | **Cumple en lo revisado:** flujo de 4 pasos siempre igual; cada resultado explica su motivo y puede explicarse en palabras; errores en texto con la acción a seguir. La sesión dura una jornada (10 h) |
| **Discapacidad auditiva** | Alternativas al audio | 1.2.x | **No aplica:** la plataforma no tiene audio ni video. El reCAPTCHA es invisible (no presenta desafíos de audio) |

## 4. Lista de verificación WCAG 2.1 AA

| Criterio | Estado | Cómo se cumple |
|---|---|---|
| 1.1.1 Contenido no textual | Cumple | Imágenes decorativas con `alt=""`; iconos con `aria-label`; avatar oculto al lector |
| 1.3.1 Información y relaciones | Cumple | `main`, `header`, `nav`, encabezados, tablas y etiquetas en formularios |
| 1.4.1 Uso del color | Cumple | Estados con texto además de color |
| 1.4.3 Contraste mínimo | Cumple | axe-core sin infracciones; tokens `--ok` y `--na` corregidos |
| 1.4.4 Cambio de tamaño | Cumple | Revisado al 200 % en 10 pantallas |
| 1.4.10 Reflujo | Cumple | Revisado a 320 px en 10 pantallas; las tablas de datos se desplazan dentro de su recuadro (excepción permitida) |
| 1.4.11 Contraste de componentes | Cumple | Contorno de foco de 3 px |
| 1.4.12 Espaciado del texto | Cumple | Sin texto cortado con el espaciado aumentado |
| 2.1.1 y 2.1.2 Teclado, sin trampas | Cumple | Recorrido con tabulador; `useDialogo` |
| 2.3.3 Animación por interacción | Cumple | `prefers-reduced-motion` |
| 2.4.1 Evitar bloques | Cumple | «Saltar al contenido principal» |
| 2.4.2 Título de página | Cumple dentro de los procesos | Paso y código del proceso; fuera de un proceso, «MiEvaluador» |
| 2.4.3 y 2.4.7 Orden y foco visible | Cumple | Verificado automáticamente |
| 3.1.1 Idioma | Cumple | `<html lang="es">` |
| 3.3.1 y 3.3.2 Errores y etiquetas | Cumple | Texto y `role="alert"` |
| 4.1.2 Nombre, función, valor | Cumple | `aria-label`, `aria-current`, `aria-expanded`, `aria-pressed` |
| 4.1.3 Mensajes de estado | Cumple | `role="status"` en avisos y cargas |

## 5. Pendientes
1. **Prueba con personas:** una sesión con un usuario de lector de pantalla (NVDA en Windows) y otro de ampliación. La auditoría automática verifica las reglas; la experiencia real solo la confirma quien la usa.
2. Título propio en las pantallas fuera de un proceso (lista de procesos, equipo, configuración).
3. Pantallas de administración (equipo, configuración, crear proceso) en la auditoría automática: piden un rol distinto de «Consulta».
