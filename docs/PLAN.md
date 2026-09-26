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

1. ~~**El "no se presentó a este lote" se deduce por ausencia.**~~ **Cerrado**
   (24/09/2026): se toma la unión de la carta de presentación y la garantía de
   seriedad, hace falta que fallen las dos lecturas, y cuando discrepan se
   evalúan todos los lotes y se avisa. El N.A. dice de dónde salió y a qué
   lotes sí se presenta. Antes: si se lee mal
   la carta, ese lote sale N/A y se aprueba sin evaluar. Debe exigir cita.
2. ~~**El catálogo puede dar por cubierto un requisito que en realidad no
   está cubierto.**~~ **Cerrado** (24/09/2026): se revisaron los 448 requisitos
   que el catálogo declaraba cubiertos en los 14 pliegos. Se encontraron 55
   falsos positivos, todos aprobaciones indebidas potenciales: el personal clave
   (39) lo tapaba la regla del puntaje porque el pliego lo describe en ese
   capítulo; el rango financiero de las mipymes; y el reparto de actividades del
   proponente plural. Hay una lista explícita de temas que el motor no verifica
   y que ganan sobre todas las reglas. Los requisitos que frenan subieron de 408
   a 463: el número creció porque el sistema dejó de mentirse. Texto anterior:
   el catálogo puede dar por cubierto un requisito que en realidad no
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
| C | ~~**Personal clave**~~ **Hecho** (25/09/2026) · planteamiento del 24/09 | El documento tipo dice que los soportes del personal **no se evalúan con la oferta**: «no se evaluarán los soportes de los perfiles requeridos, por lo que no serán exigidos como parte de los documentos que conformen la propuesta»; se verifican tras firmar el contrato. Lo que sí es de la etapa: que estén el Formato 8 (causal de rechazo) y el Formato 9 (para los 5+5 puntos), diligenciados y suscritos. Programado: `tecnica.personal_clave` (habilitante, nº 111) y `tecnica.personal_clave_adicional` (puntaje, nº 129) verifican que los dos formatos estén, sean de este proceso, no sean la plantilla en blanco y estén suscritos. Se buscan por lo que dicen, no por su número, porque en el documento tipo de obra el «Formato 8» es el de discapacidad. Los soportes siguen sin verificarse, que es lo que el pliego manda. En los 14 pliegos, los requisitos que frenan bajaron de 461 a 427 |
| D | Huecos de lectura del pliego: CM-016 no se leyó, plazo falta en 5 de 14, lotes en 0 en 2, CM-045 lee 31 meses | — |
| E | Extranjeros y apostilla | 34 casos; propuesta: dejarlo siempre en revisión |

## 3. Mejorar lo que ya existe

| Qué | Cuánto pesa |
|---|---|
| El saldo de contratos en ejecución (Formato 5C) | 48 de 98 en LP-022, 21 de 32 en MC-019 |
| El acta de un contrato que aún no se encuentra | 6 de 11 en LP-027 |
| El Formato 3 en PDF con el encabezado partido | hoy va a revisión con el motivo correcto |
| ~~Elegir el rango de la Matriz 2 con el criterio que ella misma da (SMMLV)~~ **Hecho** (24/09/2026) | 13 de 13 matrices se resuelven solas: el rango sale del presupuesto del lote en SMMLV y se usa la tabla de «los demás proponentes», no la de Mipyme, que es más laxa. Ya no hay que registrar los umbrales a mano. Las mediciones anteriores de LP-027 usaban por error los de Mipyme (liquidez 1,1 en vez de 1,2) |
| Tiempo por oferta | mediana 49 s, picos de 332 s |

## 3 bis. El registro de lo que no automatizamos

Cada proceso evaluado deja anotado, en `RequisitoNoAutomatizado`, lo que su
pliego exige y el programa no sabe verificar: el texto, la cita, la clase, en
cuántos procesos ha aparecido y —lo que manda— **cuántas veces una persona tuvo
que asumirlo**, porque eso es trabajo humano que se repetirá en el siguiente
proceso.

