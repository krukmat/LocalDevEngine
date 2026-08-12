# Criterio de trabajo — LocalDevEngine

Versión propia del workflow de agente, derivada de
[`/Users/matias/dubbridge/docs/playbooks/AGENT_WORKFLOW_GUIDE.md`](/Users/matias/dubbridge/docs/playbooks/AGENT_WORKFLOW_GUIDE.md)
y [`RRI_POLICY.md`](/Users/matias/dubbridge/docs/policies/RRI_POLICY.md), filtrando lo que es
patrón genérico de proceso de lo que es infraestructura específica de ese repo (Rust/mobile,
roles Gemma/Muse Glimmer/D14, `make` targets, ADR-036/037/038/039). Gobierna el trabajo de agente
en LocalDevEngine a partir de ahora — reemplaza cualquier criterio ad hoc usado hasta P1/O1.

**No es una copia.** Cada sección abajo dice explícitamente si viene adoptada, adaptada a los
mecanismos reales de este repo, o deliberadamente omitida — y por qué.

## Qué se adopta tal cual (es patrón, no infraestructura)

1. **RRI como gate previo a implementar**, con [R5](rri-anchor-localdevengine.md) resolviendo
   D/P/K y `/Users/matias/dubbridge/scripts/rri.py --platform python` computando la fórmula. Ya en
   uso desde el programa de capa relacional.
2. **Bandas → ruta de ejecución** (0-25 Low, 26-40 Moderate, 41-55 Med-high, 56+ Complex+),
   universales — vienen de la fórmula, no de la infraestructura de dubbridge.
3. **Reflection pattern** (Draft → Critique → Revise) para toda tarea de desarrollo con RRI ≥ 26,
   con el conteo de pasadas de dubbridge sin cambios porque no depende de su infraestructura:
   Moderate 2, Med-high 3, Complex 4.
4. **Decomposition triggers** — RRI final ≥ 56 (gate duro), F≥4∧K≥3, C≥4∧D≥3, penalty
   `refactor_and_behavior` activo, T≥4∧P≥4 (primero characterization tests, luego implementación).
   Universales, ya usados en el programa (F3.3a de P4 se partió exactamente por el último trigger).
5. **Modelo de comunicación con duda socrática**: no asentir sin verificar contra una fuente citable
   (archivo, línea, salida de comando); no inferir posición de una pregunta; señalar explícitamente
   cuando algo no tiene fuente en vez de afirmarlo. Esto ya gobierna esta sesión de facto (el
   registro de supuestos R1 es la aplicación directa de esta regla al programa entero).
6. **Formato de cierre de tarea de desarrollo**: Reflection log → evidencia de review → estado
   final, en ese orden, antes de marcar `[x] Done`. Adaptado en la sección "Cierre" abajo porque
   los pasos concretos (unit coverage certification, owner verification) sí trasladan, pero la
   evidencia de review no — ver §3.

## Qué se adapta (el mecanismo es válido, la implementación de dubbridge no aplica)

### 1. Peer review de dos fases → banda decide **si** hace falta, no **qué modelo local** revisa

Dubbridge resuelve el reviewer por banda a un modelo local específico (Muse Glimmer, Gemma) con
cadena de fallback a D14. LocalDevEngine no tiene esos roles — tiene `architect`/`qa_auditor` ya
integrados **dentro del propio pipeline** (`config/settings.yaml`: ambos en
`muse-glimmer:30b-q4_K_M`), y el programa de capa relacional ya definió su propio auditor externo
(Codex `sol-high`, tope 8 invocaciones, ver
[programa-capa-relacional.md](../programa-capa-relacional.md) §"Auditor externo").

**Regla adaptada:**

| Banda | Revisor de fase 1 (antes de implementar) | Revisor de fase 2 (código) |
|---|---|---|
| Low (0-25) | Ninguno obligatorio — ejecución directa | Ninguno obligatorio |
| Moderate (26-40) | El propio agente, aplicando Reflection | El propio agente, aplicando Reflection |
| Med-high (41-55) | El propio agente + Codex `sol-high` si la tarea es una de las 8 con presupuesto asignado en el programa | Igual — mismo presupuesto compartido, no uno nuevo por fase |
| Complex+ (56+) | Descomposición obligatoria primero; cada subtarea vuelve a pasar por esta tabla en su propia banda | — |

