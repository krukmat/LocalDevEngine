# Plan: mitigación de los gaps del receipt + controles extra en la migración de fenixCRM

## Contexto

Dos documentos ya evaluaron cada lado por separado:

- [docs/plan-receipt-interface-callers.md](plan-receipt-interface-callers.md) (este repo) — qué le falta al `trace`/dict de retorno de `run_complex_task` para servir de recibo verificable, con prioridad P0/P1/P2.
- `docs/plans/local_dev_engine_delegation_migration_proposal.md` (fenix) — el análisis de gaps (G1-G11) para migrar `scripts/delegate-low-rri.py` de un call plano a Gemma hacia LocalDevEngine como backend.

Este plan une los dos: **qué mitigar dentro del engine** (Parte A) y **qué controles agregar del lado de fenix al consumir el resultado del outsourcing** (Parte B), respetando la regla ya establecida que condiciona todo lo demás:

> El recibo lo genera el mismo código que se está auditando. Solo puede bajar la confianza del llamador, nunca subirla por encima de lo que el llamador verifica por su cuenta.

Esto significa que Parte A y Parte B no son simétricas. Parte A hace que el recibo *diga la verdad sobre lo que el pipeline hizo*. Parte B hace que fenix *nunca dependa de que ese recibo diga la verdad* — lo trata como una pista a auditar, no como una prueba. Un engine perfecto en Parte A sin ningún control en Parte B sigue siendo, para fenix, una caja negra que se autocalifica. Los controles de Parte B son necesarios incluso si Parte A se implementa entera.

---

## Parte A — Mitigación dentro del engine

Reordena el P0/P1/P2 de `plan-receipt-interface-callers.md` en una secuencia de ejecución, y le suma un ítem que ese doc no cubría porque estaba fuera de su alcance (el contrato de *salida*, no el recibo): el perfil `fenix-tagged-file` que pide G1 del proposal de fenix.

| Paso | Cambio | Gaps que cierra | Por qué va en este orden |
|---|---|---|---|
| 1 | `--json`/`--out` + exit codes con significado (0/2/3) | Receipt plan P0 (7,8); fenix G2 | Sin esto no hay nada que consumir por subprocess — todo lo demás depende de que exista un JSON parseable |
| 2 | RAG stats y resultado del design gate en el dict de retorno | Receipt plan P0 (1,2); habilita señales #2 y #3 | Sin esto el recibo miente por omisión — un `qa_approved: true` puede esconder un design gate que se rindió |
| 3 | **Perfil de salida `fenix-tagged-file`**, seleccionable con `--output-contract`, que enseña al Implementer (y a la QA de implementation-check) la gramática `STATUS`/`FILE START`/`PATH`/`ACTION`/`CONTENT` de fenix en vez de prosa libre | fenix G1, y mitiga G11 | Es nuevo respecto al receipt plan (ese doc no contemplaba el contrato de *contenido*, solo el de *metadata*). Crítico: la QA de implementation-check debe validar conformidad de gramática como parte de su verdict cuando este perfil está activo — si no, QA puede aprobar una implementación "correcta" que fenix igual no puede parsear (exactamente G11) |
| 4 | `config_fingerprint` en el recibo + `ran: true\|false` explícito en cada stage opcional | Receipt plan P1 (3,5); hallazgo #10 | Habilita que fenix pueda distinguir "el gate corrió y aprobó" de "el gate estaba apagado por config" — precondición de los controles B2/B3/B9/B10 de abajo |
| 5 | Recibo también en la falla (`status: "failed"` + `trace` parcial) y `pipeline.max_run_seconds` interno con `asyncio.wait_for` → `status: "timeout"` | Receipt plan P1 (4) / P2 (11); fenix G7 | Con el wall cap de fenix (900s hoy, ~24 min observados en `COMPLEX_ARCHITECTURE`) alguien va a matar el proceso. Si el timeout lo dispara el engine primero, el kill externo de fenix pasa a ser el último recurso, no la norma — y el recibo parcial sobrevive |
| 6 | `.go` en `ingestion.extensions` + reingesta | fenix G3 | Trivial en código, pero bloqueante: sin esto el RAG de fenix está ciego a `internal/`, `cmd/`, `pkg/` |
| 7 (opcional/P2) | Chunker estructural para Go (`func `/`type `/`package ` en columna 0); override `FENIX_OLLAMA_HOST`-like para el host de Ollama | fenix G4, G6 | El propio proposal de fenix ya los marca como Fase 2 / no bloqueantes — se listan acá solo para no perder la referencia cruzada |

