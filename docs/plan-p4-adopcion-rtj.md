# P4 — Adopción de RT-J

Parte de [programa-capa-relacional.md](programa-capa-relacional.md). **Este es el único de los cinco
proyectos que es sobre RT-J.**

## Premisa

La hipótesis operativa es que **RT-J funciona**. Este proyecto no la re-discute. Su trabajo es que la
adopción tenga éxito: contribución **atribuible** y efecto **medible en un factory sin dominio
privilegiado**.

| Decisión | Elección |
|---|---|
| Modelo | **RT-J** (~85M, 12 capas, ventana de 8.192 celdas) |
| Licencia | Uso **interno / investigación** — `cc-by-nc-sa-4.0`; ShareAlike contamina derivados de los pesos. Un futuro uso comercial reabre esto. |
| Deployment | **In-process**, con PyTorch como extra opcional e import perezoso |
| Superficie | **Bloque advisory renderizado**, separado del autoritativo y con score |

## Dependencias entrantes

| De | Artefacto | Verificación | Tipo |
|---|---|---|---|
| P0 | `docs/policies/rri-anchor-localdevengine.md` | sin advisory `no anchor-rubric match` | **Dura** — sin él F3.3b sube de 41 a 58 (Complex) |
| P0 | `[profiles.sol-high]` | `codex --profile sol-high` | **Dura** para F3.4 + los 4 bundles Med-high |
| P2 | `tests/run_relational_gate.py`, corpus de 5 dominios, `labels.json` | `--provider none` reproduce el fallo documentado | **Dura** — F3.4 mide con ese runner |
| P2 | `selection.py` con el fallback arreglado | F1.4a pasa | **Dura** — si no, RT-J se lleva el crédito de arreglar un bug del selector |
| P3 | `context/relational/base.py` (ABC) | `rtj.py` implementa el mismo contrato | **Dura** |
| P3 | `tests/test_relational_contract.py` parametrizado | verde con `name_inference` | **Dura** — baja `T` 4→2 en F3.1/F3.2a/b/c |
| P3 | `name_inference.py` — el piso | gate en 0 | **Dura** — es el baseline de comparación |
| **P3** | **`docs/residuo-relacional-por-dominio.md`** | existe, con números por dominio | **Dura — es el denominador de F3.4** |
| P1 | `core/pipeline/*.py` ≤500 líneas | `wc -l core/pipeline/*.py` | **Blanda** — cambia la ruta de F3.3b/F4.3, no su factibilidad |

P4 instancia además su propio **R2** (que incluye el criterio de salida de la calibración F0.1) y
**R3** — ver [P0](plan-p0-metodo-y-medicion.md).

---

## F0 — Calibración. Bloquea el gasto de cómputo.

| # | Tarea | RRI | Banda | Dep. | Ej. | Aceptación |
|---|---|---|---|---|---|---|
| F0.1a | **Calibrar el encoding**: snapshot → formato tensorial de RT (qué celda es qué, qué va como conocido y qué como faltante) | 28 | Moderate | R2, R5 | H | doc con el mapeo campo a campo |
| F0.1b | **Calibrar el encuadre**: qué celda se enmascara para que la predicción *sea* una señal de relación | 30 | Moderate | F0.1a | H | doc |
| F0.1c | **Calibrar el decoding**: distribución predicha → ranking de relaciones con confidence que entre en `RelationalHint` | 28 | Moderate | F0.1b | H | doc |
| F0.1d | Chequeo de calibración sobre `hostile_naming.json` | 15 | Low | F0.1c | H | la relación no declarada aparece en top-3 |
| F0.2 | Métrica primaria y secundarias, escritas | 10 | Low | R2 | H | §métrica del decision record |
| F0.3 | Nota de licencia en README + `requirements-rfm.txt` | 6 | Low | — | A | el texto existe y nombra NC-SA y ShareAlike |

**F0.1 es calibración, no viabilidad.** No pone a prueba la premisa: determina **con qué ajustes** la
interfaz de predicción de celdas de RT-J emite rankings de relación. El trabajo concreto: RT-J publica
cabezas de clasificación/regresión sobre **celdas** (AUROC 0.7310 / MAE 0.2677) y su librería asume
datos relacionados ya recuperados, mientras que la caja del diagrama consume *relaciones, paths y
scores*. Encoding, encuadre y decoding son los tres parámetros que traducen entre esas dos formas.

Es H y no A por **G2**: leer qué publica un modelo externo requiere fuentes externas, y el engine es
local.

