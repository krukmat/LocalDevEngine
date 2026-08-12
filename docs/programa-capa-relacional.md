# Programa: capa relacional y sus proyectos antecesores

Documento paraguas. Define **cinco proyectos separados**, el contrato entre ellos, y las reglas
comunes (agnosticismo de dominio, catalogación RRI, gates deterministas, auditor externo).

Cada proyecto tiene su propio documento, su propio gate de cierre y su propio valor entregable:

| # | Proyecto | Documento | ¿Sobre RT-J? |
|---|---|---|---|
| **P0** | Método y medición | [plan-p0-metodo-y-medicion.md](plan-p0-metodo-y-medicion.md) | No |
| **P1** | Refactor de `core/orchestrator.py` | [plan-p1-refactor-orchestrator.md](plan-p1-refactor-orchestrator.md) | No |
| **P2** | Selector: arreglo + instrumento | [plan-p2-selector-instrumento.md](plan-p2-selector-instrumento.md) | No |
| **P3** | Piso relacional determinista | [plan-p3-piso-relacional.md](plan-p3-piso-relacional.md) | No |
| **P4** | Adopción de RT-J | [plan-p4-adopcion-rtj.md](plan-p4-adopcion-rtj.md) | Sí |

---

## Contexto

El diagrama objetivo incluye una caja **Relational Intelligence (RFM / RT-J)** que hoy tiene **cero
footprint** en el repo: ni módulo, ni ABC, ni dependencia.

La necesidad que llena está verificada y es reproducible
([decision-capa-contextual-ba-rfm-broker.md](decision-capa-contextual-ba-rfm-broker.md) §Q10),
enunciada en términos estructurales, sin dominio:

> Existe una relación real entre dos tablas que **(a)** no está declarada como FK, y **(b)** cuyos
> nombres no comparten tokens con la consulta. `select_tables()` no puede verla por ninguna de sus
> dos vías: el cierre de FK no la alcanza porque no hay FK, y el match léxico no la alcanza porque
> los nombres no se parecen. La tabla necesaria se descarta **en silencio**, dentro de un bloque
> rotulado AUTHORITATIVE.

Schemas sin FKs declaradas son comunes en producción (MyISAM, integridad gestionada en la
aplicación, warehouses). El caso está codificado en `tests/fixtures/schema/hostile_naming.json`.

**Premisa fijada:** la hipótesis operativa es que RT-J funciona. Este programa no la re-discute; su
trabajo es que la adopción **tenga éxito** — resultado atribuible, reversible, y ninguna rama del
desenlace que deje trabajo tirado.

### Decisiones tomadas

| Decisión | Elección |
|---|---|
| Modelo | **RT-J** (~85M, 12 capas, ventana de 8.192 celdas) |
| Licencia | Uso **interno / investigación** — `cc-by-nc-sa-4.0` aceptable; ShareAlike contamina derivados de los pesos. Un futuro uso comercial reabre esto. |
| Deployment | **In-process**, con PyTorch como extra opcional e import perezoso |
| Superficie | **Bloque advisory renderizado**, separado del autoritativo y con score |

---

## Por qué cinco proyectos y no uno

Puntuar el trabajo con RRI dejó visible algo que el encuadre inicial escondía: **la mayor parte de
lo planeado no es sobre RT-J.** Arreglar un bug vivo del selector, construir un instrumento de
medición, refactorizar el orquestador y escribir el anchor rubric del repo tienen valor, gate y
criterio de cierre **propios** — y estaban empaquetados dentro de una adopción, cobrando su costo
político y quedando rehenes de su desenlace.

| # | Proyecto | Tareas | Entregable | Gate de cierre |
|---|---|---|---|---|
| **P0** | Método y medición | R1, R4, R5, auditor | Anchor rubric del repo, frontera de delegación, auditor externo configurado | `rri.py` ancla D/P/K sin advisory sobre rutas del repo |
| **P1** | Refactor `orchestrator.py` | O1-O10 | 56% del archivo desarmado en módulos ≤500 líneas, comportamiento idéntico | Recibo byte a byte idéntico **y** `wc -l` ≤ 500 por módulo |
| **P2** | Selector: arreglo + instrumento | F1.\* | Bug del fallback silencioso arreglado; gate de selección multi-dominio, offline | F1.3: el runner reproduce el fallo documentado **antes** de arreglarlo |
| **P3** | Piso relacional determinista | F2.\* | `RelationalProvider` + `name_inference`; residuo medido por dominio | F2.3: residuo cuantificado por dominio sobre las 5 fixtures |
| **P4** | Adopción de RT-J | F0.\*, F3.\*, F4.\* | Calibración, shadow mode, bloque advisory | F3.4: recall sobre el residuo **y** sin sesgo de dominio (A4) |

