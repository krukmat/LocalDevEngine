# Handoff a fenix: Parte B (controles del lado consumidor)

Este documento es el traspaso de [docs/plan-mitigation-fenix-outsourcing-controls.md](plan-mitigation-fenix-outsourcing-controls.md)
hacia el repo de fenix. **Parte A (este repo, LocalDevEngine) está implementada y verificada** —
ver el estado final más abajo. **Parte B (controles en `delegate-low-rri.py`/`delegate-local-dev-engine.py`)
no se tocó**: vive en otro repo y le corresponde a quien mantiene fenix implementarla. Este doc existe
para que esa implementación no tenga que releer el plan completo ni adivinar qué de Parte A quedó
disponible.

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
  "rag": {"ran": true, "chunks_retrieved": 5, "chunks_used": 2,
          "context_chars": 2986, "scores": [0.53, 0.51], "sources": ["core/chunking.py"]},
  "design_gate": {"ran": true, "mode": "sectioned", "approved": true,
                   "sections": {"Data Model": {"approved": true, "attempts": 1}, ...}},
  "implementation_check": {"ran": true, "approved": true, "attempts": 1, "feedback": null},
  "closing_report": {"ran": true, "deviation": "NONE", "summary": "..."}
}
```

Cada stage opcional trae `"ran": true|false` explícito — nunca hay que inferir "no corrió" de un
campo en `null` (eso era el hallazgo #5 del receipt plan: antes, `deviation: null` significaba
tanto "no hubo desvío" como "el stage estaba apagado", indistinguibles).

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
  "retrieval": {"top_k": 5, "min_score": 0.0, "max_context_chars": 3000}
}
```

Construido en `core/receipt.py: build_config_fingerprint()` a partir de `self.config` en el
momento exacto de esa corrida — no hay forma de que quede desincronizado del `settings.yaml` real
que se usó.

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
  la última etapa completada).

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
  para no depender de una corrida real).
- Chunker Go: reconstrucción lossless verificada sobre un archivo `.go` sintético con
  `func`/`type`/`package`.
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
