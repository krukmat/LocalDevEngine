# Anchor rubric — LocalDevEngine

Entregable de **R5** en [plan-p0-metodo-y-medicion.md](../plan-p0-metodo-y-medicion.md), parte de
[programa-capa-relacional.md](../programa-capa-relacional.md). Tabla `glob → (D, P, K) floor` para
que `rri.py` deje de reportar `no anchor-rubric match` sobre cualquier ruta de primer nivel de este
repo — sin ancla, D/P/K quedan en juicio del agente y la regla de baja confianza los sube un escalón,
lo que cambia de banda tareas reales (ver la tabla comparativa en P0 §"R5 en detalle").

**Nota de proceso:** esta tabla es H (humano) por G2 — el factory no puede escribir su propia
frontera de delegación sin volverse juez de sí mismo. El borrador de abajo lo redactó Claude Code por
instrucción directa del usuario, no el pipeline local de este repo; sigue pendiente de que el humano
la revise, edite lo que no comparta y la confirme antes de tratarla como gobernante real de bandas de
ejecución.

## Cómo se aplica

Cada fila es `RubricRow(glob, D, P, K, adr, label)`. `match_rubric()` recorre las filas **en orden**
y usa la primera que matchea (`fnmatchcase`, donde un solo `*` cubre `/` — cubre subárboles enteros).
Por eso el orden abajo es siempre de más específica a más general: un archivo puntual antes que el
directorio que lo contiene, un directorio antes que su padre.

El floor **nunca baja** un valor que el agente ya haya estimado más alto (`max(agente, floor)`); solo
garantiza un piso cuando el agente no tiene con qué anclar. `P ≥ 4` en cualquier ruta tocada dispara
el penalty automático `auth_security` (+10) — el nombre es heredado del rubric genérico de dubbridge,
pero el chequeo real es `P >= 4` sin importar si la ruta es literalmente auth; aquí se usa igual, para
marcar "alto radio de impacto" en general (igual que "migrations" en el rubric genérico, que no es
auth y también lleva P=5).

## Tabla

