# Plan: MiEvaluador como plataforma multi-entidad y multi-evaluación

Estado: **propuesta v2 para revisión** (no implementado). Incorpora las decisiones del 17/09/2026.

## 1. Objetivo

Pasar de una herramienta de un solo usuario a una plataforma donde:

- Varias **entidades** usan el sistema **totalmente aisladas** entre sí.
- Cada proceso de contratación tiene **varias evaluaciones**: **jurídica**, **técnica** y **financiera** (y otras que se agreguen), cada una con sus propios requisitos, equipo y responsables.
- Un **jefe de área** asigna evaluaciones a los integrantes de su equipo, que hacen las revisiones manuales.
- Las evaluaciones van a una **fila central de trabajos** con posición, tiempo estimado, barra de avance y **aviso por correo** (desde @lemartek.com).
- Las entidades **ajustan los criterios** y pueden **crear requisitos nuevos** desde un panel.
- Todo queda en el servidor, con **auditoría**, y los documentos de los proponentes se eliminan **30 días** después de finalizado el proceso.

## 2. Decisiones tomadas

| # | Tema | Decisión |
|---|---|---|
| 1 | Inicio de sesión | Correo y contraseña propios. En la pantalla de login se muestran también **Microsoft**, **Google** y **Empleados LeMarTek** como "próximamente"; se implementan en el backend más adelante. |
| 2 | Acceso a datos de una entidad | Nadie de LeMarTek ve datos de una entidad salvo con **permiso temporal** del administrador de esa entidad (auditado). **Excepción: el superadministrador `santiagopebe01@lemartek.com`**, con acceso total. |
| 3 | Roles | Se usan los propuestos, ajustados por área (ver §3). |
| 4 | Visibilidad | Cada usuario trabaja solo en **sus** evaluaciones asignadas; además hay una página para **consultar todos los procesos de la entidad** (solo lectura). |
| 5 | Fuente de ofertas | **Solo Google Drive** por ahora. |
| 6 | Criterios | Cada entidad ajusta los criterios y puede **agregar requisitos nuevos** desde el panel (ver §5). |
| 7 | Correo | Envío desde un dominio **@lemartek.com**. |
| 8 | Retención | Documentos de proponentes: se eliminan **30 días** después de finalizado el proceso. |

## 3. Usuarios, áreas y roles

Cada usuario pertenece a una entidad y a una o más **áreas** (Jurídica, Técnica, Financiera…).

| Rol | Alcance | Puede |
|---|---|---|
| **Superadministrador** | Toda la plataforma | Todo: crear/suspender entidades, ver uso, estado de la fila y workers, acceso a datos (con 2FA obligatorio y auditoría). |
| **Administrador de entidad** | Su entidad | Usuarios, áreas y roles; configuración (criterios, requisitos, plantillas, Drive, correo); ver todos los procesos. |
| **Jefe de área** (ej. abogado en jefe) | Su área en su entidad | Crear procesos; **asignar evaluaciones** de su área a su equipo; ver el avance de todo su equipo; revisar y **aprobar** el informe de su área. |
| **Evaluador** (abogado, ingeniero, contador) | Evaluaciones asignadas | Revisar los casos pendientes, decidir, generar el informe de su evaluación. |
| **Consulta** | Su entidad, solo lectura | Ver procesos, resultados e informes sin modificar nada. Útil para control interno, supervisión, dirección o veeduría. |

Todos los usuarios pueden ver la página **"Procesos de la entidad"** (solo lectura del listado y el estado).

## 4. Motor de evaluación común + tipos de evaluación

Las tres evaluaciones comparten el 80 % del trabajo (descargar de Drive, descomprimir, leer PDF, OCR, detectar documentos, IA local verificada, fila, revisión humana, informe). Lo que cambia es **qué requisitos** se verifican y **cómo**.

```
                        ┌──────────── Motor común ────────────┐
Ofertas (Drive) ──▶     │ descarga · zip/rar · lectura PDF    │
                        │ OCR · detección de documentos       │
                        │ IA local verificada · caché         │
                        └───────────────┬─────────────────────┘
                                        │ "catálogo de documentos" del proponente
             ┌──────────────────────────┼──────────────────────────┐
             ▼                          ▼                          ▼
   Tipo JURÍDICA               Tipo TÉCNICA               Tipo FINANCIERA
   17 requisitos (hecho)       experiencia, personal      indicadores: liquidez,
                               clave, Formato 3, RUP…     endeudamiento, cobertura,
                                                          capital de trabajo…
             │                          │                          │
             └──── resultados + revisión humana + informe (plantilla por tipo) ───┘
```

