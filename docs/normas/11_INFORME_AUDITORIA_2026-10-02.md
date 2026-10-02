# Informe de auditoría técnica — 2 de octubre de 2026

**Producto:** MiEvaluador 1.1.0 · **Versión del código:** `3dcb3ae` (rama main)
**Herramienta:** `Backend/scripts/auditar_calidad.sh` · **Evidencia:** `docs/normas/evidencias/2026-10-02/`

## 1. Resultado

| Control | Norma | Resultado |
|---|---|---|
| Pruebas automáticas (617) | 25010 · 27001 8.29 | Aprobado: 617 de 617 (2 omitidas por falta de material de prueba) |
| Dependencias Python (pip-audit) | 27001 8.8 | Aprobado: 0 vulnerabilidades conocidas |
| Dependencias JavaScript (npm audit) | 27001 8.8 | Aprobado: 0 vulnerabilidades |
| Análisis estático (Bandit) | 27001 8.28 | Aprobado: 0 hallazgos medios o altos (62 bajos, revisados) |
| Compilación, tipos y lint del frontend | 25010 | Aprobado |
| Integridad de la auditoría | 27001 8.15 | Aprobado: cadena íntegra, 1 hueco documentado |
| Inventario de la IA | 42001 | **Pendiente:** 3 modelos en uso sin aprobación formal |
| Accesibilidad WCAG 2.1 AA (axe-core) | Res. 1519 de 2020 | Aprobado: 0 infracciones en 4 combinaciones de pantalla y tamaño |
| Restauración de respaldo | 27001 8.13 | Aprobado: restaurado en 1 s, datos completos, auditoría íntegra |
| Escaneo con Nessus | 27001 8.8 | **Pendiente** (documento 07) |

## 2. Hallazgos corregidos en esta auditoría

| # | Hallazgo | Severidad | Corrección |
|---|---|---|---|
| 1 | El segundo factor solo era obligatorio para el superadministrador y el soporte; evaluadores y jefes entraban solo con contraseña | Alta | Obligatorio para todos los roles en producción (`EXIGIR_2FA_A_TODOS`) |
| 2 | Sin `RESPALDO_DIR` en `.env`, el respaldo diario terminaba en silencio sin hacerse | Alta | Corregido en `respaldo.sh`; nueva prueba de restauración |
| 3 | urllib3 2.7.0 con tres vulnerabilidades conocidas | Alta | Actualizado a 2.8.0 |
| 4 | brace-expansion (dependencia de desarrollo) con tres vulnerabilidades de denegación de servicio | Alta (solo desarrollo) | `npm audit fix` |
| 5 | Candado de la IA en `/tmp`, que otro usuario del servidor podría suplantar | Media | Movido a la carpeta de la aplicación |
| 6 | `LLM_URL` aceptaba cualquier esquema, incluido `file://` | Media | Solo `http` o `https` |
| 7 | 12 usos de MD5/SHA-1 marcados como débiles | Informativo | Son claves de caché, no seguridad: declarados `usedforsecurity=False` |
| 8 | Cadena de la auditoría rota por el borrado forzado de una cuenta en desarrollo (29/09/2026) | Baja | Hueco documentado dentro de la cadena, sin recalcularla; nuevo procedimiento (documento 08) |
| 9 | Faltaba saltar la navegación con teclado (WCAG 2.4.1) | Media | Enlace «Saltar al contenido principal» |
| 10 | El título de la pestaña era el mismo en todas las pantallas (WCAG 2.4.2) | Baja | Dice el paso y el proceso |

## 3. Controles nuevos

- **Integración continua** (`.github/workflows/calidad.yml`): pruebas con la base sin privilegios de superusuario, auditoría de dependencias, Bandit, lint y compilación en cada cambio.
- **Inventario de la IA** (`inventario_ia`): modelo y huella por uso, comparados con los aprobados; falla si hay uno sin aprobar.
- **Prueba de restauración** (`verificar_restauracion.sh`).
- **Huecos documentados en la auditoría** (`documentar_brecha_auditoria`).
- **Auditoría de accesibilidad** (`auditar_accesibilidad.py`).
- **Auditoría técnica en un comando** (`auditar_calidad.sh`), con evidencia fechada.

## 4. Pendientes

| Pendiente | Responsable | Documento |
|---|---|---|
| Aprobar formalmente los 3 modelos de IA con la medición del 27/09/2026 | Responsable de la IA | 06 |
| Escaneo con Nessus de la aplicación desplegada | Responsable de seguridad | 07 |
| Primera ejecución de la integración continua en GitHub | Desarrollo | 05 |
| Revisión de accesibilidad con lector de pantalla y zoom al 200 % | Desarrollo | 10 |
| Asignar nombres a los roles y aprobar la política | Representante legal | 01 |
| Infraestructura de LeMarTek Cloud (20 controles en fase 2) | LeMarTek | 03 |
