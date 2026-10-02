# Procedimiento de gestión de vulnerabilidades

**Código:** SGSI-PRO-07 · **Versión:** 1.0 · **Fecha:** 2/10/2026
**Normas:** ISO/IEC 27001 (8.8, 8.29, 8.34) · lineamientos de seguridad digital de MinTIC

## 1. Fuentes y frecuencia

| Herramienta | Qué revisa | Cuándo |
|---|---|---|
| **pip-audit** | Vulnerabilidades conocidas en las dependencias de Python | Cada cambio (integración continua) |
| **npm audit** | Vulnerabilidades conocidas en las dependencias del frontend | Cada cambio |
| **Bandit** | Análisis estático de seguridad del código Python | Cada cambio |
| **Nessus** | Escaneo de la aplicación desplegada y de su infraestructura | Antes de cada salida a producción, cada trimestre y tras cambios de infraestructura |
| **Prueba de penetración** | Ataque controlado por un tercero | Anual (`docs/PLAN_PRUEBAS_ATAQUE.md`) |

## 2. Escaneo con Nessus

Nessus está instalado en el equipo de desarrollo (`/opt/nessus`). **Solo se escanean sistemas propios o con autorización escrita.**

### Encenderlo (requiere permisos de administrador)
```
sudo systemctl start nessusd
```
Abrir https://localhost:8834, crear la cuenta y activar la licencia. La primera vez descarga los plugins, lo que puede tardar.

### a) La aplicación, ahora
Escanear el aplicativo **como queda en producción** (nginx con sus cabeceras de seguridad y sin DEBUG), no el servidor de desarrollo: en desarrollo no hay cabeceras ni restricciones, y el informe saldría con hallazgos que en producción no existen.
1. Levantar la pila de producción en local, siguiendo `docs/DESPLIEGUE.md`: `docker compose -f despliegue/docker-compose.yml up -d`. Queda en el puerto 8080.
2. En Nessus: **New Scan → Web Application Tests**.
   - Objetivo: `127.0.0.1`, puerto 8080.
   - El certificado TLS lo pone el proxy de LeMarTek Cloud, delante de nginx: los hallazgos de TLS se revisan en la fase b).
   - Sin credenciales, para ver lo que ve un atacante externo.
3. Un segundo escaneo **Basic Network Scan** al mismo objetivo, para puertos y servicios expuestos.
4. Exportar los informes (**Report → PDF** y **.nessus**) a `docs/normas/evidencias/AAAA-MM-DD/`.

### b) LeMarTek Cloud, cuando esté montado
- **Basic Network Scan** desde fuera, a las IP públicas.
- **Advanced Scan con credenciales** (SSH) a cada servidor, para parches y configuración.
- Escaneo de cumplimiento contra los CIS Benchmarks del sistema operativo, si la licencia lo permite.
- Coordinarlo fuera de horarios de evaluación (control 8.34): nunca en plena evaluación de un proceso.

## 3. Tiempos de corrección

| Severidad (CVSS) | Plazo máximo |
|---|---|
| Crítica (9,0–10) | 72 horas, o se retira el servicio afectado |
| Alta (7,0–8,9) | 15 días |
| Media (4,0–6,9) | 60 días |
| Baja (0,1–3,9) | Próxima versión, o se acepta con justificación |

Un hallazgo que no se corrige se acepta formalmente: queda escrito por qué, con responsable y fecha de nueva revisión.

## 4. Registro
Cada hallazgo va a la tabla siguiente y se cierra con la evidencia del nuevo escaneo.

| Fecha | Herramienta | Hallazgo | Severidad | Acción | Estado |
|---|---|---|---|---|---|
| 2/10/2026 | pip-audit | urllib3 2.7.0: PYSEC-2026-4175, -4176 y -4177 | Alta | Actualizado a 2.8.0 | Cerrado |
| 2/10/2026 | npm audit | brace-expansion: tres DoS (GHSA-q2hr-2g5m-vwhr y otros) | Alta (solo desarrollo) | `npm audit fix` | Cerrado |
| 2/10/2026 | Bandit | 12 usos de MD5/SHA-1 (B324) | Alta según Bandit; real: ninguna, son claves de caché | Declarados `usedforsecurity=False` | Cerrado |
| 2/10/2026 | Bandit | Candado de la IA en `/tmp` (B108) | Media | Movido a la carpeta de la aplicación | Cerrado |
| 2/10/2026 | Bandit | `urlopen` sin restringir esquema (B310) | Media | `LLM_URL` solo http(s); URL fijas del SECOP revisadas | Cerrado |
| 2/10/2026 | Revisión manual | Segundo factor solo para superadministrador y soporte | Alta | Obligatorio para todos en producción | Cerrado |
| 2/10/2026 | Revisión manual | El respaldo diario se cortaba en silencio sin `RESPALDO_DIR` | Alta | Corregido; prueba de restauración | Cerrado |
| — | Nessus | Escaneo de la aplicación | — | Pendiente | Abierto |