- Un **tipo de evaluación** declara: su catálogo de requisitos, los documentos que necesita, sus evaluadores, su plantilla de informe y sus criterios configurables.
- Un proceso puede tener **una, dos o las tres** evaluaciones; cada una con su responsable, avance, pendientes e informe.
- Las evaluaciones de un mismo proceso **comparten la lectura de documentos**: el proponente se descarga y lee una sola vez.
- La jurídica actual pasa a ser el primer tipo, sin cambiar su lógica ni su acierto.

**Para construir la técnica y la financiera se necesitan ejemplos reales** (como se hizo con la jurídica): el informe de evaluación técnica y financiera de un proceso, la plantilla Excel de cada una y las reglas que aplican el ingeniero y el contador. Con eso se miden contra la realidad, igual que la jurídica (85,5 %).

## 5. Criterios configurables y requisitos nuevos desde el panel

Tres niveles, de lo más simple a lo más flexible:

1. **Ajustar parámetros** de requisitos existentes: vigencias (COPNIA 3 meses, certificados 1 mes), porcentaje de la garantía, umbrales de indicadores financieros, requisito activo/inactivo, obligatorio/no aplica. Formularios simples.
2. **Crear requisitos a partir de plantillas de regla** (sin programar). El administrador arma el requisito combinando bloques ya probados:
   - *Qué documento*: título o frases que lo identifican (ej. "CERTIFICADO DE…").
   - *Qué dato extraer*: fecha de expedición, valor, nombre, cédula/NIT, frase.
   - *Qué verificar*: vigencia máxima N meses a la fecha de cierre · valor ≥ fórmula · frase de "sin novedad" presente · nombre/cédula coincide con el representante o integrantes · aplica solo a persona jurídica / plural.
   - Ejemplo: "Certificado de la Junta Central de Contadores del contador, vigencia máxima 3 meses, debe decir *NO REGISTRA ANTECEDENTES*".
3. **Requisito asistido por IA**: el administrador lo describe en lenguaje natural; la IA local **propone** la regla usando los mismos bloques del nivel 2; el administrador la **prueba contra ofertas reales** de un proceso anterior (ve en qué proponentes cumple o no y por qué) y solo entonces la **activa**. La IA nunca decide sola: arma la regla, y la regla se verifica como todas.

Cada cambio de criterios queda **versionado**: una evaluación siempre registra con qué versión de reglas se hizo (importante ante reclamaciones).

## 6. Procesos, asignaciones y fila de trabajos

### 6.1 Ciclo de vida

Proceso (datos del Documento Base) → una o más **evaluaciones** (jurídica/técnica/financiera), cada una:

```
Sin asignar ─▶ Asignada ─▶ En fila ─▶ Evaluando ─▶ En revisión ─▶ Aprobada
                                           │              │
                                        pausar      reabrir (jefe)
```

- El **jefe de área** crea el proceso (o lo recibe) y **asigna** la evaluación de su área a un evaluador (o a varios, repartiendo proponentes).
- El evaluador recibe un **correo** con la asignación.
- Al terminar la evaluación automática, el evaluador revisa los pendientes; el jefe **aprueba** y se emite el informe.

### 6.2 Fila central

- Cada **proponente** es un trabajo; la lectura de documentos se hace una vez y alimenta los tipos de evaluación del proceso.
- **Reparto justo** entre entidades y procesos (una evaluación grande no bloquea a otra pequeña).
- **Tiempo estimado** = trabajos por delante × tiempo medio real ÷ workers activos.
- Recuperación ante caídas (trabajos huérfanos vuelven a la fila), reintento aislado, pausar/cancelar.
- **Correo** al terminar y si algo falla.

## 7. Páginas

| Página | Para quién | Contenido |
|---|---|---|
| **Login** | Todos | Correo y contraseña; botones Microsoft / Google / Empleados LeMarTek (próximamente); recuperar contraseña; aceptar invitación. |
| **Mis evaluaciones** | Evaluador, jefe | Lista de mis evaluaciones con **barra de progreso animada**, estado, posición en fila, **tiempo estimado**, pendientes por revisar, fecha de cierre; filtros y búsqueda. |
| **Procesos de la entidad** | Todos (lectura) | Todos los procesos con sus evaluaciones, avance, responsables y estado. |
| **Equipo y asignaciones** | Jefe de área | Evaluaciones sin asignar, carga de trabajo de cada integrante (evaluaciones y pendientes), asignar/reasignar, avance del equipo. |
| **Nuevo proceso** | Jefe / evaluador | Asistente actual (Documento Base, Drive, datos), eligiendo qué evaluaciones incluye. |
| **Evaluación** | Asignados | Matriz, revisión e informe (lo actual), por tipo de evaluación. |
| **Fila de trabajos** | Administrador, superadmin | Qué se está evaluando, cola, workers, tiempos. |
| **Administración de la entidad** | Administrador | Usuarios, áreas, roles, invitaciones; criterios y requisitos (§5); plantillas de informe; Drive; permisos temporales de soporte. |
| **Superadministración** | Superadmin | Entidades, uso, salud del sistema, auditoría global. |
| **Mi perfil** | Todos | Datos, contraseña, notificaciones. |