**Cada proyecto se puede detener sin dejar trabajo tirado.** Es la propiedad que la separación
compra: parar después de P2 deja un bug arreglado y un instrumento reutilizable; parar después de
P3 deja Q10 resuelto de forma determinista.

---

## Contrato entre proyectos

Lo que cruza una frontera es siempre un **artefacto nombrado con un comando que verifica que
llegó** — nunca "el proyecto anterior terminó".

**Tipo de dependencia:**
- **Dura** — sin el artefacto, el gate del proyecto consumidor **no es medible**. No hay ruta
  alternativa.
- **Blanda** — el proyecto consumidor corre igual, pero por una ruta más cara o menos delegable.

### P0 → P1, P2, P3, P4

| Artefacto publicado | Consumido por | Verificación | Tipo |
|---|---|---|---|
| `docs/policies/rri-anchor-localdevengine.md` — tabla `glob → (D,P,K) floor` | Los cuatro, al puntuar cualquier tarea | `rri.py --platform python --touches core/orchestrator.py` no emite `no anchor-rubric match` para rutas del repo (o los floors se aplican a mano desde la tabla) | **Dura** |
| `~/.codex/config.toml` con `[profiles.sol-high]` | P2 (gate F1.3), P3 (gate F2.3), P4 (gate F3.4 + bundles Med-high) | `codex --profile sol-high` resuelve `gpt-5.6-sol` / `high` | **Dura** para los gates auditados |
| Registro de supuestos (R1) + frontera de delegación (R4) | Los cuatro | Los documentos existen y R4 lista las clases de tarea no delegables | **Blanda** |

**Por qué el anchor rubric es dependencia dura y no burocracia:** sin él, D/P/K quedan en juicio sin
ancla, y la regla del policy (*"treat the variable as one step higher when confidence is Low"*)
sube F3.3b de **41 a 58 → banda Complex → descomposición obligatoria**. La ausencia del rubric
cambia la banda, y con ella la ruta de ejecución.

### P1 → P4

| Artefacto publicado | Consumido por | Verificación | Tipo |
|---|---|---|---|
| `core/pipeline/*.py`, cada módulo ≤500 líneas | F3.3b, F4.3 (que pasan a apuntar a `core/pipeline/context_stages.py` en vez de `core/orchestrator.py`) | `wc -l core/pipeline/*.py` todos ≤500 | **Blanda** |
| `Orchestrator.run_complex_task` con firma y contrato intactos | Todo consumidor del recibo (`main.py`, fenix) | `tests/test_orchestrator_golden.py` verde | **Blanda** |

**Es blanda a propósito.** Sin P1, F3.3b y F4.3 no se caen: se ejecutan por la opción 3 de G1
(agente primario/cloud, con el motivo registrado). Con P1, bajan de "no delegable" a Moderate
delegable. P1 cambia la **ruta**, no la **factibilidad**.

### P2 → P3, P4

| Artefacto publicado | Consumido por | Verificación | Tipo |
|---|---|---|---|
| `tests/run_relational_gate.py` (`--corpus`, `--provider`, `--per-fixture`, exit code = casos fallidos) | P3 (F2.2c), P4 (F3.4) | `python tests/run_relational_gate.py --provider none` reproduce el fallo documentado | **Dura** |
| Corpus de 5 dominios: `tests/fixtures/schema/{small,medium,hostile_naming,telemetry,logistics}.json` | P3, P4 | los 5 parsean con `parse_snapshot()` | **Dura** |
| `tests/fixtures/relational/labels.json` — verdad de referencia, ≥3 queries/fixture | P3, P4 | ≥1 caso de relación no declarada por fixture | **Dura** |
| `context/schema/selection.py` con el fallback arreglado | P3, P4 | el test rojo de F1.4a pasa; `run_conformance_gate.py` sigue en 0 | **Dura** |

