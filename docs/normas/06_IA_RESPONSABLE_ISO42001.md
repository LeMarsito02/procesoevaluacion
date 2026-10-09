# Política de IA responsable, inventario y evaluación de impacto

**Código:** SGIA-POL-06 · **Versión:** 1.0 · **Fecha:** 2/10/2026
**Normas:** ISO/IEC 42001:2023 · Concepto C-1015 de 2026 de la ANCP-CCE · Marco Ético para la IA en Colombia · Ley 1581 de 2012

## 1. Política
LeMarTek usa la inteligencia artificial en MiEvaluador **solo como apoyo** a la verificación de requisitos habilitantes. Sus compromisos:

1. **La IA propone, la persona decide.** Ningún resultado es definitivo sin adopción humana; la decisión sobre cada oferta es del servidor público competente.
2. **La IA extrae, el código decide.** El modelo lee datos puntuales del documento o responde preguntas concretas; la regla de cumple o no cumple la aplica el código, de forma determinista.
3. **Todo se comprueba contra el documento.** Un dato que la IA extrae y que no aparece literalmente en el texto se descarta (verificación anti-invención, `motor/llm/cliente.py`).
4. **Ante la duda, a una persona.** Si la IA no está disponible, tarda o responde algo inválido, el requisito va a revisión humana. Nunca se aprueba por defecto.
5. **IA local.** Los modelos corren en el servidor; ningún documento se envía a servicios de IA de terceros.
6. **Transparencia.** Cada resultado que usó IA lo dice («IA» en la interfaz), registra el modelo usado y puede explicarse en palabras.
7. **Medición antes de usar.** Ningún modelo nuevo o actualizado se usa en evaluaciones reales sin medirlo antes contra informes de referencia, con 0 aprobaciones indebidas.

## 2. Roles
| Rol | Responsabilidad |
|---|---|
| Responsable de la IA (LeMarTek) | Mantiene el inventario, mide y aprueba los modelos, revisa esta política. |
| Evaluador de la entidad | Revisa lo pendiente con el soporte a la vista; acepta el compromiso de uso. |
| Jefe de área de la entidad | Revisa la muestra de control y aprueba la evaluación. |

## 3. Inventario de sistemas de IA

| Uso | Modelo | Licencia (verificada en la fuente oficial) | Qué hace | Qué NO hace | Control |
|---|---|---|---|---|---|
| Extracción de documentos | `llama3.1:8b` (8B, Q4_K_M) | Llama 3.1 Community License: uso comercial permitido; exige mostrar «Built with Llama» y el aviso de copyright de Meta (se muestra en «Acerca de» y en la ficha del sistema) | Extrae nombres, cédulas, valores y fechas de documentos de la oferta | Decidir si cumple | Anti-invención: el dato debe estar en el texto |
| Lectura del pliego | `qwen3:4b` (4B, Q4_K_M) | Apache 2.0 | Propone requisitos y parámetros del pliego, con su cita | Fijar requisitos sin confirmación | Una persona confirma cada parámetro antes de evaluar |
| Visión | `qwen2.5vl:7b` (7B) | Apache 2.0 | Lee documentos escaneados (fecha de expedición de la cédula) | Decidir antecedentes | Reglas de confianza; si duda, a revisión |
| Asistente de consulta | El mismo de extracción (`llama3.1:8b`; `ASISTENTE_MODELO` lo cambia) | La del modelo que se configure | Responde preguntas de la persona sobre las evaluaciones que puede ver, citando la evaluación de donde sale cada dato | Decidir, aprobar, modificar datos ni leer evaluaciones ajenas | Solo consultas de lectura con los permisos de quien pregunta (`evaluaciones/asistente.py`); aviso visible; cada conversación y cada consulta quedan guardadas y auditadas |

**Prestación de servicios (OPS):** el módulo no usa ninguno de estos modelos. Lee los documentos con reglas y con reconocimiento de texto (Tesseract, Apache 2.0), pone la experiencia en línea con aritmética de fechas y deja para una persona lo que no pudo confirmar; la idoneidad la confirma una persona, con su nombre y la fecha (`motor/ops`, `evaluaciones/ops.py`).

