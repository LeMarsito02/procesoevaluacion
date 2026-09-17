# Plan: MiEvaluador como plataforma multi-entidad

Estado: **propuesta para revisión** (no implementado).

## 1. Objetivo

Pasar de una herramienta de un solo usuario (estado en el navegador) a una plataforma donde:

- Varias **entidades** (ICCU y otras) usan el sistema **totalmente aisladas** entre sí.
- Cada entidad tiene **usuarios con roles** (administrador, coordinador, abogado…).
- Un abogado maneja **varios procesos** a la vez.
- Las evaluaciones van a una **fila central de trabajos** con posición, tiempo estimado, avance y **aviso por correo** al terminar.
- Todo queda **guardado en el servidor** (no en el navegador) con **auditoría** de quién hizo qué.

## 2. Arquitectura propuesta

```
Navegador (React)  ──HTTPS──▶  API (FastAPI)  ──▶  PostgreSQL (datos + fila de trabajos)
                                   │                       ▲
                                   │                       │ toma trabajos
                                   ▼                       │
                          Almacenamiento de archivos   Worker(s) de evaluación ──▶ OCR / IA local
                          (por entidad)                    │
                                                           └──▶ Correo (SMTP)
```

Decisiones clave:

| Tema | Propuesta | Por qué |
|---|---|---|
| Base de datos | **PostgreSQL** + SQLAlchemy 2 + migraciones Alembic | Estándar, robusto, seguridad a nivel de fila (RLS). |
| Fila de trabajos | **La misma PostgreSQL** (`SELECT … FOR UPDATE SKIP LOCKED`) | Un componente menos que Redis: menos RAM en tu PC y menos cosas que operar; aguanta de sobra el volumen esperado. Si algún día no alcanza, se cambia a Redis sin tocar la lógica. |
| Workers | Proceso separado del API (`python -m app.worker`), reutiliza la evaluación en una sola pasada actual | El API responde rápido aunque haya evaluaciones pesadas; se escalan workers por separado (en LeMarCloud, otra máquina virtual). |
| Sesión | Cookie **httpOnly + Secure + SameSite** con sesión guardada en BD | Más segura que tokens en el navegador y se puede revocar (cerrar sesión en todos lados, desactivar usuario). |
| Contraseñas | **Argon2id**, política mínima, bloqueo temporal por intentos fallidos | Buenas prácticas actuales. |
| Correo | SMTP configurable (dominio de LeMarTek) | Invitaciones, recuperar contraseña, aviso de evaluación terminada. |
| Archivos | Carpeta por entidad (`/datos/<entidad>/…`), luego almacenamiento S3 compatible en LeMarCloud | Aislamiento físico además del lógico. |

## 3. Entidades, usuarios y roles

### 3.1 Roles

| Rol | Alcance | Puede |
|---|---|---|
| **Superadministrador** (LeMarTek) | Toda la plataforma | Crear/suspender entidades, crear su primer administrador, ver métricas de uso. **No ve documentos ni resultados** de las entidades (ver pregunta 2). |
| **Administrador de entidad** | Su entidad | Invitar/desactivar usuarios y asignar roles, configurar la entidad (plantilla Excel, criterios, correo), ver todos los procesos de la entidad. |
| **Coordinador jurídico** | Su entidad | Crear procesos, asignarlos a abogados, ver y revisar todos los procesos, cerrar/aprobar informes. |
| **Abogado evaluador** | Procesos asignados | Crear procesos, evaluar, revisar casos, generar informe. |
| **Consulta** | Procesos asignados | Solo lectura (ej. control interno). |

Permisos definidos en un solo lugar del backend (matriz rol × acción), probados automáticamente.

### 3.2 Aislamiento entre entidades (lo más importante)

Tres capas, para que un error en una no exponga datos:

1. **Aplicación**: toda consulta pasa por un repositorio que exige `entidad_id` de la sesión; no existe una forma de consultar "sin entidad". Si alguien pide un proceso de otra entidad, la respuesta es **404** (ni siquiera confirma que existe).
2. **Base de datos**: **Row-Level Security** de PostgreSQL en todas las tablas con `entidad_id`; la conexión fija la entidad de la sesión. Aunque el código tuviera un error, la BD no devuelve filas ajenas.
3. **Archivos y cachés**: carpeta por entidad; las cachés de resultados se separan por entidad (las de OCR/IA se indexan por el contenido del archivo, así que no revelan nada que el usuario no tenga ya).

Más:
- **Pruebas automáticas de aislamiento**: por cada endpoint, un usuario de la entidad A intenta leer/modificar recursos de la entidad B y debe fallar.
- **Auditoría**: registro inmutable de accesos y acciones (quién, qué, cuándo, desde dónde).
- Credenciales de Google Drive **por entidad** (cada entidad comparte sus carpetas con su propia cuenta de servicio, o sube los zip directamente).

## 4. Procesos y fila de trabajos

### 4.1 Ciclo de vida de un proceso

```
Borrador ─▶ En fila ─▶ Evaluando ─▶ En revisión ─▶ Finalizado
   ▲            │           │              │
   └── editar   └ cancelar  └ pausar       └ reabrir (coordinador)
```