Se consulta con `manage.py que_falta_automatizar` o con
`GET /api/evaluaciones/requisitos-no-automatizados` (solo superadministración y
soporte: junta información de varias entidades). Cuando se programe la
verificación de uno, se anota en su campo `verificacion` y deja de pedirse.

Tiene un hermano, `CausaDeRevision`, que mide la otra mitad: no lo que el pliego
pide y no verificamos, sino lo que **sí sabemos verificar y la lectura falló** en
una oferta (no se encontró el acta de un contrato, no se leyó el ingreso
operacional, no apareció el RUP de un integrante). Se cuenta por oferta, porque
eso es el trabajo humano: una lectura que falla en 48 de 98 ofertas cuesta 48
revisiones. Conviene no confundirlos: uno se arregla programando una verificación
nueva, el otro mejorando una lectura que ya existe. Se consulta con el mismo
comando y con `GET /api/evaluaciones/causas-de-revision`.

No cambia ninguna evaluación y nunca da nada por cumplido: es la hoja de ruta,
sacada de los pliegos reales en vez de suposiciones. Cargado con los 14 pliegos
del ICCU da 253 requisitos distintos, 27 de ellos exclusiones. En la primera
lectura de esa lista aparecieron dos falsos negativos del catálogo (la tarjeta
profesional del contador y la terminación del contrato antes del cierre), que ya
están arreglados: de 461 requisitos que frenaban se pasó a 438.

### Medición de ICCU-LP-027 (11 ofertas, 24/09/2026)

Escenario real de uso: el evaluador confirma una vez los parámetros del pliego y
asume una vez los requisitos que el programa no verifica.

| | Resultado |
|---|---|
| Aprobaciones indebidas | **0** |
| Decisiones iguales al informe del ICCU | 6 de 22 (1 técnica, 5 financiera) |
| Mediana por oferta | ~30 s (pico de 209 s) |

Las causas de lo que quedó a revisión, ya en el registro:

- **técnica**: el acta o certificación de un contrato no aparece (3 ofertas), el
  área intervenida (1), el objeto de un contrato que no se puede clasificar ni
  descartar (1), experiencia de un socio (1).
- **financiera**: el ingreso operacional que no se lee de los estados financieros
  (4 ofertas, es la causa mayor), el RUP de un integrante que no aparece (2), y
  certificados de la Junta Central de Contadores vencidos al cierre (3). **Criterio
  resuelto** (25/09/2026): tiene que estar vigente al cierre y, si no lo está, va a
  revisión, no a rechazo —que es lo que el motor ya hacía—. Lo que se arregló es el
  costo de revisarlo: el motivo dice de quién es la tarjeta, cuándo venció, cuántos
  días antes del cierre y en qué archivo está, y cada certificado es su propio punto
  de revisión. Consultarlo en línea no serviría: uno expedido después del cierre no
  prueba que estuviera vigente al cierre.

## 3 ter. La lectura del pliego, comprobada contra lo publicado

La entidad publica en el SECOP el presupuesto oficial y el plazo de cada proceso, y
eso está en el portal de datos abiertos. Comparar esas dos cifras con las que sale
del PDF es la forma más barata de saber si un pliego se leyó mal:

    manage.py verificar_lectura_pliegos

Al 25/09/2026, con 20 pliegos en el dataset: **18 coinciden al peso**, uno no tiene
datos publicados con ese código (LP-035) y uno no corresponde (LP-010-2025: el PDF
del dataset dice 2.392 millones a 5 meses y lo publicado son 36.539 a 21, así que
el archivo no es de la versión final de ese proceso).

Esa comparación encontró tres pliegos por lotes que se leían como si tuvieran uno
solo —LP-035 («Lote No. 1»), LP-038 (la columna trae solo el número)— y en todos el
presupuesto del proceso quedaba siendo el del primer lote, con el que se calculan el
capital de trabajo, la capacidad residual y la experiencia exigida. Es el tipo de
error que no se ve en una prueba con texto inventado.

