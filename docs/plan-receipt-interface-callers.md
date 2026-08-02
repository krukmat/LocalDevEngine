# Plan: receipt verificable + interfaz para sistemas que llaman al motor

## Contexto

Hoy `main.py` es la única forma de invocar el pipeline, y su salida es texto ANSI en stdout para que lo lea un humano. Cuando el llamador es **otro agente** (caso concreto: fenix delegando propuestas de código vía `subprocess`), el motor pasa a ser una caja negra: el llamador ve el resultado final pero no puede verificar *qué hizo el pipeline para producirlo*.

El riesgo real no es "el modelo mintió". Es **degradación silenciosa**: que el pipeline haga menos de lo que dice hacer (fast path en una tarea de código, RAG vacío, gate de diseño que se rindió) y que el llamador lo aplique como si hubiera pasado por las cinco etapas.

`run_complex_task` ya devuelve un `trace` por etapa. Este plan evalúa **qué le falta a ese trace para servir como recibo verificable**, y qué hay que ajustar en la interfaz para que un llamador no-humano pueda consumirlo.

**Límite explícito, que condiciona todo el diseño:** el recibo lo genera el mismo código que se está auditando. No es una frontera de seguridad ni una atestación independiente. Sirve para detectar que se hizo *menos*, nunca para probar que se hizo *bien*. La regla derivada: **el recibo solo puede bajar la confianza del llamador, nunca subirla por encima de lo que el llamador verifica por su cuenta.**

---

## Las cuatro señales que un llamador necesita, contra lo que el motor devuelve hoy

| # | Señal | ¿Está en el dict de retorno? | Evidencia |
|---|---|---|---|
| 1 | `fast_path: true` — el Router saltó RAG + design gate + QA entero | ✅ Sí | `core/orchestrator.py:342` |
| 2 | `chunks_used == 0` — la propuesta se escribió a ciegas | ❌ **No existe** | `_build_rag_context` (`:185-241`) calcula `chunks_retrieved`/`chunks_used`/`context_chars`/`scores` y **solo los loguea** (`:235-240`). Devuelve un `str`; no recibe `trace` ni le agrega nada. |
| 3 | `qa_approved: false` — el pipeline no convergió | ⚠️ Parcial y **engañoso** | `:572` devuelve solo el resultado del *implementation check*. El `all_approved` del design gate se calcula en `:446` y se loguea en `:448-451`, pero **nunca se retorna**. Un run donde el gate se rindió en 2 de 4 secciones y la implementación pasó, retorna `qa_approved: true`. |
| 4 | Attempts por sección | ✅ Sí | `qa_entry["attempt"]` + `qa_entry["section"]` (`:421-423`) |

O sea: de las cuatro señales, **una falta por completo y otra sobreestima la confianza** — exactamente en la dirección peligrosa.

---

## Hallazgos adicionales (huecos que las cuatro señales no cubren)

| # | Hallazgo | Evidencia |
|---|---|---|
| 5 | **`deviation: null` significa dos cosas incompatibles.** Es `None` tanto en fast path (`:345`) como cuando `pipeline.closing_report: false` deja el stage sin correr (`:541-543`). El llamador no puede distinguir "no se detectó desvío" de "el chequeo no se ejecutó". Fail-closed exige distinguirlo. | `core/orchestrator.py:341-349`, `:541-566` |
| 6 | **Un run que falla no deja recibo.** `ModelCallError` se propaga desde `_call_model` y `trace` es una lista local: todo lo hecho hasta el punto de falla se pierde. El llamador recibe una excepción sin saber en qué etapa murió. | `models/base.py:5-11`, `core/orchestrator.py:308` |
| 7 | **El exit code es siempre 0.** `ask_once` captura `ModelCallError` e imprime (`main.py:136-137`); comando desconocido, query vacía y fallo de modelo terminan igual que un éxito. No hay ningún `sys.exit` fuera del guard de import (`main.py:16`). | `main.py:126-137`, `:226-255` |
| 8 | **No hay salida estructurada.** `ask_once` descarta `result` después de imprimirlo (`:131-135`). Un `subprocess` tendría que quitar ANSI y parsear encabezados en español (`--- PLAN DEL ARQUITECTO ---`) para separar plan de implementación. Es el hueco que bloquea todo lo demás. | `main.py:64-97`, `:126-135` |
| 9 | **El recibo no es autocontenido.** Lleva `request_id` pero no la query que respondió ni un hash. Guardado como artefacto de auditoría, no permite probar a qué tarea corresponde. | `core/orchestrator.py:568-580` |
| 10 | **La config puede desactivar los chequeos sin que el recibo lo muestre.** `closing_report: false` anula el reporte de cierre; `max_qa_iterations: 0` hace que el loop QA corra exactamente una vez y no pueda devolver nada al Architect (`range(0+1)`, y `attempt == max_iterations` corta en la primera pasada). El presupuesto de retrieval (`top_k`, `max_context_chars`) también condiciona la señal #2. Nada de esto viaja en el resultado: **las cuatro señales pueden dar bien mientras la config apagó lo que declaran medir.** | `config/settings.yaml:54-78`, `core/orchestrator.py:351`, `:497`, `:543` |
| 11 | **No hay `schema_version`.** Si el shape cambia, el llamador no tiene cómo fallar cerrado sobre una versión desconocida. | — |
| 12 | **No hay timestamps absolutos.** Hay `duration_ms` por etapa (`:136`) pero ni `started_at`/`finished_at` ni duración total. Un registro de auditoría necesita tiempo de pared. | `core/orchestrator.py:130-138` |
| 13 | **La superficie de librería no tiene ciclo de vida.** `Orchestrator` no expone `aclose()` ni context manager: `main.py` alcanza el interno `cli.orchestrator.embedder.aclose()` (`:255`). Quien embeba la clase tiene que conocer ese detalle. | `main.py:254-255`, `core/orchestrator.py:75-86` |
| 14 | **No hay deadline de run completo.** `request_timeout_seconds: 300` es **por llamada HTTP**, no por pipeline. Un run con reintentos son 8-11 min; uno patológico es N etapas × 300s sin techo. El único recurso del llamador es matar el proceso — que destruye el recibo. | `config/settings.yaml:66`, `core/orchestrator.py:79-85` |
| 15 | **La entrada es solo argv.** `sys.argv[2]` (`main.py:245`), argumentos extra ignorados en silencio. Un paquete de entrada real (tarea + extractos de archivos + restricciones de ADR) choca con el límite de argv y con el quoting del shell. | `main.py:244-249` |
| 16 | **El recibo no puede declarar qué archivos se tocaron.** `implementation` es texto libre; no hay patch estructurado ni lista de paths. No es un bug — refuerza que el llamador tiene que construir el diff él mismo — pero hay que decirlo en el contrato para que nadie construya un allowlist sobre lo que el recibo declara. | `core/orchestrator.py:568-580` |
| 17 | `run_simple_query` (`:582-591`) sigue siendo código muerto fuera del call path. En una superficie pública de librería, invita a llamarlo creyendo que es el fast path. | `core/orchestrator.py:582`, CLAUDE.md |