## 8. Aislamiento y seguridad

1. **Aplicación**: toda consulta exige la entidad de la sesión; recursos de otra entidad responden 404.
2. **Base de datos**: Row-Level Security de PostgreSQL por `entidad_id`.
3. **Archivos y cachés** separados por entidad.
4. **Pruebas automáticas de aislamiento** en cada endpoint.
5. **Auditoría** inmutable (accesos, asignaciones, decisiones, cambios de criterios, permisos de soporte).
6. **2FA obligatorio** para el superadministrador y recomendado para administradores.
7. **Retención**: tarea diaria que elimina los documentos de proponentes 30 días después de aprobada la última evaluación del proceso (se conservan resultados, decisiones e informes).
8. Contraseñas Argon2id, sesiones en cookie httpOnly/Secure, bloqueo por intentos, límites de peticiones.

## 9. Arquitectura técnica

- **Django 6 + Django Ninja** (API tipada, ORM, migraciones, sesiones, CSRF y hashing Argon2 integrados) servido con Uvicorn (ASGI).
- **PostgreSQL** (datos, fila de trabajos con `SKIP LOCKED`, RLS).
- **Workers** de evaluación separados de la API; el paquete `motor/` (Python puro, sin Django) conserva toda la lógica de evaluación.
- **Motor común** + **registro de tipos de evaluación** (jurídica como primer tipo).
- **Correo SMTP** @lemartek.com. Almacenamiento de archivos por entidad (S3 compatible en LeMarCloud).
- Frontend React con enrutamiento por páginas, misma marca y solo modo claro.

## 10. Fases

| Fase | Contenido | Resultado verificable |
|---|---|---|
| **F0. Base** ✅ | Migración de FastAPI a Django + Django Ninja, PostgreSQL, migraciones, configuración, estructura del motor común y registro de tipos (jurídica migrada sin cambiar su acierto) | La medición jurídica da el mismo 85,5 %. |
| **F1. Identidad y aislamiento** ✅ | Entidades, áreas, usuarios, roles, login (+ botones de próximamente), invitaciones, recuperación, auditoría, superadmin con 2FA, pruebas de aislamiento. La RLS se aplica en F2 sobre las tablas de datos de la entidad (procesos, evaluaciones, documentos) | Dos entidades de prueba no se ven entre sí. |
| **F2. Procesos, evaluaciones y asignaciones** ✅ | Procesos con varias evaluaciones; asignación por jefe; "Mis evaluaciones", "Procesos de la entidad", "Equipo y asignaciones"; revisiones guardadas en el servidor; RLS de PostgreSQL con rol de base de datos sin privilegios | Un jefe asigna, el evaluador revisa desde otro equipo sin perder nada. |
| **F3. Fila de trabajos** | Worker separado, reparto justo, barras de progreso y ETA en vivo, pausar/cancelar, recuperación, correos | Varias evaluaciones de distintos usuarios avanzan en orden y avisan por correo. |
| **F4. Criterios configurables** | Nivel 1 (parámetros) y nivel 2 (plantillas de regla) con prueba contra ofertas reales y versionado | Una entidad crea un requisito nuevo sin programar y lo prueba. |
| **F5. Tipos técnica y financiera** | Con los ejemplos reales: catálogos, evaluadores, plantillas, medición contra informes reales | Acierto medido de cada tipo. |
| **F6. IA para requisitos y endurecimiento** | Nivel 3 (requisito asistido por IA), retención de 30 días, límites, copias de seguridad, despliegue en LeMarCloud | Lista de verificación de seguridad completa. |

## 11. Pendiente por definir

1. **Ejemplos para técnica y financiera**: informes reales, plantillas Excel y criterios del ingeniero y del contador (para F5).
2. **Retención**: al eliminar documentos a los 30 días, ¿se conservan resultados, decisiones e informes? (propuesta: sí).
3. **Asignación**: ¿un jefe asigna la evaluación completa a una persona, o también puede repartir proponentes de un mismo proceso entre varios evaluadores? (propuesta: ambas).
4. **Aprobación**: ¿el informe debe aprobarlo el jefe antes de descargarlo como definitivo? (propuesta: sí, con borrador descargable antes).
