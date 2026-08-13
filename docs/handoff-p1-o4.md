# Handoff: retomar P1 en O4

Traspaso de sesión para continuar [docs/plan-p1-refactor-orchestrator.md](plan-p1-refactor-orchestrator.md)
(parte del programa [docs/programa-capa-relacional.md](programa-capa-relacional.md), pero lo que importa
acá es solo P1). Pegar la sección "Prompt de arranque" como primer mensaje en la sesión nueva.

## Estado verificado al momento de este handoff

Commit `7bad5b1`, rama `main`, sin cambios sin commitear (salvo `.DS_Store`, ajeno al proyecto).

- O1 (recibo golden), O2 (borrado de `run_simple_query`) y O3 (`PipelineContext`) están hechos y
  commiteados.
- `core/orchestrator.py` tiene 1125 líneas — sigue muy por encima del umbral G1 de 500 líneas; la
  extracción a `core/pipeline/*.py` recién empieza en O5.
- `core/pipeline/context.py` ya existe: dataclass `PipelineContext` con todo el estado que
  `_run_pipeline_body` compartía como locales sueltos (query, request_id, trace, decision,
  schema_block/stats, rag_pieces/stats, context, budget_stats, breakdown, plan,
  design_gate_outcome, implementation, qa_approved/feedback, implementation_check_attempts,
  closing_report, deviation, summary). `_run_pipeline_body` construye un `ctx` una vez al inicio y
  todo el método fue convertido mecánicamente de locales a `ctx.<campo>` — cero cambios de control
  de flujo, prompts o logs.
- Tests: `.venv/bin/python tests/test_orchestrator_golden.py` → 3/3 PASS (`test_goldens_exist`,
  `test_scenarios_match_golden`, `test_run_simple_query_is_deleted`). **Usar `.venv/bin/python`,
  no `python`/`python3` del sistema — ahí no está numpy instalado.**

## Próxima tarea: O4 — `PipelineStage` ABC + `OutcomeRecorder`

De la tabla del plan (`docs/plan-p1-refactor-orchestrator.md` líneas 57-59):

```
| O4 | `PipelineStage` ABC + `OutcomeRecorder` | 28 | Moderate | O3 | golden intacto |
```

RRI 28, banda Moderate, depende de O3 (ya satisfecho), criterio de aceptación "golden intacto"
(byte a byte, vía `tests/test_orchestrator_golden.py`).

Qué construye, según la sección "Patrones, elegidos por lo que ya hay adentro" del plan:

- **`PipelineStage`** (Chain of stages): ABC que formaliza la forma que ya tiene implícita cada
  etapa de `_run_pipeline_body` — recibe contexto, llama un modelo, parsea la respuesta, escribe
  al trace. Sería el quinto ABC del repo junto a `BaseModel` (`models/base.py`), `BaseMemory`
  (`memory/base.py`), `SchemaProvider` (`context/schema/base.py`) y el `RelationalProvider` que P3
  todavía no construyó.
- **`OutcomeRecorder`** (Builder/Recorder): acumulador donde cada etapa escribe directamente su
  propio `outcome.X.ran` (y el resto de su outcome) en vez de que, como ahora, se reconstruya al
  final del método a partir de locales dispersos (`rag_stats`, `schema_stats`,
  `design_gate_outcome`, etc.). Es la invariante que el recibo ya promete (`"ran": true|false`
  nunca ambiguo), ahora aplicada en el punto de escritura en vez de reconstruida al final.

Alcance de O4: solo define las dos abstracciones. No mueve ninguna etapa real a un módulo
separado todavía — eso es O5 (etapas de contexto: router, RAG, schema, assemble) y O8
(implementación, closing report, conformance), ambas dependientes de O4. Le siguen a O4 también
O6 (`ReviewLoop`, Template Method que unifica el loop del design gate y el del implementation
check, RRI 44, Med-high, depende de O4).

Regla dura que gobierna todo P1, no solo O4: **refactor y cambio de comportamiento nunca en la
misma tarea** — si alguna tarea de refactor dispara el penalty RRI `refactor_and_behavior` (+8),
está mal especificada. El criterio de aceptación literal es "golden intacto", no "queda más
limpio".

**Frontera de delegación ("problema de arranque"):** O1-O5 no son delegables a un agente local
porque `orchestrator.py` sigue por encima del umbral G1 mientras esas tareas corren — el archivo
que un implementador local necesitaría leer es el mismo que el proyecto existe para achicar. O4
todavía cae en esa zona humano/cloud. Desde O5 en adelante (una vez que hay módulos chicos
extraídos) O6-O10 vuelven a ser delegables con normalidad.

## Qué hacer ahora

Implementar O4: decidir la ubicación del archivo (el plan lista `core/pipeline/base.py` en
"Módulos resultantes"; `OutcomeRecorder` puede vivir ahí mismo o en un archivo hermano, a criterio
de quien implemente), definir la ABC y el recorder, y verificar que
`.venv/bin/python tests/test_orchestrator_golden.py` sigue en 3/3 antes de comitear.

No hace falta tocar `_run_pipeline_body` todavía para usar estas abstracciones — de hecho no
deberían usarse ahí hasta O5+, o O4 dejaría de ser un refactor puro. **Confirmar con el usuario
antes de decidir** si O4 mueve algo de `_run_pipeline_body` o si se limita a declarar las
abstracciones sin cablearlas (ambas lecturas son defendibles del texto del plan; no asumir).

## Prompt de arranque

> Estoy retomando el refactor P1 de `core/orchestrator.py` en LocalDevEngine, descrito en
> `docs/plan-p1-refactor-orchestrator.md`. Leé `docs/handoff-p1-o4.md` para el estado completo:
> O1-O3 están hechos y commiteados (`7bad5b1`), los goldens pasan 3/3 con `.venv/bin/python`, y la
> próxima tarea es O4 (`PipelineStage` ABC + `OutcomeRecorder`). Seguí desde ahí.