---

## Qué ajustar

Dos capas separadas: **el recibo** (qué dato) y **el transporte** (cómo lo obtiene un llamador no-humano).

### A. El recibo

Shape propuesto. Todo stage opcional lleva `ran: true|false` explícito — ningún `null` puede significar dos cosas (hallazgo 5).

```json
{
  "schema_version": "1.0",
  "request_id": "a1b2c3d4e5f6",
  "status": "completed | failed | timeout",
  "query": "<texto original>",
  "query_sha256": "…",
  "started_at": "2026-08-02T18:07:53.827Z",
  "finished_at": "2026-08-02T18:16:25.114Z",
  "duration_ms": 511287,
  "macro_iteration": 1,

  "outcome": {
    "router_decision": "CODING_REQUEST",
    "fast_path": false,
    "rag":  { "ran": true, "chunks_retrieved": 5, "chunks_used": 2,
              "context_chars": 2986, "scores": [0.533, 0.506],
              "sources": ["core/chunking.py", "memory/base.py"] },
    "design_gate": { "ran": true, "mode": "sectioned", "approved": false,
                     "sections": { "Data Model": {"approved": true,  "attempts": 1},
                                   "Error Handling": {"approved": false, "attempts": 3} } },
    "implementation_check": { "ran": true, "approved": true, "attempts": 1, "feedback": null },
    "closing_report": { "ran": true, "deviation": "NONE", "summary": "…" }
  },

  "config_fingerprint": {
    "models": { "router": "phi3:mini", "manager": "gemma4:26b-a4b-it-qat",
                "architect": "qwen3.6:35b-a3b", "implementer": "qwen3.6:35b-a3b",
                "qa_auditor": "gemma4:26b-a4b-it-qat" },
    "max_qa_iterations": 2,
    "closing_report_enabled": true,
    "retrieval": { "top_k": 5, "min_score": 0.0, "max_context_chars": 3000 }
  },

  "artifacts": { "breakdown": "…", "plan": "…", "implementation": "…", "closing_report": "…" },
  "trace": [ { "stage": "routing", "role": "router", "model": "phi3:mini",
               "attempt": null, "duration_ms": 2066.0, "verdict": null,
               "decision": "CODING_REQUEST" } ],
  "error": null
}
```

Cambios de código que esto implica:

