# Sistema de calidad y seguridad de MiEvaluador

**Producto:** MiEvaluador, versión 1.1.0 · **Titular:** LeMarTek Labs S.A.S. · NIT 902069061-9
**Alcance:** el aplicativo MiEvaluador (backend, frontend, motor de evaluación e IA local), su desarrollo y su operación. La infraestructura de LeMarTek Cloud se documenta en una segunda fase; aquí aparece solo lo que el aplicativo exige de ella.
**Fecha:** 2 de octubre de 2026 · **Revisión:** anual, o antes si hay una modificación sustancial (ver `CHANGELOG.md`).

## Marcos de referencia

| Marco | Qué es | Cómo se adopta |
|---|---|---|
| **ISO/IEC 25010:2023** | Modelo de calidad del producto de software | Marco interno de calidad con métricas medidas. No es certificable. |
| **ISO/IEC 27001:2022** | Sistema de gestión de seguridad de la información | Controles del Anexo A implementados en el aplicativo; certificación en la hoja de ruta. |
| **ISO/IEC 42001:2023** | Sistema de gestión de inteligencia artificial | Política, inventario, evaluación de impacto y control de cambios de los modelos. |
| **MinTIC: MSPI y lineamientos de gestión de riesgos de seguridad digital** | Modelo que aplican las entidades públicas, con la metodología de riesgos del DAFP | Matriz de riesgos en ese formato, para que encaje en el modelo de la entidad. |
| **MinTIC: Resolución 1519 de 2020, anexo 1 (accesibilidad web)** | Remite a WCAG 2.1 nivel AA | Auditoría automática con axe-core y lista de verificación manual. |
| **Ley 1581 de 2012** | Protección de datos personales | La entidad es la responsable y LeMarTek la encargada. |

## Documentos

| # | Documento | Normas |
|---|---|---|
| 01 | [Política de seguridad de la información](01_POLITICA_SEGURIDAD_INFORMACION.md) | 27001 (5.1) · MinTIC |
| 02 | [Matriz de riesgos de seguridad digital](02_MATRIZ_RIESGOS_SEGURIDAD_DIGITAL.md) | MinTIC/DAFP · 27001 (6.1) · 42001 (6.1) |
| 03 | [Declaración de Aplicabilidad (Anexo A)](03_DECLARACION_APLICABILIDAD_27001.md) | 27001 |
| 04 | [Plan de calidad del producto](04_PLAN_CALIDAD_ISO25010.md) | 25010 |
| 05 | [Control de cambios](05_CONTROL_DE_CAMBIOS.md) | 27001 (8.25, 8.32) · 25010 · 42001 |
| 06 | [Política de IA responsable, inventario y evaluación de impacto](06_IA_RESPONSABLE_ISO42001.md) | 42001 |
| 07 | [Gestión de vulnerabilidades (incluye Nessus)](07_GESTION_DE_VULNERABILIDADES.md) | 27001 (8.8, 8.29) · MinTIC |
| 08 | [Gestión de incidentes](08_GESTION_DE_INCIDENTES.md) | 27001 (5.24–5.28) · MinTIC |
| 09 | [Respaldo y restauración](09_RESPALDO_Y_RESTAURACION.md) | 27001 (8.13) · 25010 (fiabilidad) |
| 10 | [Accesibilidad (MinTIC)](10_ACCESIBILIDAD_MINTIC.md) | Res. 1519 de 2020 · WCAG 2.1 AA · 25010 (usabilidad) |
| 11 | [Informe de auditoría técnica del 2/10/2026](11_INFORME_AUDITORIA_2026-10-02.md) | Todas |

Complementan este paquete: `docs/CUMPLIMIENTO_LEGAL.md` (supervisión humana, expediente LEG-004 y Concepto C-1015 de 2026), `docs/DESPLIEGUE.md` y `CHANGELOG.md`.

## Cómo se produce la evidencia

```
Backend/scripts/auditar_calidad.sh          # pruebas, dependencias, Bandit, lint, auditoría, IA y accesibilidad
Backend/scripts/verificar_restauracion.sh   # restaura el último respaldo en una base temporal
python manage.py verificar_auditoria        # cadena de huellas del registro de auditoría
python manage.py inventario_ia              # modelos de IA en uso frente a los aprobados
```

La evidencia queda en `docs/normas/evidencias/AAAA-MM-DD/` (fuera del repositorio, porque trae datos del entorno). Los informes de Nessus se guardan en la misma carpeta. Se archiva junto con este paquete en cada revisión.

## Cómo hablar del estado de cada norma

| Estado | Frase correcta |
|---|---|
| Con certificado vigente | «Certificados en ISO/IEC 27001» |
| Implementando para certificar | «En proceso de certificación ISO/IEC 27001» |
| Usada como guía | «Desarrollado bajo el modelo ISO/IEC 25010», «alineados con ISO/IEC 27001 y 42001» |

Hoy ninguna está certificada: la frase correcta es **«alineados con»**.
