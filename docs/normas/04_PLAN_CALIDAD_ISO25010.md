# Plan de calidad del producto — modelo ISO/IEC 25010:2023

**Código:** CAL-PLAN-04 · **Versión:** 1.0 · **Fecha:** 2/10/2026 · **Producto:** MiEvaluador 1.1.0

La ISO/IEC 25010 define el modelo de calidad; no es certificable. Este plan fija, para cada característica, qué se mide, la meta y el valor actual con su evidencia. Se actualiza en cada versión y en cada revisión anual. Forma correcta de citarla: *«desarrollado bajo el modelo de calidad ISO/IEC 25010»*.

## Métricas por característica

| Característica | Subcaracterística | Métrica | Meta | Valor actual | Evidencia |
|---|---|---|---|---|---|
| **Adecuación funcional** | Corrección | Aprobaciones indebidas: requisitos que el sistema dio por cumplidos y la entidad rechazó | 0 | **0** en 4.998 decisiones (techo de error ≤ 0,08 %) | Medición del 27/09/2026 (`Backend/.scratch/medicion_2026-09-27/cifras.json`) |
| | Completitud | Verificaciones resueltas automáticamente con evidencia | ≥ 70 % | **73,1 %** (3.655 de 4.998) | Ídem |
| | Pertinencia | Requisitos tomados del pliego de cada proceso | 100 % | Lectura del pliego con confirmación humana | `motor/pliego/` |
| **Eficiencia de desempeño** | Comportamiento temporal | Minutos de máquina por oferta y área | ≤ 5 min | 1,3 a 3,8 min según área y modalidad | Medición del 27/09/2026 |
| | | Proceso completo de 80 ofertas, 3 áreas | ≤ 3 h | ≈ 3 h | Medición interna |
| | Uso de recursos | Una sola consulta a la IA a la vez por servidor | Sí | Sí (candado de la IA) | `motor/llm/cliente.py` |
| **Compatibilidad** | Interoperabilidad | Formatos de entrada aceptados | PDF, ZIP, RAR; carpeta compartida o carga directa | Cumple | `motor/procesamiento/` |
| | Coexistencia | Varias entidades en la misma instalación sin interferir | Sí | Fila con reparto justo por entidad | `evaluaciones/trabajador.py` |
| **Capacidad de interacción** (usabilidad) | Reconocibilidad y aprendizaje | Flujo guiado por pasos | 4 pasos | Datos → Evaluación → Control → Informe | Interfaz |
| | Protección contra errores | Decisiones con justificación y soporte visto | 100 % | Obligatorio por diseño | `evaluaciones/muestra.py` |
| | Inclusividad | Infracciones WCAG 2.1 AA automáticas | 0 | **0** | Documento 10 |
| | | Prueba con usuarios evaluadores | 1 por versión mayor | Pendiente | — |
| **Fiabilidad** | Tolerancia a fallos | Un fallo de la IA no detiene la evaluación | Sí | Sí: se manda a revisión humana | `motor/llm/cliente.py` |
| | Recuperabilidad | Trabajos que sobreviven a un reinicio | 100 % | Sí (fila persistente en la base) | `evaluaciones/trabajador.py` |
| | | Restauración de respaldo probada | Mensual | Probada el 2/10/2026 (1 s) | Documento 09 |
| **Seguridad** | Confidencialidad | Aislamiento entre entidades en la base | Sí | Row-Level Security | Documento 03 (8.3) |
| | Integridad | Auditoría verificable | Íntegra | Íntegra (1 hueco documentado) | `verificar_auditoria` |
| | Autenticidad | Segundo factor en producción | 100 % de usuarios | Sí | Documento 03 (8.5) |
| | Resistencia | Vulnerabilidades conocidas en dependencias | 0 | **0** | pip-audit y npm audit (2/10/2026) |
| | | Hallazgos medios o altos de análisis estático | 0 | **0** | Bandit (2/10/2026) |
| | | Hallazgos críticos o altos de Nessus | 0 | Pendiente de escaneo | Documento 07 |
| **Mantenibilidad** | Capacidad de prueba | Pruebas automáticas que pasan | 100 % | **617 de 617** (2 omitidas por falta de material) | `auditar_calidad.sh` |
| | Modularidad | Motor separado por área (jurídica, técnica, financiera) | Sí | Sí | `motor/` |
| | Modificabilidad | Cada cambio pasa por integración continua | 100 % | Configurada | `.github/workflows/calidad.yml` |
| **Flexibilidad** (portabilidad) | Instalabilidad | Despliegue reproducible en contenedores | Sí | `docker-compose` | `docs/DESPLIEGUE.md` |
| | Adaptabilidad | Modelos de IA y parámetros configurables sin cambiar código | Sí | Variables de entorno | Documento 06 |
| **Protección** (*safety*) | Operación a prueba de fallos | Ante la duda, a revisión humana; nunca aprobación por defecto | Sí | Sí | Medición: 0 aprobaciones indebidas |
| | Advertencia de riesgos | Muestra de control obligatoria antes de aprobar | Sí | Sí | `evaluaciones/muestra.py` |

## Cómo se mide
- **Cada cambio:** integración continua (pruebas, dependencias, Bandit, lint y compilación).
- **Cada versión:** `Backend/scripts/auditar_calidad.sh` y una medición contra informes reales de referencia, incluido al menos un proceso a ciegas (no usado para desarrollar).
- **Cada trimestre:** escaneo con Nessus y prueba de restauración.

## Brechas y plan
| Brecha | Acción | Plazo |
|---|---|---|
| Prueba de usabilidad con evaluadores reales | Sesión con el equipo de la primera entidad | Implementación (semanas 3–5) |
| Escaneo con Nessus | Documento 07 | Antes de la salida a producción |
| Accesibilidad de las pantallas internas | Auditoría manual con lector de pantalla (documento 10) | Próxima versión |