**Por qué es dura:** el gate de P3 es una medición, y sin instrumento no hay medición. Y el arreglo
del selector va **antes** de cualquier baseline: si no, un provider posterior se lleva el crédito
de arreglar un bug del selector y el resultado queda inatribuible.

### P3 → P4

| Artefacto publicado | Consumido por | Verificación | Tipo |
|---|---|---|---|
| `context/relational/base.py` — `RelationalHint`, `RelationalResult`, `RelationalProvider` (ABC) | `rtj.py` implementa el mismo ABC | importa; el contrato está documentado | **Dura** |
| `tests/test_relational_contract.py` — parametrizado por provider | F3.1, F3.2a/b/c: cubre `rtj.py` sin escribir tests nuevos, bajando `T` de 4 a 2 | verde con `--provider name_inference` | **Dura** |
| `context/relational/name_inference.py` — implementación de referencia | P4, como piso contra el que se compara RT-J | `run_relational_gate.py --provider name_inference --per-fixture` → exit 0 | **Dura** |
| **`docs/residuo-relacional-por-dominio.md`** — el residuo medido, desglosado por dominio | **F3.4: es el denominador del gate de P4** | el documento existe y tiene números por cada uno de los 5 dominios | **Dura** |

**El residuo es el artefacto crítico de todo el programa.** El gate de P4 no es "¿RT-J es bueno?",
es "¿RT-J recupera lo que el piso determinista no recuperó, y lo hace parejo entre dominios?". Sin
el residuo medido por dominio, ese criterio no tiene denominador y F3.4 no es evaluable.

### Conflictos de archivo entre proyectos

Dos proyectos distintos tocan el mismo archivo. No es un problema de orden lógico sino de
coordinación, y hay que declararlo:

| Archivo | Proyectos | Regla |
|---|---|---|
| `context/schema/selection.py` | P2 (F1.4b, arregla el fallback) · P4 (F4.1, amplía con hints) | **P4 no arranca F4.1 hasta que P2 esté cerrado**, y P2 no reabre el archivo después. Si se solapan, el arreglo y la ampliación se mezclan en un solo diff y la atribución se pierde. |
| `core/orchestrator.py` | P1 (lo desarma entero) · P4 (F3.3b, F4.3) | **P1 y P4 no pueden tocarlo en paralelo.** Si P1 corre, P4 espera su cierre y reapunta esas dos tareas a `core/pipeline/`. Si P1 no corre, P4 usa la opción 3 de G1. |
| `core/receipt.py` | P4 (F3.3a-ii, bump 1.2→1.3) | Sin conflicto, pero es contrato público que fenix consume: F3.3a-i (caracterización) va primero, sin excepción. |

---

## Invariante A — Agnosticismo de dominio

Aplica a P2, P3 y P4. LocalDevEngine es un factory **genérico**: no tiene dominio de negocio
privilegiado, igual que no tiene dialecto privilegiado ([context/schema/base.py](../context/schema/base.py))
ni convención de nombres privilegiada ([selection.py](../context/schema/selection.py)).

- **A1 · Cero vocabulario de dominio en el código.** Sin tablas de sinónimos, sin diccionarios de
  entidades, sin listas de nombres de negocio. Solo operaciones estructurales: solapamiento de
  tokens, corte de camelCase, plegado singular/plural, contención de nombre. El `_STOPWORDS` de
  `selection.py` (artículos y verbos de tarea) es el único listado admisible.
- **A2 · Corpus multi-dominio, métrica reportada por dominio.** Una mejora que aparece en un dominio
  y no en otros es sobreajuste al fixture. El gate exige que se sostenga **en todos**, no en el
  promedio.
- **A3 · Nada aprendido del corpus vuelve al engine como conocimiento de dominio.** Se ajustan
  parámetros estructurales (umbrales, profundidad, corte de confianza). No se agrega un nombre.
- **A4 · El sesgo de dominio de RT-J es criterio de gate** (solo P4). Viene preentrenado sobre
  RelBench y arrastra los priors de dominio de esos datos. Un modelo que ayuda en los dominios
  parecidos a su preentrenamiento y no en el resto es inaceptable acá aunque su promedio sea bueno.

