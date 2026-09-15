# Requisitos jurídicos — ICCU-CM-037-2026

Tabla de referencia de los 18 requisitos de la evaluación jurídica, según la
plantilla real (`MODELO`/`P-XX`) y las explicaciones del abogado Nicolás.
`Fila` es la fila en cada hoja `P-XX` del Excel. `Estado` indica si ya está
automatizado.

| # | Fila | Requisito | Documento fuente | Criterio de cumple | Estado |
|---|------|-----------|-------------------|---------------------|--------|
| 1 | 29 | Carta de presentación de la propuesta - Formato No. 1 | Formato 1 (por título interno) | Menciona lote(s) del Documento Base, número del proceso, objeto relacionado, y el nombre declarado como representante legal coincide entre apertura y cierre de la carta | ✅ Automatizado |
| 2 | 33 | Propuesta suscrita o avalada por un Ingeniero y/o Arquitecto | COPNIA (por título interno "Consejo Profesional Nacional de Ingeniería") | El nombre del COPNIA coincide con quien firma la propuesta (Requisito 1), matrícula vigente, COPNIA con máximo 3 meses de expedido (contado desde la fecha de cierre) | ✅ Automatizado |
| 3 | 37 | Antecedentes disciplinarios profesionales del Ingeniero y/o arquitecto que avala la propuesta | El **mismo** COPNIA del Requisito 2 | El COPNIA indica que el profesional no tiene antecedentes disciplinarios, y que no está vencido (máx. 3 meses) — si el COPNIA no está vigente, no cumple y se deja constancia de que "el COPNIA aportado no está en vigencia" | ⏳ Reutiliza casi todo lo ya construido para el Requisito 2 |
| 4 | 41 | Conformación de proponente plural - Formato 2 | Formato 2 "Conformación de Proponente Plural" (solo si es Consorcio o Unión Temporal) | **N.A.** si es persona natural o persona jurídica individual. Si es Consorcio/UT: el documento debe indicar el tipo (Consorcio/UT), el listado de integrantes con su % de participación (debe sumar 100%), y estar firmado por el representante legal de cada integrante persona jurídica y por cada integrante persona natural | 🔲 Por construir |
| 5 | 45 | REDAM (Registro de Deudores Alimentarios Morosos) — nombre personalizado para este proceso, la plantilla genérica trae "Puntaje de Industria Nacional" en su lugar | Certificado REDAM (por título interno) | Debe aportarse el REDAM del representante legal (y del representante legal + suplente si es Consorcio/UT). Si no se aporta: no cumple, con nota "No aporta certificado REDAM" | 🔲 Por construir |
| 6 | 49 | Certificado de Existencia y Representación legal, con expedición no mayor a un mes | Certificado de Existencia y Rep. Legal (Cámara de Comercio) | Fecha de expedición ≤ 1 mes antes de la fecha de cierre. Si es Consorcio/UT: uno por cada integrante persona jurídica (las personas naturales solo aportan cédula) | 🔲 Por construir |
| 7 | 53 | Objeto Social acorde con el objeto de la Licitación | El mismo Certificado de Existencia y Rep. Legal | El objeto social de la empresa debe relacionarse con el objeto del proceso (ej. interventoría, obra pública, ingeniería civil) | 🔲 Por construir — reutiliza la lógica de comparación de palabras clave que ya se construyó para el objeto de la carta (Requisito 1) |
| 8 | 57 | Facultades Representante Legal | El mismo Certificado de Existencia y Rep. Legal | No debe haber restricción para contratar por cuantía/razón. Si el certificado indica un límite (ej. requiere autorización de Asamblea para montos > 500 SMMLV) y el proceso supera ese límite, debe existir un acta de autorización aparte | 🔲 Por construir — el caso del límite probablemente requiera marcarlo siempre para revisión humana, no es automatizable con certeza |
| 9 | 61 | Registro Único de Proponentes – RUP | RUP (Cámara de Comercio) | Vigencia ≤ 1 mes antes de la fecha de cierre | 🔲 Por construir |
| 10 | 65 | Sanciones | El mismo RUP | El RUP no debe registrar sanciones/multas vigentes; si las hay, se debe especificar cuál | 🔲 Por construir — depende del mismo documento del Requisito 9 |
| 11 | 69 | Garantía de Seriedad de la Propuesta conforme solicitado | Póliza / Garantía de seriedad del proponente | Beneficiario = entidad (ICCU), menciona el proceso y el lote correspondiente, vigencia ≥ 3 meses desde el cierre, valor ≥ 10% del lote de mayor valor ofertado — **estos valores objetivo ya se calculan automáticamente en la Fase 1** (`garantia_seriedad` del Documento Base); falta cruzarlos contra la póliza real del proponente | 🔲 Por construir — reutiliza directamente los valores ya calculados en Fase 1 |
| 12 | 73 | Pago de seguridad social y aportes legales | Formato de pago de seguridad social (nombre varía: "Formato 5", "Formato 6", etc.) | Documento firmado por el representante legal (y por el revisor fiscal si el certificado de existencia indica que la sociedad tiene uno). Uno por cada integrante si es plural | 🔲 Por construir |
| 13 | 77 | Registro Único Tributario - RUT | — | **N.A. siempre** — el abogado indicó que actualmente no se exige/valida este requisito | 🔲 Trivial: marcar siempre N.A. |
| 14 | 81 | Boletín de Responsables de la Contraloría General de la República | Certificado de Contraloría (antecedente estándar) | Se aporta el antecedente del representante legal (y suplente si aplica); no debe figurar como responsable fiscal | 🔲 Por construir — mismo patrón que REDAM/Procuraduría/Policía/RNMC |
| 15 | 85 | Certificado de Antecedentes Disciplinarios de la Procuraduría General de la Nación | Certificado de Procuraduría (antecedente estándar) | Igual patrón que Contraloría | 🔲 Por construir — mismo patrón genérico de "antecedente" |
| 16 | 89 | Antecedentes Judiciales Policía Nacional | Certificado de Policía Nacional (antecedente estándar) | Igual patrón que Contraloría/Procuraduría | 🔲 Por construir — mismo patrón genérico |
| 17 | 93 | Imposición de multas - Código Nacional de Policía (RNMC) | Certificado RNMC (antecedente estándar) | Igual patrón; el RNMC requiere la fecha de expedición de la cédula como dato de consulta | 🔲 Por construir — mismo patrón genérico |
| 18 | 97 | Certificado de Revisor Fiscal donde conste si la sociedad es abierta o cerrada | Certificado del Revisor Fiscal | **N.A.** si la sociedad no es S.A. Si es S.A., debe aportarse el certificado indicando si es abierta o cerrada | 🔲 Por construir |

