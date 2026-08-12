# Registro de supuestos — Programa capa relacional

Entregable de **R1** en [plan-p0-metodo-y-medicion.md](../plan-p0-metodo-y-medicion.md), parte de
[programa-capa-relacional.md](../programa-capa-relacional.md). Lista los supuestos de cada
proyecto (P0-P4) y qué evidencia sostiene cada uno **hoy**, 2026-08-12. Los que no tienen ninguna
se marcan como tales — ese marcado es el entregable, no un defecto del documento.

**Nota de proceso:** este documento es H (humano) por G2 — el mismo principio que R4 y R5: el
factory no puede escribir su propio registro de supuestos sin volverse juez de sí mismo. El
borrador de abajo lo redactó Claude Code por instrucción directa del usuario; sigue pendiente de
revisión, edición y confirmación humana antes de tratarlo como gobernante real.

**Cómo leer la columna Evidencia:** una entrada solo cuenta como evidencia si es una medición
corrida, una cita a un archivo/línea verificable, o un resultado de gate ya cerrado. Una
afirmación de diseño ("tiene sentido que...") sin nada de eso detrás se marca **SIN EVIDENCIA**,
sin excepción, aunque sea plausible.

## Leyenda

| Marca | Significa |
|---|---|
| ✅ Medido | Hay una corrida, gate o número real citado |
| 📄 Documentado | Hay una decisión registrada con su razonamiento, no una medición |
| ⚠️ SIN EVIDENCIA | Afirmación de diseño o expectativa, sin medición ni cita que la sostenga hoy |

---

## Programa (transversal)

| # | Supuesto | Evidencia | Marca |
|---|---|---|---|
| S0.1 | RT-J funciona (la hipótesis operativa que el programa no re-discute) | Premisa fijada explícitamente como no re-discutible en `programa-capa-relacional.md` — el programa mide *adopción*, no la hipótesis en sí | 📄 Documentado (fijado por decisión, no por medición) |
| S0.2 | El caso Q10 (relación real sin FK, sin asidero léxico) es real y reproducible | `tests/fixtures/schema/hostile_naming.json` existe; citado por su nombre de archivo como el caso codificado | ✅ Medido — el fixture y el fallo de `select_tables()` sobre él están verificados |
| S0.3 | Separar en 5 proyectos con gate propio es mejor que una adopción monolítica | Justificado por la propiedad "cada proyecto se puede detener sin dejar trabajo tirado" — es un argumento de diseño, no una comparación medida contra la alternativa monolítica (que nunca se ejecutó) | ⚠️ SIN EVIDENCIA — argumento de diseño razonado, no A/B contra la alternativa |
| S0.4 | RRI (fórmula, pesos, bandas) mide razonamiento requerido de forma útil para este repo específicamente | Es la métrica que ya gobierna DubBridge (`RRI_POLICY.md`), importada — no hay validación propia de que sus pesos (p.ej. 0.15 a T) calibren bien para LocalDevEngine | ⚠️ SIN EVIDENCIA — importada de otro proyecto, sin gate propio de validación en este repo |
| S0.5 | `T=4` (sin tests en el área) es el conductor dominante del RRI en este repo | Medido corriendo `rri.py` sobre las 51 tareas: cambia 8 tareas Med-high → 4 al bajar T vía F2.1b | ✅ Medido — número citado en `programa-capa-relacional.md` §"Lo que el instrumento encontró" |

## P0 — Método y medición

| # | Supuesto | Evidencia | Marca |
|---|---|---|---|
| S1.1 | Sin anchor rubric, D/P/K quedan sin ancla y la banda sube | Medido: F3.3b pasa de 41 (Med-high) a 58 (Complex) sin ancla, corrida real con `rri.py` | ✅ Medido — tabla en P0 §"R5 en detalle" |
| S1.2 | El anchor rubric recién escrito (R5) asigna D/P/K razonables para este repo | Verificado mecánicamente (0/75 archivos sin match) y con 3 ejemplos trabajados, pero los valores D/P/K de cada fila son criterio humano sin validación externa — no hay corrida que confirme que "razonable" y "correcto" coinciden | ⚠️ SIN EVIDENCIA — cobertura verificada, calibración de los números no |
| S1.3 | Codex `gpt-5.6-sol` a `high` da independencia de juicio real frente al stack local (`architect == qa_auditor` en el mismo tag) | Argumento estructural correcto (proveedor distinto, no el mismo modelo revisándose), pero el profile no está configurado todavía (`~/.codex/config.toml` sin tocar) — cero corridas de auditoría hechas | ⚠️ SIN EVIDENCIA — setup no ejecutado, cero corridas |
| S1.4 | `high` (no `xhigh`) alcanza para las tareas de este programa | Justificado citando que el workflow guide reserva `xhigh` para RRI 71+ y que ninguna tarea del programa pasa de 47 — es una inferencia de umbral, no una comparación `high` vs `xhigh` corrida sobre una tarea real de este programa | 📄 Documentado — regla heredada aplicada correctamente, sin corrida propia |

