# Declaración de Aplicabilidad — ISO/IEC 27001:2022, Anexo A

**Código:** SGSI-SOA-03 · **Versión:** 1.0 · **Fecha:** 2/10/2026 · **Alcance:** el aplicativo MiEvaluador

**Estados:** **I** implementado en el aplicativo · **P** parcial · **D** cubierto por un documento de este paquete · **F2** depende de la infraestructura (LeMarTek Cloud, segunda fase) · **N/A** no aplica, con justificación.

Resumen: de 93 controles, 89 aplican y 4 no aplican. De los 89 que aplican, 33 están implementados en el aplicativo, 12 están parciales, 24 quedan cubiertos por un documento de este paquete y 20 dependen de la infraestructura (segunda fase).

## 5. Controles organizacionales

| Control | Estado | Cómo se cumple / dónde |
|---|---|---|
| 5.1 Políticas de seguridad | D | Documento 01 |
| 5.2 Roles y responsabilidades | D | Documento 01, sección 4 |
| 5.3 Segregación de funciones | I | Roles: el evaluador decide, el jefe de área aprueba; la muestra de control exige revisión contra soporte (`evaluaciones/permisos.py`, `evaluaciones/muestra.py`) |
| 5.4 Responsabilidades de la dirección | D | Documento 01 |
| 5.5 Contacto con autoridades | D | Documento 08 (colCERT, SIC) |
| 5.6 Contacto con grupos de interés | D | Documento 07 (fuentes de vulnerabilidades) |
| 5.7 Inteligencia de amenazas | P | Bases de vulnerabilidades consultadas por pip-audit y npm audit; Nessus |
| 5.8 Seguridad en la gestión de proyectos | D | Documento 05 |
| 5.9 Inventario de activos | D | Documento 02, sección 2; inventario de IA (`inventario_ia`) |
| 5.10 Uso aceptable | I | Compromiso de uso: sin aceptarlo el evaluador no decide requisitos |
| 5.11 Devolución de activos | D | Documento 01 (desactivación de cuentas); contrato con la entidad |
| 5.12 Clasificación de la información | D | Documento 02, sección 2 |
| 5.13 Etiquetado | P | Informes rotulados como preinforme o informe adoptado; el resto, pendiente |
| 5.14 Transferencia de información | I | Solo HTTPS (HSTS); descargas autenticadas y registradas en la auditoría |
| 5.15 Control de acceso | I | Roles por entidad y área (`cuentas/models.py`, `evaluaciones/permisos.py`) |
| 5.16 Gestión de identidades | I | Cuentas nominales creadas por el administrador de la entidad; se desactivan, no se reutilizan |
| 5.17 Información de autenticación | I | Contraseñas temporales de cambio obligatorio, validadores de contraseña, segundo factor TOTP |
| 5.18 Derechos de acceso | I | Asignación por áreas; acceso de soporte de LeMarTek solo con permiso temporal (`AccesoSoporte`) |
| 5.19 Seguridad con proveedores | D | Documento 01, sección 5 |
| 5.20 Seguridad en acuerdos con proveedores | D | Contrato de transmisión de datos con la entidad (Ley 1581) |
| 5.21 Cadena de suministro TIC | I | Dependencias fijadas en versión exacta y auditadas en cada cambio (integración continua) |
| 5.22 Seguimiento de servicios de proveedores | F2 | Proveedor de nube |
| 5.23 Seguridad en servicios en la nube | F2 | LeMarTek Cloud |
| 5.24 Planificación de gestión de incidentes | D | Documento 08 |
| 5.25 Evaluación de eventos | D | Documento 08 |
| 5.26 Respuesta a incidentes | D | Documento 08 |
| 5.27 Aprendizaje de incidentes | D | Documento 08 |
| 5.28 Recolección de evidencias | I | Auditoría inalterable con cadena de huellas; expediente por evaluación |
| 5.29 Seguridad durante interrupciones | P | La fila de trabajos sobrevive a reinicios; sin IA el sistema sigue y manda a revisión |
| 5.30 Preparación TIC para la continuidad | F2 | LeMarTek Cloud |
| 5.31 Requisitos legales y contractuales | D | `docs/CUMPLIMIENTO_LEGAL.md` (Concepto C-1015 de 2026, LEG-004) |
| 5.32 Derechos de propiedad intelectual | I | Registro ante la DNDA; licencias de dependencias; copyright en la interfaz |
| 5.33 Protección de registros | I | Expediente y auditoría inalterables; la retención no los borra |
| 5.34 Privacidad y datos personales | I | Ley 1581: retención automática, IA local, aislamiento por entidad, acceso mínimo |
| 5.35 Revisión independiente | P | Prueba de penetración externa y auditoría de certificación, pendientes |
| 5.36 Cumplimiento de políticas | I | `auditar_calidad.sh` y la integración continua verifican los controles técnicos |
| 5.37 Procedimientos documentados | D | `docs/DESPLIEGUE.md` y documentos 05, 07, 08 y 09 |

## 6. Controles de personas

| Control | Estado | Cómo se cumple / dónde |
|---|---|---|
| 6.1 Verificación de antecedentes | D | Proceso de vinculación de LeMarTek (documento 01) |
| 6.2 Términos y condiciones del empleo | D | Cláusulas de confidencialidad en contratos |
| 6.3 Concienciación y formación | P | Capacitación a la entidad en la implementación; plan interno pendiente |
| 6.4 Proceso disciplinario | D | Documento 01, sección 6 |
| 6.5 Responsabilidades al terminar | D | Desactivación inmediata de cuentas |
| 6.6 Acuerdos de confidencialidad | D | Documento 01, sección 5 |
| 6.7 Trabajo remoto | F2 | Acceso administrativo por VPN en LeMarTek Cloud |
| 6.8 Reporte de eventos | D | Documento 08 |

