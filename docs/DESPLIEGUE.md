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
| IA local | Ollama en el nodo de IA (`LLM_URL`): `llama3.1:8b` para los documentos de la oferta y `qwen3:14b` (o `qwen3:4b` sin GPU) para leer el pliego completo. Opcional: sin ella el sistema funciona y marca para revisión lo que no pueda confirmar. |
| Consultas en línea | Playwright + Chromium en la imagen de `api`: el sistema trae solo el RNMC y el COPNIA y los adjunta al expediente. Sin esto el botón avisa y el evaluador sube el certificado a mano. |

## Pasos

1. `cp despliegue/.env.ejemplo Backend/.env` y completar todas las claves (`openssl rand -base64 48` para `DJANGO_SECRET_KEY`).
2. Copiar la cuenta de servicio de Google Drive a `Backend/credentials/service_account.json` y compartir con ella las carpetas de ofertas.
3. `docker compose --env-file Backend/.env -f despliegue/docker-compose.yml up -d --build`
4. Crear el superadministrador:
   `docker compose -f despliegue/docker-compose.yml exec api python manage.py createsuperuser`
   (el primer ingreso obliga a configurar la verificación en dos pasos).
5. Publicar `web` detrás del proxy TLS de LeMarCloud con el dominio de `DJANGO_ALLOWED_HOSTS`. El proxy debe enviar `X-Forwarded-Proto: https` (con `DJANGO_DEBUG=0` Django redirige a HTTPS).
6. DNS de lemartek.com: SPF, DKIM y DMARC de Hostinger para que los correos no lleguen a spam.

Requerimientos completos del servidor (hardware, paquetes, puertos, variables): **docs/REQUERIMIENTOS_SERVIDOR.txt**.

## Inicio de sesión con Microsoft (Entra ID)

Opcional. Sin configurarlo, el botón aparece como «No habilitado» y todos entran con contraseña.

1. En Entra ID, registrar la aplicación «MiEvaluador» con cuentas de **cualquier directorio organizativo** (multiinquilino), tipo **Web**.
2. Dirección de retorno: `https://<dominio>/api/auth/microsoft/retorno` (en desarrollo, `http://localhost:5173/api/auth/microsoft/retorno`). Debe coincidir con `FRONTEND_URL`.
3. Crear un secreto de cliente y poner en `Backend/.env`: `MICROSOFT_CLIENT_ID` y `MICROSOFT_CLIENT_SECRET`. Anotar su vencimiento: al vencer, nadie entra con Microsoft.
4. Permisos: solo `openid`, `profile` y `email` (los de iniciar sesión). No pedir acceso al directorio.
5. Por cada entidad, el superadministrador registra el **identificador del directorio** de la entidad en *Entidades → Microsoft*. El área de sistemas de la entidad debe aprobar la aplicación en su directorio.
6. Reiniciar `api`.

Entra solo quien ya tiene usuario en MiEvaluador y cuya cuenta es del directorio registrado para su entidad. El segundo factor de MiEvaluador se sigue pidiendo según el rol. Superadministrador y soporte entran siempre con contraseña y segundo factor.

### Carpetas de ofertas en el OneDrive de la entidad (Microsoft 365)

Las entidades siguen pegando el **enlace** de la carpeta de ofertas. Si el enlace
es de su OneDrive o SharePoint (`…sharepoint.com`), MiEvaluador lo lee con
Microsoft Graph usando la misma aplicación del inicio de sesión, con un permiso
de **solo lectura de archivos**. Solo se leen enlaces del directorio de la
propia entidad: el directorio sale de la dirección del enlace y se compara con
el registrado en *Entidades → Microsoft* (también al crear el proceso).

1. En la aplicación «MiEvaluador» de Entra ID agregar el permiso **de
   aplicación** de Microsoft Graph `Files.Read.All` (no el delegado).
2. Agregar la dirección de retorno `https://<dominio>/api/auth/microsoft/onedrive-retorno`.
3. Por cada entidad: *Entidades → Microsoft → «Enlace para el administrador»*,
   y enviarlo al **administrador global** de Microsoft 365 de la entidad. Al
   abrirlo aprueba el permiso para su directorio y ve una página de confirmación.
