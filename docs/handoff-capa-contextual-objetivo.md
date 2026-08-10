# Handoff — Capa Contextual objetivo (Analyst/BA, Context Broker, RFM/RT-J)

**Tipo:** documento de apertura de análisis. **Nada de lo que describe está construido, ni
planeado, ni desbloqueado.**

**⚠️ Actualización 2026-08-09 — el worklist de §7 se analizó; ver
[decision-capa-contextual-ba-rfm-broker.md](decision-capa-contextual-ba-rfm-broker.md).**
Resultado: **Q2** → "nada con 2 proveedores", Broker **diferido**. **Q10** → **sí hay caso** (el
propio fixture `hostile_naming.json` codifica una relación real sin FK declarado, y
`select_tables` la pierde), y queda detrás de una inferencia determinista de FKs por nombre de
columna, mucho más barata y ya medida sobre los fixtures. **Q8/Q9/Q11** → **RT-J descartado**
por tres motivos independientes: pesos bajo `cc-by-nc-sa-4.0` (NonCommercial, incompatible con
un consumidor comercial), consume filas reales y no metadata (choca con la invariante de §6), y
predice valores en vez de resolver schema-linking. El doc externo lo recomendaba para ranking de
joins: es una lectura equivocada de lo que el modelo hace.
**Q4** → **sin responder**: el corpus de la Fase 3 (9 queries, todas DDL atómico o mantenimiento
genérico, cero reglas de negocio) no es un instrumento válido para esa pregunta; el BA sigue
abierto. Ese documento además reporta un modo de falla silencioso de la capa de schema ya
construida (un match léxico débil desactiva el fallback `include_all_if_no_match`), que es
independiente de las tres piezas y probablemente más urgente que ellas.
**Para quién:** la próxima instancia que retome esto en frío, sin el hilo de conversación
donde nació.
**Origen:** el diagrama *"LocalDevEngine – Arquitectura Objetivo con Capa Contextual
RFM/RT-J"* y el documento externo `LocalDevEngine_RFM_RTJ_Architecture_Recommendation.md`
(advisory, no verificado por sus propios autores — su §29 lo dice explícitamente).

---

## 0. Cómo leer esto, y qué NO es

Tres advertencias antes de cualquier cosa:

1. **Esto no contradice ni deroga [plan-schema-grounding.md](plan-schema-grounding.md) §8.**
   Ese §8 declara "RFM / RT-J / Context Broker / rol de BA/Analyst" fuera de alcance y dice
   que retomarlos es *"una conversación nueva de cero, no un ítem en cola"*. Este documento
   **es** esa conversación nueva, y arranca donde el §8 la dejó: en cero. Nada de acá se
   construye mientras la Fase 3 del schema grounding siga sin correr.

2. **El documento externo es advisory y sus afirmaciones sobre este repo no vienen
   verificadas.** La §1 de acá verifica caja por caja qué de lo que describe existe. Donde
   el doc externo y el código difieren, gana el código.

3. **Choque de numeración de fases — es el error más fácil de cometer acá.** El doc externo
   tiene sus propias "Phase 0..4" (§13-§17) que **no** son las Fases 0-4 de
   [plan-schema-grounding.md](plan-schema-grounding.md). Traducción obligatoria:

   | Doc externo | Qué pide | Equivalente real en este repo |
   |---|---|---|
   | Phase 0 — Baseline & harness | Medir el pipeline actual antes de tocarlo | **No existe.** Parcialmente cubierto por la Fase 3 del schema plan (ver §2) |
   | Phase 1 — Deterministic Relational Context | Schema grounding + su gate A/B | **Fases 0/R/1/2 construidas; la Fase 3 ES ese gate** |
   | Phase 2 — Context Broker + Analyst IR | Broker y rol BA | No construido, no planeado |
   | Phase 3 — RFM/RT-J shadow mode | RT-J en paralelo, sin influir la salida | No construido, no planeado |
   | Phase 4 — Controlled RFM adoption | RFM como contexto advisory | No construido, no planeado |

   Cuando escribas "Fase 3" en este repo, **por defecto significa el gate empírico del schema
   grounding**. Si te referís a la del doc externo, decí "Phase 3 (doc externo)".

---

## 1. Estado verificado, caja por caja del diagrama

Verificado contra el código el 2026-08-09 (`grep` sobre `*.py`/`*.md`, más lectura directa de
[core/orchestrator.py](../core/orchestrator.py) y [config/settings.yaml](../config/settings.yaml)).

### Capa Contextual

