# Plan de trabajo de MiEvaluador

Estado: 24/09/2026. Los números salen de las mediciones guardadas en
`estadisticas/` y del dataset de 16 procesos del ICCU (`datasetdepruebas/`).

## 0. El objetivo doble (manda sobre todo lo demás)

> Que se revise lo menos posible, y que jamás se apruebe uno indebidamente.

La tentación al querer bajar las revisiones es relajar los criterios. Está
prohibido: fue lo que produjo la aprobación indebida de P-81 en ICCU-LP-022 al
aflojar el emparejamiento de actas.

**Las revisiones se bajan atacando sus causas, nunca bajando el listón.** Cada
revisión tiene una causa medible; arreglar la causa quita la revisión sin
tocar la seguridad. Así se desbloquearon los 11 proponentes de ICCU-LP-027 al
leer el anticipo del pliego, y así se resolvió el área de las actas.

### Las cinco palancas para revisar menos sin arriesgar

1. **Confirmar una vez por proceso, no por proponente.** Un parámetro del
   pliego sin confirmar manda a revisión a los 107 proponentes del proceso;
   confirmarlo una vez los libera todos. Igual con el rango de la Matriz 2 y
   con los requisitos que el motor no verifica.
2. **Revisión dirigida, no de la oferta entera.** Si un requisito queda en
   duda, debe ir a revisión ese requisito, no el proponente completo.
3. **Dejar el trabajo hecho para quien revisa:** el documento en la página
   correcta, el número a comparar y la cita. La métrica no es solo cuántas
   revisiones, sino cuántos minutos cuesta cada una.
4. **Ante la duda numérica, la lectura que no aprueba.** Ya se hace con el
   saldo de contratos en ejecución y con la holgura del 50 % en la capacidad
   residual; es regla general.
5. **El rechazo también exige evidencia.** Rechazar por un error de lectura es
   riesgo legal igual que aprobar de más: se aprueba con evidencia, se rechaza
   con evidencia, y todo lo demás es revisión.

### Cómo se mide

| Indicador | Meta | Si falla |
|---|---|---|
| Aprobaciones indebidas | **0, sin excepción** | bloquea la entrega |
| Decisiones que el programa toma solo | subirlo sin tocar el anterior | se optimiza |
| Minutos de revisión por oferta | bajarlo | se optimiza |

El primero es una condición, no una métrica a optimizar.

## 1. La garantía contra aprobaciones indebidas

No se puede prometer un 0 % de error de lectura con documentos escaneados. Lo
que sí es una propiedad estructural del sistema: **el programa nunca aprueba
un requisito que no verificó.**

Ya está garantizado en cinco frentes:

- lo que el pliego exige y no se puede medir (área, longitud, porcentaje de un
  contrato) va a revisión;
- lo que el pliego exige y el motor no sabe verificar se nombra y va a
  revisión (`motor/pliego/catalogo_tecnico.py`);
- un dato que no se pudo leer nunca se vuelve un "no aplica" aprobado
  (patrimonio, sociedad anónima, tipo de proponente);
- las cifras y fechas imposibles van a revisión (RUP con activos negativos,
  plazo o anticipo fuera de rango, certificados muy posteriores al cierre);
- lo que solo vio la IA no aprueba hasta que una persona lo confirme
  (`motor/pliego/fusion.py`).

### Huecos por cerrar

1. **El "no se presentó a este lote" se deduce por ausencia.** Si se lee mal
   la carta, ese lote sale N/A y se aprueba sin evaluar. Debe exigir cita.
2. **El catálogo puede dar por cubierto un requisito que en realidad no
   verificamos** (falso positivo del emparejamiento por palabras). Revisar una
   vez, contra los 14 pliegos, lo que dice cubrir.
3. **La medición solo cubre 3 procesos con ofertas.** Cero indebidas en 417
   proponentes no prueba nada sobre procesos no vistos.

### Red de seguridad permanente

- Prueba de regresión con los casos conocidos: P-81 de LP-022, P-26 y P-55 de
  LP-027. Si alguno se aprueba, la entrega se bloquea.
