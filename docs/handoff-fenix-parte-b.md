# Handoff a fenix: Parte B (controles del lado consumidor)

Este documento es el traspaso de [docs/plan-mitigation-fenix-outsourcing-controls.md](plan-mitigation-fenix-outsourcing-controls.md)
hacia el repo de fenix. **Parte A (este repo, LocalDevEngine) está implementada y verificada** —
ver el estado final más abajo. **Parte B (controles en `delegate-low-rri.py`/`delegate-local-dev-engine.py`)
no se tocó**: vive en otro repo y le corresponde a quien mantiene fenix implementarla. Este doc existe
para que esa implementación no tenga que releer el plan completo ni adivinar qué de Parte A quedó
disponible.

## Aviso: el recibo subió a `schema_version` 1.1

Después de la sesión que cerró Parte A, se agregó una capa opt-in nueva (schema grounding,
`--schema-file`, ver [docs/plan-schema-grounding.md](plan-schema-grounding.md)) que tocó la forma
del recibo otra vez. El cambio es **aditivo**: todo lo documentado abajo para Parte A sigue
presente exactamente igual, con dos claves nuevas en `outcome` (`schema_grounding`,
`context_budget`), un campo nuevo en `outcome.rag` (`chunks_eligible`) y un sub-bloque nuevo en
`config_fingerprint` (`request`). Un parser que solo lee las claves que ya conoce sigue
funcionando sin tocar nada. **La única forma de romperse es si `delegate-local-dev-engine.py`
valida `schema_version == "1.0"` de forma estricta** (igualdad exacta en vez de "es al menos
1.0") — si B2 o cualquier otro control hace eso, hay que relajarlo a `>= "1.0"` o listar `"1.0"` y
`"1.1"` como válidos. Ninguno de los 11 controles de Parte B necesita la capa de schema grounding
para funcionar; es indiferente a ellos salvo por este chequeo de versión.

## Qué cambió en LocalDevEngine (Parte A) — disponible para consumir hoy

Todos los pasos A1-A7 del plan están implementados en `main`. Resumen por pieza:

### A1 — `--json`/`--out`/`--quiet` + exit codes

```
python main.py ask --json [--out FILE] [--quiet] [--output-contract fenix-tagged-file] "<query>"
python main.py ask --input-file FILE.txt              # o stdin si no hay query posicional
```

- `--json`: stdout es **JSON puro** (el recibo completo, ver A2 abajo); el stream en vivo del
  modelo se redirige a stderr. Sin `--json`, stdout sigue siendo texto legible con colores ANSI
  como siempre.
- `--out FILE`: escribe el recibo a `FILE` en vez de stdout; stdout queda para el stream legible.
- `--quiet`: apaga el streaming en vivo entero (ni stdout ni stderr).
- `--input-file FILE` / stdin: para packets que no entran o no escapan bien en argv.
- Exit codes: **0** = el pipeline corrió (completo, fast-path, o incluso `status: "failed"/"timeout"`
  se documentan aparte, ver abajo) y hay un recibo parseable. **2** = el motor falló a mitad de
  corrida o pegó en `max_run_seconds` (recibo parcial, igual generado). **3** = error de uso
  (flag desconocida, argumentos extra, comando desconocido).
- **Importante para B6:** el exit code SOLO informa "hay recibo o no". Un `status: "failed"` o
  `status: "timeout"` con exit 2 sigue trayendo un recibo válido y parseable — no es lo mismo que
  "no hay nada que leer". Y exit 0 nunca implica `qa_approved: true` ni ningún juicio de calidad.

Implementado en `main.py` (`_parse_ask_args`, `DevOrchestratorCLI.ask_once`).

### A2 — RAG stats + resultado del design gate en el recibo

`run_complex_task` ahora devuelve, además de las claves legacy (`plan`, `implementation`,
`fast_path`, `qa_approved`, `qa_feedback`, `breakdown`, `closing_report`, `deviation`,
`request_id`, `trace`, `macro_iteration` — todas se mantienen sin cambios para no romper nada
existente), un objeto `outcome` con:

```json
"outcome": {
  "router_decision": "CODING_REQUEST",
  "fast_path": false,
  "rag": {"ran": true, "chunks_retrieved": 5, "chunks_eligible": 4, "chunks_used": 2,
          "context_chars": 2986, "scores": [0.53, 0.51], "sources": ["core/chunking.py"]},
  "schema_grounding": {"ran": false},
  "context_budget": {"ran": true, "max_total_chars": 6000, "schema_chars": 0,
                      "breakdown_chars": 420, "prior_report_chars": 0, "rag_chars": 2986,
                      "rag_pieces_included": 2, "rag_pieces_dropped": 2, "reserved_chars": 0,
                      "used_chars": 3406, "over_budget": false},
  "design_gate": {"ran": true, "mode": "sectioned", "approved": true,
                   "sections": {"Data Model": {"approved": true, "attempts": 1}, ...}},
  "implementation_check": {"ran": true, "approved": true, "attempts": 1, "feedback": null},
  "closing_report": {"ran": true, "deviation": "NONE", "summary": "..."}
}
```

Cada stage opcional trae `"ran": true|false` explícito — nunca hay que inferir "no corrió" de un
campo en `null` (eso era el hallazgo #5 del receipt plan: antes, `deviation: null` significaba
tanto "no hubo desvío" como "el stage estaba apagado", indistinguibles). Lo mismo aplica ahora a
`schema_grounding` (`ran: false` si la corrida no recibió `--schema-file`, o si fue fast-path) y a
`context_budget` (`ran: false` solo en fast-path, que no arma contexto).

`rag.chunks_eligible` vs. `rag.chunks_used`: `chunks_eligible` es cuántos chunks pasaron el cap
por-fuente (`max_chunks_per_source`); `chunks_used` es cuántos de esos entraron de verdad en el
presupuesto compartido después de que el bloque de schema y el outline del Manager reclamaran su
parte (ver `context_budget` y "Extra: schema grounding" más abajo). Para **B3** (grounding
relevante al scope), el campo correcto a mirar sigue siendo `chunks_used` — es el que refleja qué
terminó realmente en el prompt, no solo qué se recuperó.

### A3 — Perfil de salida `fenix-tagged-file`

`--output-contract fenix-tagged-file` hace que el Implementer reciba la gramática exacta que ya
espera `delegate-low-rri.py` (`STATUS`/`SUMMARY`/`=== FILE START ===`/`PATH`/`ACTION`/
`--- CONTENT ---`/`=== FILE END ===`), copiada **verbatim** del propio `build_payload()` de ese
script — no es una gramática nueva, es la misma que ya usan con Gemma hoy. Fuente:
`prompts/specialized_prompts.py: PromptRegistry._FENIX_TAGGED_FILE_GRAMMAR`.

Además — esto es lo que cierra G11 del lado del motor — cuando este perfil está activo, la QA de
implementation-check recibe una instrucción explícita: **debe** marcar `NEEDS_REVISION` si la
gramática está rota, sin importar si el código es correcto (`get_qa_review_template`'s
`contract_check` block). Esto reduce la probabilidad de que `qa_approved: true` esconda una
respuesta que el parser real rechaza, pero **no la elimina** — ver B4 abajo, que es el control que
de verdad cierra ese gap.

Verificado en vivo: una corrida real con `--output-contract fenix-tagged-file` sobre una tarea de
código produjo un output que el parser de `delegate-low-rri.py` (`parse_file_block`/la función que
lee `=== FILE START ===`) acepta tal cual — ver sección "Verificación" más abajo para el resultado
concreto de esa corrida.

### A4 — `config_fingerprint`

Cada recibo trae:

```json
"config_fingerprint": {
  "models": {"router": "phi3:mini", "manager": "gemma4:26b-a4b-it-qat", ...},
  "max_qa_iterations": 2,
  "closing_report_enabled": true,
  "retrieval": {"top_k": 5, "min_score": 0.0, "max_context_chars": 6000},
  "schema_grounding": {"max_tables": 12, "max_chars": 4000, "fk_expansion_depth": 1},
  "request": {"output_contract": null, "schema_grounding": false, "schema_tables": 0}
}
```

Construido en `core/receipt.py: build_config_fingerprint()` a partir de `self.config` en el
momento exacto de esa corrida — no hay forma de que quede desincronizado del `settings.yaml` real
que se usó. `max_context_chars` subió de 3000 a 6000 porque ahora es el techo de **todo** el
contexto ensamblado (schema + outline + RAG), no solo de los chunks — si `delegate-local-dev-engine.py`
tiene ese número hardcodeado en algún check de B2, hay que actualizarlo.

El sub-bloque `request` es nuevo: a diferencia del resto de `config_fingerprint` (que viene de
`self.config`, fijo por deploy), estos son los parámetros **de esa corrida puntual** —
`output_contract` y `schema_grounding`/`schema_tables` no viven en `settings.yaml`, se pasan por
request. Antes de este cambio, un caller no tenía forma de verificar desde el recibo si
`--output-contract fenix-tagged-file` estuvo activo en una corrida dada; ahora sí. Relevante para
**B2**: el chequeo de precondición debería incluir `request.output_contract` si fenix depende de
que ese contrato esté activo.

### A5 — Recibo en la falla + `pipeline.max_run_seconds`

- `config/settings.yaml: pipeline.max_run_seconds` (default 1500s) envuelve la corrida completa
  con `asyncio.wait_for`. Si se cumple, el resultado es `status: "timeout"` con el `trace` parcial
  hasta donde llegó — nunca una excepción sin estado ni un proceso colgado.
- Cualquier `ModelCallError` (fallo HTTP/transporte con Ollama) durante la corrida produce
  `status: "failed"` con `error: {stage, role, model, message}` y el mismo `trace` parcial.
- En ambos casos, `plan`/`implementation`/`breakdown`/`closing_report` quedan en `null` — no hay
  resultado parcial de esas claves, solo el trace/outcome de lo que sí corrió.
- Verificado en vivo: bajando `max_run_seconds` a 5s y 15s sobre una query de código real, ambos
  casos produjeron un recibo `status: "timeout"` válido (JSON parseable, `error.stage` reflejando
  la última etapa completada). También verificado un `ModelCallError` genuino apuntando
  `LDE_OLLAMA_HOST` a un puerto inalcanzable: `status: "failed"`, exit 2, `error.message: "All
  connection attempts failed"`.

**Para B7:** si van a fijar `FENIX_LDE_MAX_WALL_SECONDS` en fenix, debe quedar por encima de
`max_run_seconds` (1500s hoy) para que el timeout interno del motor dispare primero que el kill
externo — así el recibo parcial sobrevive.

### A6 — `.go` en ingestion + chunker estructural Go

`config/settings.yaml: ingestion.extensions` ahora incluye `.go`, y `core/chunking.py` parte
archivos Go en unidades por `func `/`type `/`package ` en columna 0 (mismo mecanismo que ya existía
para Python). Si fenix quiere que LocalDevEngine indexe su codebase Go (`internal/`, `cmd/`,
`pkg/`), correr `python main.py ingest <path-al-repo-de-fenix>` (reingesta — reemplaza por fuente,
no duplica).

### A7 — Override de host Ollama

`LDE_OLLAMA_HOST` (env var) reemplaza el default `http://localhost:11434/api` en las tres
construcciones de cliente (`ModelFactory`, `EmbeddingService`). Útil si fenix corre su propio
Ollama en otro host/puerto y necesita que LocalDevEngine le pegue a ese en vez del local.

### Extra: `Orchestrator.aclose()` / `async with`

`Orchestrator` ahora expone `aclose()` y `__aenter__`/`__aexit__`, así que un caller que lo
embeba como librería (en vez de invocar el CLI) no necesita tocar `orchestrator.embedder`
directamente.

### Extra: schema grounding (`--schema-file`, opt-in, no forma parte del plan A1-A7)

Construido en una sesión posterior, documentado acá porque toca el recibo que Parte B consume.
**Fenix no necesita usar esto** — es opt-in y no afecta ningún control B1-B11 si no se pasa
`--schema-file`. Si en algún momento fenix quisiera exportar el schema de su propia base de datos
para reducir invención de nombres de tabla/columna en las respuestas del Implementer, la interfaz
es:

```
python main.py ask --schema-file schema.json "<query>"
```

`schema.json` es un snapshot exportado por fenix (tablas/columnas/tipos/FK) — LocalDevEngine
**nunca** abre una conexión a una base de datos ni ve una credencial; ver
[docs/plan-schema-grounding.md](plan-schema-grounding.md) §3.1 y §7. Un archivo inválido o
inexistente es `EXIT_USAGE` (3), nunca una corrida degradada en silencio.

Cuando está activo, `outcome.schema_grounding` trae:

```json
"schema_grounding": {
  "ran": true, "source": "schema.json", "dialect": "postgresql",
  "tables_in_snapshot": 4, "tables_shown": ["public.orders", "public.customers"],
  "tables_omitted": [], "matched": ["public.orders"], "related_via_fk": ["public.customers"],
  "strategy": "lexical", "degraded": false, "reason": null,
  "block_chars": 812, "max_chars": 4000, "block_over_budget": false,
  "conformance_check": {
    "ran": true, "verdict": "NO_CONFORME",
    "violations": [
      {"type": "UNKNOWN_COLUMN_REF", "detail": "public.orders.discount_percent", "line": 42}
    ],
    "regions_checked": 3, "regions_unparseable": 0, "regions_untyped": 0
  }
}
```

`conformance_check` **reemplaza** el `identifier_check` que una versión anterior de este
documento marcó como no utilizable (ver [docs/fase3-decision.md](fase3-decision.md) para el
diagnóstico completo de por qué el checker basado en regex fallaba en ambas direcciones — eso
sigue siendo la historia correcta de por qué se reemplazó, no una descripción del campo actual).
El reemplazo está especificado en
[docs/plan-schema-conformance.md](plan-schema-conformance.md) y **construido** (tareas C.1–C.6):
un extractor basado en `ast` de Python (no regex) reconoce patrones SQLAlchemy declarativo
(`__tablename__`, `Column`/`mapped_column`, `.query(Model)`/`select(Model)`), resuelve cada
referencia contra `snapshot ∪ definiciones vistas en la salida`, y produce una lista tipada de
violaciones en vez de un contador escalar. Validado contra un corpus de 22 casos etiquetados a
mano (los 15 recibos con implementación real de la Fase 3 + 7 sembrados) con **0 falsos positivos
y 100% de detección** (`tests/run_conformance_gate.py`, corpus en
`tests/fixtures/schema/conformance_corpus/`).

**Qué sí es utilizable, y con qué límites:**

- `verdict: "CONFORME" | "NO_CONFORME"` y la lista `violations` (`type`, `detail`, `line`) **sí
  son una señal de auditoría real** — determinista, recomputable por fenix a partir de
  `(implementación, snapshot)`, y verificada contra evidencia real, no solo teóricamente
  recomputable como pasaba con el campo anterior.
- **Alcance de reconocimiento, no de dato**: el modelo de datos verificado es 100% genérico (el
  `SchemaSnapshot` que fenix exporta). Lo que NO es genérico todavía es qué *patrones de código*
  el extractor reconoce — hoy solo SQLAlchemy declarativo en Python. Cualquier otro acceso a
  datos (Django ORM, `psycopg2`/queries crudas, SQL embebido) no genera `UNKNOWN_*` porque el
  extractor no lo reconoce — en cambio, la región se marca `UNPARSEABLE_REGION` (si el bloque se
  declaró como código pero no parseó, o es SQL — SQL nunca se parsea, ver más abajo) o
  `UNTYPED_REGION` (bloque de código sin lenguaje declarado). **Un `verdict: "CONFORME"` con
  varios `UNPARSEABLE_REGION`/`UNTYPED_REGION` no significa "sin alucinaciones" — significa "sin
  alucinaciones detectadas en lo que se pudo verificar".** fenix debe mirar `regions_unparseable`/
  `regions_untyped` junto con `verdict`, no solo `verdict` solo.
- **SQL crudo nunca se parsea** (decisión registrada en plan-schema-conformance.md §5: `sqlglot`
  quedó deferido por falta de evidencia de que fuera necesario — los dos únicos eventos de
  invención genuinos de la Fase 3 fueron construcciones Python/ORM, no SQL). Toda región `sql`
  se reporta como `UNPARSEABLE_REGION`, siempre.
- `regions_checked` es cuántas regiones Python se lograron parsear y analizar; no incluye prosa
  (nunca se analiza, por diseño) ni SQL/untyped (van a los contadores de arriba).

**Lo que sigue sin cambiar:** este campo corre en modo `report` únicamente — nunca bloquea ni
gatea la corrida. El modo `enforce` (rechazar y reintentar sobre una violación) está especificado
pero diferido (C.7 en plan-schema-conformance.md §8), condicionado a que la forma del pipeline
BA/Broker se defina primero, porque tocaría el mismo lazo QA↔Implementer que esa pieza
reestructuraría. Si fenix necesita bloqueo hoy, tiene que leer `conformance_check.verdict` y
decidir del lado de fenix — el motor no lo hace por vos todavía.

**Estado del resto de la capa:** el bloque de schema en sí (selección + render autoritativo)
sigue disponible y es opt-in, sin costo si no se activa. La Fase 3 no pudo demostrar
estadísticamente que reduzca invención de nombres (el instrumento de medición de esa fase era el
`identifier_check` roto) — eso sigue siendo cierto y no lo revierte el trabajo de arriba, que es
sobre la *detección* post-hoc, no sobre si el bloque previene la invención en primer lugar.

## Qué NO cambió (y por qué importa para Parte B)

- El motor **sigue autoreportándose**. Nada de Parte A es una atestación independiente — un motor
  con un bug (o modificado) puede emitir un recibo prolijo con `qa_approved: true` y
  `config_fingerprint` correcto. Esto es estructural, no algo que una iteración futura de Parte A
  vaya a resolver.
- El motor **no emite un patch estructurado**. `artifacts.implementation` sigue siendo texto (o,
  con `--output-contract fenix-tagged-file`, texto en una gramática específica) — nunca una lista
  de paths que el allowlist de fenix pueda confiar ciegamente. El parser de fenix sigue siendo la
  única fuente de verdad sobre qué archivos se tocaron.

## Los 11 controles de Parte B — qué falta implementar en fenix

Copiados de la tabla original del plan (ver el doc completo para el detalle de cada uno). Estado:
**ninguno implementado en fenix todavía** — esta sección es la lista de trabajo, no un reporte de
avance.

| # | Control | Depende de Parte A | Bloqueado hoy? |
|---|---|---|---|
| B1 | `qa_approved`/`deviation` son señales de auditoría, nunca gates de aceptación — el gate real sigue siendo `enforce_scope()` + `peer-workflow-review.py --caller-kind local-provider` | No | **No** — se puede escribir ya |
| B2 | `config_fingerprint` como precondición: comparar contra los valores esperados antes de aceptar; si no matchean, `BLOCKED` | Sí (A4) | Desbloqueado — A4 está listo |
| B3 | Grounding relevante al scope: `chunks_used > 0` Y al menos un `source` dentro de `--allow-path` | Sí (A2) | Desbloqueado — A2 está listo |
| B4 | El parser de `delegate-local-dev-engine.py` es el gate real de la gramática, nunca `qa_approved` | Sí (A3) | Desbloqueado — A3 está listo |
| B5 | El allowlist se aplica a los `FILE START` blocks reales, nunca a lo que `trace`/`artifacts` declaran | No | **No** — ya es invariante de fenix hoy |
| B6 | Exit code 0 = "hay recibo", nunca "aprobado" | Sí (A1) | Desbloqueado — A1 está listo |
| B7 | Preferir que el timeout lo dispare el engine: `FENIX_LDE_MAX_WALL_SECONDS` > `max_run_seconds` (1500s) | Sí (A5) | Desbloqueado — A5 está listo |
| B8 | Lock file real para contención de Ollama (no solo regla operacional) | No | **No** — del lado de fenix enteramente |
| B9 | Binding `query_sha256`/`task_id`: verificar que corresponde al packet enviado antes de aceptar | Sí (A4/A5) | Desbloqueado — `query_sha256` está en el recibo |
| B10 | Auditoría de doble columna en `logs/gemma-audit/YYYY-MM.jsonl`: `lde_qa_approved` vs. verificación independiente (B3/B4) | Sí (A2/A4) | Desbloqueado |
| B11 | `fast_path: true` en una tarea `CODING_REQUEST`-shaped es anomalía → `BLOCKED` | No | **No** — `fast_path` ya estaba en el dict antes de este plan |

**Los cinco que no dependen de Parte A (B1, B5, B6, B8, B11) ya se podían escribir antes de esta
sesión** — el plan original los señalaba como "adoptar hoy, sin esperar". Con Parte A ahora
completa, **los once están desbloqueados**. Ninguno tiene código en fenix todavía.

## Siguiente paso recomendado (del plan original, sección "Encaje con la Fase 0")

Correr B3, B4 y B11 durante los mismos runs de la spike de Fase 0 de fenix (los 2-3 packets de
tareas Low-RRI reales que el §9 de `local_dev_engine_delegation_migration_proposal.md` ya pide),
no en una corrida aparte — así cualquier `qa_approved: true` que B4 rechace por gramática inválida
es la evidencia real de G11 que ese proposal necesita.

## Verificación de Parte A (lo que se corrió en esta sesión)

- `ask --json --quiet` sobre una query fast-path (`SIMPLE_TASK`) → exit 0, `outcome.fast_path: true`,
  `outcome.rag.ran: false`, stdout parseable con `json.loads` sin ANSI.
- `max_run_seconds` bajado a 5s y 15s sobre una query `CODING_REQUEST` real (invocando el
  Orchestrator directamente, no vía CLI) → ambos casos `status: "timeout"`, JSON válido, `trace`
  parcial presente, `error.stage` reflejando la última etapa completada.
- `--input-file` con una query fast-path → recibo correcto, `query` coincide con el contenido del
  archivo.
- Exit codes de uso: `--output-contract bogus` → 3; query posicional + argumento extra → 3;
  comando desconocido → 3.
- Mapeo de exit code para `status: "timeout"`/`"failed"` → 2 (verificado con un Orchestrator fake
  para no depender de una corrida real, y luego confirmado con un `ModelCallError` real apuntando
  `LDE_OLLAMA_HOST` a un puerto inalcanzable).
- Chunker Go: reconstrucción lossless verificada sobre un archivo `.go` sintético con
  `func`/`type`/`package`.
- `closing_report_enabled: false` verificado por lectura de código (`core/orchestrator.py`):
  `outcome.closing_report` es exactamente `{"ran": false}` cuando `pipeline.closing_report` está
  apagado — nunca trae `deviation`, así que no puede confundirse con `{"ran": true, "deviation":
  "NONE"}`.
- `--output-contract fenix-tagged-file` sobre una tarea de código real (`CODING_REQUEST`,
  "crear `is_palindrome` en `utils/palindrome.py` + tests"): pipeline completo Router→RAG→
  Manager→Architect↔QA (sectioned, una sección — Dependencies/Integration — necesitó una
  revisión, aprobada en el intento 2)→Implementer↔QA (aprobado en el intento 1)→closing report
  (`deviation: NONE`), 530s de duración total, `status: "completed"`. El output crudo del
  Implementer se pasó, sin ninguna modificación, por la función real `parse_tagged_response`
  de `delegate-low-rri.py` (importada directamente del repo de fenix, no reimplementada) y
  parseó limpio: `status: "patch"`, `summary` correcto, 3 archivos (`utils/__init__.py`,
  `utils/palindrome.py`, `test_palindrome.py`) con `path`/`action`/`contents` completos y
  correctamente delimitados, `test_commands` y `risk_notes` extraídos. Confirma que el contrato
  es byte-compatible con el parser existente de fenix sin tocarlo.

Lo que quedó explícitamente fuera de esta sesión: el `config_fingerprint` con
`max_qa_iterations: 0` forzado (verificación B2/B9 del plan) no se corrió — es una prueba del lado
de fenix (`delegate-local-dev-engine.py` detectando el mismatch), no algo que LocalDevEngine deba
demostrar por su cuenta más allá de que el campo existe y refleja `self.config` con precisión (lo
cual sí se verificó, ver el primer bullet de esta lista).