## Reglas transversales (aplican a varios requisitos)

- **Tipo de proponente** (persona natural / persona jurídica / Consorcio / Unión
  Temporal): se puede leer directamente de la casilla "El Proponente es:" que
  ya viene en el Formato 1 (Requisito 1) — vale la pena extraerlo una sola vez
  y reutilizarlo en los Requisitos 4, 5, 6, 12, 14-17.
- **Quién es "el representante legal" a evaluar en antecedentes** (REDAM,
  Contraloría, Procuraduría, Policía, RNMC): si es proponente plural, es el
  representante legal *del consorcio/UT* (elegido) y su suplente — no cada
  integrante — según lo aclarado por el abogado. Esto se define en el
  documento del Requisito 4.
- **Vigencia de 1 mes** (Requisitos 6 y 9): mismo patrón de fecha que ya se
  construyó para el Requisito 2 (COPNIA), solo cambia el máximo (1 mes en vez
  de 3) y el documento fuente.
- **Antecedentes "estándar"** (REDAM, Contraloría, Procuraduría, Policía,
  RNMC — Requisitos 5, 14, 15, 16, 17): comparten la misma forma — un
  certificado oficial de una entidad, identificable por título interno, que
  hay que verificar que (a) exista, (b) no reporte hallazgos, y (c) esté a
  nombre de la persona correcta. Es el mismo patrón ya probado con COPNIA,
  solo cambian el título a buscar y el texto que indica "sin novedad".
