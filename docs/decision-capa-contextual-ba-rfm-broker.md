# Análisis — Capa Contextual objetivo: BA/Analyst, RFM/RT-J, Context Broker

**Tipo:** registro de análisis del worklist de
[handoff-capa-contextual-objetivo.md](handoff-capa-contextual-objetivo.md) §7 (Q4, Q10, Q2).

**Fecha:** 2026-08-09.

> **Nota sobre este documento.** Una primera versión cerró BA y RFM como "no justificados"
> apoyándose en los 18 recibos de la Fase 3. Esa conclusión era inválida y fue retirada: el
> corpus de la Fase 3 fue construido para medir resolución de schema, no interpretación de
> requerimientos ni cobertura relacional, y usarlo para responder Q4/Q10 repite exactamente el
> error de validez de instrumento que [fase3-decision.md](fase3-decision.md) documenta. Lo que
> sigue es el análisis corregido, con las mediciones que la primera versión no hizo.

---

## Resultado

| Pregunta | Respuesta | Estado de la pieza |
|---|---|---|
| **Q4** — ¿qué fallo observado arreglaría un BA? | **Sin responder.** El corpus disponible no puede contestarla. | **BA: abierto**, pendiente de un corpus válido |
| **Q10** — ¿hay un caso donde el cierre de FK falla y un RFM acertaría? | **Sí, hay caso.** Reproducible hoy, en este repo. | **Necesidad viva**, detrás de un arreglo determinista más barato |
| **Q8/Q9/Q11** — RT-J concretamente | **Circular**: exige como entrada el contexto relevante ya seleccionado, que es justamente lo que Q10 pide resolver. | **RT-J: descartado** (5 motivos, ver §Q8/Q9/Q11) |
| **Q2** — ¿qué gana un Broker con 2 proveedores? | **Nada, hoy.** | **Broker: diferido** (sin cambios) |

**Además — hallazgo no previsto por el worklist, y probablemente lo más accionable de todo este
análisis:** la capa de schema grounding *ya construida* tiene un modo de falla silencioso
demostrable (§4). No tiene que ver con BA, RFM ni Broker.

---

## Q4 — ¿Qué fallo observado, concreto, arreglaría un BA?

**Respuesta: no se puede contestar con la evidencia que existe. La pregunta sigue abierta.**

El corpus disponible son los 18 recibos de la Fase 3 (`tests/results/schema_ab/raw/`), que
cubren **9 queries distintas**:

```
Add a discount code field to orders      Improve error handling in the api
Add a due date field to tasks            Improve logging across the service
Add a phone number column to Cliente     Index the sku column for faster lookup
Add an index on the amount_cents column  Clean up unused configuration files
Add an index on the montoTotal column
```

Un BA produce entidades de dominio, **reglas de negocio**, criterios de aceptación y
ambigüedades. Ninguna de esas 9 queries contiene una regla de negocio: seis son operaciones DDL
atómicas de un solo campo o índice, y las tres restantes son mantenimiento genérico sin
dominio. No hay stakeholders en conflicto, no hay criterios de aceptación implícitos, no hay
lógica de negocio que malinterpretar.

Por lo tanto "0 de 15 breakdowns malinterpretaron el requerimiento" **no es evidencia de que un
BA no sirva** — es ausencia de evidencia producida por un instrumento que no podía detectar la
cosa. Es el mismo error que la Fase 3 diagnosticó en `check_identifiers()`: medir con un
aparato no válido para la pregunta y leer el resultado como si lo fuera.

Lo que sí quedó verificado, y vale por separado: en las 3 ambigüedades genuinas que el corpus
sí contiene (`amount_cents` existe en 3 tablas; falta una tabla de descuentos; goal genérico sin
archivos visibles), **el Manager pidió aclaración explícita o señaló el gap por su cuenta**, sin
etapa adicional. Es un dato a favor de la hipótesis "el BA no hace falta", pero sobre
ambigüedad *estructural*, que no es la que el BA promete resolver.

**Para cerrar Q4 de verdad hace falta:** un corpus de queries con reglas de negocio reales
(varias entidades, criterios de aceptación, restricciones de dominio) y revisar ahí si el
breakdown del Manager las malinterpreta. Sin eso, cerrar el BA sería una decisión sin sustento,
en cualquiera de las dos direcciones.

---

## Q10 — ¿Hay un caso donde el cierre de FK determinista falla y un RFM acertaría?

**Respuesta: sí, y está codificado a propósito en un fixture de este mismo repo.**

`tests/fixtures/schema/hostile_naming.json`, textualmente:

```json
{ "name": "facturas",
  "comment": "Invoices — snake_case, plural, Spanish, no declared FK to Cliente",
  "columns": [ { "name": "clienteId",
                 "comment": "References Cliente.id_cliente but no FK declared" } ] }
```

