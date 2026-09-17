# Despliegue de MiEvaluador (LeMarCloud)

## Piezas

| Servicio | Qué hace |
|---|---|
| `db` | PostgreSQL 18. La app entra con un rol **sin superusuario ni BYPASSRLS** (lo crea `despliegue/postgres-inicial.sh`); si no, el aislamiento entre entidades (Row-Level Security) no se aplicaría. |
| `migraciones` | Aplica migraciones y termina. |
| `api` | Django + Django Ninja (uvicorn, 2 procesos). |
| `trabajador` | Atiende la fila de evaluación (`manage.py trabajar_fila`). Se pueden correr varios, incluso en otras VM, contra la misma base. |
| `tareas` | Cada 24 h: retención de documentos (`aplicar_retencion`) y copia de seguridad (`scripts/respaldo.sh`, 14 días). |
| `web` | nginx: frontend compilado, proxy de `/api` y cabeceras de seguridad (CSP, HSTS, nosniff, frame DENY). |
| IA local | Ollama con `llama3.1:8b` en el nodo de IA (`LLM_URL`). Opcional: sin ella el sistema funciona y marca para revisión lo que no pueda confirmar. |

## Pasos

1. `cp despliegue/.env.ejemplo Backend/.env` y completar todas las claves (`openssl rand -base64 48` para `DJANGO_SECRET_KEY`).
2. Copiar la cuenta de servicio de Google Drive a `Backend/credentials/service_account.json` y compartir con ella las carpetas de ofertas.
3. `docker compose --env-file Backend/.env -f despliegue/docker-compose.yml up -d --build`
4. Crear el superadministrador:
   `docker compose -f despliegue/docker-compose.yml exec api python manage.py createsuperuser`
   (el primer ingreso obliga a configurar la verificación en dos pasos).
5. Publicar `web` detrás del proxy TLS de LeMarCloud con el dominio de `DJANGO_ALLOWED_HOSTS`. El proxy debe enviar `X-Forwarded-Proto: https` (con `DJANGO_DEBUG=0` Django redirige a HTTPS).
6. DNS de lemartek.com: SPF, DKIM y DMARC de Hostinger para que los correos no lleguen a spam.

## Lista de verificación antes de abrir a una entidad

- [ ] `DJANGO_DEBUG=0` (desactiva el panel de Django y los endpoints de medición).
- [ ] `DB_USUARIO` no es superusuario: `select rolsuper, rolbypassrls from pg_roles where rolname = current_user` → `f, f`.
- [ ] Correo de prueba recibido (invitación a una cuenta propia).
- [ ] Superadmin con 2FA activo.
- [ ] Respaldo diario generado y **restaurado una vez** en una base de prueba.
- [ ] `aplicar_retencion --simulacro` corre sin errores.
- [ ] Trabajador activo visible en la página **Fila**.
- [ ] Carpeta de Drive de prueba compartida con la cuenta de servicio.
- [ ] Firewall: solo el puerto del proxy abierto; PostgreSQL y Ollama sin exposición pública.

## Capacidad

Cada proponente usa hasta ~4 GB de RAM en el peor caso (RUP y pólizas escaneadas) y el carril pesado 7 GB.
Regla práctica: `MAX_WORKERS` ≈ (RAM de la VM − 6 GB) / 4. Con la medición del ICCU (81 proponentes),
2 procesos en paralelo tardan ~60 min en frío; 8 procesos (≈ 38 GB) lo bajan a ~15 min.