Los procesos se descubren con `manage.py buscar_procesos_secop`. Los documentos no
se pueden bajar por comandos: el portal responde con un reCAPTCHA a lo que no venga
de un navegador, y eso no se fuerza.

## 3 quater. Qué mejorar en cada área, por lo que pesa

Sale de las mediciones contra informes reales y de los dos registros. Cada línea
trae cuántas revisiones costó, porque esa es la unidad: una lectura que falla en
30 de 97 ofertas cuesta 30 revisiones.

### Jurídica — una sola causa explica casi todo

En ICCU-LP-022 (97 proponentes) los cuatro certificados de antecedentes son lo
peor del área, y **fallan por lo mismo**:

| Certificado | Se resuelve solo | Revisiones | Causa dominante |
|---|---|---|---|
| Medidas correctivas (RNMC) | 36 % | 62 | «no se encontró por título» (37) |
| Responsabilidad fiscal (Contraloría) | 39 % | 59 | «no se encontró por título» (33) |
| Antecedentes disciplinarios (Procuraduría) | 41 % | 57 | «no se encontró por título» (31) |
| Antecedentes judiciales (Policía) | 44 % | 54 | «no se encontró por título» (35) |

**136 revisiones de un solo proceso** por no encontrar un documento que casi
siempre está en la oferta. Vale la pena averiguar por qué no se encuentra antes de
tocar nada: si son escaneos sin texto, si el título cambia, o si vienen dentro de
un PDF combinado con otros documentos. Es la mejora más rentable del proyecto.

Lo demás del área, en orden:

- **Aval del ingeniero** (53 % en LP-022): el COPNIA no se encuentra (8) o está
  expedido hace más de tres meses (6). Lo segundo no es un fallo: es el criterio
  del abogado y debe seguir yendo a revisión.
- **Seguridad social** (66 %): en proponentes plurales se confirma el formato de
  un integrante y no de los demás (19).
- **Carta de presentación** (77 %): el objeto de la carta no se parece al del
  Documento Base (7).

### Técnica — la experiencia, y dos factores de puntaje

- **Experiencia por lote**: es lo que menos se decide solo (11 % en el lote 2 de
  LP-022, 26 % en el lote 1). Las causas concretas, del registro de LP-027 y
  CM-043: el acta o certificación de un contrato que no aparece en la oferta, el
  área intervenida que no se puede dar por cumplida, y el objeto de un contrato
  que no se puede ni aceptar ni descartar.
- **Vinculación de personas con discapacidad** (40 %) y **empresas de mujeres**
  (43 %): los dos factores de puntaje que más revisión piden.
- El **Formato 3 en PDF con el encabezado partido** sigue yendo a revisión con el
  motivo correcto.

### Financiera — el capital de trabajo y la capacidad residual

- **Capital de trabajo por lote**: 13 % y 16 %, lo peor de todo el sistema (150
  revisiones entre los dos lotes de LP-022).
- **Capacidad residual** (19 %): el Formato 5C no se encuentra, o el saldo de los
  contratos en ejecución no se puede leer.
- **Validez de los documentos** (51 %): el certificado de la Junta Central de
  Contadores vencido al cierre (criterio resuelto: va a revisión) y los estados
  financieros de un integrante que no aparecen.
- **El ingreso operacional** que no se lee de los estados financieros: en LP-027
  fue la causa financiera número uno (4 de 11 ofertas).

En cambio los indicadores financieros y organizacionales ya van al 90 %.

### Por dónde empezaría

1. Los cuatro antecedentes jurídicos: una sola causa, 136 revisiones.
2. El ingreso operacional y el Formato 5C: destraban capital de trabajo y
   capacidad residual, que son lo peor del sistema.
3. El acta o certificación de contrato que no aparece: la causa técnica número uno.

Estas cifras son de la medición del 22/09/2026 para jurídica; el motor cambió
bastante desde entonces, así que conviene volver a medirla antes de decidir.

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