Es decir: una relación real que el cierre de FK **no puede ver**, porque no hay FK declarado.
Esto no es un caso de laboratorio — schemas sin FKs declaradas son enormemente comunes en
producción (MyISAM, integridad referencial gestionada en la aplicación, warehouses).

**Verificado ejecutando `select_tables()` sobre ese fixture:**

| Query | matched | related (FK) | omitted |
|---|---|---|---|
| `Add a phone number column to Cliente` | Cliente, commandes, facturas | commande_lignes | … |
| `Add an index on the montoTotal column` | facturas | — | **Cliente**, … |
| `Show total invoiced per customer` | facturas | — | **Cliente**, … |

El tercer caso es el que importa: una consulta que **requiere** el join `facturas → Cliente`
selecciona solo `facturas` y descarta `Cliente` explícitamente. El cierre de FK no lo alcanza
(no hay FK) y el match léxico tampoco ("customer" no matchea "Cliente", "invoiced" no matchea
"facturas"). El primer caso funciona **por casualidad**: `Cliente` entró porque la query dijo
literalmente "Cliente", y `facturas` entró porque su columna se llama `clienteId`. Con un nombre
de columna heredado (`owner_ref`, `cod_cli`) esa vía también desaparece.

### Pero esto no justifica un RFM — justifica algo mucho más barato primero

Si la relación está latente en el *nombre* de la columna, se puede inferir sin modelo. Y esa
inferencia se puede **validar de forma honesta**: correrla sobre schemas que sí tienen FKs
declaradas y medir si las reproduce. Medido sobre los tres fixtures, con la misma normalización
de tokens que usa `selection.py`:

| Fixture | FKs declaradas | Inferidas | Reproduce | Recall | Precisión |
|---|---|---|---|---|---|
| `small` | 3 | 3 | 3 | 100% | 100% |
| `hostile_naming` | 3 | 4 | 3 | 100% | 75% |
| `medium` | 17 | 16 | 12 | 71% | 75% |

En `hostile_naming` el único "falso positivo" **es la relación verdadera no declarada**
(`facturas → Cliente`) — exactamente el caso que Q10 pedía, encontrado por una heurística de
nombres de una decena de líneas, sin dependencias nuevas.

En `medium` (15 tablas, el más realista) la precisión de 75% dice que **no se puede afirmar
automáticamente**: aseverar una FK inventada dentro de un bloque rotulado AUTHORITATIVE es
justamente la alucinación que esta capa existe para evitar. Serviría como *generador de
candidatos*, marcado como inferido y no como declarado.

Y las 5 relaciones que la inferencia **no** recupera en `medium` son informativas:
`tasks → users`, `audit_log → users`, `task_comments → users` — columnas cuyo nombre no contiene
el de la tabla destino (un `assignee_id` o `actor_id` apuntando a `users`). Eso **sí** es
relación semántica no recuperable del nombre, y es el nicho que un RFM reclama.

**Conclusión de Q10:** el nicho existe y no está vacío — mi respuesta anterior ("no hay caso")
era falsa. Pero es un **residuo** que solo se puede medir *después* de aplicar la inferencia
determinista por nombres, que es órdenes de magnitud más barata. El orden correcto es:
inferencia determinista → medir qué queda sin resolver → recién ahí evaluar instrumentos.
**R2 del doc externo no está confirmado ni refutado; está sin medir.**

---

## Q8 / Q9 / Q11 — RT-J concretamente: por qué no

