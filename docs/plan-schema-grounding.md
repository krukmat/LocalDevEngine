# Plan — Schema Grounding (contexto relacional determinista)

**Estado:** Fases 0, R, 1 y 2 construidas y verificadas offline. Fase 3 (gate empírico) **corrió
y concluyó NO-GO** — no por un empeoramiento limpio, sino porque `check_identifiers()` (el
instrumento de medición del gate) resultó no ser confiable en ninguna dirección al auditar los
recibos crudos a mano; ver [docs/fase3-decision.md](fase3-decision.md) para el detalle completo
y qué haría falta para remedir. Por regla de este mismo documento (§5.3), **ninguna tarea de
Fase 4 se hace**. La capa queda opt-in, sin costo para quien no la usa, tal como estaba tras la
Fase 2. La deuda documental (§6) es independiente de ese gate y no espera a nada.

**Continuación:** el alcance de la capa fue redefinido en
[docs/plan-schema-conformance.md](plan-schema-conformance.md) — de persuadir al modelo a
verificar su salida con parsers AST y un veredicto determinístico. Ese documento reemplaza a
la Fase 4 (§5.3) y es donde sigue el trabajo.

**Este documento es la única fuente de verdad del plan.** Reemplaza tanto a la versión
original (que decía "cero líneas de código escritas" — ya no es cierto) como al documento
intermedio `plan-schema-grounding-pendientes.md`, que existió brevemente para separar "lo
construido" de "lo pendiente" y cuyo contenido está fusionado acá. Ese archivo ya no existe;
si algo lo referencia, es un puntero viejo a esta página.

**Origen.** Surge de analizar la "Fase 1 — Deterministic Relational Context" del documento
`LocalDevEngine_RFM_RTJ_Architecture_Recommendation.md`, que llegó como recomendación
externa. El pedido original la enmarcaba como "una fase extra de RAG". Este documento
rechaza ese encuadre (§2) y lo reemplaza por uno que el propio documento fuente sostiene.

**Restricción rectora, declarada por el dueño del repo:** *LocalDevEngine es un motor
genérico; la ingestión se basa en los requerimientos de cada proyecto.* No hay una base de
datos de referencia, ni un dialecto privilegiado. Esa restricción no es un detalle de
alcance — cambió el diseño (§3) y es la razón por la que varias decisiones que parecían
preferencias pasaron a ser requisitos.

---

## 1. El problema que resuelve

El pipeline recupera contexto por **similitud semántica** (`_build_rag_context`,
[core/orchestrator.py](../core/orchestrator.py)): embebe la query, busca los top-k chunks
por coseno, los concatena con su path y score. Eso funciona para "mostrame cómo se hace X en
este repo".

No funciona para preguntas con carga relacional. Si el Architect necesita saber que
`orders.customer_id` referencia `customers.id`, la similitud coseno puede traerle un chunk
que *menciona* ambas tablas sin que eso constituya evidencia de que la FK existe. El modelo
entonces inventa: nombres de columna plausibles, joins que no cierran, tipos que no son. Y el
pipeline no tiene forma de notarlo — el QA Auditor es otro LLM mirando el mismo texto.

Schema grounding aporta un tipo de contexto distinto: **metadata estructural verificada**
(tablas, columnas, tipos, PK/FK, nullability) que se afirma como hecho, no como sugerencia.

## 2. Por qué NO es "una fase extra de RAG"

El encuadre inicial era "otra fuente de contexto que se suma al RAG". Es incorrecto, y el
documento fuente lo dice en su §7:

> The RFM may suggest relational relevance, but only schema grounding may assert that a
> structural relation exists.

La diferencia es de **autoridad**, no de origen. El RAG produce candidatos probabilísticos
con un score; el schema produce afirmaciones deterministas sin score. Si se mezclan en el
mismo bloque de texto con el mismo formato, el modelo no puede distinguirlos y se pierde
exactamente la propiedad que hacía valiosa la fase.

Consecuencias de diseño que se derivan de esto, todas ya implementadas:

- El bloque de schema va **etiquetado** como autoridad determinista, textualmente separado
  del bloque RAG en el prompt ([context/schema/render.py](../context/schema/render.py)).
- No lleva score. Un score sugiere que es negociable.
- No se ingiere al vector store. Si entra al store, entra al mismo ranking probabilístico que
  todo lo demás, y vuelve a ser RAG.
- En el recibo va en su propio bloque (`outcome.schema_grounding`), no dentro de
  `outcome.rag`.

