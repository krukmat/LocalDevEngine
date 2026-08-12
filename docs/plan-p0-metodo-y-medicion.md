# P0 — Método y medición

Parte de [programa-capa-relacional.md](programa-capa-relacional.md). **No toca código de producto.**

## Por qué existe

Este repo tiene **tres instancias documentadas del mismo fallo**: la Fase 3 del schema grounding dio
NO-GO porque el *instrumento* era inválido ([fase3-decision.md](fase3-decision.md)); la primera
versión del análisis de capa contextual fue **retirada** por usar un corpus construido para otra
pregunta; y la fase 2 del macro-loop se construyó sin correr el gate de la fase 1.

P0 existe para que no haya una cuarta. No es ceremonia: produce artefactos que **cambian la banda de
ejecución** de las tareas de los otros cuatro proyectos.

## Dependencias entrantes

Ninguna. P0 es la raíz del programa.

## Tareas

| # | Artefacto | RRI | Banda | Ej. | Aceptación |
|---|---|---|---|---|---|
| R1 | **Registro de supuestos.** Los supuestos de cada proyecto y qué evidencia sostiene cada uno **hoy**. Los que no tienen ninguna se marcan como tales — ese marcado es el entregable. | 5 | Low | H | el documento existe y cada supuesto tiene evidencia o marca de "sin evidencia" |
| R4 | **Frontera de delegación.** Qué tareas **no** puede ejecutar el factory sobre sí mismo. Es G2, escrito. | 7 | Low | H | lista las clases de tarea no delegables con su razón |
| R5 | **Anchor rubric de LocalDevEngine** — tabla `glob → (D,P,K) floor` para `core/`, `context/`, `memory/`, `models/`, `prompts/`, `config/`, `tests/`, `docs/` | 18 | Low | H | ver criterio abajo |
| — | **Auditor Codex `sol-high`**: agregar `[profiles.sol-high]` a `~/.codex/config.toml` **sin tocar el default global** | — | — | H | `codex --profile sol-high` resuelve `gpt-5.6-sol` / `high` |

Las tres tareas son humanas por **G2**: el factory no puede escribir su propia frontera de
delegación ni su propio registro de supuestos sin volverse juez de sí mismo.

## R5 en detalle — por qué es la tarea de más apalancamiento del programa

Ninguna ruta de LocalDevEngine matchea el rubric genérico de `rri.py` salvo `tests/*` y `docs/*`, así
que **D, P y K quedan en juicio del agente sin ancla** — el calculador lo reporta como advisory
`no anchor-rubric match`. El policy tiene una regla para ese caso:

> *"Low-confidence scores on D, P, or K are themselves a signal: treat the variable as one step
> higher when confidence is Low."*

Aplicándola, medido con el calculador:

| Tarea | Con ancla | Sin ancla (D/P/K en baja confianza) |
|---|---|---|
| F3.3b (P4) | 41 → Med-high | **58 → Complex, descomposición obligatoria** |
| F2.2a (P3) | 33 → Moderate | 47 → Med-high |
| F1.4b (P2) | 31 → Moderate | 39 → Moderate |

**La ausencia del rubric cambia la banda, y con ella la ruta de ejecución.** Por eso es dependencia
dura y no burocracia.

Formato mínimo del entregable (`docs/policies/rri-anchor-localdevengine.md`): filas ordenadas de más
específica a más general, cada una `glob | D | P | K | razón`. Candidatos evidentes a partir de la
estructura actual del repo: `core/receipt.py` (contrato público que fenix consume), `core/orchestrator.py`
(orquestación asíncrona), `context/schema/*` y `context/relational/*` (lógica de selección de
contexto), `models/*` y `memory/*` (integraciones), `config/*` (wiring), `tests/*` y `docs/*` (0/0/0).

**Extensión opcional:** registrar un profile `localdevengine` en `/Users/matias/dubbridge/scripts/rri.py`
(patrón `PROFILES` + `DETECTION_ORDER`) para que `--platform` lo resuelva solo. El entregable
obligatorio es la tabla; el profile es comodidad.

## Gate de cierre

```bash
python3 /Users/matias/dubbridge/scripts/rri.py --platform python \
  --touches core/orchestrator.py --cc 5 --D 4 --K 3 --P 3 --T 4 --A 0 --X 3
# criterio: no aparece la línea "Advisory: ... no anchor-rubric match"
# (o, si el rubric se aplica a mano, la tabla cubre toda ruta de primer nivel del repo)

codex --profile sol-high exec "ping"   # resuelve gpt-5.6-sol / high
```

## Dependencias salientes

| Hacia | Artefacto | Verificación | Tipo |
|---|---|---|---|
| P1, P2, P3, P4 | `docs/policies/rri-anchor-localdevengine.md` | el gate de arriba | **Dura** — sin él los puntajes de los cuatro son de baja confianza |
| P1 (O10), P2 (F1.3), P3 (F2.3), P4 (F3.4 + 4 bundles Med-high) | `[profiles.sol-high]` en `~/.codex/config.toml` | `codex --profile sol-high` resuelve el modelo correcto | **Dura** para los gates auditados |
| P1, P2, P3, P4 | Registro de supuestos (R1), frontera de delegación (R4) | los documentos existen | **Blanda** |

## Lo que P0 explícitamente no entrega

**R2 y R3 no viven acá: son por gate.** Cada proyecto instancia los suyos antes de medir su propio
criterio de cierre.

| # | Artefacto, instanciado por cada proyecto | RRI | Banda |
|---|---|---|---|
| R2 | **Criterio numérico del gate, escrito antes de medir.** Un umbral fijado después de ver el resultado no es un umbral. | 2 | Low |
| R3 | **Matriz resultado → acción.** Para cada desenlace posible de ese gate, qué se hace. Es lo que evita seguir a la etapa siguiente "porque ya estaba planeada". | 28 | Moderate |

Cada proyecto cierra con un **punto de reflexión**: releer el resultado contra su propio R3 y
registrar continuar / ajustar / parar. Un punto de reflexión que no puede cambiar el curso no es un
punto de reflexión.