### Cobertura de fixtures

| Fixture | Forma | Rasgo que ejercita |
|---|---|---|
| `small.json` | 4 tablas, snake_case inglés, FKs declaradas | caso limpio |
| `medium.json` | 15 tablas, 17 FKs | escala; columnas cuyo nombre no contiene la tabla destino |
| `hostile_naming.json` | 8 tablas: ES/FR/DE mayúsculas/CamelCase/`t3_xk_legacy` | relación real sin FK; nombres opacos sin asidero léxico |
| **`telemetry.json`** *(nuevo, P2)* | series temporales / sensores | dominio no-CRUD, claves compuestas |
| **`logistics.json`** *(nuevo, P2)* | rutas / nodos / tránsitos | grafo con auto-referencia |

Las tres existentes comparten forma: **CRUD de negocio**. Los dos nuevos existen para romper ese
supuesto. Sin ellos, A2 no se puede afirmar y ninguna medición autoriza una proyección al caso
general.

---

## Catalogación de tareas: RRI (Required Reasoning Index)

Las tareas no se dimensionan con una etiqueta S/M/L inventada. Se puntúan con **RRI**, la métrica
que ya gobierna este flujo de trabajo en DubBridge
(`/Users/matias/dubbridge/docs/policies/RRI_POLICY.md`, calculador canónico
`/Users/matias/dubbridge/scripts/rri.py`). RRI estima *cuánto razonamiento, contexto, cuidado y
verificación* exige una tarea **antes** de que un agente la implemente — se mide sobre la entrada,
no sobre la salida, que es justamente lo que hace falta para asignar.

```
RRI = 100 × ((0.18·C + 0.12·F + 0.15·D + 0.15·T + 0.12·A + 0.12·K + 0.10·P + 0.06·X) / 5) + Penalties
```

C complejidad ciclomática · F archivos · D dominio · T riesgo de cobertura · A ambigüedad ·
K acoplamiento · P impacto público/seguridad/datos · X tamaño de contexto. Cada una 0-5.

**Estado de la importación en este repo.** RRI ya aparece en LocalDevEngine, pero solo como palabra:
[handoff-fenix-parte-b.md:301](handoff-fenix-parte-b.md) habla de "tareas Low-RRI" y
[antares-advisor-portability-guide.md:873](antares-advisor-portability-guide.md) lo clasifica como
**"Not portable"**. Esa clasificación es imprecisa y hay que corregirla: `rri.py` **sí** es portable
por diseño (perfiles `rust`/`go`/`rn`/`python`/`generic`); lo que no es portable es el *anchor rubric
anclado a los ADR de DubBridge*. La fórmula, los pesos, las penalties, las bandas y los triggers son
universales.

**Invocación para este repo** — LocalDevEngine no tiene `pyproject.toml`/`setup.py`, así que
`--platform auto` no detecta Python y degrada a `generic`. Hay que pasarlo explícito:

```bash
python3 /Users/matias/dubbridge/scripts/rri.py --platform python \
  --touches context/relational/name_inference.py \
  --cc 15 --D 3 --K 1 --P 2 --T 2 --A 1 --X 2
```

### Bandas → ruta de ejecución

| RRI | Banda | Effort | Ruta de implementación | Gate |
|---|---|---|---|---|
| 0-25 | Low | S | Agente primario, o Gemma local (`gemma4:26b-a4b-it-qat`) para parches simples | Sin card de aprobación |
| 26-40 | Moderate | M | **Local-first**: runner agéntico con `qwen3.6:27b-q4_K_M`, hasta **2 reparaciones** | HITL + tests en el área |
| 41-55 | Med-high | L | Refinamiento advisory (Muse Glimmer) → **una sola sesión**, ≤8 turnos, ≤300 s, **0 reparaciones** | HITL con plan + criterios explícitos |
| 56+ | Complex+ | L/XL | **Descomposición obligatoria** antes de implementar | Humano revisa el plan |

