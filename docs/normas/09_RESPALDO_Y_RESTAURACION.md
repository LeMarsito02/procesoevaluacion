# Procedimiento de respaldo y restauración

**Código:** SGSI-PRO-09 · **Versión:** 1.0 · **Fecha:** 2/10/2026
**Normas:** ISO/IEC 27001 (8.13) · ISO/IEC 25010 (fiabilidad: recuperabilidad)

## 1. Qué se respalda
- La base de datos completa (`pg_dump`), con el usuario de mantenimiento: con el usuario de la aplicación, el aislamiento por entidad filtraría las filas y el respaldo quedaría vacío.
- Los archivos subidos por las entidades (`Backend/almacenamiento/`).
- Una suma SHA-256 de cada archivo.

No se respaldan las ofertas en caché (se regeneran) ni los modelos de IA (se descargan de nuevo y se verifican con `inventario_ia`).

## 2. Respaldo
```
Backend/scripts/respaldo.sh
```
- **Frecuencia:** diaria (cron o temporizador de systemd).
- **Verificación:** al crearlo se comprueba que el archivo se pueda leer.
- **Conservación:** 14 días (`RESPALDO_DIAS`).
- **Destino:** `RESPALDO_DIR` (por defecto `~/respaldos/mievaluador`), con permisos 700/600.
- **Copia fuera del servidor:** obligatoria en producción; se define con LeMarTek Cloud (fase 2).

## 3. Prueba de restauración
```
Backend/scripts/verificar_restauracion.sh
```
Restaura el último respaldo en una base **temporal** (no toca la de la aplicación) y comprueba:
1. las sumas SHA-256;
2. que la restauración termina sin errores, y cuánto tarda;
3. que hay datos (entidades, usuarios, procesos, resultados, auditoría);
4. que la cadena de la auditoría restaurada está íntegra.

Al final borra la base temporal y deja una línea en `restauraciones.log`, junto a los respaldos: esa es la evidencia.

- **Frecuencia:** mensual, y después de cada cambio de infraestructura.
- **Objetivos:** pérdida máxima de datos (RPO) de 24 horas; restauración (RTO) en menos de 4 horas.

## 4. Restauración real
```
pg_restore -h HOST -p PUERTO -U SUPERUSUARIO -d mievaluador --clean --if-exists db_FECHA.dump
tar xzf almacenamiento_FECHA.tar.gz -C Backend/
python manage.py verificar_auditoria
python manage.py inventario_ia
```
Restaurar en producción es un incidente (documento 08): se registra.

## 5. Registro de pruebas
| Fecha | Respaldo | Resultado |
|---|---|---|
| 2/10/2026 | `db_20261002_081844.dump` | Sumas correctas · restaurado en 1 s · 2 entidades, 5 usuarios, 7 procesos, 1.572 resultados, 280 eventos · auditoría íntegra |

La prueba del 2/10/2026 destapó una falla: sin `RESPALDO_DIR` en `.env`, el respaldo diario terminaba en silencio sin hacerse. Quedó corregida (documento 07).