| Caja del diagrama | Qué existe hoy | Dónde | Veredicto |
|---|---|---|---|
| **RAG Semántico** | Completo: embeddings vía `/api/embed`, `LocalVectorMemory` con coseno, chunking estructural, presupuesto de retrieval | [core/orchestrator.py](../core/orchestrator.py) `_build_rag_context`, [memory/local_memory.py](../memory/local_memory.py), [core/chunking.py](../core/chunking.py) | ✅ Construido |
| **Schema Grounding (Determinístico)** | Construido y verificado offline + fast path. **No** verificado en pipeline completo. Snapshot estático provisto por el llamador — el motor nunca abre una conexión | [context/schema/](../context/schema/) (5 módulos), `--schema-file` | ⚠️ Construido, **sin medir** (Fase 3) |
| **Schema Grounding → "Introspección de DB (Postgres/SQLite/…)"** | No existe. El diagrama promete introspección viva; hoy es un archivo JSON/YAML exportado por el llamador | — | ❌ No construido (sería 4.4, doblemente gated) |
| **Relational Intelligence (RFM / RT-J)** | Cero footprint. Ni módulo, ni ABC, ni dependencia, ni mención fuera de docs | — | ❌ No construido |
| **Context Broker** | Existe un **proto-broker no reconocido como tal**: `_assemble_context` ya hace prioridad entre fuentes, presupuesto único, y emite `outcome.context_budget`. Lo que NO hace: proveniencia, confianza, normalización por proveedor, ni decidir *qué* proveedor corre | [core/orchestrator.py:278-381](../core/orchestrator.py) | 🟡 Parcial, sin abstracción |
| **Contrato de Contexto (unificado)** | No existe como artefacto. Lo que sale de `_assemble_context` es **un string** concatenado, no una estructura con proveniencia | [core/orchestrator.py:278](../core/orchestrator.py) | ❌ No construido |

### Pipeline de agentes

| Caja del diagrama | Estado | Nota |
|---|---|---|
| Router | ✅ | `phi3:mini`, 4 categorías, ya misclasifica |
| **Analyst / BA (nuevo)** | ❌ **No existe** | Ninguna etapa entre Router y Manager |
| Manager (breakdown) | ✅ | |
| Architect | ✅ | Con plan seccionado en 4 secciones fijas |
| QA Gate 1 (design) | ✅ | Seccionado + fallback monolítico |
| Implementer | ✅ | Con `output_contract` opcional |
| QA Gate 2 (implementation) | ✅ | **Pero no consume la señal de schema**: `identifier_check` reporta, no gatea (eso es 4.1) |
| Manager cierre | ✅ | Closing report + macro-loop con HITL |

**Lectura corta:** de las 4 fuentes de contexto del diagrama, **1 está completa (RAG), 1 está
construida pero sin medir (Schema), 2 no existen**. Del pipeline, falta **1 etapa (Analyst/BA)**
y **1 flecha** (Schema → QA Gate 2).

Un detalle útil que el doc externo no menciona: existe un rol **`copilot`** definido en
[config/settings.yaml](../config/settings.yaml) (`granite-code:8b`, prioridad 6) que **no está
en ningún camino de ejecución**. Es un asiento vacío en la config, no una etapa muerta en el
código — no lo confundas con una base para el BA.

---

## 2. La dependencia que ordena todo: la Fase 3 ya es el gate del doc externo

Esto es lo más importante de este handoff y es fácil de pasar por alto.

El doc externo §13 (Phase 0) cierra con **"Do not proceed without a baseline"**, y su §14
(Phase 1) exige comparar `Baseline` vs `Baseline + Schema Grounding` antes de agregar nada.
Ese gate **ya está definido, con criterio fijado antes de medir**, en
[plan-schema-grounding.md](plan-schema-grounding.md) §5.2. Es decir: el repo está parado
exactamente en la puerta que el doc externo pone antes de todo lo demás. No hay atajo — el
Broker, el BA y el RFM están detrás de esa misma puerta, no solo la Fase 4 del schema plan.

### La decisión que hay que tomar ANTES de escribir la tarea 3.1

Hay una diferencia de alcance real entre los dos gates:

| | Fase 3 (schema plan, §5.2) | Phase 0 (doc externo, §13) |
|---|---|---|
| Escenarios | 3 fixtures × 3 queries = 9 casos | 6 categorías de tarea |
| Métrica | 1: `outcome.schema_grounding.identifier_check.unknown_count` | 9: tablas/columnas alucinadas, joins inválidos, revisiones de QA, latencia, tamaño de contexto, swaps de modelo, corrección final, etc. |
| Variantes | 2 (con/sin `--schema-file`) | 4 (A/B/C/D de §25: RAG / +Schema / +BA IR / +RFM) |
| Propósito | decidir sobre **una** capa | servir de baseline a **todas** |