- Trazabilidad: cada decisión guarda su motivo, su archivo y su cita.

## 2. Lo que falta implementar

| Fase | Qué | Cuánto pesa |
|---|---|---|
| A | ~~Filtrar el ruido del catálogo~~ **Hecho** (24/09/2026) | 498 → 410 frenan. Cada frase del pliego se clasifica por el riesgo de ignorarla: exclusión (48), exigencia (324), regla de lectura (38) frenan; permiso (39) y encabezado no. Los permisos se muestran antes de rechazar. Lo de proponentes extranjeros nunca se da por verificado |
| B | ~~El 50 % de experiencia de un integrante del proponente plural~~ **Hecho** (24/09/2026) | El motor ya lo verificaba (50 %, 5 % y uno sin aportar); el catálogo no lo reconocía escrito en plural. La regla exige que el aporte sea de experiencia o un porcentaje, para no tapar «los integrantes deben aportar el certificado de antecedentes» |
| C | **Personal clave** (director, residente, profesionales: formación, experiencia, acta de grado, tarjeta) | 39+ casos, área nueva completa; es el corazón de los concursos de méritos |
| D | Huecos de lectura del pliego: CM-016 no se leyó, plazo falta en 5 de 14, lotes en 0 en 2, CM-045 lee 31 meses | — |
| E | Extranjeros y apostilla | 34 casos; propuesta: dejarlo siempre en revisión |

## 3. Mejorar lo que ya existe

| Qué | Cuánto pesa |
|---|---|
| El saldo de contratos en ejecución (Formato 5C) | 48 de 98 en LP-022, 21 de 32 en MC-019 |
| El acta de un contrato que aún no se encuentra | 6 de 11 en LP-027 |
| El Formato 3 en PDF con el encabezado partido | hoy va a revisión con el motivo correcto |
| Elegir el rango de la Matriz 2 con el criterio que ella misma da (SMMLV) | 13 procesos |
| Tiempo por oferta | mediana 49 s, picos de 332 s |

## 4. Verificación continua

1. Ofertas de 3 o 4 procesos más.
2. Banco de pliegos con su verdad esperada y una prueba que los verifique
   todos, para no comprobar a mano que un arreglo no rompió otro pliego.
3. Tablero de medición por proceso guardado en `estadisticas/`.

## Orden de ejecución

**Primero (mayor efecto, sin tocar el criterio de aprobación):**

1. ~~Confirmar una vez por proceso: un parámetro o un requisito asumido libera
   a todos los proponentes.~~ **Hecho** (24/09/2026). `requisitos_asumidos` en
   `AnalisisPliego`, `GET/POST /{id}/requisitos-pliego`, pantalla
   `RequisitosPliego.tsx`. La clave del requisito aguanta que la IA lo lea con
   otras palabras pero no que cambie una cifra, para que asumir «5 años» no dé
   por revisado «8 años».
2. ~~Revisión dirigida: que un requisito sin verificar sea su propio punto del
   informe y no tumbe el lote entero.~~ **Hecho** (24/09/2026). `PuntoDeRevision`
   con ámbito («proceso» = del pliego, igual para todos; «oferta» = de esta
   oferta), `experiencia_acreditada` en técnica y `capacidad_acreditada()` en
   financiera, expuestos en el detalle del requisito y en `QueFaltaRevisar.tsx`.
   Un lote cuya experiencia está acreditada y solo espera algo del pliego lo
   dice así, en vez de parecer un incumplimiento. Sigue sin aprobarse solo.
3. ~~Filtrar el ruido del catálogo.~~ **Hecho**: ver la fase A. Lo que bajó el
   conteo no fue borrar requisitos, fue clasificarlos por riesgo; y quien de
   verdad baja el costo es la palanca 1 (una vez por proceso).
4. ~~El 50 % de experiencia del integrante.~~ **Hecho**: ver la fase B.
5. Los tres huecos de la garantía.

**Después:** personal clave, el SCE, el Formato 3 en PDF.

**Al final:** banco de pliegos, medición con más ofertas, tiempo por oferta.
