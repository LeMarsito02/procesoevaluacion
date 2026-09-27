# Registro de cambios de MiEvaluador

La versión del producto está en `Backend/VERSION` y queda registrada en cada
evaluación aprobada, en el reporte, en el expediente y en la ficha de
transparencia. Las **modificaciones sustanciales** (expediente LEG-004,
numeral 9.3: cambio del modelo de IA o de su proveedor, de la forma en que se
aplican las reglas del pliego, o nuevos tipos de documento o funciones) se
marcan como tales: exigen nuevas mediciones, actualizar la ficha del sistema y
avisar a las entidades.

## 1.1.0 — 2026-09-27 · Modificación sustancial (control humano)

Cumplimiento del expediente LEG-004 v1.2 y del Concepto C-1015 de 2026 de la
ANCP-CCE: el sistema verifica y propone; la persona adopta.

- **Muestra de control** antes de aprobar: 10 verificaciones del sistema
  sorteadas por área, repartidas entre ofertas y requisitos distintos (no se
  revisan ofertas completas), con semilla reproducible, revisión contra el
  soporte y ampliación a revisión humana de todo el requisito en que aparezca
  un error. Lo demás se adopta en bloque. Acta en Word dentro del expediente.
- **Adopción del puntaje técnico** con un clic, después de ver la tabla de
  puntajes preliminares; el orden de elegibilidad solo incluye puntajes
  adoptados.
- **Soporte visto antes de decidir** un requisito con documento; sin documento,
  justificación de lo consultado.
- **Compromiso de uso** del evaluador (numeral 6.4), aceptado y auditado.
- Lenguaje: «Verificado por MiEvaluador – adoptado por…» en lugar de «Aprobado
  automáticamente»; pre-informe hasta la adopción; puntaje y orden de
  elegibilidad **preliminares**; constancia de uso (numeral 6.2) en Word y Excel.
- **Auditoría inmutable** también en la base de datos (trigger) y con huellas
  encadenadas (`manage.py verificar_auditoria`).
- Un proceso que tuvo expediente **no se elimina**: se archiva.
- **Trazabilidad**: versión del sistema y modelos de IA en cada resultado y en
  cada evaluación aprobada; bitácora completa e indicadores de revisión en el
  expediente.
- El **superadministrador** solo ve los procesos de una entidad con permiso
  temporal de su administrador (numeral 4.5).
- **Ficha de transparencia algorítmica** (Directiva Conjunta 007 de 2025) en la
  aplicación y en Word.
- **Paquete de escrow** (`manage.py paquete_escrow`) con catálogo de reglas
  generado desde el código.
- Corrección: los informes técnico, financiero y consolidado fallaban al
  generarse desde la API (nombre del proponente).

Modelos de IA sin cambios en esta versión (`llama3.1:8b`, `qwen3:4b`,
`qwen2.5vl:3b`); su reemplazo por modelos Apache 2.0 sobre vLLM será la
próxima modificación sustancial.

## 1.0.0

Versión inicial: módulos jurídico, técnico y financiero; plataforma
multi-entidad; expediente permanente.