4. Pulsar **«Probar»**: MiEvaluador pide a Microsoft un token para ese
   directorio y comprueba que trae el permiso. Si después la entidad lo revoca,
   «Probar» lo detecta y lo desmarca.

Sin la aprobación, al pegar el enlace sale el aviso «La entidad aún no autoriza
a MiEvaluador a leer su OneDrive». Los enlaces de OneDrive personal (`1drv.ms`)
y de Google Drive funcionan como antes.

## Al desplegar una versión nueva

1. `manage.py migrate`
2. `manage.py depurar_requisitos` — si las reglas del pliego dejaron de exigir algo (un formato de puntaje, un duplicado de lo que el motor ya verifica), quita esos resultados de las evaluaciones en curso para que no sigan contando como pendientes. Las evaluaciones aprobadas no se tocan.
3. Reiniciar `api` **y** `trabajador` (el trabajador mantiene el código en memoria).
4. Si la versión cambia el modelo de IA o la forma de aplicar las reglas, es una **modificación sustancial** (expediente LEG-004, numeral 9.3): subir `Backend/VERSION`, anotarla en `CHANGELOG.md`, repetir `medir_rendimiento` y avisar a las entidades.

## Lista de verificación antes de abrir a una entidad

- [ ] `DJANGO_DEBUG=0` (desactiva el panel de Django y los endpoints de medición).
- [ ] `PROXIES_CONFIABLES` igual al número de proxies delante de la app (si no, los límites y el bloqueo por intentos se aplican a la IP del proxy y afectan a todos).
- [ ] `DB_USUARIO` no es superusuario: `select rolsuper, rolbypassrls from pg_roles where rolname = current_user` → `f, f`.
- [ ] Correo de prueba recibido (aviso de cuenta creada a una cuenta propia).
- [ ] Superadmin con 2FA activo.
- [ ] Respaldo diario generado y **restaurado una vez** en una base de prueba.
- [ ] `aplicar_retencion --simulacro` corre sin errores.
- [ ] Trabajador activo visible en la página **Fila**.
- [ ] Carpeta de Drive de prueba compartida con la cuenta de servicio.
- [ ] `SUPERADMIN_SIN_PERMISO` sin definir o en `0`: el superadministrador solo ve los procesos de una entidad con permiso temporal de su administrador (LEG-004, 4.5).
- [ ] `manage.py verificar_auditoria` dice «Auditoría íntegra» (la cadena de huellas de la auditoría no está rota).
- [ ] `MUESTRA_VERIFICACIONES` en 10 o más (verificaciones por muestra de control y por área; la entidad puede exigir más).
- [ ] `manage.py paquete_escrow --salida …` genera el paquete para el depósito del código (si el contrato lo prevé).
- [ ] Firewall: solo el puerto del proxy abierto; PostgreSQL y Ollama sin exposición pública.
- [ ] Cifrado en reposo (RF-21): `cifrar_archivos --verificar` sin archivos en claro, respaldos `.age` copiados a `RESPALDO_REMOTO` y el disco de Docker sobre LUKS.

## Capacidad

Cada proponente usa hasta ~4 GB de RAM en el peor caso (RUP y pólizas escaneadas) y el carril pesado 7 GB.
Regla práctica: `MAX_WORKERS` ≈ (RAM de la VM − 6 GB) / 4. Con la medición de referencia (81 proponentes de un proceso real),
2 procesos en paralelo tardan ~60 min en frío; 8 procesos (≈ 38 GB) lo bajan a ~15 min.

## Prestación de servicios (OPS)

Módulo con licencia aparte: una entidad lo ve con candado hasta que se le
activa.

1. Aplicar las migraciones (`manage.py migrate`) y reiniciar el backend **y el
   trabajador**: el trabajador de la fila es quien lee los documentos de cada
   contratación.
2. Activar el módulo en la entidad: *Entidades → OPS*, o
   `manage.py honorarios_iccu --nit <NIT>`, que además registra la tabla de
   honorarios 2026 del ICCU (Resolución 1750 de 2025). Las demás entidades
   registran la suya en *OPS → Tabla de honorarios*, una por vigencia.