El harness de la Fase 3 es, materialmente, el **primer artefacto de test del repo** (la tarea
3.6 lo dice: hoy no hay `tests/`, ni runner, ni convención). Si se construye estrecho — un
script que solo extrae `unknown_count` — cada pieza siguiente (BA, Broker, RFM) va a tener que
reconstruirlo desde cero, y peor: **las mediciones no van a ser comparables entre sí**, que es
justo lo que hace inútil un experimento A/B/C/D.

> **Recomendación (decidir explícitamente, no por omisión):** construir la tarea 3.3 (el
> script de A/B) como un **runner de variantes con un extractor de métricas por recibo**, no
> como un script de un solo número. Concretamente: que tome `(fixture, query, variante)`,
> guarde el recibo crudo, y extraiga un dict de métricas de él. La variante hoy es solo
> `con/sin --schema-file`; el punto es que agregar una tercera variante después sea un
> parámetro, no un reescritura.
>
> **Lo que NO recomiendo:** ampliar la Fase 3 a las 6 categorías y 9 métricas del doc externo
> *antes* de correrla. Eso convierte una tarde de máquina (18 corridas × 10-25 min) en una
> semana, y viola la regla que ordena el plan entero: no construir más encima de lo que no se
> midió. Ampliar el *diseño* del runner es barato; ampliar el *experimento* no.

Costo de esta recomendación: unas horas extra en 3.3. Costo de no tomarla: rehacer el harness
tres veces, o peor, comparar números que no se pueden comparar.

---

## 3. Las tres piezas faltantes — paquetes de análisis

Cada pieza está planteada como un paquete cerrado: qué promete el diagrama, qué hay hoy más
cercano, las preguntas que hay que contestar **antes** de diseñar nada, y el experimento más
barato que las contesta. Ninguna trae diseño propuesto a propósito: diseñar antes de contestar
las preguntas es exactamente el error que este repo ya cometió con el macro-loop (ver el
comentario de `max_macro_iterations` en [config/settings.yaml](../config/settings.yaml)).

### 3.1 Context Broker + Contrato de Contexto

**Lo que promete el diagrama:** un componente que fusiona las 4 fuentes, les asigna
proveniencia y confianza, y emite un contrato estable que todos los agentes consumen igual.

**Lo más cercano que existe:** `_assemble_context` ([core/orchestrator.py:278](../core/orchestrator.py))
ya es un broker en todo menos el nombre. Tiene orden de prioridad explícito y comentado
(schema → outline → reporte previo → RAG), un presupuesto único que es el techo real de todo
lo que llega a un prompt, degradación grácil (solo RAG pierde piezas), y telemetría propia
(`outcome.context_budget`). Lo que le falta para ser lo del diagrama son tres cosas, y solo
una es difícil:

- *(fácil)* una **abstracción de proveedor** — el patrón ya está establecido tres veces en
  este repo: [models/base.py](../models/base.py), [memory/base.py](../memory/base.py),
  [context/schema/base.py](../context/schema/base.py). Un `ContextProvider` ABC sería el
  cuarto y sería consistente.