Objetivo de fragmentación (regla del policy): dividir hasta que cada subtarea quede en **RRI ≤ 55
con A ∈ {0,1}**. Este programa apunta más abajo: **≤ 40**, donde entra la ruta local-first con
presupuesto de reparación. Las 41-55 que quedan son deuda declarada, no descuido.

### Tres gates deterministas que corren *antes* del RRI

- **G1 · Tamaño de archivo objetivo: 500 líneas.** Todo archivo en `allowed_paths` **y todo archivo
  que el implementador local deba leer entero** se cuenta antes de armar la card. Por encima del
  umbral la tarea no es delegable como está: se decompone, se refactoriza el archivo primero (P1), o
  se escala registrando el motivo. **`core/orchestrator.py` mide 1122 líneas** — 2,2× el umbral.
- **G2 · El factory no puede ser su propio juez.** RRI mide riesgo de *implementación*, no validez de
  *instrumento* — no tiene variable para "si esta etiqueta está mal, todas las mediciones mienten".
  Por eso esta regla queda fuera del cálculo y por encima de él. No se delegan: etiquetar el corpus
  (es la verdad de referencia), leer el resultado de un gate y decidir continuar/parar, verificar
  afirmaciones sobre RT-J contra fuentes externas (requiere web; el engine es local), y P0 entero.
  Un agente **puede proponer** etiquetas; la confirmación es humana.
- **G3 · Evidencia de review, o override tipado.** Ninguna tarea de desarrollo cierra sin el
  artefacto de review de su banda o un `REVIEW-OVERRIDE: <tipo> — <razón>` auditable. El silencio no
  pasa.

Y sigue en pie **`output_contract: fenix-tagged-file`** para todo task que produzca archivos, así el
resultado es parseable sin intervención.

### Lo que el instrumento encontró al correrlo

Puntuar las 51 tareas con `rri.py` no fue tabulación: cambió el plan en tres puntos, con números.

1. **La calibración de RT-J no tenía criterio de salida escrito** → penalty `no_verification` **+15**
   sobre F0.1a/b/c, que las ponía en Med-high (43-45). Declarar F0.1d como su criterio *antes* de
   empezar — que es literalmente lo que R2 exige — las baja a **28-30, Moderate**.
2. **`T=4` es el conductor dominante de RRI en este repo, no la complejidad de la capa.**
   LocalDevEngine no tiene suite de tests (solo runners de gate), así que "no hay tests en el área"
   puntúa 4 casi en todas partes, con peso 0.15. Un test de contrato del ABC parametrizado por
   provider — **una sola tarea, F2.1b** — baja T a 2 en cinco tareas río abajo y saca a F3.1 y F3.2a
   de Med-high (**-6 puntos cada una**). Más barato y más útil que partirlas en pedazos más chicos.
3. **F3.3a disparó un trigger de descomposición real**: `T ≥ 4 ∧ P ≥ 4` (sin tests + cambia el
   contrato público del recibo que fenix consume) → +10 y regla explícita *"first subtask must be
   characterization tests"*. Se parte en F3.3a-i y F3.3a-ii, que quedan en 27 y 24 sin penalty.

Efecto neto: **8 tareas en Med-high → 4**, y **ninguna en Complex**.

---

## Auditor externo: Codex `gpt-5.6-sol` a `high`

**Por qué hace falta uno.** G2 dice que el factory no puede ser su propio juez, y hoy eso empuja todo
a "humano". Pero el problema es más específico que "es local": el stack de este repo tiene
`architect` y `qa_auditor` **en el mismo tag** (`muse-glimmer:30b-q4_K_M`,
[config/settings.yaml](../config/settings.yaml)), así que en el design gate el revisor y el diseñador
son el mismo modelo. Un auditor de otro proveedor es la única independencia real disponible.

**Configuración — un profile, no el default global.** `~/.codex/config.toml` tiene hoy
`model = "gpt-5.6-terra"` / `model_reasoning_effort = "medium"` como default global, compartido por
DubBridge, fenix, blackbox y este repo. Cambiar esas dos líneas subiría el costo de *toda* sesión de
Codex en *todos* los proyectos para beneficiar a uno. Se agrega un profile opt-in:

```toml
# ~/.codex/config.toml — agregar; no tocar las lineas 1-2 (default global)
[profiles.sol-high]
model = "gpt-5.6-sol"
model_reasoning_effort = "high"
```