| Glob | D | P | K | Razón |
|---|---|---|---|---|
| `core/receipt.py` | 3 | 4 | 4 | Contrato público que consume fenix (`SCHEMA_VERSION`); un cambio de forma rompe al llamador sin que ningún test local lo detecte. |
| `core/orchestrator.py` | 4 | 4 | 5 | Punto de integración de toda capa de contexto (router → RAG → schema → Manager → Architect↔QA → Implementer↔QA → recibo). El archivo más acoplado del repo — K máximo. |
| `core/*` | 2 | 3 | 3 | Ingesta y chunking (`ingestor.py`, `chunking.py`): alimentan la memoria que el resto del pipeline consume, pero son deterministas y están bien encapsulados. |
| `context/schema/conformance.py` | 3 | 4 | 2 | Única superficie del recibo que puede **subir** la confianza del llamador (`docs/plan-schema-conformance.md`), no solo bajarla. Un falso `CONFORME` es peor que un falso negativo en cualquier otro campo self-reported. |
| `context/schema/selection.py` | 3 | 4 | 3 | Sitio del bug del fallback silencioso (P2, F1.4a/b): un hit incidental de una sola columna apaga `include_all_if_no_match` dentro de un bloque rotulado AUTHORITATIVE. Modo de falla silencioso, no ruidoso. |
| `context/schema/*` | 3 | 3 | 3 | Resto de selección/render/extracción de schema grounding — asertado como autoritativo sobre RAG cuando difieren. |
| `context/relational/*` | 3 | 2 | 3 | Mismo patrón de proveedor que schema (P3, `RelationalProvider` — directorio aún no existe, fila reservada), pero produce *hints* rankeados, no un bloque autoritativo; el costo de un error es menor. |
| `context/antares/*` | 4 | 4 | 2 | `asyncio.create_subprocess_exec` de un CLI externo (I5 — argv, sin shell) + contención de path (I6). Clase seguridad, no clase lógica de negocio. K bajo: es hoja no bloqueante (I1), nada aguas abajo depende de su salida. |
| `context/*` | 2 | 2 | 2 | Selección de contexto en general, sin la especificidad de las filas de arriba (p. ej. un subpaquete nuevo aún no clasificado). |
| `models/ollama_model.py` | 2 | 3 | 4 | Streaming NDJSON + `keep_alive`; toda etapa cuyo output el usuario lee pasa por `generate_stream()`. |
| `models/*` | 2 | 2 | 4 | ABC + factory (Strategy/Factory); alto acoplamiento (todo rol pasa por acá) pero bajo conocimiento de dominio — es HTTP genérico contra Ollama. |
| `memory/*` | 2 | 2 | 3 | Vector store local (NumPy, escritura atómica). Una corrupción degrada el RAG en silencio (similitud mal calculada), no rompe el pipeline. |
| `prompts/specialized_prompts.py` | 3 | 4 | 4 | `OUTPUT_CONTRACTS["fenix-tagged-file"]` es una gramática externa copiada verbatim del parser de fenix. Un desvío de texto rompe al llamador sin que ningún test local lo capture — mismo perfil de riesgo que `receipt.py`. |
| `prompts/*` | 2 | 2 | 3 | Templates por rol/etapa; un cambio de texto altera el comportamiento de cada etapa sin que lo capture un compilador ni un linter. |
| `config/settings.yaml` | 1 | 2 | 5 | Sin secretos (el host de Ollama es `LDE_OLLAMA_HOST`, no config), pero es la única fuente que lee cada rol — un tag de modelo o un budget mal puesto degrada el pipeline entero sin tocar una línea de código. |
| `config/*` | 1 | 1 | 3 | Wiring genérico, mismo criterio que arriba a menor escala. |
| `main.py` | 3 | 4 | 4 | Segunda superficie de contrato externo de fenix: exit codes (0/2/3) y la forma de `--json`. Valida `--schema-file` antes de invocar el pipeline. |
| `tests/*` | 0 | 0 | 0 | Sin efecto en producción; la única consecuencia de romperlo es el propio gate. |
| `docs/*` | 0 | 0 | 0 | Mismo criterio que `tests/*`. |
| `*.md` | 0 | 0 | 0 | Documentación de raíz (`README.md`, `CLAUDE.md`, `README_DOCUMENTATION.md`) — mismo nivel que `docs/*`. En la práctica solo matchea archivos `.md` de raíz: cualquier `.md` anidado ya cae en una fila más específica antes de llegar acá (primer match gana). |
| `requirements.txt` | 0 | 1 | 3 | Sin conocimiento de dominio, pero una versión incompatible de `httpx`/`numpy`/`PyYAML` rompe cada etapa que la usa (streaming, embeddings) — alto K, y normalmente en forma ruidosa (`ImportError`), de ahí P bajo. |
| `*` | 1 | 1 | 1 | Piso conservador para cualquier ruta de primer nivel todavía no clasificada. Falla hacia incluir — mismo principio que `include_all_if_no_match` en `selection.py` — en vez de dejar cualquier archivo nuevo en `no anchor-rubric match`. Agregar una fila explícita antes de que ese archivo crezca, no confiar en este piso a largo plazo. |

## Verificación de cobertura

Corrida offline (no toca `dubbridge/scripts/rri.py`, construye el `PlatformProfile` en memoria y
llama a `match_rubric()` directamente) contra los 75 archivos reales del repo hasta profundidad 3,
excluyendo `.git`, `__pycache__`, `.vector_store` y `.claude`: **0 rutas sin match**. Los tres
ejemplos trabajados (`context/schema/selection.py`, `core/orchestrator.py`,
`context/relational/name_inference.py` con T/A/X/C de referencia) devuelven bandas Med-high, Complex
y Moderate respectivamente — sin la advisory, y en línea con lo que P1/P2/P3 ya asumen sobre esas
rutas (orchestrator.py no delegable sin refactor; selection.py sensible; el piso relacional en
territorio Moderate).

## Extensión opcional — no hecha

El entregable obligatorio es la tabla de arriba; registrar un profile `localdevengine` en
`PROFILES`/`DETECTION_ORDER` de `/Users/matias/dubbridge/scripts/rri.py` (mismo patrón que
`_DUBBRIDGE_RUBRIC`) para que `--platform localdevengine` (o auto-detección) la resuelva sin pasarla
"a mano" es comodidad, no gate. Queda deliberadamente sin hacer acá porque toca un archivo de otro
proyecto (dubbridge) fuera del alcance de este repo — se hace bajo confirmación explícita, no como
parte de R5.

## Gate de cierre

Con la tabla de arriba aplicada "a mano" (opción explícita del gate en P0), el criterio de R5 —
"la tabla cubre toda ruta de primer nivel del repo" — está verificado por la corrida de cobertura de
arriba: 0 de 75 archivos reales sin match.
