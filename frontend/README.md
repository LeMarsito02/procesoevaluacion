# MiEvaluador — interfaz

React + TypeScript + Vite. Quien usa esta pantalla es un abogado de contratación
revisando ofertas, no un técnico: todo lo que sigue sale de ahí.

## Levantarla

```bash
npm install
npm run dev          # http://localhost:5173 (o el primero libre)
npm run build        # comprueba tipos y arma dist/
npx tsc --noEmit     # solo los tipos
```

Necesita el backend en `http://localhost:8000` (ver `Backend/`). La sesión va por
cookie: sin backend arriba, la pantalla de entrada carga pero no se puede entrar.

## Banco de pruebas visual

`http://localhost:5173/#/previsualizacion` abre los componentes de revisión con
datos inventados, sin crear un proceso ni iniciar sesión: el panel de un
proponente, el visor de documentos, la matriz, el detalle técnico y el
financiero, y el asistente de creación. Hay un control para estrechar el panel y
ver cómo se comporta.

Sirve para mirar un cambio de estilo sin montar un proceso entero. Solo existe en
desarrollo: la condición es estática y el archivo no entra en el paquete de
producción (compruébelo con `npm run build`, no debe aparecer ningún
`Previsualizacion-*.js` en `dist/assets`).

Añadiendo `/panel` o `/visor` al hash, esas dos ventanas se abren solas.

## Cómo está organizado

| | |
|---|---|
| `Raiz.tsx` | sesión, rutas y qué página se pinta. Las páginas que no son del trabajo diario (configuración, equipo, entidades, fila, rendimiento, mejoras) se cargan aparte |
| `paginas/` | una por ruta |
| `components/` | piezas de las páginas; las grandes son `PasoEvaluacion` (la matriz), `PanelProponente` (el detalle de una oferta) y `VisorDocumento` |
| `estado.ts` | de un resultado del motor a un estado de pantalla (`cumple`, `revisar`, `no_aplica`, `error`, y los revisados por una persona) |
| `requisitos.ts` | el catálogo: número, título, qué se verifica y a qué grupo pertenece |
| `glosario.tsx` | las siglas del oficio, explicadas al pasar el cursor, y el partido de los motivos en lista |
| `dialogo.ts` | comportamiento de ventana modal (foco atrapado) para el panel y el visor |
| `http.ts` | API, CSRF, sesión vencida y mensajes de error en español, nunca el error técnico |

## Reglas de la interfaz

Estas no son de estilo, son del oficio. Cambiarlas cambia lo que pasa en un
proceso de contratación real.

1. **Los dos botones de decisión pesan igual.** Uno verde sólido frente a otro
   pálido empuja a marcar "Cumple", y aprobar sin mirar es justo lo que no puede
   pasar. Misma razón: no hay atajo de teclado para decidir.
2. **No se enuncian reglas del pliego que no vengan del backend.** El glosario
   explica siglas (SMMLV, RUP, CRP…) pero no numerales ("3.5.6"): cambian de un
   proceso a otro, y decir lo que creemos que significan le pone al abogado una
   regla que quizá ese pliego no tiene. Lo mismo vale para la explicación que
   redacta el modelo local.
3. **Lo que el programa no verificó se ve.** Un requisito sin revisar no se
   pinta como aprobado, y descargar el informe con pendientes se confirma: en el
   Excel salen como NO CUMPLE.
4. **Se distingue "no está" de "no lo pudimos leer".** Son cosas distintas para
   quien revisa: una se subsana, la otra se mira a mano.
5. **Contraste mínimo 4.5:1** en el texto. Los tokens de color ya lo cumplen
   sobre los fondos donde se usan; si añade uno, compruébelo.

## Al tocar estilos

`styles.css` es un solo archivo con tokens arriba (`:root`) y secciones por
bloque. No hay framework de CSS. Los colores de estado (`--ok`, `--warn`,
`--bad`, `--na`) se usan también en las píldoras y en la matriz: cambiarlos toca
toda la pantalla.
