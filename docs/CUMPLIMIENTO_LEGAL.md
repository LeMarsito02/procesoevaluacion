# Cumplimiento legal: cómo MiEvaluador deja la decisión en las personas

Guía técnica para auditores, oficinas de control interno y de TI, y para el
abogado que mantiene el expediente jurídico-técnico **LEG-004**. Explica cómo el
programa cumple el **Concepto C-1015 de 2026** de la ANCP – Colombia Compra
Eficiente («no es jurídicamente válido trasladar a un sistema de inteligencia
artificial el juicio o la competencia») y dónde está cada control en el código.

## 1. El principio: el sistema verifica y propone, la persona adopta

| El sistema… | La persona… |
|---|---|
| Contrasta cada documento con la regla del pliego que la entidad confirmó | Confirma las reglas leídas del pliego, una por una |
| Da un requisito por **verificado** solo si encuentra todos los datos que la regla exige | Revisa **uno por uno** lo pendiente, los incumplimientos y las subsanaciones |
| **Nunca** emite «no cumple»: lo que no puede verificar queda pendiente | Decide el «no cumple», siempre con justificación y viendo el soporte |
| Propone un puntaje y un orden de elegibilidad **preliminares** | Adopta el puntaje proponente por proponente |
| — | Adopta lo verificado por el sistema después de la **muestra de control** |
| — | Aprueba la evaluación (jefe del área) y suscribe el informe (comité) |

## 2. Controles y dónde están

| Control | Qué hace | Código |
|---|---|---|
| Muestra de control | Sortea 10 ofertas por área (`MUESTRA_OFERTAS`) con semilla guardada; se revisa todo lo que el sistema verificó en ellas contra su soporte; un error envía todo ese requisito a revisión humana; sin muestra cerrada y posterior al último cambio no se aprueba | `Backend/evaluaciones/muestra.py`; API `/api/evaluaciones/{id}/muestra` |
| Acta de la muestra | Word con semilla, ofertas, ítems, resultados, quién y cuándo | `muestra.generar_acta`; va al expediente |
| Soporte visto antes de decidir | Decidir un requisito con documento exige haberlo abierto (evento `documento.visto` de las últimas 12 horas); sin documento, justificación de lo consultado | `muestra.exigir_soporte`; endpoint `revisiones` |
| Adopción del puntaje | El puntaje técnico se adopta proponente por proponente; la adopción caduca si cambia un factor; el orden de elegibilidad solo incluye puntajes adoptados | `Backend/evaluaciones/puntaje.py`; `motor/consolidado.py` |
| Compromiso de uso | Texto del numeral 6.4; sin aceptarlo no se decide nada; queda en la auditoría con versión e IP | `evaluaciones/cumplimiento.py` (`COMPROMISO_*`); `/api/auth/compromiso` |
| Lenguaje y rótulos | «Verificado por MiEvaluador – adoptado por…»; pre-informe hasta la adopción; puntaje y orden «preliminares»; constancia del numeral 6.2 en Word y Excel | `cumplimiento.py`, `reporte.py`, `servicios.py` |
| Auditoría inmutable | La aplicación no modifica ni borra eventos; un trigger de PostgreSQL rechaza `UPDATE` y `DELETE`; cada evento guarda una huella encadenada con el anterior | `cuentas/models.py` (`EventoAuditoria`), migración `cuentas/0007_auditoria_inmutable` |
| Verificación de la auditoría | Recalcula la cadena de huellas y dice dónde se rompe | `manage.py verificar_auditoria` |
| Procesos con expediente | No se eliminan (ni reabiertos): se archivan | `servicios.eliminar_proceso`; `/api/evaluaciones/procesos/{id}/archivar` |
| Trazabilidad | Versión del sistema y, si hubo IA, modelos usados en cada resultado; versión y modelos al aprobar | `Resultado.trazabilidad`; `Evaluacion.version_sistema`, `modelos_ia` |
| Expediente | Informe, reporte, acta de la muestra, `bitacora.csv` con todos los eventos del proceso, indicadores de revisión, regla aplicada por resultado, huellas SHA-256 | `evaluaciones/expediente.py` |
| Acceso de LeMarTek | Ni soporte ni superadministración ven procesos de una entidad sin permiso temporal que otorga su administrador (1 a 72 horas, con motivo, auditado); LeMarTek no puede dárselo a sí misma | `cuentas/seguridad.entidades_con_datos`; `api/equipo.py` |
| Transparencia algorítmica | Ficha en lenguaje claro con la configuración real (versión, modelos, licencias, controles, medición) | `evaluaciones/transparencia.py`; `/api/acerca`, `/api/acerca/ficha` |

## 3. Cómo auditar

1. **La auditoría no fue alterada:** `python manage.py verificar_auditoria`.
2. **Una muestra se puede reproducir:** con la semilla del acta y la lista de
   ofertas con verificaciones del sistema, `evaluaciones.muestra.sortear`
   devuelve las mismas ofertas.
3. **Las mediciones se pueden repetir:** `python manage.py medir_rendimiento`
   (ver `estadisticas/`).
4. **El código:** `python manage.py paquete_escrow --salida paquete.zip` genera
   el código fuente con dependencias fijadas, documentación, catálogo de reglas
   (`docs/REGLAS_DEL_MOTOR.md`, generado desde `motor/criterios.py`) y un
   manifiesto con la huella de cada archivo. Excluye secretos, credenciales y
   datos de entidades.
5. **Las pruebas:** `Backend/evaluaciones/tests_cumplimiento.py` cubre cada
   control de esta guía.

## 4. Variables de entorno

| Variable | Valor por defecto | Para qué |
|---|---|---|
| `MIEVALUADOR_VERSION` | contenido de `Backend/VERSION` | Versión registrada en evaluaciones, reportes y ficha |
| `MUESTRA_OFERTAS` | `10` (mínimo 10) | Ofertas por muestra de control |
| `SUPERADMIN_SIN_PERMISO` | `0` | `1` solo en desarrollo: el superadministrador ve todo sin permiso |

## 5. Modificaciones sustanciales

Cambiar el modelo de IA o su proveedor, la forma en que se aplican las reglas o
agregar tipos de documento o funciones es una modificación sustancial (LEG-004,
numeral 9.3): se sube la versión, se anota en `CHANGELOG.md`, se repiten las
mediciones y se actualiza la ficha del sistema.