## 3. Qué implica que el motor sea genérico

Con la restricción rectora, cuatro cosas cambiaron respecto de un diseño con BD de
referencia:

**3.1. El snapshot per-request es requisito, no preferencia.** Un motor genérico no puede
sostener conexiones a las bases de N proyectos con M dialectos, ni decidir cuál corresponde a
cada request. El schema llega **en la request** (`--schema-file`), igual que
`output_contract`. El engine queda stateless respecto de la BD y nunca toca credenciales.
Esto elimina de raíz toda la superficie de riesgo de §7.

**3.2. El formato es un IR normalizado, no un dump.** Nada de `pg_dump`, nada de salida cruda
de `PRAGMA table_info`. La traducción desde cada dialecto es responsabilidad de quien
introspecta (el llamador), no del engine — de ahí que `SchemaProvider` (ABC) sea el punto
central del diseño ([context/schema/base.py](../context/schema/base.py)).

**3.3. La selección léxica no puede asumir convenciones de nombres.** `snake_case`,
`CamelCase`, prefijos, plurales en inglés o castellano — un motor genérico no puede
hardcodear ninguna. La política ante la duda es **fallar hacia incluir**: una tabla omitida
del bloque es una tabla que el modelo va a inventar, que es exactamente el fallo que la fase
existe para evitar.

**3.4. No se puede medir contra "el schema".** El gate empírico necesita fixtures sintéticas
versionadas en el repo (§5, Fase 3), no una BD real — es la única forma de tener una medición
repetible en un motor sin proyecto propio.

---

## 4. Qué está construido

| Componente | Archivo | Verificado |
|---|---|---|
| IR + `SchemaProvider` ABC | [context/schema/base.py](../context/schema/base.py) | offline |
| Carga JSON/YAML + normalización | [context/schema/snapshot.py](../context/schema/snapshot.py) | offline |
| Selección léxica + cierre FK | [context/schema/selection.py](../context/schema/selection.py) | offline |
| Renderizado con etiqueta de autoridad | [context/schema/render.py](../context/schema/render.py) | offline |
| Chequeo determinista de identificadores | [context/schema/identifiers.py](../context/schema/identifiers.py) | offline |
| Presupuesto de contexto de punta a punta | `_assemble_context` en [core/orchestrator.py](../core/orchestrator.py) | offline |
| Wiring en el pipeline | `_build_schema_context`, `_run_pipeline_body` | fast path live |
| `outcome.schema_grounding` / `outcome.context_budget` | [core/receipt.py](../core/receipt.py), `SCHEMA_VERSION` 1.1 | fast path live |
| `--schema-file` | [main.py](../main.py) | offline |
| Bloque `schema_grounding:` en config | [config/settings.yaml](../config/settings.yaml) | offline |
| Snapshot de ejemplo | [docs/examples/schema-snapshot.example.json](examples/schema-snapshot.example.json) | offline |

**"Offline" quiere decir:** verificado con scripts deterministas sin Ollama (30 checks, hoy
solo en el scratchpad de una sesión — no en el repo, ver tarea 3.6). **"Fast path live"**
quiere decir: el wiring se ejercitó en corridas reales contra Ollama por el camino rápido del
pipeline, pero el pipeline completo con `--schema-file` nunca corrió de punta a punta contra
un caso diseñado para que el modelo se equivoque sin el schema. Esa distinción es exactamente
lo que la Fase 3 (§5) tiene que cerrar.

**Decisiones que se tomaron por asunción** al construir, sin las fixtures que originalmente
iban a validarlas (R.2/R.3, ver §5.1 tabla), y que sólo la Fase 3 puede confirmar o refutar:

1. El snapshot lo provee el llamador; el motor nunca abre una conexión.
2. La selección es léxica pura, sin embeddings, y **falla hacia incluir**.
3. El bloque de schema va primero en el prompt y con etiqueta de autoridad explícita.
4. El chequeo de identificadores es conservador (sólo posiciones relacionales inequívocas):
   prefiere perder hallazgos reales antes que producir falsos positivos.
5. Un snapshot inválido es error de uso (exit 3), nunca una corrida degradada en silencio.

## 5. Qué falta

### 5.1 Historial de fases (para quien busque cómo se llegó acá)