**Licencias:** se verifican en el archivo LICENSE oficial de cada modelo, no en la etiqueta de Ollama. El 2/10/2026 se encontró que Ollama marca `qwen2.5vl:3b` como Apache 2.0, cuando su licencia oficial (Qwen Research License) prohíbe el uso comercial: se reemplazó por el 7B. El registro está en `evaluaciones/transparencia.py` (`LICENCIAS`) y `inventario_ia` no deja aprobar un modelo sin uso comercial verificado.

El inventario vivo, con la huella exacta de cada modelo y su aprobación, lo da:
```
python manage.py inventario_ia
python manage.py inventario_ia --aprobar --por "Nombre, cargo" --evidencia "Medición del AAAA-MM-DD"
```
Las aprobaciones quedan en `Backend/config/modelos_ia_aprobados.json` (versionado). En producción se usará un modelo mayor (GPU L4 de 24 GB): se aprueba igual, con su propia medición.

## 4. Evaluación de impacto

| Aspecto | Impacto posible | Personas afectadas | Medidas | Riesgo residual |
|---|---|---|---|---|
| **Decisiones erróneas** | Un proponente habilitado o rechazado por error | Proponentes, entidad | La IA no decide; muestra de control obligatoria; si encuentra un error, todo el requisito pasa a revisión; 0 aprobaciones indebidas medidas | Bajo |
| **Sesgo o trato desigual** | Criterios distintos entre proponentes | Proponentes | Las mismas reglas del pliego para todos; la IA solo extrae datos, no valora | Bajo |
| **Alucinación** | La IA inventa un dato | Proponentes | Verificación anti-invención contra el texto literal | Bajo |
| **Privacidad** | Exposición de datos personales | Representantes legales, profesionales | IA local; retención de 30 días; aislamiento por entidad | Bajo |
| **Dependencia excesiva** | El evaluador aprueba sin mirar | Entidad | Compromiso de uso; decidir exige abrir el soporte; muestra de control | Moderado (seguimiento) |
| **Opacidad** | No se entiende por qué se decidió algo | Entidad, órganos de control | Motivo y documento en cada resultado; explicación en palabras; expediente con trazabilidad | Bajo |
| **Cambio silencioso del modelo** | Resultados distintos sin aviso | Todos | Huella del modelo aprobada; el despliegue falla si no coincide | Bajo |
| **Respuesta equivocada del asistente** | La persona confía en un dato mal dicho por el chat | Entidad, proponentes | El asistente no decide ni escribe; solo recibe datos de las consultas; cita la evaluación para verificar; aviso permanente de que puede errar | Moderado (seguimiento) |
| **Instrucciones escondidas en una oferta** | Un texto de un proponente intenta manipular al asistente | Entidad | Las consultas son de solo lectura y entregan campos acotados; el asistente no puede actuar; instrucción expresa de tratar los datos como información | Bajo |

## 5. Ciclo de vida de un modelo
1. **Selección:** licencia que permita el uso comercial, verificada en el archivo LICENSE oficial; capacidad para correr en el servidor.
2. **Medición:** contra informes reales de referencia, incluido al menos un proceso a ciegas. Criterio de aceptación: 0 aprobaciones indebidas, sin perder automatización frente al modelo anterior.
3. **Aprobación:** `inventario_ia --aprobar`, con responsable y evidencia; modificación sustancial en `CHANGELOG.md`.
4. **Operación:** cada resultado registra el modelo en su trazabilidad.
5. **Seguimiento:** el tablero de rendimiento y los hallazgos de las muestras de control.
6. **Retiro:** se desaprueba en el inventario; los resultados viejos conservan su trazabilidad.

## 6. Pendientes
- Medir el modelo de visión 7B (fecha de expedición de la cédula) y aprobar los tres modelos con `inventario_ia --aprobar` y el nombre real del responsable.
- Publicar una ficha de transparencia del sistema para las entidades.
- Asistente de consulta: medir su exactitud con un banco de preguntas de respuesta conocida antes de habilitarlo a una entidad, definir cuánto tiempo se conservan las conversaciones y mencionarlo en la política de tratamiento de datos.