Nota sobre el paso 3: es el único ítem de esta tabla que toca `prompts/` y la firma de `get_implementer_task_template`/`get_qa_review_template` (hay que roscar un parámetro de perfil). Vale la pena implementarlo junto con el paso 2 (ambos tocan el mismo QA de implementation-check) para no pasar dos veces por ese código.

---

## Parte B — Controles extra en fenix al consumir el resultado del outsourcing

Cada control dice **qué verificar de forma independiente**, no qué campo del recibo leer — leer el campo es necesario pero nunca suficiente, por la regla del Contexto.

| # | Control | Verificación independiente (no confiar en el recibo) | Depende de Parte A |
|---|---|---|---|
| B1 | `qa_approved` y `deviation` son señales de auditoría, no gates de aceptación | El gate real sigue siendo `enforce_scope()` + `peer-workflow-review.py --caller-kind local-provider` resolviendo a Claude Code, exactamente como hoy con Gemma | No — el dict ya trae estos campos |
| B2 | `config_fingerprint` como precondición de aceptación | Antes de parsear el resultado, comparar `config_fingerprint.models`/`max_qa_iterations`/`closing_report_enabled` contra los valores esperados (los de `config/settings.yaml` de LocalDevEngine en el momento de la ingesta de fenix). Si no matchean → tratar como `BLOCKED`, no como degradado silencioso | Sí — paso A4 |
| B3 | Grounding relevante al scope, no solo grounding presente | `outcome.rag.chunks_used > 0` **y** al menos una `source` cae dentro de `--allow-path`. Un recibo con `chunks_used: 3` pero sourced todo fuera del allowlist es tan ciego como `chunks_used: 0` para esta tarea puntual | Sí — paso A2 |
| B4 | El parser de `delegate-local-dev-engine.py` es el gate real de la gramática, no la QA interna del engine | Nunca asumir que `qa_approved: true` con `--output-contract fenix-tagged-file` implica gramática válida. Si el parseo estricto (`STATUS`/`FILE START`/...) falla estructuralmente, es `BLOCKED` — mismo comportamiento que hoy tiene un parse-fail de Gemma | Sí — paso A3 |
| B5 | El path allowlist se aplica a los archivos reales que `enforce_scope()` recibe de los `FILE START` blocks, nunca a lo que `trace`/`artifacts` declaran haber tocado | Ya es un invariante del proposal (§10) — se restata acá porque un recibo más rico (con `artifacts.plan`, `trace` detallado) es justo lo que tienta a alguien a atajar por ahí en una futura iteración | No |
| B6 | Exit code 0 significa "hay recibo", no "es seguro aplicar" | Mapear 0/2/3 al vocabulario de outcomes de fenix (`ok`/`blocked`/`error`) sin jamás tratar exit 0 como aprobación — la aprobación la da B1+B4+peer review | Sí — paso A1 |
| B7 | Preferir que el timeout lo dispare el engine, no el wall cap de fenix | Fijar `FENIX_LDE_MAX_WALL_SECONDS` por encima del `pipeline.max_run_seconds` interno del engine (ej. 1800s vs 1500s), para que el `status: "timeout"` con trace parcial llegue primero que el `SIGKILL` externo | Sí — paso A5 |
| B8 | Lock file real para la contención de Ollama, no solo regla operacional | El §8 del proposal deja esto como "regla operacional, escalar a lock file si mide problemas". Dado que `local-qwen` (revisor) y el Architect/Implementer de LocalDevEngine comparten el mismo tag (`qwen3.6:35b-a3b`) bajo un Ollama de un solo slot, y que el revisor es la propiedad anti-trampa central del sistema, conviene implementar el lock desde el arranque de Fase 1 en vez de esperar a medir el problema — un thrashing de unload/reload silencioso ahí no es solo un costo de latencia, es un riesgo de que el revisor corra degradado sin que nadie lo note | No |
| B9 | Binding `query_sha256` / `task_id` | Verificar que el `query_sha256` del recibo corresponde al hash del packet efectivamente enviado, antes de aceptar el resultado — protege contra mezclas en reintentos o corridas concurrentes | Sí — paso A4/A5 (campo nuevo del receipt plan #9) |
| B10 | Auditoría de doble columna: señal del engine vs. verificación independiente de fenix | En `logs/gemma-audit/YYYY-MM.jsonl`, loguear lado a lado `lde_qa_approved` (lo que dice el recibo) y el resultado del parseo estricto B4 / scope B3 (lo que fenix verificó). Una divergencia sostenida en el tiempo es la señal de que el recibo no es confiable *para este uso*, y alimenta la decisión de Fase 1→default del §9 del proposal con datos, no con intuición | Sí — paso A2/A4 |
| B11 | `fast_path: true` en una tarea de código es anomalía, no éxito | Si el Router de LocalDevEngine clasificó como fast path una tarea que fenix envió como `CODING_REQUEST`-shaped, tratar como `BLOCKED` y loguear — significa que se saltó RAG + design gate + QA enteros | No — el dict ya trae `fast_path` |

### Qué puede adoptar fenix hoy, sin esperar a Parte A

B1, B5, B6 (parcial — sin exit codes reales todavía, pero la disciplina de "no tratar la salida como aprobación" aplica ya) y B11 no dependen de ningún cambio en el engine: son disciplina en `delegate-local-dev-engine.py` sobre el dict que `run_complex_task` **ya devuelve hoy**. B8 tampoco depende del engine — es un lock file del lado de fenix. Vale la pena escribir estos cinco antes de que Parte A termine, para no acumular deuda de gobernanza mientras se espera el roadmap del engine.

El resto (B2, B3, B4, B7, B9, B10) está genuinamente bloqueado por los campos correspondientes de Parte A — no hay forma de verificarlos sin que el dato exista primero.

---

## Encaje con la Fase 0 del proposal de fenix

El §9 del proposal ya exige, como gate para pasar de Fase 0 a Fase 1: *"al menos un resultado `PATCH` end-to-end genuino que el scope-enforcement y diff-building existentes de fenix acepten sin modificación"*. El paso A3 (perfil `fenix-tagged-file`) es literalmente lo que ese gate mide. Recomendación concreta: correr los controles B3, B4 y B11 **durante los mismos runs de la spike de Fase 0** (§9, punto 2 del proposal — los 2-3 packets de tareas Low-RRI reales), no después. Si alguno de esos runs produce un `qa_approved: true` que B4 rechaza por gramática inválida, es la evidencia real de G11 que el proposal pide y todavía no tiene — confirma o descarta el riesgo con datos del propio spike en vez de una corrida aparte.

---

## Qué esto no resuelve

Mismos límites que ya estaban en `plan-receipt-interface-callers.md` y en el §13/§10 del proposal de fenix, sin cambios:

- No hay atestación independiente del recibo — sigue siendo autoreportado.
- No reemplaza el peer review externo (`local-qwen`/Claude Code) — los controles de Parte B son auditoría adicional, nunca un sustituto de `peer-workflow-review.py`.
- No resuelve la contención de Ollama más allá del lock (B8) — sigue siendo necesario serializar propuesta y revisión cuando comparten tag.

## Verificación

- Paso A1-A3 verificados por el propio criterio de `plan-receipt-interface-callers.md` (sección Verificación de ese doc) más: una tarea con `--output-contract fenix-tagged-file` produce un output que el parser existente de `delegate-low-rri.py` (o una variante mínima) acepta sin tocar el parser.
- B2/B9: correr con `config/settings.yaml` alterado (`max_qa_iterations: 0`) y confirmar que `delegate-local-dev-engine.py` lo detecta vía `config_fingerprint` y lo trata como `BLOCKED`, no como degradado silencioso.
- B4: alimentar manualmente una respuesta con gramática rota (falta `FILE START`) con `qa_approved: true` forzado, y confirmar que el parser de fenix igual la rechaza — prueba que B4 no depende del veredicto interno del engine.
- B8: con el lock activo, disparar `delegate-local-dev-engine.py` y `peer-workflow-review.py --caller-kind local-provider` en paralelo sobre la misma sesión y confirmar serialización (uno espera al otro) en vez de thrashing de unload/reload en los logs de Ollama.