```bash
codex --profile sol-high        # sesión interactiva de auditoría
codex exec --profile sol-high   # auditoría no interactiva, para los gates
```

`high` y no `xhigh`/`max`: el propio workflow guide reserva `xhigh` para RRI 71+ y dice que se use
*"only when eval evidence shows a gain"*. Ninguna tarea del programa pasa de 47. Subir el effort sin
esa evidencia es gasto sin criterio — exactamente lo que R2 prohíbe para los gates.

**Qué audita, y qué no.** Auditar no es decidir. El auditor entra donde hace falta un segundo par de
ojos independiente; la decisión de continuar/parar sigue siendo humana.

| Toca | No toca |
|---|---|
| **P2 / F1.3** — ¿el runner reproduce de verdad el fallo documentado, o solo lo parece? | Leer un gate y decidir continuar/parar — **humano** |
| **P3 / F2.3** — ¿el residuo está bien caracterizado, o hay relaciones mal clasificadas? | P0 entero — **humano** |
| **P4 / F3.4** — el gate: ¿la mejora se sostiene por dominio, o es sesgo de RelBench? | Confirmar etiquetas del corpus (es la verdad de referencia) — **humano** |
| Bundle de evidencia de las 4 Med-high (F3.2b, F3.2c, F3.3b, F4.3) | Implementar: el auditor lee, no escribe |
| **P1 / O10** — equivalencia del recibo tras el refactor | |

**Tope de uso: 8 invocaciones.** Cuatro lecturas de gate (uno por proyecto con gate medible) +
cuatro bundles Med-high. No se audita tarea por tarea — las Low y Moderate ya tienen su revisor de
banda local. Auditar todo duplicaría el costo para revisar de nuevo lo que el instrumento ya mide
con un exit code.

**Nota de independencia:** las 4 Med-high por ADR-038 se refinan con Muse Glimmer y, si escalan, van
a Codex. Cuando eso pasa, Codex **implementa** esa tarea y por lo tanto no puede auditarla — el
auditor de esa tarea baja a la cadena de fallback local. Es el mismo principio que rompe hoy
`architect == qa_auditor`; no vale la pena arreglarlo en un lado y repetirlo en el otro.

---

## Arquitectura de la capa relacional (P3 + P4)

Cuarto ABC del repo, mismo patrón que [models/base.py](../models/base.py),
[memory/base.py](../memory/base.py) y [context/schema/base.py](../context/schema/base.py):

```
context/relational/
  base.py            RelationalHint, RelationalResult, RelationalProvider (ABC)   <- P3
  name_inference.py  determinista, 0 dependencias                                  <- P3
  rtj.py             RT-J, import perezoso de torch                                <- P4
  render.py          bloque advisory                                               <- P4
```

```python
@dataclass
class RelationalHint:
    from_table: str; from_columns: List[str]
    to_table: str;   to_columns: List[str]
    confidence: float                    # [0,1]
    source: str                          # "name_inference" | "rtj"
    evidence: str                        # por qué, en una línea legible

@dataclass
class RelationalResult:
    hints: List[RelationalHint]
    ranked_tables: List[Tuple[str, float]]
    provider: str
    degraded: bool = False
    reason: Optional[str] = None

class RelationalProvider(ABC):
    @abstractmethod
    def infer(self, snapshot: SchemaSnapshot, query: str) -> RelationalResult: ...
```

El ABC no es ceremonia: hace la capa testeable offline contra un provider determinista
(`name_inference` es su primer ocupante, antes que RT-J), lo que separa los bugs de integración de
los del modelo, y deja la implementación reemplazable.

Integración en [core/orchestrator.py](../core/orchestrator.py) `_build_schema_context` (~388) — ya
síncrono, model-free, devuelve `(block, stats)`. La capa corre **dentro** del proveedor de schema,
así que no es un tercer proveedor de contexto y la conclusión de Q2 (el Broker no gana nada con 2
proveedores) sigue en pie.

---

## Config nueva (`config/settings.yaml`) — la introduce P4

