# Procedimiento de gestión de incidentes de seguridad

**Código:** SGSI-PRO-08 · **Versión:** 1.0 · **Fecha:** 2/10/2026
**Normas:** ISO/IEC 27001 (5.24 a 5.28, 6.8) · lineamientos de seguridad digital de MinTIC · Ley 1581 de 2012

## 1. Qué es un incidente
Todo evento que comprometa o pueda comprometer la confidencialidad, la integridad o la disponibilidad de la información de MiEvaluador. Por ejemplo:
- acceso de una entidad a datos de otra, o de un tercero a cualquier dato;
- cuenta usada por alguien distinto de su titular;
- `verificar_auditoria` reporta una rotura no documentada;
- vulnerabilidad crítica explotable (documento 07);
- pérdida de datos o respaldo que no se puede restaurar;
- una aprobación indebida detectada después de adoptar un informe;
- caída del servicio en plena evaluación.

## 2. Clasificación
| Nivel | Criterio | Tiempo de respuesta |
|---|---|---|
| **Crítico** | Datos personales o de ofertas expuestos; auditoría alterada; aprobación indebida en un informe adoptado | Inmediato (≤ 2 horas) |
| **Alto** | Vulnerabilidad crítica sin explotar; servicio caído en evaluación | ≤ 8 horas |
| **Medio** | Falla sin exposición de datos | ≤ 2 días hábiles |
| **Bajo** | Evento sin efecto | Próxima revisión |

## 3. Pasos
1. **Reporte:** cualquier persona lo reporta al responsable de seguridad de LeMarTek por el canal de soporte acordado con la entidad.
2. **Registro:** se abre un registro con fecha, quién reporta, qué pasó y nivel.
3. **Contención:** según el caso, desactivar cuentas, retirar el permiso de soporte, pausar la fila de evaluación o aislar el servidor.
4. **Evidencia:** preservar antes de corregir:
   - `python manage.py verificar_auditoria` y una exportación de los eventos;
   - un respaldo de la base en ese momento (`scripts/respaldo.sh`);
   - los registros del servidor.
5. **Erradicación y recuperación:** corregir con el procedimiento de emergencia del documento 05 y, si hace falta, restaurar (documento 09).
6. **Comunicación:**
   - **A la entidad afectada:** siempre en incidentes críticos y altos, dentro del plazo del contrato.
   - **A la Superintendencia de Industria y Comercio:** si hubo violación de datos personales, la entidad (responsable del tratamiento) reporta; LeMarTek (encargado) le entrega la información necesaria.
   - **A colCERT:** en incidentes de ciberseguridad relevantes.
7. **Cierre y lecciones aprendidas:** causa raíz, controles nuevos, actualización de la matriz de riesgos (documento 02).

## 4. Caso especial: huecos en la auditoría
La auditoría no se puede modificar ni borrar desde la aplicación. Si alguien con acceso a la base desactiva esa protección y borra eventos (por ejemplo, para eliminar a la fuerza una cuenta), la cadena de huellas se rompe:

1. Si el borrado fue **autorizado**, se documenta el hueco sin recalcular la cadena:
   ```
   python manage.py documentar_brecha_auditoria --motivo "..." --por "Nombre, cargo"
   ```
   El comando se niega si el evento fue **modificado** (no falta ningún evento antes de la rotura).
2. Si el borrado o la modificación **no fueron autorizados**, es un incidente crítico.

**Lo indicado para retirar a una persona es desactivar su cuenta, no borrarla.**

## 5. Registro de incidentes
| Fecha | Descripción | Nivel | Acción | Estado |
|---|---|---|---|---|
| 29/09/2026 | Borrado forzado de una cuenta en el entorno de desarrollo; se eliminaron 3 eventos de auditoría (36–38) | Bajo (desarrollo, autorizado por el titular) | Hueco documentado en la auditoría (evento 283) el 2/10/2026 | Cerrado |