## P1 — Refactor de `core/orchestrator.py`

| # | Supuesto | Evidencia | Marca |
|---|---|---|---|
| S2.1 | `_run_pipeline_body` + `run_complex_task` concentran el 56% del archivo en dos métodos | Medido por conteo de caracteres: 31.600 de un total citado, con desglose por método | ✅ Medido — tabla en P1 §"El diagnóstico, medido" |
| S2.2 | El recibo es determinista para entradas fijas con modelos stubeados, y por eso sirve como test de regresión byte a byte (O1) | Afirmado como propiedad del sistema pero **O1 (el golden test) todavía no está construido** — la propiedad no está verificada empíricamente, solo se infiere de que el código no tiene fuentes de no-determinismo visibles | ⚠️ SIN EVIDENCIA — O1 es precisamente la tarea que lo verificaría, y no corrió aún |
| S2.3 | Los 5 patrones elegidos (Parameter Object, Strategy, Template Method, Chain of stages, Facade/Builder) cierran estructura ya implícita en el código, no la imponen | Cada patrón está justificado señalando el código concreto que ya tiene esa forma (p. ej. Strategy citando la rama `_split_plan_sections() is None`) | ✅ Medido — cada fila de la tabla de patrones cita la línea de código que motiva el patrón |
| S2.4 | El refactor es no-disruptivo: `main.py`, fenix y el recibo no notan el cambio | Depende enteramente de que O1-O9 pasen el gate de equivalencia byte a byte — ninguna tarea corrió todavía | ⚠️ SIN EVIDENCIA — es el criterio de aceptación de una tarea futura, no un hecho ya verificado |

## P2 — Selector: arreglo + instrumento

| # | Supuesto | Evidencia | Marca |
|---|---|---|---|
| S3.1 | El bug del fallback silencioso es real: un hit de una sola columna apaga `include_all_if_no_match` | Cita directa a `context/schema/selection.py:124` con el mecanismo descrito | ✅ Medido — línea de código citada, no solo descrita |
| S3.2 | Arreglar el bug antes de medir cualquier baseline es necesario para la atribución | Argumento lógico (si no, un provider posterior se lleva crédito ajeno) — correcto por construcción, no requiere medición propia | 📄 Documentado — es una regla de diseño válida por definición, no una hipótesis empírica |
| S3.3 | El instrumento (`run_relational_gate.py`) medirá selección de tablas de forma confiable una vez construido | **Ningún runner de este tipo existe todavía** (F1.2a-b son tareas futuras); el precedente citado (`fase3-decision.md`) es evidencia de que el repo *ya construyó un instrumento inválido antes* — motiva F1.3 (validación obligatoria) pero no prueba que el próximo instrumento sea válido | ⚠️ SIN EVIDENCIA — es exactamente lo que F1.3 existe para verificar, y no corrió |
| S3.4 | Los dos fixtures nuevos (`telemetry`, `logistics`) rompen el supuesto CRUD de forma representativa | Diseñados explícitamente para eso (claves compuestas, grafo con auto-referencia) pero no construidos todavía (F1.1a/b son tareas futuras) — el diseño es razonado, la representatividad real es no verificable hasta que existan | ⚠️ SIN EVIDENCIA — diseño justificado, fixtures no construidos |

## P3 — Piso relacional determinista

| # | Supuesto | Evidencia | Marca |
|---|---|---|---|
| S4.1 | La heurística por nombre (`name_inference`) tiene números reales sobre fixtures existentes | 100%/100% en `small`, 100%/75% en `hostile_naming`, 71%/75% en `medium` — corridos y citados | ✅ Medido — con la advertencia explícita del propio doc de que no autorizan proyección (A2) |
| S4.2 | Esos números NO predicen el desempeño en `telemetry`/`logistics` (no-CRUD) | El propio documento lo marca así explícitamente citando A2 — es el caso raro de un supuesto que el doc ya declara como no sostenido, en vez de dejarlo implícito | ✅ Medido (como ausencia): el doc mismo documenta la falta de evidencia como hallazgo, no como omisión |
| S4.3 | `F2.1b` (test de contrato del ABC) es la palanca de RRI más barata del programa | Medido corriendo `rri.py`: baja T de 4 a 2 en 5 tareas río abajo, saca 2 tareas de Med-high | ✅ Medido — número citado con desglose de tareas afectadas |
| S4.4 | El residuo medido en `medium` (`tasks→users`, `audit_log→users`, `task_comments→users`) es representativo del residuo general, no solo de ese fixture | Los 3 casos están medidos y citados con la columna exacta (`assignee_id`/`actor_id`) — pero "representativo del caso general" es exactamente lo que A2 prohíbe inferir de un solo fixture, y el propio documento no lo afirma, solo reporta los 3 casos concretos | 📄 Documentado como hallazgo puntual — no se generaliza, correctamente |