**Timebox 3 días, iteración de calibración acotada.** F0.1d no es un veredicto sobre RT-J: si el
criterio no se alcanza, se ajustan los parámetros de F0.1a-c y se vuelve a correr, dentro del
timebox. Lo acotado es el tiempo, no la cantidad de intentos — una calibración sin tope de reloj es
tiempo abierto, que es exactamente lo que R2 existe para impedir.

**Estas tres tareas puntuaban 43-45 (Med-high) hasta que R2 les fijó el criterio de salida.** El
penalty `no_verification` (+15, el más grande del policy) las castigaba por no tener estrategia de
verificación declarada. Declararla las baja a Moderate.

→ **RF0**: al cerrar la calibración, F3 arranca con los tres parámetros escritos, y F3.2b/c los
**implementan** en vez de descubrirlos. Si el timebox se agota antes del criterio, R3 dice qué se hace
con el tiempo restante.

---

## F3 — RT-J en shadow mode

| # | Tarea | RRI | Banda | Dep. | Ej. | Aceptación |
|---|---|---|---|---|---|---|
| F3.1 | `requirements-rfm.txt` + import perezoso + degradación por `ImportError` | 35 | Moderate | F2.1b | A | sin el extra: `degraded=True, reason="rfm_dependency_missing"`, la corrida no cae |
| F3.2a | Carga de checkpoint + config `checkpoint_path` | 35 | Moderate | F3.1 | A | carga o degrada con razón explícita |
| F3.2b | Encoding snapshot → tensor (implementa F0.1a) | **42** | Med-high | F3.2a, F0.1d | A | produce el tensor esperado |
| F3.2c | Inferencia + decoding → `RelationalResult` (implementa F0.1b/c) | **42** | Med-high | F3.2b | A | devuelve hints con confidence |
| F3.3a-i | **Test de caracterización del recibo 1.2** (contrato que fenix ya consume) | 27 | Moderate | — | A | fija el shape actual antes de tocarlo |
| F3.3a-ii | `outcome.relational_intelligence` + `config_fingerprint.relational`, bump 1.2→**1.3** | 24 | Low | F3.3a-i, F2.1a | A | recibo válido con `"ran": true\|false`; F3.3a-i sigue verde |
| F3.3b | Cablear el provider en `_build_schema_context` con `shadow_only: true` | **41** | Med-high | F3.3a-ii, F3.2c | **H/cloud** | corrida real emite el bloque en el recibo — **G1 dispara** |
| F3.3c | Entrada en [handoff-fenix-parte-b.md](handoff-fenix-parte-b.md) | 3 | Low | F3.3a-ii | A | documenta el bump a 1.3 |
| F3.4 | **Medición + test de sesgo de dominio (A4)** | 29 | Moderate | F3.3b, F2.3 | H | ver gate abajo |

**Shadow = riesgo cero:** la salida va solo al recibo, ningún prompt cambia.

**F3.3a se partió porque el instrumento lo exigió.** Como una sola tarea puntuaba 43 con el trigger
`T ≥ 4 ∧ P ≥ 4` activo (sin tests **y** cambiando el contrato público del recibo que fenix ya validó
contra 1.1/1.2), y la regla del policy para ese trigger es explícita: *"first subtask must be
characterization tests; implementation is the second subtask"*. Partida da 27 + 24, sin penalty, y de
paso deja fijado el shape que fenix consume antes de tocarlo.

**F3.2b/c se quedan en Med-high a propósito.** Son el encoding y el decoding: `D=4`, `K=3`, CC estimada
~20, `A=1` incluso con la calibración cerrada. Bajarlas más exigiría fragmentar contra un diseño que
F0.1 todavía no escribió.

**F3.3b es no delegable por G1** mientras P1 no cierre — ver conflictos abajo.

---

## F4 — Bloque advisory renderizado

| # | Tarea | RRI | Banda | Dep. | Ej. | Aceptación |
|---|---|---|---|---|---|---|
| F4.1 | Ampliar `select_tables()` con hints ≥ umbral, marcados `related_via_inference` | 38 | Moderate | F3.4, **P2 cerrado** | A | tabla antes omitida aparece en la selección |
| F4.2 | `context/relational/render.py` — bloque separado, no-autoritativo, **con** score | 29 | Moderate | F4.1 | A | el bloque existe y declara que las relaciones no están declaradas |
| F4.3 | Presupuesto: `relational.max_chars` en `_assemble_context` | **47** | Med-high | F4.2 | **H/cloud** | `outcome.context_budget` refleja el bloque — **G1 dispara** |
| F4.4 | Test: el bloque de hints se dropea **entero** antes que el schema pierda una tabla | 24 | Low | F4.3 | A | test verde |
| F4.5 | A/B end-to-end contra Ollama | 35 | Moderate | F4.4 | H | el modelo usa la relación correcta en el join |