| Fase | Contenido | Estado |
|---|---|---|
| **0** — Presupuesto de contexto de punta a punta | `_assemble_context`, política de truncado, corrección de `config_fingerprint` | ✅ Done |
| **R** — Refinamiento en papel (R1-R5) | Definir IR, selección, renderizado, extracción de identificadores, degradación | ✅ Done, pero **sin** las fixtures R.2/R.3 que iban a validarlo — resuelto por asunción |
| **1** — Provider mínimo | `SchemaProvider`, parsing, wiring en el seam, `--schema-file`, config | ✅ Done |
| **2** — Chequeo determinista de identificadores | Extracción + comparación contra el IR, reporta sin gatear | ✅ Done |
| **3** — Gate empírico | Ver §5.2 | ✅ Done — **NO-GO**, ver [docs/fase3-decision.md](fase3-decision.md) |
| **4** — Solo si la Fase 3 lo justifica | Ver §5.3 | 🔒 **Cerrada, no se hace** (3.5 = negativo) |

### 5.2 Fase 3 — el gate empírico *(bloqueante para todo lo demás)*

**Regla que ordena esto:** la capa ya existe, así que el riesgo dejó de ser "no poder
construirla" y pasó a ser **construir más encima sin haber medido la que hay**. Es
exactamente el error que este repo ya cometió una vez con el macro-loop (ver
`config/settings.yaml`, comentario de `max_macro_iterations`, y §5.3 tarea 3 más abajo). Por
eso esta fase va antes que cualquier otra cosa nueva.

**Lo que separa "construido" de "funciona":**

- **Nunca se corrió el pipeline completo con `--schema-file` contra un caso donde el modelo
  se equivocaría sin el schema.** No hay evidencia de que el bloque cambie el resultado.
- **No se sabe si el modelo respeta la etiqueta de autoridad.** El header le dice que no
  invente y que el bloque le gana al contexto recuperado. Que lo obedezca es una hipótesis.
- **El chequeo de identificadores no tiene tasa de detección conocida.** Atrapa una tabla y
  una columna inventadas en SQL explícito y sabe ignorar `self.config`; no se sabe qué
  fracción de invenciones reales atrapa sobre salida de modelo de verdad.
- **El presupuesto subió de 3000 a 6000 chars sin medir el efecto.** Coherente (ahora cubre
  bloques que antes no contaba), pero no medido en un pipeline cuyo cuello de botella es la
  latencia.

**Criterio de continuación, fijado ANTES de medir:**

> Sobre las 3 fixtures, la corrida **con** `--schema-file` debe producir estrictamente menos
> identificadores desconocidos que la corrida **sin** él, en al menos 2 de las 3, y ninguna
> regresión en la tercera.
>
> Si no se cumple: **no se construye nada más de esta capa**. La capa queda como está
> (opt-in, sin costo para quien no la usa) y se documenta el resultado negativo.

El criterio está escrito antes de correr nada a propósito. Un criterio elegido después de ver
los números no es un gate, es una racionalización.

| # | Tarea | Detalle | Depende de |
|---|---|---|---|
| 3.1 | Fixtures de schema | 3 snapshots sintéticos en `tests/fixtures/schema/`: uno chico (4 tablas, como el ejemplo), uno mediano normalizado (~15 tablas, FKs en cadena — prueba el cierre a profundidad 1), uno con nombres hostiles (convenciones mezcladas, tablas sin FK declarada, nombres en otro idioma — prueba que la selección no asume convención) | — (R1 ya cerrado) |
| 3.2 | Queries de prueba | 3 por fixture: una que nombra la tabla, una que nombra sólo una columna, una que no nombra nada relacional (dispara `strategy: all`) | 3.1 |
| 3.3 | Script de A/B | Corre cada (fixture, query) con y sin `--schema-file`, guarda ambos recibos, extrae `outcome.schema_grounding.identifier_check.unknown_count` — para la corrida sin schema, calcula el mismo número offline contra el snapshot que *no* se pasó | 3.1, 3.2, Fases 0/1/2 (ya satisfechas) |
| 3.4 | Correr y registrar | 18 corridas de pipeline completo. A ~10-25 min cada una, es una tarde de máquina. Los recibos crudos se guardan, no sólo el resumen | 3.3 |
| 3.5 | Decidir | ✅ Hecho — **NO-GO**. Aplicado literal: 2 de 3 fixtures mejoran pero `small` empeora (22 vs 16), rompiendo "ninguna regresión en la tercera". Pero además, auditando a mano los 18 recibos crudos (no solo el resumen): `check_identifiers()` no solo cuenta ruido (imports, objetos de catálogo SQL, palabras sueltas) como desconocido — en 4 de 7 corridas `with` marcó el 100% de lo revisado como desconocido pese a uso correcto y verificado de las tablas mostradas (`known_tables=[]` con tablas correctas en el código). Descontando el ruido, solo sobreviven 2 eventos genuinos en 18 corridas, uno a favor de la hipótesis y uno en contra — sin base para afirmar mejora en ninguna dirección. El NO-GO se sostiene, pero por invalidez del instrumento de medición, no por un empeoramiento limpio. Detalle completo en [docs/fase3-decision.md](fase3-decision.md) | 3.4 |
| 3.6 | Subir el smoke test offline al repo | Las 30 verificaciones offline hoy viven en el scratchpad de una sesión, no en el repo — nadie las puede volver a correr. Moverlas a `tests/` es lo que hace posible reusar 3.1-3.2 como fixtures reales de test, no solo de este gate | — (puede hacerse en paralelo a 3.1) |