1. **`_build_rag_context` devuelve `(context, stats)`** en vez de solo el string, o recibe `trace` y appendea una entrada `stage="rag"`. Cierra el hueco #2, que es el más importante: sin esto la señal "escribió a ciegas" solo existe en logs.
2. **Retornar el resultado del design gate.** `all_approved` (`:446`) y el `mode` (sectioned/monolithic) al dict. Cierra la sobreestimación del hallazgo #3. `qa_approved` top-level se mantiene con su significado actual (implementation check) por compatibilidad, pero el recibo expone los dos por separado.
3. **`config_fingerprint`** armado desde `self.config` en el `return`. Cierra el #10 — es la diferencia entre señales chequeables y señales chequeables-pero-vacías.
4. **Recibo en la falla.** Envolver el cuerpo de `run_complex_task` para que `ModelCallError` produzca `status: "failed"` + `error: {stage, role, model, message}` + el `trace` parcial, en vez de perder todo (#6). Decisión abierta: retornar el recibo o adjuntarlo a la excepción (`ModelCallError` ya tiene precedente de campo extra con `partial`).
5. **`query`, `query_sha256`, timestamps, `schema_version`** — campos nuevos, sin lógica (#9, #11, #12).
6. **Punto único de construcción.** El recibo se arma en `core/` (p. ej. `core/receipt.py: build_receipt()`), no en `main.py`, para que la vía CLI y la vía librería emitan **el mismo objeto**. Si `main.py` lo arma por su cuenta, las dos se separan en la primera modificación.

Compatibilidad: las claves actuales (`plan`, `implementation`, `fast_path`, `qa_approved`, `qa_feedback`, `breakdown`, `closing_report`, `deviation`, `request_id`, `trace`, `macro_iteration`) se conservan. Los consumidores internos son `_print_result` y `_macro_rerun_available` (`main.py:64-97`, `:139-149`) — no hay razón para romperlos.

### B. El transporte

7. **`python main.py ask --json [--out FILE] "<query>"`**. Con `--json`, el stream de modelo va a **stderr** y stdout queda como JSON puro; con `--out`, el recibo va al archivo y stdout sigue siendo el stream legible. `--quiet` desactiva `on_chunk` del todo (#8).
8. **Exit codes con significado** (#7). Recomendación: `0` = el pipeline corrió hasta el final y hay recibo; `2` = falla del motor (recibo parcial); `3` = error de uso. **No** codificar `qa_approved`/`deviation` en el exit code: eso es política del llamador, y meterla acá obliga a cambiar el motor cada vez que un llamador cambia su umbral de aceptación. El recibo es la autoridad; el exit code solo dice si hay recibo.
9. **Entrada por stdin o `--input-file`** (#15), para paquetes de entrada que no caben ni se escapan bien en argv. Y fallar con código `3` ante argumentos extra en vez de ignorarlos.
10. **`Orchestrator.aclose()` + `__aenter__`/`__aexit__`** (#13), y `main.py` deja de tocar `embedder` directo.
11. **`pipeline.max_run_seconds`** con `asyncio.wait_for` alrededor del run, emitiendo `status: "timeout"` con trace parcial (#14). Un llamador que mata el proceso pierde justo la evidencia que necesitaba para decidir.
12. **Borrar `run_simple_query`** (#17).

### Prioridad

| Prioridad | Ítems | Por qué |
|---|---|---|
| **P0** — sin esto no hay contrato | `--json`/`--out` (7), exit codes (8), RAG en el recibo (1), design gate retornado (2) | Sin JSON no hay consumo posible; sin RAG y design gate el recibo miente por omisión. |
| **P1** — sin esto el recibo engaña | `ran` explícito (5), `config_fingerprint` (3), recibo en falla (4), query + schema_version (5) | Cada uno es un caso donde el llamador leería "todo bien" sobre un pipeline degradado. |
| **P2** — calidad de contrato | timestamps, stdin, `max_run_seconds`, `aclose()`, borrar dead code | Mejoran el uso; ninguno cambia una decisión de aceptación. |

---

## Lo que este plan explícitamente NO resuelve

- **Atestación independiente.** El recibo lo firma el sospechoso. Un motor con un bug (o modificado) puede emitir un recibo prolijo. No hay forma de arreglar esto desde adentro del motor.
- **Claims sobre archivos.** El motor no emite patch estructurado (#16); el llamador construye el diff comparando archivos reales y aplica su allowlist sobre eso, nunca sobre lo que el recibo declara.
- **Reemplazar el peer review externo.** El QA Auditor interno revisa *el plan contra sí mismo* y *la implementación contra el plan*. Un revisor externo revisa *el diff final contra los estándares del proyecto que lo recibe*. Son objetos de revisión distintos; colapsarlos deja al proponente corrigiendo su propio examen. Además `architect` e `implementer` comparten tag con lo que suele usarse como revisor local (`qwen3.6:35b-a3b`, `config/settings.yaml:15-24`) — con Ollama en slot único, propuesta y review también hay que **serializarlos**, nunca en paralelo.

## Verificación

Cada ítem P0/P1 se verifica sobre un run real:

- `--json` sobre una query fast-path → `outcome.fast_path: true`, `outcome.rag.ran: false`, stdout parseable con `json.loads` sin limpiar ANSI.
- `--json` sobre un `CODING_REQUEST` completo → `outcome.rag.chunks_used > 0` con `sources` del propio repo, `design_gate.sections` con attempts por sección, y esos números **coincidiendo con las líneas de log** del mismo run (el log sigue siendo la referencia cruzada).
- Recibo en falla: apagar Ollama a mitad de run → `status: "failed"`, exit code 2, `trace` con las etapas completadas antes del corte.
- `config_fingerprint`: correr con `closing_report: false` → `outcome.closing_report.ran: false` y `config_fingerprint.closing_report_enabled: false`, distinguible de `deviation: "NONE"`.