3. Retención: `manage.py aplicar_retencion` (el mismo comando diario) borra
   las copias de los documentos de las contrataciones confirmadas hace más de
   `RETENCION_DIAS`. Se conservan lo leído, lo decidido y quién confirmó.
4. No usa la IA: lee con reglas y con OCR (Tesseract, ya incluido en la
   imagen). No necesita GPU ni Ollama.
5. Límite de carga: cada envío admite hasta 50 MB
   (`DATA_UPLOAD_MAX_MEMORY_SIZE` y `client_max_body_size` de nginx). Un
   expediente típico pesa entre 8 y 21 MB; lo que no quepa se agrega después
   desde la pantalla de la contratación.
6. Para medir el módulo con un expediente real, sin guardar nada:
   `manage.py medir_ops <carpeta de la entidad> <carpeta del contratista> --fecha AAAA-MM-DD --nit <NIT>`.

## Bitácora inmodificable (RF-20)

La auditoría la protegen tres cosas: el trigger que rechaza UPDATE y DELETE
(y otro para TRUNCATE), la cadena de huellas (`manage.py verificar_auditoria`)
y que la aplicación **no sea dueña de las tablas**. El contenedor
`migraciones` corre con el rol de mantenimiento (`DB_ADMIN_USUARIO`) y, después
de `migrate`, `manage.py asegurar_permisos_bd --rol-app <DB_USUARIO>`, que:

- pasa al rol de mantenimiento la propiedad de lo que tuviera la aplicación
  (una instalación anterior a esta versión se corrige sola en el primer
  despliegue);
- le deja a la aplicación lectura y escritura en sus tablas, y en la auditoría
  solo SELECT e INSERT;
- revisa todo y falla el despliegue si la auditoría no quedó protegida.

Para comprobarlo en cualquier momento:
`manage.py asegurar_permisos_bd --rol-app mievaluador_app --verificar`.
Criterio de aceptación: con el rol de la aplicación, un UPDATE, DELETE o
TRUNCATE sobre `cuentas_eventoauditoria` falla, y `ALTER TABLE … DISABLE
TRIGGER` también (no es dueña).

En desarrollo la aplicación sigue siendo dueña de todo (para poder migrar
con un solo rol): ahí el verificador informa el problema, y es lo esperado.


## Cifrado en reposo (RF-21)

Tres capas:

1. **Archivos con datos personales, cifrados por la aplicación** (AES-256-GCM):
   documentos aportados, expedientes, pliegos, actas, ofertas económicas,
   documentos de las OPS (cédulas, certificados) y la caché de ofertas
   descargadas de Drive o subidas a mano. La clave es `CLAVE_CIFRADO_ARCHIVOS`;
   sin ella el despliegue no arranca. Un archivo alterado no se entrega: falla
   la verificación de su etiqueta. Las plantillas de informe (formatos en
   blanco) quedan en claro.
   - Generarla: `manage.py cifrar_archivos --generar-clave`, y guardar una
     copia en la bóveda de la entidad. **Si se pierde, los archivos no se
     pueden recuperar.**
   - El contenedor `migraciones` cifra lo que haya quedado en claro de una
     versión anterior. Para comprobarlo: `manage.py cifrar_archivos
     --verificar` (falla si queda algo en claro).
   - Rotarla: poner la nueva primero (`CLAVE_CIFRADO_ARCHIVOS=nueva,anterior`),
     desplegar y correr `manage.py cifrar_archivos --rotar`. Cuando
     `--verificar` diga «0 con una clave anterior», ya se puede quitar la
     anterior.
