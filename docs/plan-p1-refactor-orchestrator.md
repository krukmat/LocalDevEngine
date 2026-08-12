# P1 — Refactor de `core/orchestrator.py`

Parte de [programa-capa-relacional.md](programa-capa-relacional.md). **Proyecto independiente:** no
depende de P2/P3/P4 ni ellos de él para existir. Puede correr en paralelo desde el día uno.

## Por qué existe

`core/orchestrator.py` mide **1122 líneas**, contra el umbral de delegación de **500** (G1). El gate
se chequea *antes* del RRI y no se compensa con puntaje: el implementador local lee archivos
enteros, así que 1122 líneas entran a su ventana en cada turno, empujando afuera la tarea real.

Es el **punto de integración de toda capa de contexto** — schema grounding entró por ahí, la capa
relacional entra por ahí, y cualquier capa futura también. Este es el segundo plan que lo esquiva.

### El diagnóstico, medido

El archivo no es "largo": tiene el flujo entero en dos métodos.

| Método | chars | % del archivo |
|---|---|---|
| `_run_pipeline_body` | 20.219 | 36% |
| `run_complex_task` | 11.381 | 20% |
| **subtotal** | **31.600** | **56%** |
| los otros 13 métodos | 24.781 | 44% |

`_run_pipeline_body` contiene, en línea recta: router → contexto → Manager → design gate
(*sectioned* con fallback monolítico) → loop Implementer↔QA → closing report → conformance check.
`run_complex_task` envuelve eso con timeout, `try/except`, armado del recibo y las claves legacy.

## Dependencias entrantes

| De | Artefacto | Verificación | Tipo |
|---|---|---|---|
| P0 | `docs/policies/rri-anchor-localdevengine.md` | `rri.py --platform python --touches core/orchestrator.py` sin advisory | **Dura** para la validez de los puntajes de abajo |
| P0 | `[profiles.sol-high]` en `~/.codex/config.toml` | `codex --profile sol-high` | **Dura** para la auditoría de O10 |

## Patrones, elegidos por lo que ya hay adentro

No es una lista genérica: cada patrón cierra una estructura que **ya existe implícita** en el código.

| Patrón | Qué resuelve, concretamente |
|---|---|
| **Parameter Object** (`PipelineContext`) | El body arrastra estado compartido como locales que crecen (query, request_id, trace, breakdown, context, plan, implementation, qa_feedback, contadores). Sin objetivar ese estado, ninguna etapa se puede extraer. Es la tarea que habilita las demás. |
| **Strategy** (design gate) | Ya hay **dos algoritmos intercambiables** ahí: gate por secciones y fallback monolítico, seleccionados según si `_split_plan_sections()` devuelve `None`. Es Strategy sin el nombre; explicitarlo saca la rama anidada más grande del body. |
| **Template Method** (`ReviewLoop`) | El design gate y el implementation check son **el mismo loop**: llamar → parsear veredicto → si rechaza, revisar → reintentar hasta `max_qa_iterations`. Hoy está escrito dos veces. |
| **Chain of stages** (`PipelineStage` ABC) | Cada etapa tiene la misma forma: recibe contexto, llama un modelo, parsea, escribe al trace. Quinto ABC del repo, consistente con `BaseModel`, `BaseMemory`, `SchemaProvider` y el `RelationalProvider` de P3. |
| **Builder / Recorder** (`OutcomeRecorder`) | `outcome.X.ran` se reconstruye al final desde locales dispersos. Con un acumulador, lo escribe **la etapa que corrió (o no corrió)**, que es justamente la invariante que el recibo promete. |
| **Facade** (`Orchestrator`) | Es lo que hace el refactor no-disruptivo: `run_complex_task` conserva firma y contrato. `main.py`, fenix y el recibo no se enteran. |

## Tareas