**Por qué no hay cadena de fallback a un tercer modelo:** este repo no tiene un stack de revisores
locales dedicados — `architect`/`qa_auditor` son roles del pipeline de producción
(`core/orchestrator.py`), no un mecanismo de revisión de las tareas de *desarrollo del propio
repo*. Usarlos para eso mezclaría "el motor revisándose a sí mismo escribiendo el motor", que es
justamente lo que G2 prohíbe. Cuando la tarea lo amerita (Med-high, cruza una de las 4 clases G2 de
[frontera-delegacion-programa-relacional.md](frontera-delegacion-programa-relacional.md)), el único
revisor externo disponible hoy es Codex `sol-high` — sin él configurado, esa fila queda en
`REVIEW-OVERRIDE: pipeline-failure — sol-high profile no configurado aún` (ver §3).

### 2. Unit coverage certification → certificación real, sin la exigencia del 90%

Dubbridge exige 90% de cobertura de línea como gate duro. LocalDevEngine **no tiene suite de
tests** — es un hecho ya documentado (P0: "T=4 es el conductor dominante del RRI en este repo,
LocalDevEngine no tiene suite de tests, solo runners de gate"). Imponer 90% sin una fase de
transición sería copiar un número sin evaluar si aplica.

**Regla adaptada:** toda tarea de desarrollo con RRI ≥ 26 certifica cada caso HP-#/EC-# contra un
test real y pasante (`tests/test_*.py` o un runner de gate offline como
`tests/run_conformance_gate.py`), igual que dubbridge exige — pero **sin** el piso de 90% de
cobertura de línea. La tabla de certificación (HP-#/EC-# → test → resultado) es obligatoria; el
número de cobertura global no lo es, hasta que el repo tenga una suite real que lo haga medible sin
ambigüedad. Revisar esta excepción cuando O1-O10 hayan dejado una primera red de regresión real
(`tests/test_orchestrator_golden.py`, ya escrito) — el criterio de reapertura es el mismo que usó
`sqlglot` en `plan-schema-conformance.md`: evidencia medida, no fecha de calendario.

### 3. Evidencia de review "artefacto o override" → adaptado sin Makefile ni ledger append-only

Dubbridge exige que cada tarea tenga o un artefacto JSON de review commiteado o una línea
`REVIEW-OVERRIDE: <tipo> — <razón>` con su fila en un ledger append-only, verificado por
`make qa-docs`. LocalDevEngine no tiene ese Makefile ni ese mecanismo de enforcement.

**Regla adaptada:** cada tarea de desarrollo con RRI ≥ 26 registra, en su cierre, una de:

```
Review: sol-high <ruta al output/transcript> — PASS|FINDINGS
Review: agente (Reflection) — sin revisor externo, banda no lo exige
REVIEW-OVERRIDE: <sol-high-no-configurado|urgencia|no-aplica> — <razón>
```

Sin ledger separado por ahora — la línea vive en el propio documento de cierre de la tarea. Si el
volumen de tareas crece lo suficiente para que "buscar todas las REVIEW-OVERRIDE dispersas" se
vuelva un problema real, se crea el ledger entonces (mismo principio que "no evidence, no la clase
de infraestructura"— no construir el ledger antes de tener una razón medida para necesitarlo).

### 4. Ruta de implementación local-first → el implementador local **es LocalDevEngine, no un tercero**

Dubbridge enruta Low a Gemma vía Ollama y Moderate a `qwen3.6:27b-q4_K_M` vía un runner propio
(`scripts/local-agent/run_local_task.py`), con el agente primario como orquestador de registro y
la nube como escalamiento. La primera versión de este documento **descartó** el equivalente acá,
razonando que "el sub-agente que ejecutaría la tarea de desarrollo de este repo es el propio Claude
Code" — eso está mal: ignora que LocalDevEngine **ya es, literalmente, un motor de implementación
local** (`Implementer` role, `qwen3.6:27b-q4_K_M`, con QA gate incluido, per
`config/settings.yaml`). Descartarlo dejaba afuera del propio proceso de desarrollo la pieza
central del producto — lo opuesto a priorizar LocalDevEngine.

**Regla corregida:** para toda tarea de desarrollo con RRI 0-40 (Low o Moderate) cuyos archivos
tocados **y** cuyos archivos que el implementador debe leer completos ya estén bajo el umbral G1
(500 líneas), la ruta de implementación por defecto es **el propio pipeline de LocalDevEngine**, no
Claude Code directo. No hace falta un runner externo nuevo: el CLI que el producto ya expone para
un llamador no-humano (fenix) sirve exactamente para este propósito — dogfooding real, no una
capa nueva.

**Mecanismo:**

```bash
python main.py ask --json --output-contract fenix-tagged-file \
  "<descripción de la tarea con criterio de aceptación>" \
  [--schema-file <snapshot>] \
  > /tmp/receipt.json
```

- `--output-contract fenix-tagged-file` da bloques de archivo parseables sin ambigüedad
  (`STATUS`/`SUMMARY`/`=== FILE START ===`/`PATH`/`ACTION`/`--- CONTENT ---`/`=== FILE END ===`) —
  la misma gramática que este repo ya construyó para fenix, reusada acá para el mismo problema
  exacto: un llamador consumiendo output de archivos sin ambigüedad de parseo.
- Claude Code (agente primario, orquestador de registro) lee el recibo antes de aplicar nada:
  `outcome.design_gate.approved`, `outcome.implementation_check.approved`,
  `outcome.implementation_check.attempts`. Cualquier `false`, o una violación de gramática en el
  output tageado, es escalamiento — nunca un reintento silencioso.
- El agente primario revisa personalmente el diff aplicado contra el criterio de aceptación de la
  tarea antes de commitear — misma regla no negociable que dubbridge aplica a los parches de
  Gemma ("Gemma-authored Low-RRI patches require an independent primary-agent review"), acá
  aplicada al propio output de LocalDevEngine.

**Escalamiento (se abandona la ruta local, Claude Code toma la tarea directo):**
- `qa_approved: false` después de agotar `max_qa_iterations` (config, default 2).
- `status: "timeout"` o `"failed"` en el recibo.
- El output no parsea como gramática `fenix-tagged-file` válida.
- El router clasificó mal a fast path una tarea que necesitaba el pipeline completo
  (`outcome.fast_path: true` en una tarea que claramente no era simple).

**No elegible:** cualquier tarea cuyo(s) archivo(s) objetivo ya superen G1 (500 líneas) al momento
de leerlos — por eso O1-O5 de P1 se quedan con Claude Code directo (circular: no se puede delegar
el refactor del archivo que bloquea la delegación), mientras que O6-O10 (archivos nuevos bajo
`core/pipeline/`) se vuelven elegibles apenas O5 cierre.

**Por qué esto importa más allá de la conveniencia:** cada invocación real es también un ejercicio
en vivo del producto mismo — los campos `outcome.*` del recibo, el design gate, el conformance
checker, quedan ejercitados contra una tarea real, no trivial, adversarial por naturaleza
(LocalDevEngine editando su propio código fuente), no solo contra smoke tests sintéticos. Es el
mismo argumento que P0 ya hizo para medir RRI sobre rutas reales del repo en vez de asumirlo.

## Qué se omite deliberadamente (no aplica a este repo, no es solo "distinto nombre")

- **Task Cards v2 / Compact Approval Task Card**: formato de presentación pensado para un flujo de
  aprobación humana por tarjeta con routing de vendor dual (Codex + Claude) en paralelo. Este repo
  ya tiene su propio formato de planificación (`docs/plan-*.md`, `docs/policies/*.md`) que cumple
  la misma función (objetivo, alcance, criterio de aceptación) sin la capa de presentación
  cross-vendor, que no aplica — LocalDevEngine no enruta implementación entre Codex y Claude en
  paralelo, ni tiene esa decisión pendiente.
- **ADR change propagation contract**: este repo no usa ADRs (Architecture Decision Records) como
  artefacto — usa docs versionados con su propio historial de decisiones inline (ver cómo
  `programa-capa-relacional.md` documenta sus propias decisiones tomadas). No hay equivalente que
  adaptar; sería inventar una capa nueva sin necesidad demostrada.
- **Runner local-agent / gate ADR-038 / D14**: infraestructura de ejecución delegada de dubbridge.
  LocalDevEngine tiene su propio motor de ejecución (`core/orchestrator.py`, el objeto de P1) — no
  hace falta un runner externo que delegue a un sub-agente, porque el "sub-agente" que ejecutaría
  la tarea de desarrollo de este repo es el propio Claude Code trabajando directo sobre el repo.
- **Reviewability budget gate (context-window-derived)**: existe porque dubbridge delega parches a
  Gemma dentro de una ventana de contexto fija. Sin ese mecanismo de delegación, no hay ventana que
  presupuestar. El equivalente real de este repo es **G1** (500 líneas), ya vigente y ya la razón
  de que exista P1.
- **Antares touchpoints "mandatory workflow before implementing"**: LocalDevEngine ya tiene su
  propia integración de Antares (T0-T11, `--cwe-check` opt-in, ver CLAUDE.md), con su propio
  conjunto de invariantes (I1-I11) — es una integración *distinta y ya cerrada*, no una pendiente de
  portar desde dubbridge.
- **Push Reviewer / CI-triggered review**: este repo no tiene CI configurado. No hay nada que
  adaptar hasta que exista.

## Cierre de tarea de desarrollo (checklist, en orden)

Aplica a toda tarea de desarrollo (no a docs-only/config-only/planning). Evaluar en este orden —
no empezar por la certificación de cobertura.

```
[ ] 1. Reflection log (solo RRI >= 26) — Draft -> Critique -> Revise, N pasadas
       según banda (Moderate 2, Med-high 3, Complex 4). Formato:

       ### Reflection log
       Pasadas requeridas: <N> (`<RRI>` -> `<banda>`)
       #### Pass 1
       - Draft verdict: <resumen de una línea>
       - Critique findings: <bullets, o "sin hallazgos">
       - Revisions applied: <bullets, o "ninguna">

[ ] 2. Review (todas las bandas) — una de las tres líneas de la sección
       "Evidencia de review" arriba (sol-high / agente-Reflection / REVIEW-OVERRIDE).

[ ] 3. Unit coverage certification (solo RRI >= 26) — tabla Case ID | Tipo |
       Comportamiento | Evidencia de test | Resultado. N/A no permitido para
       HP-#/EC-# de una tarea de desarrollo real.

[ ] 4. Owner final verification (todas las bandas) — quién verificó, cuándo,
       declaración de qué se verificó, comandos exactos corridos.

[ ] 5. Sincronizar artefactos de estado afectados (docs/plan-*.md,
       docs/policies/*, este mismo documento si el criterio cambió) en el
       mismo pase de trabajo — no como limpieza posterior.
```

Recién con los 5 pasos aplicables marcados, la tarea pasa a `[x] Done` y se reporta como completa.

## Escala de esfuerzo

Se deriva de la banda RRI, nunca de una estimación subjetiva de tiempo o de fastidio operativo —
misma regla que dubbridge, universal:

| Banda RRI | Effort |
|---|---|
| Low (0-25) | S |
| Moderate (26-40) | M |
| Med-high (41-55) | L |
| Complex+ (56+) | L/XL |

## Modo de pensamiento (thinking)

Activar razonamiento extendido cuando la tarea exige trade-offs de arquitectura con más de dos
restricciones interactuando, diseño de algoritmo novedoso, o diagnóstico de fallas no
deterministas. No activarlo para tests de lógica ya especificada, ediciones de config, o
actualizaciones de docs — la estrategia ya está predefinida en esos casos.

## Relación con lo ya construido en este programa

Este documento no reemplaza nada de `programa-capa-relacional.md` o P0-P4 — los complementa. R5
(anchor rubric) sigue siendo la fuente de D/P/K; R1 (registro de supuestos) sigue el mismo
principio de "citar fuente o marcar sin evidencia" que la sección de comunicación de arriba
formaliza; R4 (frontera de delegación) sigue gobernando qué tareas son G2 y por lo tanto nunca
pasan por este checklist de cierre de tarea de desarrollo, porque no son delegables en primer
lugar.

## Gate de cierre

Este documento se considera vigente desde que se commitea. Se aplica retroactivamente al criterio
usado para O1 solo de forma informativa (O1 fue Low/simple, sin Reflection formal por banda — no se
reabre); rige de acá en adelante, empezando por O2.
