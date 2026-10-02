# Política de seguridad de la información de MiEvaluador

**Código:** SGSI-POL-01 · **Versión:** 1.0 · **Fecha:** 2/10/2026 · **Aprueba:** Representante legal de LeMarTek Labs S.A.S.
**Normas:** ISO/IEC 27001:2022 (5.1) · MSPI de MinTIC · Ley 1581 de 2012

## 1. Objetivo
Proteger la confidencialidad, la integridad y la disponibilidad de la información que las entidades públicas procesan en MiEvaluador —ofertas de los proponentes, datos personales, resultados de evaluación y registros de auditoría— y garantizar que la decisión sobre cada oferta quede siempre en un servidor público, con evidencia.

## 2. Alcance
El aplicativo MiEvaluador en todos sus ambientes (desarrollo, pruebas y producción), su código fuente, sus modelos de IA, sus respaldos y las personas de LeMarTek que lo desarrollan, operan o dan soporte.

## 3. Principios
1. **La información de la entidad es de la entidad.** La entidad es la responsable del tratamiento y LeMarTek la encargada (Ley 1581). LeMarTek no ve datos de una entidad sin un permiso temporal que otorga el administrador de esa entidad.
2. **Las ofertas no salen del servidor.** La IA corre localmente; ningún documento se envía a servicios de IA externos ni a API públicas. Las únicas consultas externas son a páginas oficiales (COPNIA, Policía y similares), con el dato mínimo, como lo haría el evaluador.
3. **Aislamiento entre entidades.** Cada entidad ve solo sus datos, y la base de datos lo impone por sí misma (Row-Level Security), no solo la aplicación.
4. **Mínimo privilegio y segundo factor.** Cada rol accede a lo que necesita. El segundo factor es obligatorio para todos los usuarios en producción.
5. **Todo queda registrado y nada se borra del registro.** Quién vio qué documento y quién decidió qué queda en una auditoría inalterable, encadenada con huellas criptográficas.
6. **Lo dudoso nunca se aprueba solo.** Ante la duda, el sistema manda a revisión humana; nunca aprueba por defecto.
7. **Seguridad desde el diseño.** Ningún cambio llega a producción sin pruebas automáticas, revisión de dependencias y análisis de seguridad (ver documento 05).

## 4. Roles y responsabilidades
| Rol | Responsabilidad |
|---|---|
| Representante legal de LeMarTek | Aprueba esta política, asigna recursos y revisa el sistema una vez al año. |
| Responsable de seguridad de la información | Mantiene la matriz de riesgos, los controles y la gestión de incidentes y vulnerabilidades. |
| Responsable de la IA | Mantiene el inventario de modelos y aprueba sus cambios con medición (documento 06). |
| Equipo de desarrollo | Aplica el control de cambios y el desarrollo seguro. |
| Administrador de la entidad | Crea y desactiva las cuentas de su entidad y otorga los permisos temporales de soporte. |
| Todo usuario | Protege sus credenciales, acepta el compromiso de uso y reporta incidentes. |

*(Asignar nombres en el acta de aprobación.)*

## 5. Lineamientos
- **Cuentas:** se desactivan, no se borran. Borrar una cuenta exige eliminar sus eventos de auditoría y rompe la cadena (ver documento 08).
- **Contraseñas:** mínimo 10 caracteres, no comunes ni solo numéricas; las temporales se cambian en el primer ingreso. Cinco intentos fallidos bloquean el correo durante 15 minutos.
- **Sesiones:** cookies seguras y solo HTTP; duran como máximo una jornada (10 horas).
- **Retención:** los documentos de los proponentes se borran 30 días después de aprobar el proceso (configurable por contrato); el expediente y la auditoría se conservan.
- **Respaldos:** diarios, verificados al crearse y con prueba de restauración mensual (documento 09).
- **Vulnerabilidades:** revisión de dependencias en cada cambio y escaneo con Nessus antes de cada salida a producción y cada trimestre (documento 07).
- **Material de pruebas:** las ofertas reales usadas en pruebas no se suben al repositorio de código.
- **Proveedores:** todo proveedor que trate información de las entidades firma acuerdo de confidencialidad y de transmisión de datos.

## 6. Incumplimiento
El incumplimiento se trata como incidente de seguridad (documento 08) y puede dar lugar a acciones disciplinarias o contractuales.

## 7. Revisión
Anual, o antes ante una modificación sustancial del producto, un incidente grave o un cambio normativo.