Verificado el 2026-08-09 contra fuentes primarias: [página del proyecto](https://star-project.stanford.edu/rt-j/),
[model card en HF](https://huggingface.co/stanford-star/rt-j) (frontmatter crudo),
[repo de código](https://github.com/snap-stanford/relational-transformer) (quickstart) y
[la doc de la librería](https://relationaltransformers.com/).

**Qué es RT-J, en sus propias palabras.** La documentación oficial lo define en una frase:
*"A relational transformer predicts a missing cell from the related data around it."*
85M parámetros, 12 capas, ventana de 8.192 **celdas**, dos variantes publicadas —
clasificación (AUROC media 0.7310) y regresión (MAE media 0.2677) — sobre tareas de RelBench.

Los motivos van ordenados **de más fuerte a más débil**, que es lo contrario del orden en que
una versión anterior de este documento los presentó.

### 1. Circularidad: RT-J consume como entrada lo que necesitamos como salida ← el motivo decisivo

La doc de la librería es explícita en que el modelo **no** hace análisis de esquema, y que
reunir el contexto relevante es responsabilidad de quien lo invoca: la aplicación
*"gathers a bounded context of related cells"* y la librería *"assumes users have already
retrieved relevant related data"*. El quickstart lo confirma: se le pasa una base ya
preprocesada a tensores y un evaluador con `ctx_size=128`, `local_ctx_size=64`, es decir, un
muestreo de filas de contexto ya decidido.

Ese paso previo — **decidir qué datos relacionados son los relevantes** — es exactamente Q10.
RT-J lo presupone resuelto. Para usarlo hay que haber resuelto antes el problema que
queríamos que resolviera. No es un problema de integración: es la forma del modelo.

### 2. El tipo de salida no puede expresar la respuesta

La cabeza del modelo es de clasificación o regresión: emite una etiqueta o un valor escalar
(por eso se lo mide en AUROC y MAE). No existe una forma de salida en la que quepa *"estas tres
tablas son relevantes y se unen por estas claves"*. Aunque se le diera la entrada correcta, no
hay canal por donde salga la respuesta que buscamos.

### 3. No hay interfaz en lenguaje natural

Las tareas se identifican como tareas nombradas de RelBench sobre datos preprocesados
(`table_name == "driver-dnf"` en el ejemplo oficial), no como preguntas. La entrada de este
motor es un pedido de desarrollo en lenguaje natural. No hay puente entre ambas cosas, y
construirlo sería el trabajo entero, no la integración.

*(Punto de honestidad: la literatura que sí ataca esta tarea es otra — RAT-SQL, RSL-SQL,
Schema-R1, SchemaGraphSQL, "Extractive Schema Linking". RT/RT-J no aparece en ella. Si alguna
vez se retoma este frente, el estado del arte a mirar está ahí, no en RelBench.)*

### 4. Requiere la base poblada, no el snapshot de metadata — *argumento retirado*

No recibe un JSON de esquema: recibe una base real convertida al formato tensorial de RT, de la
que muestrea filas. Esto choca con [plan-schema-grounding.md](plan-schema-grounding.md) §7 (sin
sample rows) y con la invariante de que el motor nunca abre una conexión.

**Pero el diagrama objetivo propone cambiar exactamente esa invariante:** incluye "Introspección
de DB (Postgres/SQLite/…)" dentro de Schema Grounding y lista "Datos de Ejemplo — muestras,
catálogos, tablas de referencia" como fuente de contexto de primera clase, con "Privacidad: todo
local" como principio. Contra esa arquitectura, este punto no es un bloqueo: es una consecuencia
a asumir deliberadamente. **Se retira como argumento en contra de RT-J**, y queda anotado como
lo que cuesta adoptar el diagrama, independientemente de qué modelo lo llene.

### 5. Licencia: `cc-by-nc-sa-4.0` — el motivo más débil, y el único negociable

NonCommercial + ShareAlike, verificado en el frontmatter del model card. Bloquea a un consumidor
comercial y contamina derivados. Va último a propósito: es el único que podría cambiar (otra
licencia, uso solo de investigación). Los motivos 1-3 son estructurales y **ningún cambio de
licencia ni de arquitectura los toca**.

### El diagrama objetivo pide algo que RT-J no produce

Revisado el diagrama *"Arquitectura Objetivo con Capa Contextual RFM/RT-J"* directamente. Su
caja de Relational Intelligence especifica:

> **RFM / RT-J (~85M)** — *Devuelve: relaciones relevantes, paths, patrones, scores de confianza*

Esa es una salida estructurada sobre el esquema. RT-J publica dos variantes (clasificación y
regresión, medidas en AUROC/MAE) y se define como *"predicts a missing cell"*: un escalar por
celda. **La caja y el modelo que la nombra no coinciden** — no es que este repo sea demasiado
restrictivo, es que el diagrama le atribuye a RT-J una capacidad que el modelo no publica.

Peor, el diagrama lo ubica **aguas arriba**, como proveedor que decide qué es relevante. La
librería de RT-J declara lo contrario: *"assumes users have already retrieved relevant related
data"*. Está dibujado en la única posición del pipeline donde no puede ir (motivo 1).

*Corroboración de que el diagrama es aspiracional:* su Registro de Modelos lista
`qwen2.5:7b-instruct` (Router), `qwen2.5coder:7b-instruct` (Architect) y `qwen-coder:7b`
(Implementer). El [settings.yaml](../config/settings.yaml) real corre `phi3:mini` y
`qwen3.6:35b-a3b`. Ninguno coincide.

**La caja sí se puede llenar — con otra cosa.** La salida que el diagrama pide (relaciones,
paths, scores de confianza) es exactamente lo que produce la inferencia determinista de FKs por
nombre medida arriba, con la precisión por fixture haciendo de score de confianza. Sin PyTorch,
sin checkpoints, sin licencia y sin datos productivos. **La conclusión no es borrar la caja: es
cambiar lo que va adentro.**

### El steelman, y por qué tampoco alcanza

*"Que RT-J lo corra fenix de su lado, donde sí tiene acceso a la base, y nos pase el
resultado."* Arquitectónicamente es válido y no violaría ninguna invariante de este repo. Pero
¿el resultado de qué? De predecir un valor de celda. Eso no dice qué tablas son relevantes para
un pedido de código — sigue chocando con los motivos 1 y 2, que no dependen de dónde corra el
modelo. RT-J resuelve un problema real y valioso; no es el nuestro.

### Nota sobre el doc externo

Recomendaba RT-J para ranking de caminos de join y schema linking. Es una lectura equivocada de
lo que el modelo hace, verificable en la documentación oficial en cinco minutos. Es la primera
instancia concreta de que la advertencia del handoff (*"advisory, no verificado por sus propios
autores"*) era acertada, y es motivo suficiente para verificar directamente cualquier otra
afirmación técnica de ese documento antes de actuar sobre ella.

**Estado: RT-J descartado. La necesidad de Q10 sigue viva.** Un instrumento futuro tendría que
(a) tomar metadata de esquema y una pregunta en lenguaje natural, (b) emitir un ranking de
tablas/caminos, (c) tener licencia compatible — y aun así competir contra la inferencia
determinista por nombres, que cuesta unas decenas de líneas y todavía no se construyó.

---

## Q2 — ¿Qué gana el sistema hoy, con 2 proveedores, que `_assemble_context` no dé ya?

**Respuesta: nada. Esta sí se sostiene.**

`_assemble_context` ([core/orchestrator.py:278-380](../core/orchestrator.py)) ya tiene orden de
prioridad fijo y comentado (schema → outline → reporte previo → RAG), un presupuesto único que
es el techo real de todo lo que llega al prompt, degradación gradual (solo RAG pierde piezas) y
telemetría propia (`outcome.context_budget`).

Con 2 proveedores externos reales (RAG y schema — `breakdown`/`prior_report` son artefactos
internos del pipeline, no proveedores), una abstracción `ContextProvider` no cambiaría ningún
comportamiento observable. Nótese que la inferencia de FKs de Q10 **tampoco** sería un tercer
proveedor: es una mejora *dentro* del proveedor de schema. Q2 no cambia por eso.

**Broker: diferido.** Se reabre si aparece un tercer proveedor real.

---

## 4. Hallazgo no previsto: un match léxico débil desactiva el fallback de seguridad

Esto salió del análisis de Q10 y es independiente de BA/RFM/Broker. Afecta código en producción.

`select_tables()` tiene un fallback deliberado: `include_all_if_no_match: true` incluye el
snapshot entero cuando no hay ningún match léxico, con el razonamiento (correcto, y comentado en
el módulo) de que *"una tabla de más cuesta presupuesto, una de menos hace que el modelo la
invente, y solo el segundo falla callado"*.

Pero ese fallback solo dispara cuando `scores` queda **totalmente vacío**. En
`Show total invoiced per customer`, la tabla `facturas` puntúa 1.0 por un match incidental:
el token `total` de la query pega contra la columna `montoTotal`. Con eso, `scores` deja de
estar vacío, el fallback no dispara, y `Cliente` se omite.

El resultado es **peor que no tener schema grounding**: al modelo se le entrega un bloque
rotulado "DETERMINISTIC SCHEMA (AUTHORITATIVE)", que se le indica que gana sobre la prosa
recuperada, y del que se cayó en silencio la tabla que la tarea necesita. Un match parcial y
débil es más peligroso que ningún match, porque el "ningún match" tiene red y el parcial no.

**Esto es una hipótesis con evidencia reproducible, no un bug confirmado en producción** — no se
midió el efecto sobre la salida final del pipeline. Pero es barato de comprobar y el arreglo es
acotado (p. ej. exigir un score mínimo o una cobertura mínima de tokens antes de considerar que
"hubo match"). **Merece su propio análisis, antes que cualquier discusión sobre BA o RFM.**

---

## Qué queda abierto

- **Q4:** sin responder. Requiere un corpus con reglas de negocio reales.
- **Q7** (métrica de ambigüedad del BA): sigue viva, porque el BA no se cerró.
- **Q10 residual:** cuánto queda sin resolver tras la inferencia por nombres. Medible, y es el
  único trabajo que podría volver a abrir la discusión sobre un modelo relacional.
- **Q1, Q3, Q5, Q6:** siguen dependiendo de las anteriores.
- **Q8, Q9, Q11: cerradas** para RT-J (ver arriba). Se reabrirían solo ante otro instrumento.

## Qué NO cambia

No se diseña ninguna de las tres piezas. [plan-schema-grounding.md](plan-schema-grounding.md) §8
sigue vigente. H3/H5/`needs_relational_context` siguen sin dueño. La inferencia de FKs por
nombres está *propuesta y medida en fixtures*, no construida ni aprobada.