```yaml
# Inteligencia relacional (opt-in, solo activa si el request trae --schema-file).
# NO es un tercer proveedor de contexto: es una mejora DENTRO del proveedor de schema.
# Emite relaciones INFERIDAS, nunca declaradas — se renderizan en su propio bloque, con
# score, y jamás dentro del bloque AUTHORITATIVE.
relational:
  provider: "none"          # none | name_inference | rtj
  min_confidence: 0.5       # umbral para ampliar la selección (F4.1)
  max_hints: 8
  max_chars: 800            # se descuenta de schema_grounding.max_chars, no del RAG
  shadow_only: true         # true = solo al recibo, no toca ningún prompt (F3.3)
  checkpoint_path: null     # solo para provider: rtj
```

---

## Resumen costo-beneficio

**51 tareas en cinco proyectos.**

| Proyecto | Tareas | Bandas | Delegación local |
|---|---|---|---|
| P0 | 3 + setup | 3 Low | Humanas por G2 |
| P1 | 10 | 2 Low · 7 Moderate · 1 Med-high | O1-O5 humano/cloud (arranque circular); O6-O10 delegables |
| P2 | 10 | 6 Low · 4 Moderate | 7 agente · 2 agente+confirmación · 1 humana |
| P3 | 6 | 3 Low · 3 Moderate | 5 agente · 1 humana |
| P4 | 22 | 8 Low · 11 Moderate · 3 Med-high | 13 agente · 9 humanas (7 por G2, 2 por G1) |

**Dónde está concentrado el gasto:** las 4 tareas Med-high y las 13 de F3/F4 dependen de lo que P3
mida como residuo **por dominio**. Ese reparto no se puede anticipar: las cifras que hay de la
heurística determinista salen de tres fixtures que comparten forma (CRUD de negocio) y bajo A2 no
dicen nada del caso general. Los fixtures `telemetry`/`logistics` existen para que F2.3 sea una
medición y no una extrapolación.

**Costos declarados:**
- **VRAM:** ~85M params (~340MB fp32) al lado de un stack de 27-30B con Ollama `-np 1`. La parte
  barata.
- **Presupuesto de contexto:** 800 chars, y salen del schema, no del RAG. `max_context_chars: 6000`
  sigue siendo techo duro.
- **Recibo:** bump a 1.3 → avisarle a fenix (validó contra 1.1/1.2).
- **Auditoría externa:** 8 invocaciones de `gpt-5.6-sol` a `high`, vía profile opt-in. El default
  global de Codex (`terra`/`medium`) no se toca.
- **H3 (vector store sin noción de proyecto) NO contamina ningún gate:** P2, P3 y F3.4 miden
  `select_tables()` directo, offline, sin RAG y sin Ollama. Ventaja real frente a la Fase 3 del
  schema plan, que tuvo que esquivarlo con un workaround.
- **Ollama `-np 1` limita el paralelismo real.** Los frentes son independientes por archivo, pero
  comparten un único slot: dos tareas Moderate simultáneas sobre `qwen3.6:27b-q4_K_M` se serializan,
  y alternar con `gemma4:26b-a4b-it-qat` fuerza unload+reload. Paralelizar sirve para separar
  contexto y conflictos de archivo, no para ganar wall-clock — salvo agrupando por modelo.

---

## FODA

