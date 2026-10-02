# Procedimiento de control de cambios y desarrollo seguro

**Código:** SGSI-PRO-05 · **Versión:** 1.0 · **Fecha:** 2/10/2026
**Normas:** ISO/IEC 27001 (8.25, 8.28, 8.29, 8.31, 8.32) · ISO/IEC 25010 (mantenibilidad) · ISO/IEC 42001 (control de cambios de la IA)

## 1. Tipos de cambio
| Tipo | Ejemplos | Requisitos adicionales |
|---|---|---|
| **Menor** | Textos, estilos, correcciones que no cambian resultados | Integración continua en verde |
| **Funcional** | Nueva verificación, cambio de una regla | Pruebas nuevas que lo cubran; anotarlo en `CHANGELOG.md` |
| **Sustancial** (LEG-004, 9.3) | Cambio del modelo de IA, de la forma de aplicar las reglas o nuevos tipos de documento | Nueva medición contra informes reales (aprobaciones indebidas = 0), subir la versión, aprobar el modelo con `inventario_ia --aprobar` y avisar a las entidades |

## 2. Flujo
1. **Rama:** todo cambio se hace en una rama, nunca directo en producción.
2. **Pruebas:** el cambio trae sus pruebas; un error corregido trae la prueba que lo reproduce.
3. **Integración continua** (`.github/workflows/calidad.yml`), que debe quedar en verde:
   - 617+ pruebas automáticas, con la base de datos SIN privilegios de superusuario, como en producción, para que el aislamiento entre entidades se pruebe de verdad;
   - pip-audit y npm audit sin vulnerabilidades conocidas;
   - Bandit sin hallazgos de severidad media o alta;
   - tipos, lint y compilación del frontend.
4. **Revisión:** otra persona revisa el cambio antes de integrarlo (en cambios funcionales y sustanciales).
5. **Versión:** `Backend/VERSION` sigue versionado semántico; queda registrada en cada evaluación aprobada.
6. **Despliegue:** solo imágenes construidas desde el repositorio (`docs/DESPLIEGUE.md`). Antes de desplegar:
   ```
   python manage.py inventario_ia        # sale con error si hay un modelo sin aprobar
   python manage.py verificar_auditoria
   ```
7. **Evidencia:** en cada versión, `Backend/scripts/auditar_calidad.sh`.

## 3. Reglas de desarrollo seguro
- Nada de SQL armado a mano con datos del usuario: se usa el ORM.
- Todo dato que extrae la IA se comprueba contra el texto del documento antes de usarlo.
- Ante la duda, el resultado va a revisión humana; nunca se aprueba por defecto.
- Ningún cambio introduce servicios externos que reciban documentos de las entidades sin una evaluación de riesgos aprobada.
- Los secretos viven en variables de entorno, nunca en el código ni en el repositorio.
- Las ofertas reales de prueba y las evidencias de auditoría no se suben al repositorio.
- Lo que solo vale en desarrollo depende de `DEBUG` y se apaga solo en producción.

## 4. Cambios de emergencia
Se permite desplegar una corrección urgente de seguridad antes de la revisión, con la integración continua en verde. La revisión se hace en las 48 horas siguientes y se registra como incidente (documento 08).
