# P2 — Selector: el arreglo y el instrumento

Parte de [programa-capa-relacional.md](programa-capa-relacional.md). **No es sobre RT-J.** Arregla un
bug vivo y construye el instrumento de medición que P3 y P4 necesitan.

## Por qué existe

Dos entregables independientes que comparten archivo y corpus:

**1 · El bug del fallback silencioso** ([context/schema/selection.py:124](../context/schema/selection.py)).
Hoy un hit incidental de **una sola columna** hace que `scores` deje de estar vacío,
`include_all_if_no_match` no dispare, y la tabla necesaria se caiga en silencio — dentro de un bloque
rotulado AUTHORITATIVE. Un match parcial y débil es peor que ningún match: el segundo tiene red, el
primero no. Afecta **hoy** a todo llamador de schema grounding, con o sin capa relacional.

**2 · El instrumento.** No existe forma de medir la calidad de `select_tables()` sobre múltiples
dominios. Sin eso, cualquier mejora posterior es una afirmación sin número.

## Dependencias entrantes

| De | Artefacto | Verificación | Tipo |
|---|---|---|---|
| P0 | `docs/policies/rri-anchor-localdevengine.md` | `rri.py --platform python --touches context/schema/selection.py` sin advisory | **Dura** |
| P0 | `[profiles.sol-high]` en `~/.codex/config.toml` | `codex --profile sol-high` | **Dura** para auditar F1.3 |

Además, P2 instancia su propio **R2** (criterio numérico del gate, escrito antes de medir) y **R3**
(matriz resultado→acción) — ver [P0](plan-p0-metodo-y-medicion.md).

## Tareas

`Ej.`: **A** agente local · **H** humano · **A+H** agente propone, humano confirma.

| # | Tarea | RRI | Banda | Dep. | Ej. | Aceptación |
|---|---|---|---|---|---|---|
| F1.1a | Fixture `telemetry.json` (~6-8 tablas, no-CRUD, claves compuestas) | 14 | Low | R5 | A | parsea con `parse_snapshot()` |
| F1.1b | Fixture `logistics.json` (~6-8 tablas, grafo con auto-referencia) | 14 | Low | R5 | A | parsea con `parse_snapshot()` |
| F1.1c | `labels.json` para los 3 fixtures existentes | 29 | Moderate | R2 | A+H | ≥3 queries/fixture, tablas requeridas etiquetadas |
| F1.1d | `labels.json` extendido a los 2 fixtures nuevos | 30 | Moderate | F1.1a, F1.1b, F1.1c | A+H | ≥1 caso de relación no declarada por fixture |
| F1.2a | `tests/run_relational_gate.py`: carga de corpus, `--corpus`, `--provider`, exit code | 28 | Moderate | F1.1c | A | corre y devuelve exit code |
| F1.2b | Cálculo de recall + salida `--per-fixture` | 15 | Low | F1.2a | A | imprime recall desglosado por dominio |
| F1.3 | **Validación del instrumento** | 24 | Low | F1.2b, F1.1d | H | reproduce el fallo conocido con `--provider none` |
| F1.4a | Test que captura el bug del fallback débil (rojo) | 24 | Low | F1.3 | A | el test falla contra el código actual |
| F1.4b | Arreglo del umbral en `select_tables()` | 31 | Moderate | F1.4a | A | F1.4a pasa |
| F1.4c | No-regresión | 10 | Low | F1.4b | A | `run_conformance_gate.py` sigue en 0 |

El runner sigue el patrón de [tests/run_conformance_gate.py](../tests/run_conformance_gate.py):
totalmente offline, sin llamada a Ollama, exit code = número de casos fallidos.

## F1.3 es obligatorio y es humano

Si el runner no reproduce el fallo **ya documentado** *antes* de arreglarlo, el instrumento está roto
y ninguna medición posterior vale. Es la lección de [fase3-decision.md](fase3-decision.md) aplicada
por adelantado, en un repo que ya la aprendió tres veces por las malas. Es H por G2: leer un
resultado de gate y decidir si el instrumento sirve no se delega.

## F1.4b — el arreglo, en términos estructurales (A1)

Un hit de *nombre de tabla* (peso 3.0) cuenta como match; hits solo-de-columna bajo umbral **no**
desactivan el fallback `include_all_if_no_match`. Sin vocabulario de dominio, sin listas de nombres:
solo el umbral.

**Va antes de cualquier baseline.** Si no, un provider posterior se lleva el crédito de arreglar un
bug del selector y el resultado queda inatribuible. Es la razón por la que P2 precede a P3, no la
conveniencia.

## Sobre el corpus: por qué no se difiere

Se evaluó mover F1.1a/b/d (los 2 fixtures nuevos + sus etiquetas) más adelante para sacar 3 tareas
del tramo inicial. **Se rechaza.** A2 exige que la métrica sea multi-dominio *desde la primera
medición*: diferirlos dejaría el piso de P3 medido sobre 3 dominios y RT-J sobre 5 — incomparables. Y
este repo ya tiene tres fallos documentados cuya causa fue exactamente esa, un instrumento construido
para otra pregunta.

Las tres fixtures existentes comparten forma: **CRUD de negocio**. `telemetry` (claves compuestas) y
`logistics` (grafo con auto-referencia) existen para romper ese supuesto.

## Gate de cierre

```bash
# F1.3 — el instrumento reproduce el fallo conocido ANTES de arreglarlo
python tests/run_relational_gate.py --provider none      # debe FALLAR el caso sin FK

# tras F1.4b
python tests/run_relational_gate.py --provider none --per-fixture
python tests/run_conformance_gate.py; echo $?            # 0, no regresión
```

Auditoría externa de F1.3: Codex `sol-high` (1 de 8) — *¿reproduce de verdad el fallo documentado, o
solo lo parece?*

## Dependencias salientes

| Hacia | Artefacto | Verificación | Tipo |
|---|---|---|---|
| P3 (F2.2c), P4 (F3.4) | `tests/run_relational_gate.py` con `--corpus`, `--provider`, `--per-fixture` | `--provider none` reproduce el fallo documentado | **Dura** |
| P3, P4 | Corpus de 5 dominios en `tests/fixtures/schema/` | los 5 parsean con `parse_snapshot()` | **Dura** |
| P3, P4 | `tests/fixtures/relational/labels.json` — verdad de referencia | ≥3 queries/fixture, ≥1 relación no declarada por fixture | **Dura** |
| P3, P4 | `context/schema/selection.py` con el fallback arreglado | F1.4a pasa; conformance gate en 0 | **Dura** |
| Repo | El bug del fallback silencioso, cerrado | — | — |

**Por qué son duras:** el gate de P3 es una medición, y sin instrumento no hay medición.

## Conflicto de archivo a coordinar

`context/schema/selection.py` lo tocan P2 (F1.4b, arregla el fallback) y P4 (F4.1, lo amplía con
hints). **P4 no arranca F4.1 hasta que P2 esté cerrado**, y P2 no reabre el archivo después. Si se
solapan, el arreglo y la ampliación se mezclan en un solo diff y la atribución se pierde.

## Valor si el programa para acá

Instrumento validado y reutilizable + selector sin fallo silencioso. Ambos independientes de que
exista cualquier capa relacional.