**Nota honesta sobre 3.1/3.2/3.6:** estas fixtures son el primer artefacto de test real del
repo. La decisión consciente de no tener suite (documentada en `CLAUDE.md`) empieza a costar
acá: no hay `tests/`, no hay runner, no hay convención. La Fase 3 la paga o no se hace.

### 5.3 Fase 4 — CERRADA, reemplazada por el alcance nuevo

> **La Fase 4 tal como está en esta tabla no se hace.** La 3.5 concluyó NO-GO, y el análisis
> mostró que el mecanismo de la capa (persuadir al modelo con un header de autoridad + medir
> con un checker de regex) es el problema, no el parámetro a ajustar. El alcance redefinido
> vive en **[docs/plan-schema-conformance.md](plan-schema-conformance.md)**: la capa pasa de
> *prevenir* alucinaciones a *verificarlas mecánicamente* con parsers AST, veredicto
> determinístico y gate opcional. La tabla de abajo se conserva como registro histórico de lo
> que se había planeado.

Ninguno de estos se toca hasta que 3.5 concluya que sí.

| # | Pendiente | Depende de | Por qué no se hizo ya |
|---|---|---|---|
| 4.1 | **QA con chequeo de conformidad de schema.** Hoy el auditor puede aprobar una implementación que referencia una columna inventada; el chequeo determinista lo detecta pero no gatea. El patrón a copiar es `output_contract` en `get_qa_review_template` | 3.5 = positivo | Gatear sobre una señal cuya tasa de detección no se midió convierte un falso positivo en un rechazo real |
| 4.2 | **`chat` no soporta schema.** El REPL no tiene equivalente de `--schema-file` | Decisión de diseño (snapshot por sesión vs. por mensaje) | No vale decidirlo antes de saber si la capa sirve |
| 4.3 | **El macro-rerun pierde parámetros.** `_maybe_offer_macro_rerun` en [main.py](../main.py) no reenvía `output_contract` — defecto preexistente, no introducido acá — y tampoco reenviaría `schema_snapshot` | 4.2 (para manifestarse; hoy `chat` no soporta ninguno de los dos) | Es un bug de una línea, pero arreglarlo sin 4.2 no cambia ningún comportamiento observable |
| 4.4 | **Providers de introspección viva** (`context/schema/sqlite.py` con stdlib, luego otros) | 3.5 = positivo, + demanda real de un llamador | Gate explícito del plan. Sólo si la Fase 3 justifica el costo, y con todas las restricciones de §7 vigentes: read-only, sin DSN por argv, sin sample rows, sin conteos de filas |

---

## 6. Deuda documental *(independiente de la Fase 3, hacer ya)*

Esto no espera al gate porque es lo único de todo el plan que empeora con el sólo paso del
tiempo — cada commit que toque el recibo o el pipeline sin actualizar estos tres documentos
los vuelve más caros de corregir después.

| # | Archivo | Qué está desactualizado | Depende de |
|---|---|---|---|
| 6.1 | [CLAUDE.md](../CLAUDE.md) | No menciona `context/`, ni `--schema-file`, ni `SCHEMA_VERSION` 1.1, ni que el presupuesto de contexto ahora se aplica de punta a punta. Describe `_build_rag_context` con un comportamiento que ya no tiene | — |
| 6.2 | [docs/handoff-fenix-parte-b.md](handoff-fenix-parte-b.md) | Documenta el recibo 1.0. Le faltan `outcome.schema_grounding`, `outcome.context_budget`, `outcome.rag.chunks_eligible` y `config_fingerprint.request`. Como es el artefacto de handoff hacia un llamador externo, su desactualización es la más cara de las tres | — |
| 6.3 | [README.md](../README.md) | No documenta `--schema-file` en la interfaz de llamador no-humano | — |