**F4.1 es prerequisito técnico, no scope creep:** un hint que apunta a una tabla omitida del bloque
AUTHORITATIVE es una **referencia colgada** — el modelo ve una relación hacia una tabla de la que no
tiene ni una columna.

**F4.2 — la asimetría es el punto:** [context/schema/render.py](../context/schema/render.py)
deliberadamente **no** lleva scores porque un hecho declarado no se pondera. Una relación inferida
**sí**. Y nunca dentro del bloque AUTHORITATIVE: aseverar ahí una relación inferida es exactamente la
alucinación que esta capa existe para evitar — el número que lo prohíbe es la precisión de 75% en
`medium`.

---

## Gate de cierre — F3.4, dos criterios, ambos obligatorios

1. **Recall sobre el residuo medido en F2.3**, con precisión reportada, superior al piso.
2. **Sin sesgo de dominio:** la mejora se sostiene en los **5** fixtures. Si aparece solo en los
   dominios CRUD de negocio y no en `telemetry`/`logistics`, se reporta como *adopción condicionada
   al dominio* — que para un factory genérico **no es una adopción**.

**Está prohibido leer el promedio.** A4 es criterio de gate, no una nota al pie: RT-J viene
preentrenado sobre RelBench y arrastra los priors de dominio de esos datos.

```bash
python tests/run_relational_gate.py --provider rtj --per-fixture

python main.py ask --json --schema-file tests/fixtures/schema/hostile_naming.json \
  "<query cuyos términos no comparten token con las tablas involucradas>" \
  | jq '.outcome.relational_intelligence, .outcome.schema_grounding.matched, .outcome.context_budget'
# esperado: relational_intelligence.ran == true, y la tabla antes omitida presente
```

Auditoría externa de F3.4: Codex `sol-high` (1 de 8). Más los 4 bundles de evidencia Med-high
(F3.2b, F3.2c, F3.3b, F4.3).

→ **RF3**: si RT-J no supera el piso, o lo supera con sesgo, el asiento y todo P2/P3 quedan en pie y
solo se cambia la implementación del provider. Esa es la razón de que el asiento exista.

→ **RF4**: cierre. El bloque es activable/desactivable por config sin tocar código.

---

## Conflictos de archivo a coordinar

| Archivo | Con | Regla |
|---|---|---|
| `context/schema/selection.py` | P2 (F1.4b) | **F4.1 no arranca hasta que P2 esté cerrado.** Si se solapan, el arreglo del bug y la ampliación con hints se mezclan en un diff y la atribución se pierde. |
| `core/orchestrator.py` | P1 | **No tocarlo en paralelo con P1.** Si P1 corre, esperar su cierre y reapuntar F3.3b/F4.3 a `core/pipeline/context_stages.py` (pasan a Moderate delegables). Si P1 no corre, usar la opción 3 de G1: agente primario/cloud con el motivo registrado. |
| `core/receipt.py` | — | F3.3a-i (caracterización) va antes de F3.3a-ii (bump), sin excepción: es contrato público que fenix consume. |

## Config que introduce este proyecto

```yaml
relational:
  provider: "none"          # none | name_inference | rtj
  min_confidence: 0.5       # umbral para ampliar la selección (F4.1)
  max_hints: 8
  max_chars: 800            # se descuenta de schema_grounding.max_chars, no del RAG
  shadow_only: true         # true = solo al recibo, no toca ningún prompt (F3.3)
  checkpoint_path: null     # solo para provider: rtj
```

`checkpoint_path` va por config, **nunca por argv** — mismo criterio que el resto del repo para
rutas y credenciales.

## Archivos

**Nuevos:** `context/relational/{rtj,render}.py`, `requirements-rfm.txt`,
`tests/test_relational_budget.py`, `tests/test_receipt_contract.py`.

**Modificados:** `core/receipt.py` (1.2→1.3), `core/orchestrator.py` **o** `core/pipeline/context_stages.py`
según corra P1, `context/schema/selection.py` (F4.1), `config/settings.yaml`,
[handoff-fenix-parte-b.md](handoff-fenix-parte-b.md), `CLAUDE.md`.