- **Borrador**: datos del Documento Base cargados y revisados (pasos 1–2 actuales).
- **En fila**: posición y tiempo estimado visibles.
- **Evaluando**: avance por proponente en vivo.
- **En revisión**: resultados listos; el abogado decide los pendientes (paso 3 actual), guardado en el servidor.
- **Finalizado**: informe generado; queda la versión del informe y quién lo aprobó.

### 4.2 Fila central

- Cada **proponente** es un trabajo. Estados: pendiente → en curso → terminado / error.
- **Reparto justo**: el worker toma el siguiente trabajo alternando entre entidades y, dentro de la entidad, entre procesos (una evaluación de 150 proponentes no bloquea a otra de 10).
- **Tiempo estimado** = trabajos por delante × tiempo medio real por proponente ÷ workers activos (se recalcula con datos reales).
- **Robustez**: si un worker muere, sus trabajos vuelven a la fila (latido cada X segundos); reintento aislado de proponentes pesados (ya existe); cancelar/pausar un proceso quita sus trabajos pendientes.
- **Avance en vivo** en la interfaz (Server-Sent Events o consulta periódica).
- **Correo** al abogado cuando termina (con enlace directo al proceso) y si falla algo.

## 5. Interfaz (solo modo claro, marca MiEvaluador)

Pantallas nuevas:
1. **Inicio de sesión**, recuperar contraseña, aceptar invitación (definir contraseña).
2. **Mis procesos** (tablero): tarjetas/tabla con estado, avance, posición en fila, pendientes por revisar, abogado asignado, fecha de cierre; filtros y búsqueda.
3. **Nuevo proceso**: el asistente actual (pasos 1–2), ahora guardado como borrador en el servidor; opción de **subir los zip** además de Drive.
4. **Proceso**: la evaluación y revisión actuales (paso 3) e informe (paso 4), con historial de decisiones.
5. **Administración de la entidad**: usuarios y roles, invitaciones, plantilla Excel, criterios configurables (ej. vigencia COPNIA 3 meses, certificados 1 mes), conexión con Drive, correo.
6. **Superadministración** (LeMarTek): entidades, uso, estado de la fila y workers.
7. **Mi perfil**: nombre, contraseña, notificaciones.

## 6. Modelo de datos (resumen)

`entidades`, `usuarios` (entidad, rol, estado), `sesiones`, `invitaciones`, `procesos` (entidad, creador, asignados, estado, datos del Documento Base), `proceso_lotes`, `proponentes`, `trabajos` (fila), `resultados` (por proponente y requisito), `revisiones` (decisión del abogado, usuario, fecha, nota), `informes` (archivo generado, versión, usuario), `configuracion_entidad` (criterios, plantilla), `auditoria`.

## 7. Fases

| Fase | Contenido | Resultado verificable |
|---|---|---|
| **F0. Base** | PostgreSQL, migraciones, configuración por entorno, estructura de módulos | La app actual funciona igual sobre la nueva base. |
| **F1. Identidad y aislamiento** | Entidades, usuarios, roles, sesión, invitaciones, recuperación de contraseña, RLS, auditoría, **pruebas de aislamiento** | Usuarios de dos entidades de prueba no se ven entre sí (pruebas automáticas en verde). |
| **F2. Procesos en el servidor** | Guardar procesos, resultados y revisiones en BD; tablero "Mis procesos"; asignación a abogados | Cerrar el navegador o cambiar de equipo no pierde nada; historial de decisiones. |
| **F3. Fila de trabajos** | Worker separado, reparto justo, posición y ETA, pausar/cancelar, recuperación ante caídas, correo al terminar | Varias evaluaciones simultáneas de distintos usuarios avanzan en orden y avisan por correo. |
| **F4. Administración** | Panel de entidad (usuarios, plantilla, criterios, Drive, subida de zip), panel de superadmin | Una entidad nueva se configura sin tocar código. |
| **F5. Endurecimiento** | 2FA opcional, límites de peticiones, políticas de retención, copias de seguridad, despliegue en LeMarCloud (contenedores) | Lista de verificación de seguridad completa. |

Cada fase se entrega funcionando y probada antes de pasar a la siguiente.

## 8. Preguntas para decidir antes de empezar

1. **Inicio de sesión**: ¿correo y contraseña propios del sistema para empezar, y luego inicio con Microsoft/Google institucional? (recomendado)
2. **Superadministrador y datos**: ¿LeMarTek debe poder ver documentos/resultados de una entidad para dar soporte? Recomendación: **no por defecto**; solo si el administrador de la entidad lo autoriza temporalmente y queda auditado.
3. **Roles**: ¿sirven los cinco propuestos (superadmin, administrador, coordinador, abogado, consulta)?
4. **Visibilidad entre abogados de una misma entidad**: ¿un abogado ve todos los procesos de su entidad o solo los que tiene asignados? Recomendación: solo los asignados; coordinador y administrador ven todos.
5. **Fuente de ofertas**: ¿solo Google Drive, o también subir los zip directamente? (recomendado ambas)
6. **Criterios por entidad**: ¿cada entidad puede ajustar reglas como la vigencia del COPNIA (3 meses) o de certificados (1 mes)? (recomendado sí, con valores por defecto)
7. **Correo**: ¿con qué dominio/servidor se envían los correos (ej. no-responder@lemartek.com)?
8. **Retención**: ¿cuánto tiempo se guardan los documentos de los proponentes después de finalizado el proceso?