2. **Respaldos cifrados y fuera del servidor**: con `RESPALDO_DESTINATARIO_AGE`
   (clave pública de [age](https://age-encryption.org)) cada respaldo queda
   cifrado y se borra la copia en claro. La clave privada **no** se guarda en
   el servidor: la tiene la entidad. Con `RESPALDO_REMOTO` (destino de
   rclone) cada respaldo se copia fuera del servidor principal y se comprueba
   que llegó igual. Con `CIFRADO_OBLIGATORIO=1` (así está en el
   docker-compose), un respaldo sin destinatario falla en vez de quedar en
   claro. Para la prueba de restauración:
   `RESPALDO_IDENTIDAD_AGE=/ruta/clave.txt scripts/verificar_restauracion.sh`
   en un equipo que tenga la clave privada.
3. **Base de datos y cachés de texto en un disco cifrado**: PostgreSQL
   (volumen `datos`) y las cachés de OCR e IA (volumen `cache`, con texto
   extraído de los documentos) van en el disco de la VM, que debe estar cifrado
   (LUKS, o el cifrado de volúmenes de LeMarCloud). Comprobarlo con
   `lsblk -o NAME,TYPE,FSTYPE,MOUNTPOINT`: el disco de
   `/var/lib/docker` debe colgar de un dispositivo `crypt`.

Criterio de aceptación: `cifrar_archivos --verificar` sin archivos en claro,
los respaldos con extensión `.age` en el servidor y en el remoto, y el disco de
Docker sobre un dispositivo `crypt`.

## OCR con PaddleOCR

Las páginas escaneadas se leen con **PaddleOCR** (PP-OCRv5, español) en el
contenedor `ocr`, con la GPU. Solo escucha dentro de la red de Docker y los
documentos no salen del servidor. Medido en el pliego escaneado ICCU-LP-014-2026
(73 páginas): Tesseract dejó 540 símbolos y palabras pegadas y no pudo leer el
plazo («¿cuo (08) … Cepo»); PaddleOCR dejó 9 y leyó «OCHO (08) MESES». En una
RTX 3050 de 4 GB tarda unos 2 s por página.

- `OCR_MOTOR=paddle` (así viene en el docker-compose) y `OCR_SERVICIO_URL=http://ocr:8866`.
  Con `OCR_MOTOR=tesseract` se vuelve al de antes.
- Si el servicio no responde, la página se lee con Tesseract y queda un
  **error** en el registro del backend: es una lectura de menor calidad.
- Las lecturas se guardan aparte por motor (`cache/ocr` y `cache/ocr_paddle`).
- Los modelos se descargan la primera vez y quedan en el volumen `modelos_ocr`.
- PaddleOCR a veces escribe la letra O por el cero dentro de códigos y cifras
  («ICCU-LP-O14-2026»); el backend lo corrige solo dentro de códigos y cifras.
- También la fecha de expedición de la cédula (lectura a fondo y recorte para la
  IA de visión). Medido en las 25 personas de ICCU-CM-043-2026 e ICCU-LP-027-2026
  contra la fecha impresa: PaddleOCR, 22 de 24 fechas confiables y ninguna
  equivocada; Tesseract, 16 y una equivocada dada por buena. `OCR_MOTOR_CEDULA`
  permite usar otro motor solo para la cédula.

En desarrollo, `Backend/scripts/iniciar_dev.sh` levanta el servicio si el `.env`
tiene `OCR_MOTOR=paddle`, con el entorno de `OCR_ENTORNO` (por defecto
`~/.local/share/mievaluador-ocr`, Python 3.12 con `Backend/ocr_servicio/requirements.txt`).

## Ofertas subidas desde el equipo (hasta 10 GB por archivo)

Las ofertas que se suben desde el equipo llegan **por pedazos de 32 MB**
(`/api/procesos/subidas`): cada pedazo cabe en el `client_max_body_size 60m`
de nginx, una caída de la red no pierde lo ya subido (se retoma desde lo que
llegó, también si se recarga la página y se eligen los mismos archivos) y el
servidor nunca tiene el archivo entero en memoria. El trabajador reparte las
ofertas desde el disco, una a la vez, y borra los temporales.

- Límites: `SUBIDA_MAXIMA_ARCHIVO` (12 GB) y `SUBIDA_MAXIMA_CARGA` (20 GB por proceso).
- Los pedazos van a `cache/subidas` y los temporales de Django a
  `cache/temporales` (no a `/tmp`, que en muchos equipos vive en la RAM).
  El volumen `cache` debe tener espacio para las cargas simultáneas más 2 GB:
  si no alcanza, la subida se rechaza de entrada con un mensaje claro.
- Las subidas abandonadas se borran a los 2 días (`aplicar_retencion`).
- Para ofertas muy pesadas sigue siendo mejor una carpeta compartida: el
  servidor las descarga directo, sin depender de la red de quien evalúa.
