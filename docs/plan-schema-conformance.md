# Plan — Schema Conformance (redefinición de alcance de la capa de schema)

**Estado:** propuesta de alcance. Ningún código escrito todavía.
**Reemplaza el alcance de:** [docs/plan-schema-grounding.md](plan-schema-grounding.md) §5.3
(Fase 4), que queda cerrada y sustituida por este documento.
**Origen:** el NO-GO de la Fase 3 ([docs/fase3-decision.md](fase3-decision.md)) no invalidó la
idea de la capa — invalidó su *mecanismo*. Este documento cambia el mecanismo.

---

## 0. Qué se puede y qué no se puede prometer

El pedido fue: *que no sea permeable a alucinaciones y sea 100% determinístico*. Hay una
versión fuerte de eso que es alcanzable y una versión que no lo es, y mezclarlas produciría
exactamente el tipo de promesa que este repo viene evitando.

**No alcanzable, nunca:** que el modelo no alucine. La salida de un LLM no es determinista y
ninguna capa de contexto la vuelve determinista. La Fase 3 lo demostró en vivo: con el bloque
de schema correcto, completo y con el header de autoridad explícito
([context/schema/render.py:24](../context/schema/render.py#L24): *"Do NOT invent tables,
columns, types or relations that are absent here"*), el modelo igual inventó una tabla
`discount_codes`. El header es una súplica, no un mecanismo.

**Alcanzable, y es lo que este plan construye:**

1. **Veredicto 100% determinístico.** Dada `(implementación, snapshot)`, el veredicto es una
   función pura: sin modelo, sin red, sin reloj. Mismas entradas → mismo resultado, siempre,
   y el llamador puede recomputarlo por su cuenta y comparar.
2. **No permeable en el sentido útil:** ninguna referencia a una tabla o columna que no existe
   puede llegar al llamador sin quedar marcada. La alucinación deja de ser *indetectable*; se
   vuelve un ítem tipado en una lista.
3. **Estado terminal determinístico.** El pipeline termina en `CONFORME` o en `NO_CONFORME` con
   la lista exacta de violaciones. Nunca en "probablemente está bien".

La inversión clave: **la capa deja de intentar prevenir la alucinación y pasa a verificarla
mecánicamente.** La permeabilidad se elimina en el borde de salida, no en el modelo.

---

## 1. Por qué la capa actual es permeable (diagnóstico confirmado)

`check_identifiers()` ([context/schema/identifiers.py](../context/schema/identifiers.py))
raspa texto libre con expresiones regulares. Ese enfoque no puede ser sólido, y falla en las
dos direcciones a la vez. Verificado ejecutando el regex real del repo:

```
_TABLE_REF_RE sobre código Python + prosa normal:
  → ['sqlalchemy.orm', 'datetime', 'models.order', 'the', 'within', 'of']
```

- **Precisión rota por construcción:** el patrón busca `FROM|JOIN|INTO|UPDATE|TABLE` con
  `re.IGNORECASE`. El `from` de Python (`from sqlalchemy.orm import Mapped`) es un match
  perfecto. Por eso los recibos de la Fase 3 están llenos de `pydantic`, `fastapi`,
  `datetime`, `alembic`, `models.task`. La defensa actual es una blocklist de nombres de
  stdlib (`_NOT_A_TABLE`, [identifiers.py:45](../context/schema/identifiers.py#L45)) — una
  carrera imposible contra el universo de paquetes de PyPI. La prosa aporta el resto:
  `INTO the`, `within`, `TABLE of`.
- **Recall roto por el mismo mecanismo:** el regex solo entiende SQL crudo. Los modelos emiten
  mayormente ORM: `__tablename__ = "orders"`, `mapped_column(...)`. Nada de eso matchea, y por
  eso 4 de 7 corridas con schema reportaron `known_tables: []` *mientras el código usaba
  correctamente las tablas mostradas*.
- **Error de categoría:** un objeto que la query pide crear se marca igual que uno inventado.
  El checker no distingue *definición* de *referencia*.

Las tres fallas tienen una sola causa raíz: **raspar en vez de parsear.** Ninguna cantidad de
regex adicional lo arregla; cada parche agranda la blocklist y deja el agujero siguiente.

---

## 2. Alcance nuevo

### 2.1 Dentro del alcance (todo determinístico, sin modelo en el camino)

| # | Componente | Determinismo |
|---|---|---|
| A | Carga/normalización/selección/render del snapshot | Ya existe, ya es determinístico — se conserva sin cambios |
| B | **Segmentación de la salida en regiones tipadas** (bloques de código con lenguaje declarado). La prosa nunca se analiza | Puro parsing de texto |
| C | **Extracción por AST**, no por regex: SQL con parser SQL real; Python con `ast` de stdlib | Parser, no heurística |
| D | **Tabla de símbolos: definiciones vs. referencias**, construida recorriendo la salida en orden | Función pura |
| E | **Reporte de conformidad tipado** (§3), reemplaza al `unknown_count` escalar | Función pura |
| F | **Gate determinístico + reintento acotado** con la lista de violaciones como feedback (§4) | Regla fija; el reintento usa modelo, la *decisión* no |

### 2.2 Fuera del alcance, explícita y permanentemente

- **Impedir que el modelo alucine.** No es un objetivo alcanzable; es el objetivo que la Fase 3
  refutó. Se detecta y se rechaza, no se previene.
- **Corrección semántica del SQL.** Que un join tenga sentido de negocio, que un índice sea
  buena idea, que el tipo elegido sea el óptimo. Eso requiere juicio; queda en el QA Auditor
  (LLM) con todas las limitaciones que eso implica.
- **Cualquier llamada a modelo dentro del camino de verificación.** Si el verificador llama a
  un LLM, deja de ser recomputable por el llamador y pierde su única propiedad valiosa.
- **Conexiones a base de datos / credenciales.** Ya estaba fuera; sigue fuera.
- **Análisis de prosa.** Si no está en una región de código tipada, no se analiza. Este es el
  recorte que elimina de raíz toda la clase de falsos positivos de la Fase 3.

### 2.3 Qué se elimina de lo construido

- `unknown_count` como métrica principal: no significa nada y no se puede accionar. Se
  reemplaza por violaciones tipadas.
- Las blocklists `_NOT_A_TABLE` / `_NOT_AN_ALIAS`: innecesarias cuando se parsea (un import no
  puede aparecer en una posición de tabla de un AST SQL).
- El header de autoridad **no se elimina, se degrada de rango**: pasa de ser *el mecanismo* a
  ser una optimización que reduce la cantidad de reintentos. Su valor ahora es medible barato
  (reintentos con vs. sin bloque), que es justo lo que la Fase 3 no pudo medir.

---

## 3. El reporte de conformidad

Reemplaza a `identifier_check`. Cada violación es tipada, localizada y accionable:

| Tipo | Significado | ¿Es alucinación? |
|---|---|---|
| `UNKNOWN_TABLE_REF` | Se referencia una tabla que no está en el snapshot **ni** fue definida antes en la misma salida | Sí — el caso central |
| `UNKNOWN_COLUMN_REF` | Columna inexistente sobre tabla conocida, o sobre tabla definida en la salida | Sí |
| `NEW_OBJECT_DEFINED` | La salida define un objeto de schema ausente del snapshot (el caso `discount_codes`) | No necesariamente — es una decisión de diseño; la política decide |
| `UNPARSEABLE_REGION` | Una región de código declarada como SQL/Python no parseó | Desconocido — **y por eso se reporta** |
| `UNTYPED_REGION` | Bloque de código sin lenguaje declarado: no hay parser elegible | Desconocido — se reporta |

**La regla que sostiene la afirmación de "no permeable":** el verificador es sólido sobre la
superficie que analiza **y explícito sobre la superficie que no pudo analizar**. Lo que no se
puede parsear se reporta como violación, nunca se omite en silencio. Un verificador que saltea
calladamente lo que no entiende tiene un agujero del tamaño de todo lo que no entiende — es
exactamente el error que se está corrigiendo.

**Definiciones vs. referencias** (resuelve el error de categoría determinísticamente): se
recorre la salida en orden construyendo una tabla de símbolos. `CREATE TABLE x` o
`class X(Base): __tablename__ = "x"` **definen**; `FROM x` / `select(X)` **referencian**. Una
referencia resuelve contra `snapshot ∪ definiciones_previas`. Así, "agregá una tabla nueva y
usala" deja de ser dos violaciones y pasa a ser un `NEW_OBJECT_DEFINED` más referencias
válidas.

---

## 4. El gate (lo que vuelve la capa no permeable)

Dos perillas ortogonales, ambas inertes si no se pasa `--schema-file`:

- `schema_mode: report | enforce`
  - `report`: verifica y reporta en el recibo, no bloquea. Es el comportamiento de la Fase 2,
    con el verificador nuevo.
  - `enforce`: una violación de referencia (`UNKNOWN_*`) rechaza la implementación y reintenta
    pasándole al Implementer **la lista exacta de violaciones**, hasta
    `max_conformance_retries`. Si no converge: el run termina con estado explícito de no
    conformidad y el reporte completo. Nunca un `qa_approved: true` encima de una referencia
    rota.
- `allow_new_objects: true | false` (default `true`)
  - Controla si `NEW_OBJECT_DEFINED` es violación. Default `true` porque crear una tabla es
    ingeniería legítima — en el caso `discount_codes` la corrida sin schema resolvió con
    columnas sobre `orders` y la corrida con schema normalizó a tabla aparte; **ninguna de las
    dos es incorrecta en abstracto**. Un llamador con un schema cerrado pone `false`.

El reintento usa el modelo; **la decisión de reintentar, no**. El estado terminal es siempre
uno de dos valores computables por el llamador.

---

## 5. Decisión de dependencia

Parsear SQL a mano reproduce la clase de bug que estamos eliminando. Se necesita un parser
real:

- **Python:** `ast` de stdlib. Sin dependencia nueva.
- **SQL:** recomiendo **`sqlglot`** — Python puro (sin binarios ni C), y *dialect-aware*, que
  encaja con el campo `dialect` que el snapshot ya transporta (`postgres`, `mysql` en las
  fixtures actuales).

Es la cuarta dependencia de un repo que hoy tiene tres ([requirements.txt](../requirements.txt):
`httpx`, `numpy`, `PyYAML`), y el minimalismo acá es un valor explícito. La contrapartida es
concreta: sin parser SQL real, la única alternativa honesta es marcar toda región SQL como
`UNPARSEABLE_REGION`, que degrada la capa a "solo verifica ORM en Python". **Es una decisión
del dueño del repo, no mía** — el diseño funciona con cualquiera de las dos, con distinto
alcance de cobertura.

---

## 6. El gate nuevo, fijado antes de medir

El gate viejo era estadístico, caro (18 corridas, "una tarde de máquina") y dependía de un
instrumento roto. El nuevo es determinístico, y por eso puede exigir números absolutos:

> Sobre un corpus etiquetado a mano de `(código, snapshot, violaciones_esperadas)`:
> **cero falsos positivos** sobre el conjunto limpio, y **100% de detección** de las
> alucinaciones sembradas en el conjunto sucio. Toda región no parseada debe aparecer
> reportada, sin excepción.
>
> Si no se cumple: no se activa `enforce`. La capa queda en `report` y se documenta.

Exigir 100% es legítimo acá justamente porque el verificador es determinístico — no es una
tasa de acierto sobre salida de modelo, es corrección de una función pura sobre entradas fijas.

**Y es barato:** los 18 recibos de la Fase 3 ya están guardados en
[tests/results/schema_ab/raw/](../tests/results/schema_ab/raw/). El verificador nuevo se puede
evaluar contra ellos **sin volver a llamar a Ollama ni una vez**. El corpus inicial sale de ahí,
etiquetado a mano — incluyendo los 2 eventos genuinos ya identificados (`Cliente.id` y
`discount_codes`), que se vuelven casos de test con resultado esperado conocido.

---

## 7. Relación con la capa contextual objetivo (Context Broker, BA, RFM)

Revisado contra [docs/handoff-capa-contextual-objetivo.md](handoff-capa-contextual-objetivo.md)
y el diagrama de arquitectura objetivo. Cuatro conclusiones:

**7.1. Esto es la flecha que falta en el diagrama, no una caja nueva.** El handoff, verificando
caja por caja, concluye que del pipeline falta *"1 etapa (Analyst/BA) y 1 flecha (Schema → QA
Gate 2)"*, y que QA Gate 2 *"no consume la señal de schema: `identifier_check` reporta, no
gatea"*. Este plan es exactamente esa flecha, más la corrección de que hoy la señal no es
gateable porque el instrumento está roto (§1).

**7.2. El verificador es el instrumento de medición de todo el programa aguas abajo.** El doc
externo propone un experimento A/B/C/D (RAG / +Schema / +BA IR / +RFM) sobre 9 métricas, dos de
las cuales son *"tablas/columnas alucinadas"* y *"joins inválidos"*. Con el detector actual esas
dos métricas no son confiables, y por lo tanto **ninguna comparación entre variantes lo es**: no
se puede atribuir una reducción de alucinaciones al BA o al RFM si el contador toma
`import pydantic` por una tabla. Arreglar el detector no está detrás del Broker — está delante
de todo el programa.

**7.3. Acoplamiento con el Broker: casi nulo, y el punto crítico ya está bien.** El Broker opera
sobre el contexto de *entrada* (fusiona, deduplica, prioriza); este verificador opera sobre la
*salida*, consumiendo `(implementación, snapshot)`. Se verificó que
[core/orchestrator.py:931](../core/orchestrator.py#L931) ya pasa el snapshot **completo**, no el
subset que la selección renderiza al prompt. **Esto queda como invariante explícita, no como
accidente:**

> El verificador se ejecuta siempre contra el snapshot completo que proveyó el llamador, nunca
> contra la selección que el Broker (o `_build_schema_context`) haya decidido mostrar. Verificar
> contra el subset convertiría cada tabla no mostrada en un falso `UNKNOWN_TABLE_REF`.

Corolario del mismo principio: el verificador consume **el IR estructurado**, nunca el texto
renderizado del prompt.

**7.4. Requisito que esta capa le impone al Contrato de Contexto (antes de que se diseñe).** El
diagrama promete un contrato unificado con *"proveniencia y confianza"* para las 4 fuentes. Si
ese contrato colapsa el schema a un score más, destruye §2 del plan original: el bloque
determinista no lleva score justamente porque un score lo vuelve negociable frente al RAG. El
contrato **debe preservar la distinción afirmado vs. candidato** como propiedad de tipo, no
reducir ambas cosas a un número comparable.

---

## 8. Orden de trabajo propuesto

| # | Tarea | Depende de |
|---|---|---|
| C.0 | Decisión sobre `sqlglot` (§5) | dueño del repo |
| C.1 | Corpus etiquetado a mano desde los 18 recibos existentes + casos sembrados | — |
| C.2 | Segmentación en regiones tipadas (B) | — |
| C.3 | Extractores por AST: Python (`ast`) y SQL | C.0, C.2 |
| C.4 | Tabla de símbolos + reporte tipado (D, E) | C.3 |
| C.5 | Correr el gate de §6 contra C.1 | C.1, C.4 |
| C.6 | Wiring en el recibo, reemplazando `identifier_check` | C.5 = positivo |
| C.7 | `enforce` + reintento acotado (§4) | C.6 **+ forma del pipeline definida** (ver abajo) |

C.1 a C.5 son **enteramente offline**: sin Ollama, sin esperas de 25 minutos, testeables en
milisegundos. Esa es la diferencia práctica más grande respecto del alcance anterior — el ciclo
de validación pasa de una tarde de máquina a una corrida de tests.

**Corte por acoplamiento (consecuencia de §7).** El trabajo se parte en dos mitades con riesgos
distintos:

- **C.1–C.6 — el verificador:** función pura, offline, sin acoplamiento con el flujo del
  pipeline. Es estable pase lo que pase con el Broker, el BA o el RFM, y además los habilita
  (§7.2). **Se puede hacer ahora.**
- **C.7 — `enforce`:** toca el lazo QA ↔ Implementer, que es precisamente lo que la
  arquitectura objetivo reestructura al insertar la etapa Analyst/BA. Construirlo antes de que
  esa forma se defina es construir contra un blanco móvil. **Se difiere**, sin bloquear nada:
  en modo `report` la señal ya queda disponible y medible.

**Nota de reusabilidad (del handoff §2):** el corpus y el runner de C.1/C.5 deben construirse
como *extractor de métricas por recibo con variantes parametrizables*, no como un script de un
número — es la misma recomendación que el handoff le hace a la tarea 3.3, y por el mismo
motivo: si cada pieza siguiente (BA, Broker, RFM) tiene que rehacer el harness, las mediciones
no van a ser comparables entre sí, que es lo que vuelve inútil un A/B/C/D.