- *(medio)* **proveniencia y autoridad como datos**, no como texto. Hoy la autoridad del
  schema es una etiqueta *dentro del string* renderizado ("DETERMINISTIC SCHEMA
  (AUTHORITATIVE)"). Funciona porque el consumidor es un modelo. No funciona para nada que
  quiera razonar sobre el contexto programáticamente.
- *(difícil)* **decidir qué proveedor corre**. Eso es routing de contexto, y el diagrama lo
  dibuja como si fuera gratis. No lo es: ver §5, el Router.

**Preguntas abiertas:**

- **Q1.** ¿El contrato es una estructura que los agentes consumen, o sigue siendo un string y
  la estructura es solo para el recibo y la medición? *(La segunda es mucho más barata y puede
  ser suficiente: los consumidores son LLMs, que leen prosa.)*
- **Q2.** ¿Qué gana el sistema hoy, con 2 proveedores, que `_assemble_context` no dé ya? Si la
  respuesta honesta es "nada hasta que haya un tercer proveedor", el Broker no es prioridad
  ahora — es una refactorización a hacer *cuando* llegue el tercero, no antes.
- **Q3.** El presupuesto es de 6000 chars y es un techo duro. Con más proveedores, ¿el Broker
  reparte mejor o solamente hay menos RAG? No hay evidencia de que más fuentes = mejor
  contexto; hay una fuerza en contra (R5 del doc externo, "context overload").

**Experimento más barato:** ninguno. Esta pieza no necesita experimento, necesita que Q2 se
conteste con honestidad. Es la única de las tres que es una **refactorización** y no una
capacidad nueva — y por eso también la única que puede esperar sin costo.

---

### 3.2 Analyst / BA + Business IR

**Lo que promete el diagrama:** una etapa entre Router y Manager que produce un IR de dominio
(entidades, reglas de negocio, criterios de aceptación, ambigüedades) antes de que empiece
cualquier planificación técnica.

**Lo más cercano que existe:** nada. La responsabilidad está repartida implícitamente entre el
Manager (descompone el objetivo en pasos) y el Architect (interpreta estructuras y
dependencias). El doc externo acierta en esto y está verificado: no hay rol de BA en el camino
de ejecución.

**A favor, específico de este repo:** es la pieza más barata de las tres en términos de
runtime. El doc externo §8.2 propone reusar el modelo físico del Manager/QA con otro system
prompt — y en este repo eso es literalmente gratis en swaps: `manager` y `qa_auditor` ya
comparten tag (`gemma4:26b-a4b-it-qat`), y Ollama corre con `-np 1`, así que una tercera
etapa sobre el mismo tag **no fuerza unload/reload**. El costo es +1 llamada al modelo
(~20-30s medido para `task_breakdown` sobre ese tag), no +1 swap.

**En contra:** agrega una etapa a un pipeline que ya tiene 6-10 llamadas por corrida y cuyo
cuello de botella declarado es la latencia. Y agrega un artefacto (el Business IR) que hay que
meter en el presupuesto de contexto de 6000 chars — compitiendo con RAG, no sumándose.

**Preguntas abiertas:**

- **Q4.** ¿Cuál es el fallo concreto, observado, que un BA arreglaría? Hoy no hay ni un caso
  registrado de "el Manager malinterpretó el requerimiento". Sin ese caso, el BA es una etapa
  que resuelve un problema hipotético. **Esta es la pregunta bloqueante de esta pieza.**
- **Q5.** ¿El Business IR entra al prompt del Manager, o solo al del Architect, o a los dos?
  Cada respuesta tiene un costo distinto en el presupuesto.
- **Q6.** ¿El BA corre siempre o solo para ciertas categorías del Router? Si es lo segundo,
  hereda el problema del Router (§5).
- **Q7.** ¿Cómo se mide "menos ambigüedad"? El doc externo §26 dice "adopt BA IR if
  requirement ambiguity decreases" sin definir cómo se observa eso. Sin una métrica definida
  *antes*, este gate no es un gate.

**Experimento más barato que contesta Q4:** correr N queries reales del historial de recibos
(los recibos guardan `query` y `breakdown`) y revisar a mano cuántos breakdowns fallaron por
malinterpretar el requerimiento vs. por otra causa. Cero código nuevo, cero corridas de
modelo. Si la respuesta es "ninguno", el BA queda documentado como innecesario y esa es una
conclusión valiosa, no un fracaso.

---

### 3.3 Relational Intelligence (RFM / RT-J)

**Lo que promete el diagrama:** un proveedor que rankea entidades relevantes, vecindarios
relacionales y caminos de join candidatos, con score de confianza, como contexto *advisory*.

**Lo más cercano que existe:** nada, y lo que se le parece es determinista y ya está:
`context/schema/selection.py` hace selección léxica + cierre de FK a profundidad 1. Es
exactamente el "deterministic schema graph" que el propio doc externo señala como el riesgo
principal del RFM (**R2: "RFM adds little beyond FK graph traversal"**).

**El costo que el doc externo subestima para este repo específicamente:** RT-J **no es un
modelo de Ollama**. Todo el runtime de este repo es HTTP contra `localhost:11434`
([models/ollama_model.py](../models/ollama_model.py)) y sus dependencias son tres
(`httpx`, `numpy`, `PyYAML`). Un RFM introduce una **clase de dependencia nueva** —
PyTorch/MPS, checkpoints, preprocesamiento — que rompe la propiedad de que todo el sistema
corre detrás de una API uniforme y de que un llamador externo solo necesita un Ollama. Eso no
es un detalle de implementación; es un cambio en qué es este proyecto.

**Preguntas abiertas:**

- **Q8. Licencia — gate duro y primero.** Los pesos publicados de RT-J tienen que revisarse
  **antes de cualquier prototipo**, no después. Un prototipo hecho sobre pesos no licenciables
  es trabajo que hay que tirar entero. *(Doc externo §10, R4.)*
- **Q9.** ¿El checkpoint publicado sirve *tal cual* para schema-linking / ranking de caminos,
  o necesita fine-tuning? Si necesita fine-tuning, la pieza sale del alcance de este proyecto
  por completo.
- **Q10.** ¿Qué mide el RFM que el cierre de FK determinista no mida ya? Formulado al revés,
  que es como hay que probarlo: **construir el caso donde el grafo de FK da la respuesta
  incorrecta y el RFM daría la correcta.** Si ese caso no se puede construir, R2 está
  confirmado y la pieza no se hace.
- **Q11.** ¿PII? El RFM opera sobre datos relacionales, no solo metadata. [plan-schema-grounding.md](plan-schema-grounding.md) §7 prohíbe sample rows sin control propio; un RFM que mire datos reales reintroduce eso a lo grande.

**Experimento más barato:** contestar Q10 **en papel**, con lápiz y un esquema de ejemplo,
antes de descargar un solo peso. Q8 en paralelo, que es leer una licencia. Ninguno de los dos
requiere código.

---

## 4. Orden de dependencias entre las piezas

```
        [Fase 3 del schema plan — GATE DURO, ya definido]
                            │
                            ├── negativo → nada de esto ocurre. Fin.
                            │
                            ▼ positivo
              [harness de variantes reusable (§2)]
                            │
        ┌───────────────────┼────────────────────┐
        ▼                   ▼                    ▼
   Q4 (BA: ¿qué       Q2 (Broker: ¿qué      Q8+Q10 (RFM:
   fallo arregla?)    gana con 2 fuentes?)   licencia + R2)
   sin código          sin código             sin código
        │                   │                    │
        ▼                   ▼                    ▼
   BA en shadow        Broker = refactor    RFM shadow mode
   (medir Q7)          cuando llegue el 3º  (solo si Q8 y Q10
        │              proveedor             pasan)
        └───────────────────┴────────────────────┘
                            ▼
              adopción según §25/§26 del doc externo
```

**Lo que este orden dice y conviene no perder:** las tres piezas tienen una fase inicial que
**no requiere escribir código** (Q2, Q4, Q8, Q10). Contestar esas cuatro preguntas es el
trabajo real del próximo paso, y se puede hacer entero sin tocar el repo y sin esperar a la
Fase 3. Es lo único de este handoff que no está bloqueado.

---

## 5. Costos reales de este repo que el doc externo no pesó

El doc externo es sólido en arquitectura y genérico en costos. Estos cinco son específicos y
cambian las conclusiones:

1. **No hay suite de tests.** Declarado como decisión consciente en [CLAUDE.md](../CLAUDE.md).
   La tarea 3.6 sería el primer `tests/` del repo. Todo lo de este handoff se apoya en
   medición, y medir sin runner es lo que hace que "shadow mode" suene barato y no lo sea.
2. **Ollama `-np 1`:** cada modelo distinto en el pipeline fuerza unload+reload. Por eso el BA
   sobre el tag del Manager es barato y cualquier modelo nuevo es caro. Está medido en los
   comentarios de [config/settings.yaml](../config/settings.yaml) (gemma3 27B denso: 157.8s en
   design gate vs. gemma4 MoE: 22.7s en task breakdown).
3. **`max_context_chars: 6000` es un techo duro, no un objetivo.** Más proveedores no agrandan
   el contexto; le sacan lugar al RAG. `_assemble_context` ya reporta `over_budget` en vez de
   truncar. Cualquier propuesta que agregue una fuente tiene que decir **a qué se lo saca**.
4. **El Router es `phi3:mini` y ya misclasifica con 4 categorías.** La dimensión
   `needs_relational_context` del doc externo §22 ya está declarada fuera de alcance por esa
   razón exacta ([plan-schema-grounding.md](plan-schema-grounding.md) §8). Cualquier diseño
   que dependa de que el Router decida si corre un proveedor hereda ese problema entero.
5. **El recibo tiene un consumidor externo real (fenix).** Cada bloque nuevo en `outcome` es
   un bump de `SCHEMA_VERSION` y una entrada en
   [handoff-fenix-parte-b.md](handoff-fenix-parte-b.md). El doc externo §21 propone
   `business_analysis` y `relational_intelligence` como si fuera gratis; el precio es avisarle
   a un llamador que ya validó contra 1.1.

Hay además un problema declarado que **va a contaminar cualquier medición** de todo esto y no
tiene dueño: **H3, el vector store no tiene noción de proyecto**
([plan-schema-grounding.md](plan-schema-grounding.md) §8). Chunks de proyectos distintos
conviven en un índice global sin filtro. La Fase 3 lo esquiva con un `vector_db_path` limpio
por corrida, que es un workaround. Un experimento A/B/C/D serio necesita el arreglo, no el
workaround.

---

## 6. Seguridad y licencia

Todo lo de [plan-schema-grounding.md](plan-schema-grounding.md) §7 sigue vigente y se extiende:

- **Nunca un DSN por argv.** Si hace falta, va por env (`LDE_DB_URL`, siguiendo el precedente
  de `LDE_OLLAMA_HOST`) o archivo.
- **Credenciales fuera de los prompts**, siempre.
- Cualquier proveedor relacional abre **read-only**.
- **Sin sample rows** sin un control propio y explícito. Un RFM que consuma datos (no
  metadata) es exactamente eso, a escala — Q11.
- **Q8 (licencia de RT-J) es un gate previo, no un checklist de cierre.**

---

## 7. Preguntas abiertas — el worklist real del próximo paso

Todas se contestan **sin escribir código** y **sin esperar a la Fase 3**, salvo donde se
indica. Esto es lo que hay que hacer, en este orden:

| # | Pregunta | Cómo se contesta | Bloquea |
|---|---|---|---|
| Q4 | ¿Qué fallo observado arreglaría un BA? | Revisar a mano `query` + `breakdown` de recibos reales ya guardados | Todo el paquete BA |
| Q10 | ¿Hay un caso donde el cierre de FK falla y un RFM acertaría? | En papel, sobre un esquema de ejemplo | Todo el paquete RFM |
| Q8 | ¿La licencia de los pesos RT-J admite el uso previsto? | Leer la licencia | Todo el paquete RFM |
| Q2 | ¿Qué gana un Broker con solo 2 proveedores? | Razonamiento honesto sobre `_assemble_context` | Prioridad del Broker |
| Q7 | ¿Cómo se observa "menos ambigüedad"? | Definir métrica **antes** de medir nada | Gate del BA |
| Q1, Q3, Q5, Q6, Q9, Q11 | (ver §3) | Dependen de las anteriores | — |

**Si Q4 y Q10 se contestan "no hay caso"**, el resultado correcto de este handoff es cerrar
las tres piezas como no justificadas y documentarlo. Eso sería un éxito arquitectónico, no un
fracaso — el propio doc externo lo dice en su §26 ("C ≈ D … that would still be a successful
architectural outcome").

---

## 8. Fuera de alcance de este handoff

- **Diseñar cualquiera de las tres piezas.** A propósito. Diseñar antes de contestar §7 es el
  error que este documento existe para evitar.
- **La Fase 4 del schema plan** (4.1-4.4). Vive en [plan-schema-grounding.md](plan-schema-grounding.md) §5.3 y tiene su propio gate.
- **H3 (vector store sin noción de proyecto) y H5 (`.sql` como prosa).** Problemas reales,
  independientes, con dueño propio. H3 se menciona en §5 porque contamina la medición, no
  porque este documento lo adopte.
- **`needs_relational_context` en el Router.** Ya declarado fuera de alcance, por el motivo de
  §5.4.

---

## 9. Punteros de lectura, en orden, para quien llegue en frío

1. [plan-schema-grounding.md](plan-schema-grounding.md) §5.2 — el gate que bloquea todo.
2. [core/orchestrator.py:278-381](../core/orchestrator.py) — `_assemble_context`, el
   proto-broker. Leer los comentarios, que explican por qué el orden de prioridad es el que es.
3. [context/schema/selection.py](../context/schema/selection.py) — el grafo de FK determinista
   contra el que hay que probar cualquier RFM (Q10).
4. [config/settings.yaml](../config/settings.yaml) — los comentarios inline tienen los números
   medidos de latencia por modelo, que son el costo real de agregar etapas.
5. [handoff-fenix-parte-b.md](handoff-fenix-parte-b.md) — quién consume el recibo y qué se
   rompe si cambia.
6. `LocalDevEngine_RFM_RTJ_Architecture_Recommendation.md` (externo) — leerlo **último**, con
   la tabla de traducción de §0 al lado.
