# Matriz de riesgos de seguridad digital de MiEvaluador

**Código:** SGSI-RIE-02 · **Versión:** 1.0 · **Fecha:** 2/10/2026
**Metodología:** Guía para la administración del riesgo y el diseño de controles en entidades públicas (DAFP) y lineamientos de gestión de riesgos de seguridad digital de MinTIC. Sirve también como análisis de riesgos de ISO/IEC 27001 (6.1.2) y de ISO/IEC 42001 (6.1).

## 1. Escalas

**Probabilidad:** Muy baja (1) · Baja (2) · Media (3) · Alta (4) · Muy alta (5)
**Impacto:** Leve (1) · Menor (2) · Moderado (3) · Mayor (4) · Catastrófico (5)
**Zona de riesgo** (probabilidad × impacto): Baja (1–4) · Moderada (5–9) · Alta (10–14) · Extrema (15–25)
**Tratamiento:** se reduce todo riesgo inherente Alto o Extremo; se acepta el riesgo residual Bajo; el Moderado se acepta con seguimiento.

## 2. Activos de información

| Código | Activo | Tipo | C | I | D |
|---|---|---|---|---|---|
| A1 | Ofertas de los proponentes (incluyen datos personales: cédulas, antecedentes) | Información | Alta | Alta | Media |
| A2 | Resultados de evaluación, revisiones y expedientes | Información | Alta | Alta | Alta |
| A3 | Registro de auditoría | Información | Media | Alta | Alta |
| A4 | Credenciales y segundo factor de los usuarios | Información | Alta | Alta | Media |
| A5 | Base de datos PostgreSQL | Software/servicio | Alta | Alta | Alta |
| A6 | Modelos de IA locales | Software | Baja | Alta | Media |
| A7 | Código fuente y reglas del motor | Software | Media | Alta | Media |
| A8 | Respaldos | Información | Alta | Alta | Alta |
| A9 | Servidor de aplicación (LeMarTek Cloud) | Infraestructura | — | Alta | Alta |

## 3. Matriz

| # | Riesgo | Activo | Causa / amenaza | Inherente (P×I) | Controles existentes (dónde) | Residual (P×I) | Tratamiento |
|---|---|---|---|---|---|---|---|
| R1 | Una entidad accede a datos de otra | A1, A2 | Error de programación o abuso de la API | 3×5 = 15 **Extremo** | Row-Level Security en la base (`evaluaciones/migrations/0002_aislamiento_rls.py`, `cuentas/aislamiento.py`), pruebas de aislamiento (`AislamientoEvaluacionesTests`) | 1×5 = 5 Moderado | Reducir: prueba de penetración externa (doc. 07) |
| R2 | Suplantación de un evaluador | A4, A2 | Robo o adivinación de contraseña | 4×4 = 16 **Extremo** | Segundo factor obligatorio en producción, bloqueo tras 5 fallos, reCAPTCHA, contraseñas de 10+ caracteres (`api/auth.py`, `cuentas/seguridad.py`) | 1×4 = 4 Bajo | Aceptar |
| R3 | Se aprueba una oferta que no cumplía (error del sistema) | A2 | Lectura errónea de un documento o alucinación de la IA | 3×5 = 15 **Extremo** | Lo dudoso va a revisión humana; verificación anti-invención (`motor/llm/cliente.py`); muestra de control obligatoria antes de aprobar (`evaluaciones/muestra.py`); medición: 0 aprobaciones indebidas en 4.998 decisiones | 1×5 = 5 Moderado | Reducir: mediciones a ciegas en cada versión (doc. 06) |
| R4 | Fuga de ofertas a terceros | A1 | Envío a servicios de IA externos | 3×5 = 15 **Extremo** | IA 100 % local (Ollama); sin API externas de IA | 1×5 = 5 Moderado | Aceptar con seguimiento (doc. 05: ningún cambio introduce servicios externos sin evaluación) |
| R5 | Alteración del registro de auditoría | A3 | Acceso directo a la base | 2×4 = 8 Moderado | Trigger que prohíbe modificar o borrar; cadena de huellas SHA-256 verificable (`verificar_auditoria`); huecos documentados | 1×4 = 4 Bajo | Aceptar |
| R6 | Pérdida de datos | A5, A2 | Falla del disco o error humano | 3×5 = 15 **Extremo** | Respaldo diario verificado y prueba de restauración (`scripts/respaldo.sh`, `scripts/verificar_restauracion.sh`) | 2×3 = 6 Moderado | Reducir: copia fuera del servidor (LeMarTek Cloud, fase 2) |
| R7 | Vulnerabilidad en una dependencia | A5, A7 | Biblioteca de terceros con fallas conocidas | 4×4 = 16 **Extremo** | pip-audit y npm audit en cada cambio (integración continua); Nessus (doc. 07) | 2×3 = 6 Moderado | Reducir: escaneo trimestral |
| R8 | Inyección o ataque web (OWASP) | A5 | Entradas maliciosas | 3×4 = 12 Alto | ORM de Django, CSRF, CSP y cabeceras de seguridad (`despliegue/nginx.conf`), límites de peticiones, Bandit | 1×4 = 4 Bajo | Aceptar; validar con Nessus |
| R9 | Cambio no controlado del modelo de IA | A6 | Actualización del modelo sin medir | 3×4 = 12 Alto | Inventario con huella del modelo y aprobación (`inventario_ia`); trazabilidad del modelo en cada resultado | 1×4 = 4 Bajo | Aceptar |
| R10 | Indisponibilidad en plena evaluación | A9 | Caída del servidor o de la GPU | 3×3 = 9 Moderado | Fila de trabajos que sobrevive a reinicios; sin la IA el sistema sigue (manda a revisión) | 2×3 = 6 Moderado | Reducir en fase 2 (redundancia en LeMarTek Cloud) |
| R11 | Personal de LeMarTek ve datos de una entidad | A1, A2 | Abuso de privilegios | 2×5 = 10 Alto | Acceso de soporte solo con permiso temporal del administrador de la entidad, registrado en la auditoría | 1×5 = 5 Moderado | Aceptar con seguimiento |
| R12 | Conservación excesiva de datos personales | A1 | Documentos que no se borran | 3×3 = 9 Moderado | Retención automática (`aplicar_retencion`, 30 días tras aprobar) | 1×3 = 3 Bajo | Aceptar |
| R13 | Inaccesibilidad para personas con discapacidad | — | Interfaz que no cumple WCAG | 3×3 = 9 Moderado | Auditoría axe-core (0 infracciones), navegación por teclado, enlace para saltar al contenido (doc. 10) | 2×2 = 4 Bajo | Reducir: prueba con lector de pantalla |

## 4. Seguimiento
El responsable de seguridad revisa esta matriz cada trimestre, tras cada incidente y antes de cada modificación sustancial, con la evidencia de `auditar_calidad.sh` y los informes de Nessus.