Nota sobre 6.2: el recibo 1.1 es **aditivo** — un consumidor 1.0 que lee sólo las claves que
conoce sigue funcionando. Pero un llamador que valide `schema_version == "1.0"` de forma
estricta se rompe. Eso hay que avisarlo, no descubrirlo.

---

## 7. Seguridad

Restricciones que se mantienen aunque cambie el resto del diseño:

- **Nunca un DSN por argv.** Se filtra a `ps` y al historial de shell. Si alguna vez hiciera
  falta uno, va por variable de entorno (`LDE_DB_URL`, siguiendo el precedente de
  `LDE_OLLAMA_HOST`) o por archivo.
- **Credenciales fuera de los prompts**, siempre.
- `include_row_counts: false` por defecto ([config/settings.yaml](../config/settings.yaml)).
  Los conteos filtran volumen de negocio.
- **Nada de sample rows** en esta fase. Si alguna vez se agrega, va con control propio: son
  datos reales, potencialmente PII, entrando a un prompt.
- Cualquier provider relacional futuro (Fase 4, tarea 4.4) abre en **read-only**.

El diseño de §3.1 (el llamador provee el snapshot) hace que casi todo esto sea vacuo hoy: el
engine nunca ve una credencial ni abre una conexión. Se documenta igual para que quien agregue
un provider directo en la Fase 4 sepa qué está reintroduciendo.

## 8. Fuera de alcance (declarado)

Se repiten acá porque ahora que la capa existe hay una tentación concreta de absorberlos:

- **H3 — el vector store no tiene noción de proyecto.** [core/orchestrator.py](../core/orchestrator.py)
  construye un único `LocalVectorMemory` desde un path global en config; chunks de proyectos
  distintos conviven en el mismo índice sin filtro. Problema real, independiente, propio. Va
  a contaminar la medición de la Fase 3 si las fixtures se ingieren al mismo store; el script
  de 3.3 debe usar un `vector_db_path` limpio por corrida, que es un workaround, no un
  arreglo.
- **H5 — `.sql` se ingiere como prosa.** `.sql` está en `ingestion.extensions` pero no tiene
  splitter estructural propio ([core/chunking.py](../core/chunking.py)), así que cae a
  párrafos. No es parte de esta capa: un archivo `.sql` ingerido es contexto probabilístico;
  el snapshot es determinista. Arreglar el chunking no sustituye al schema grounding ni al
  revés.
- **Dimensión `needs_relational_context` en el Router.** El Router es `phi3:mini` y ya
  misclasifica con cuatro categorías; agregar una quinta señal a ese modelo es empeorar un
  problema conocido.
- **RFM / RT-J / Context Broker / rol de BA/Analyst** del documento de recomendación
  original. No están diseñados ni planeados como continuación de este trabajo — si algún día
  se quieren, es una conversación nueva de cero, no un ítem en cola. Esa conversación ya tiene
  su documento de apertura: [handoff-capa-contextual-objetivo.md](handoff-capa-contextual-objetivo.md).
  **No cambia nada de este plan** — no diseña ninguna de esas piezas y las deja todas detrás
  de la Fase 3 (§5.2). Dos cosas de ahí sí impactan acá y conviene leerlas antes de escribir
  la tarea 3.1: (a) la Fase 3 **es**, literalmente, el gate que ese documento externo pone
  antes de todo lo demás (su §13 "Do not proceed without a baseline" y su §14); (b) por eso
  el harness de 3.3 conviene diseñarlo como runner de variantes con extractor de métricas por
  recibo, y no como un script de un solo número — ver §2 del handoff para el costo de no
  hacerlo. Ojo con la numeración: las "Phase 0-4" del documento externo **no** son las Fases
  0-4 de este plan; la tabla de traducción está en §0 del handoff.
- **Que el engine abra conexiones a BD.** Ver §3.1 y §7 (Seguridad).

---

## 9. Orden recomendado

1. **Deuda documental (§6)** — ya, sin esperar nada. Es lo único que empeora con el tiempo.
2. **Fase 3 (§5.2)** — el gate. Nada más se construye hasta que esté corrido y registrado.
3. **Según el resultado:** positivo → Fase 4 (§5.3) en orden 4.1, 4.2, 4.3, y 4.4 sólo si
   además hay demanda real de un llamador. Negativo → documentar y parar; la capa queda
   opt-in y sin costo para quien no la use.