| # | Tarea | RRI | Banda | Dep. | Aceptación |
|---|---|---|---|---|---|
| O1 | **Recibo golden**: capturar el recibo completo para entradas fijas, con modelos stubeados | 36 | Moderate | — | el golden se reproduce byte a byte |
| O2 | Borrar `run_simple_query` (código muerto, línea 1113) | 21 | Low | O1 | ningún caller; golden intacto |
| O3 | `PipelineContext` — objetivar el estado compartido | 32 | Moderate | O2 | golden intacto |
| O4 | `PipelineStage` ABC + `OutcomeRecorder` | 28 | Moderate | O3 | golden intacto |
| O5 | Extraer etapas de contexto (router, RAG, schema, assemble) | 38 | Moderate | O4 | golden intacto |
| O6 | `ReviewLoop` (Template Method) — unifica los dos loops QA | **44** | Med-high | O4 | golden intacto |
| O7 | Design gate como Strategy (*sectioned* \| monolítico) | 37 | Moderate | O6 | golden intacto |
| O8 | Extraer etapas de implementación, closing report y conformance | 38 | Moderate | O6 | golden intacto |
| O9 | `Orchestrator` como Facade — `run_complex_task` delgado, **firma intacta** | 40 | Moderate | O5, O7, O8 | golden intacto |
| O10 | Verificación de equivalencia + `wc -l` de cada módulo | 20 | Low | O9 | recibo idéntico **y** todo módulo ≤ 500 líneas |

Módulos resultantes: `core/pipeline/{__init__,context,base,context_stages,review_loop,design_gate,impl_stages}.py`.

## Reglas que gobiernan esta fase

- **O1 primero, sin excepción.** El recibo es contrato público que fenix ya consume, el repo no tiene
  suite, y un refactor sin red sobre un archivo de 1122 líneas es una reescritura con otro nombre.
- **Equivalencia byte a byte como criterio de aceptación de cada tarea**, no solo al final. El recibo
  es determinista para entradas fijas con modelos stubeados; eso lo vuelve el test de regresión más
  fuerte disponible sin escribir una suite entera.
- **Refactor y cambio de comportamiento nunca en la misma tarea.** Es el penalty
  `refactor_and_behavior` (+8) del RRI, y la razón de que ninguna tarea de P1 lo dispare: si alguna lo
  hace, está mal especificada.
- **Criterio de salida medible, no estético:** cada módulo resultante bajo **500 líneas**, el umbral
  de G1. La fase termina cuando `wc -l` lo confirma, no cuando "queda más limpio".

## El problema de arranque, dicho de frente

**P1 no se puede delegar a un agente local** — porque `orchestrator.py` mide 1122 líneas, que es
exactamente la condición que el proyecto elimina. Es circular y no tiene salida elegante: la primera
pasada (O1-O5) es humana o cloud. **Desde O5 en adelante los módulos extraídos ya están bajo el
umbral**, y O6-O10 tocan archivos nuevos y chicos — delegables con normalidad.

## Gate de cierre

```bash
python -m pytest tests/test_orchestrator_golden.py     # recibo byte a byte idéntico
wc -l core/pipeline/*.py core/orchestrator.py          # todos <= 500
python tests/run_conformance_gate.py; echo $?          # 0, no regresión
```

Auditoría externa de este gate: Codex `sol-high` (1 de 8).

## Dependencias salientes

| Hacia | Artefacto | Verificación | Tipo |
|---|---|---|---|
| P4 | `core/pipeline/*.py`, cada módulo ≤500 líneas | `wc -l core/pipeline/*.py` | **Blanda** |
| P4 | `Orchestrator.run_complex_task` con firma y contrato intactos | golden verde | **Blanda** |
| Repo | `tests/test_orchestrator_golden.py` — primera red de regresión sobre el recibo | golden verde | — |

**Es blanda a propósito.** Sin P1, las tareas F3.3b y F4.3 de P4 no se caen: se ejecutan por la
opción 3 de G1 (agente primario/cloud, con el motivo registrado). Con P1, bajan de "no delegable" a
Moderate delegable y su target pasa de `core/orchestrator.py` a `core/pipeline/context_stages.py`.
P1 cambia la **ruta**, no la **factibilidad**.

## Conflicto de archivo a coordinar

`core/orchestrator.py` lo tocan P1 (lo desarma entero) y P4 (F3.3b, F4.3). **No pueden ir en
paralelo.** Si P1 corre, P4 espera su cierre y reapunta esas dos tareas a `core/pipeline/`. Si P1 no
corre, P4 usa la opción 3 de G1.