| | **Positivo** | **Negativo** |
|---|---|---|
| **Interno** | **Fortalezas**<br>· La necesidad está verificada y es reproducible hoy (Q10 / `hostile_naming.json`), no supuesta<br>· El asiento (ABC) hace la capa testeable offline contra un provider determinista antes de que entre el modelo<br>· El instrumento se valida reproduciendo un fallo ya documentado (F1.3) antes de medir nada<br>· Las 51 tareas están puntuadas con una métrica externa y determinista, no con juicio propio<br>· Cinco proyectos con gate propio: cada uno entrega solo y ninguno queda rehén del desenlace del siguiente<br>· A2 impide que una mejora de un solo dominio se lea como mejora general | **Debilidades**<br>· El repo no tiene suite de tests → `T=4` estructural, el conductor dominante del RRI en todo el repo<br>· `core/orchestrator.py` (1122 líneas, 56% en dos métodos) bloquea 2 tareas de P4; P1 lo resuelve pero es un proyecto entero<br>· P1 arranca circular: no se puede delegar el refactor del archivo que impide delegar<br>· Sin anchor rubric propio, D/P/K quedan sin ancla; R5 lo mitiga pero es un artefacto sin rodaje<br>· `architect == qa_auditor` en el mismo tag: el design gate no tiene independencia real<br>· El piso determinista está medido solo sobre fixtures CRUD; su rendimiento en no-CRUD es desconocido |
| **Externo** | **Oportunidades**<br>· El corpus multi-dominio y el runner sirven a cualquier proveedor futuro del asiento<br>· R5 y P1 se reutilizan en todo el repo, no solo acá<br>· P1 desbloquea toda capa de contexto futura — `orchestrator.py` es por donde entran todas<br>· El auditor Codex `sol-high` rompe la dependencia de un solo proveedor para el juicio<br>· Corregir "RRI · Not portable" deja el flujo de trabajo realmente importado, no citado | **Amenazas**<br>· **La más seria:** sesgo de dominio de RT-J — viene preentrenado sobre RelBench, y una mejora que solo aparece en dominios parecidos a ese preentrenamiento no es adopción para un factory genérico (A4)<br>· La calibración de F0.1 puede consumir el timebox sin alcanzar el criterio, retrasando P4<br>· `cc-by-nc-sa-4.0` — ShareAlike contamina derivados de los pesos; un giro comercial reabre la decisión<br>· Cuarta repetición del fallo histórico del repo (instrumento inválido) si F1.3 se saltea<br>· Deriva de scope hacia BA/Broker/RFM, que el doc externo empuja con su propio gate sin limpiar |

---

## Conclusión

**Lo que hace exitosa la adopción no es que RT-J funcione — eso es la premisa — sino que su
contribución sea atribuible y su efecto medible en un factory sin dominio privilegiado.** Todo el
programa está construido alrededor de esas dos condiciones, y es la razón de que P2 y P3 existan
como proyectos y no como preámbulo de P4.

Tres decisiones lo sostienen, y ninguna es demora. **El bug del selector se arregla antes de medir
el baseline** — si no, RT-J se lleva el crédito de arreglar un bug ajeno. **El piso determinista va
antes que el modelo** — sin piso, cualquier mejora podría ser de la heurística; y de paso el
contrato del asiento queda validado contra un provider debuggeable offline, así los bugs de
integración no se mezclan con los del modelo. **El instrumento se valida reproduciendo un fallo
conocido** — la lección de [fase3-decision.md](fase3-decision.md) aplicada por adelantado, en un
repo que ya la aprendió tres veces por las malas.

La amenaza dominante no es que RT-J falle, es **A4: que funcione desparejo**. Viene preentrenado
sobre RelBench y arrastra esos priors; una mejora que aparece en los dominios parecidos a su
preentrenamiento y no en el resto es exactamente lo que un factory genérico no puede adoptar. Por
eso el gate de F3.4 exige que se sostenga en los 5 dominios y **prohíbe leer el promedio**, y por
eso las dos fixtures no-CRUD no son opcionales ni diferibles.

El análisis que produjo este programa cayó dos veces en la trampa que A2 describe — usar mediciones
de tres fixtures CRUD para predecir el caso general, y convertir una calibración pendiente en duda
sobre la hipótesis. Que el error sea fácil de cometer *dentro del propio plan que lo prohíbe* es el
mejor argumento a favor de que A2 y A4 sean gates ejecutables con números escritos antes (R2), y no
principios de buena voluntad.

**Recomendación: ejecutar, en este orden.** P0 primero (3 tareas Low, precondición de puntuar
cualquier otra cosa). P1 en paralelo desde el día uno: es independiente, paga por sí solo,
desbloquea F3.3b/F4.3 y beneficia a toda capa de contexto futura. Después la cadena P2 → P3 → P4. El
primer resultado que informa decisiones reales es el residuo por dominio de P3; el gate de la
adopción es F3.4.

---

## Fuera de alcance (explícito)

Analyst/BA (Q4 sigue **sin responder**: hace falta un corpus con reglas de negocio reales), Context
Broker (Q2: con 2 proveedores no gana nada; esta capa **no** es un tercero), introspección viva de
DB, y `enforce` mode del conformance check (C.7, con su propio gate).