## 7. Controles físicos

| Control | Estado | Cómo se cumple / dónde |
|---|---|---|
| 7.1 a 7.6 Perímetros, entradas, oficinas, monitoreo, amenazas físicas, áreas seguras | F2 | Centro de datos de LeMarTek Cloud |
| 7.7 Escritorio y pantalla limpios | P | La sesión vence tras la jornada; política de bloqueo de equipos, pendiente |
| 7.8 Ubicación de equipos | F2 | LeMarTek Cloud |
| 7.9 Activos fuera de las instalaciones | N/A | El aplicativo no entrega equipos a los usuarios |
| 7.10 Medios de almacenamiento | F2 | LeMarTek Cloud |
| 7.11 Servicios de soporte (energía) | F2 | LeMarTek Cloud |
| 7.12 Seguridad del cableado | F2 | LeMarTek Cloud |
| 7.13 Mantenimiento de equipos | F2 | LeMarTek Cloud |
| 7.14 Eliminación segura de equipos | F2 | LeMarTek Cloud |

## 8. Controles tecnológicos

| Control | Estado | Cómo se cumple / dónde |
|---|---|---|
| 8.1 Dispositivos de usuario final | N/A | Aplicación web; el equipo es de la entidad |
| 8.2 Derechos de acceso privilegiado | I | El superadministrador no ve datos de una entidad sin su permiso temporal (fuera de desarrollo); segundo factor obligatorio |
| 8.3 Restricción de acceso a la información | I | Row-Level Security en PostgreSQL por entidad (`evaluaciones/migrations/0002_aislamiento_rls.py`) |
| 8.4 Acceso al código fuente | I | Repositorio privado; paquete de custodia (`paquete_escrow`) con manifiesto SHA-256 |
| 8.5 Autenticación segura | I | Segundo factor para todos en producción (`EXIGIR_2FA_A_TODOS`); bloqueo tras 5 fallos en 15 min; reCAPTCHA |
| 8.6 Gestión de la capacidad | P | Fila de trabajos con capacidad configurable y reparto justo entre entidades; monitoreo, F2 |
| 8.7 Protección contra malware | P | Solo se aceptan PDF/ZIP/RAR validados; antivirus de los archivos subidos, F2 |
| 8.8 Gestión de vulnerabilidades técnicas | I | pip-audit, npm audit y Bandit en cada cambio; Nessus (documento 07) |
| 8.9 Gestión de la configuración | I | Configuración por variables de entorno; despliegue reproducible (`despliegue/docker-compose.yml`) |
| 8.10 Eliminación de información | I | `aplicar_retencion` borra las ofertas a los 30 días de aprobar; los archivos se borran solo si la base confirma |
| 8.11 Enmascaramiento de datos | P | Material del registro DNDA anonimizado; enmascaramiento en la interfaz, pendiente |
| 8.12 Prevención de fuga de datos | I | IA local sin envío externo; descargas autenticadas y registradas |
| 8.13 Respaldo de la información | I | Respaldo diario verificado y prueba de restauración (documento 09) |
| 8.14 Redundancia | F2 | LeMarTek Cloud |
| 8.15 Registro de eventos | I | `EventoAuditoria`: inicios de sesión, documentos vistos, decisiones, aprobaciones |
| 8.16 Monitoreo de actividades | P | Tablero de la fila y de rendimiento; alertas de seguridad, F2 |
| 8.17 Sincronización de relojes | F2 | NTP del servidor |
| 8.18 Programas utilitarios privilegiados | P | Comandos de administración solo en el servidor; desactivar la protección de la auditoría deja hueco documentado |
| 8.19 Instalación de software en producción | I | Solo por despliegue de imágenes construidas desde el repositorio |
| 8.20 Seguridad de redes | F2 | LeMarTek Cloud |
| 8.21 Seguridad de los servicios de red | F2 | LeMarTek Cloud |
| 8.22 Segregación de redes | P | La base y la IA no se exponen fuera de la red interna de Docker |
| 8.23 Filtrado web | N/A | El servidor no navega; solo consulta páginas oficiales fijas |
| 8.24 Uso de criptografía | I | HTTPS con HSTS; contraseñas con PBKDF2 (Django); huellas SHA-256 en auditoría y expediente |
| 8.25 Ciclo de vida de desarrollo seguro | I | Documento 05; integración continua (`.github/workflows/calidad.yml`) |
| 8.26 Requisitos de seguridad de la aplicación | I | CSRF, CSP, cabeceras de seguridad (`despliegue/nginx.conf`), límites de peticiones |
| 8.27 Arquitectura segura | I | Aislamiento en la base de datos, IA local, decisiones con soporte obligatorio |
| 8.28 Codificación segura | I | ORM (sin SQL armado a mano con datos del usuario); Bandit sin hallazgos medios ni altos |
| 8.29 Pruebas de seguridad | I | 617 pruebas automáticas, incluidas las de aislamiento y auditoría; Nessus |
| 8.30 Desarrollo externalizado | N/A | Desarrollo propio de LeMarTek |
| 8.31 Separación de ambientes | I | Lo que solo vale en desarrollo depende de DEBUG y se apaga en producción |
| 8.32 Gestión de cambios | I | Documento 05; versión y `CHANGELOG.md` |
| 8.33 Información de prueba | I | Las ofertas reales de prueba no se suben al repositorio; las demostraciones usan procesos públicos del SECOP |
| 8.34 Protección durante auditorías | D | Documento 07: los escaneos se coordinan y nunca se hacen en plena evaluación |