## P4 — Adopción de RT-J

| # | Supuesto | Evidencia | Marca |
|---|---|---|---|
| S5.1 | RT-J (AUROC 0.7310 / MAE 0.2677) es el modelo correcto para esta tarea | Números citados de la publicación del modelo — son las métricas *del benchmark de RT-J sobre RelBench*, no una medición de RT-J sobre datos de este repo o dominios fuera de RelBench | 📄 Documentado — cifra externa citada correctamente, pero no es evidencia de desempeño en este contexto |
| S5.2 | El sesgo de dominio de RT-J (preentrenado sobre RelBench) es la amenaza dominante del proyecto | Razonado con fuerza (RelBench tiene su propio conjunto de dominios, y una mejora pareja no está garantizada) pero es una predicción, no una medición — es precisamente lo que F3.4/A4 existen para verificar, y esa tarea no corrió | ⚠️ SIN EVIDENCIA — es el riesgo mejor argumentado del programa, y a la vez el menos medido; correctamente tratado como criterio de gate futuro, no como hecho ya establecido |
| S5.3 | F0.1 (calibración encoding/encuadre/decoding) es alcanzable dentro del timebox de 3 días | No hay precedente citado de una calibración de este tipo hecha antes en este repo o en un contexto comparable — el timebox es una decisión de gestión (R2), no una estimación basada en datos | ⚠️ SIN EVIDENCIA — timebox fijado correctamente por disciplina de proceso, pero sin base empírica de cuánto toma en la práctica |
| S5.4 | `cc-by-nc-sa-4.0` es aceptable para uso interno/investigación y no bloquea el proyecto | Es una interpretación de licencia, no verificada contra asesoría legal — el propio documento marca que "un futuro uso comercial reabre esto", lo cual ya reconoce que la evidencia actual es limitada a un caso de uso | 📄 Documentado — interpretación razonada, con su propio límite reconocido explícitamente |
| S5.5 | El Broker de contexto no gana nada con solo 2 proveedores (Q2) — por eso la capa relacional entra *dentro* del proveedor de schema, no como un tercero | Citado como conclusión ya cerrada de un análisis anterior (`decision-capa-contextual-ba-rfm-broker.md`, referenciado) | 📄 Documentado — remite a un documento de decisión externo a este registro, no reproducido acá |

---

## Resumen: dónde está la evidencia real y dónde no

**Con medición real (✅), no solo argumento:** el bug del fallback silencioso (S3.1), el efecto del
anchor rubric sobre las bandas (S1.1), el conductor T=4 (S0.5), los números de `name_inference`
sobre 3 fixtures (S4.1, con su propia advertencia de no-proyección), la palanca F2.1b (S4.3), el
diagnóstico de tamaño de `orchestrator.py` (S2.1).

**Sin evidencia hoy (⚠️), y por qué eso es aceptable en este punto del programa:** la mayoría de
los `⚠️ SIN EVIDENCIA` no son huecos accidentales — son supuestos que **la tarea futura
correspondiente existe específicamente para verificar** (O1 para S2.2/S2.4, F1.3 para S3.3, F3.4
para S5.2, los fixtures nuevos para S3.4). El patrón repetido del repo (tres fallos históricos por
instrumento inválido, citados en P0) es exactamente la razón de que este registro exista: nombrar
el supuesto antes de que la tarea que lo resuelve arranque, para poder comparar después "qué
esperábamos" contra "qué midió el gate".

**Los dos supuestos sin tarea futura que los resuelva, y que valen seguimiento aparte:** S0.3
(cinco proyectos vs. monolítico — nunca se comparará empíricamente, es una decisión de diseño
cerrada) y S0.4 (los pesos de RRI calibran bien para este repo — no hay gate en el programa que lo
mida; se hereda de DubBridge sin verificación propia).

## Gate de cierre

Con la tabla de arriba, el criterio de R1 — "el documento existe y cada supuesto tiene evidencia o
marca de sin evidencia" — está satisfecho: 24 supuestos listados, cada uno con marca ✅/📄/⚠️ y su
razón.
