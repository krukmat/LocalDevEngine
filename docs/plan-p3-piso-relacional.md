# P3 — Piso relacional determinista

Parte de [programa-capa-relacional.md](programa-capa-relacional.md). **No es sobre RT-J.** Construye
el asiento (`RelationalProvider`) y su primer ocupante, determinista y sin dependencias.

## Por qué existe

Dos entregables, y el segundo es el artefacto crítico de todo el programa:

**1 · El asiento.** `RelationalProvider` como cuarto ABC del repo, con `name_inference` como
implementación de referencia. Cierra Q10 —una relación real no declarada como FK y sin asidero
léxico— **sin ningún modelo**, de forma determinista y auditable.

**2 · El residuo medido por dominio.** Qué relaciones la heurística **no** recupera, desglosado por
los 5 dominios del corpus. Ese número es el **denominador del gate de P4**: sin él, "¿RT-J mejora?"
no tiene contra qué medirse.

## Dependencias entrantes

| De | Artefacto | Verificación | Tipo |
|---|---|---|---|
| P0 | `docs/policies/rri-anchor-localdevengine.md` | `rri.py --platform python --touches context/relational/name_inference.py` sin advisory | **Dura** |
| P0 | `[profiles.sol-high]` en `~/.codex/config.toml` | `codex --profile sol-high` | **Dura** para auditar F2.3 |
| **P2** | `tests/run_relational_gate.py` (`--provider`, `--per-fixture`) | `--provider none` reproduce el fallo documentado | **Dura** — sin instrumento no hay medición |
| **P2** | Corpus de 5 dominios + `labels.json` | los 5 parsean; ≥3 queries/fixture | **Dura** |
| **P2** | `selection.py` con el fallback arreglado | F1.4a pasa | **Dura** — medir el piso sobre el selector con el bug atribuye mal la mejora |

P3 instancia además su propio **R2** y **R3** — ver [P0](plan-p0-metodo-y-medicion.md).

## Arquitectura

```
context/relational/
  base.py            RelationalHint, RelationalResult, RelationalProvider (ABC)
  name_inference.py  determinista, 0 dependencias
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

Mismo patrón que [models/base.py](../models/base.py), [memory/base.py](../memory/base.py) y
[context/schema/base.py](../context/schema/base.py).

## Tareas

| # | Tarea | RRI | Banda | Dep. | Ej. | Aceptación |
|---|---|---|---|---|---|---|
| F2.1a | `context/relational/base.py` — dataclasses + ABC | 28 | Moderate | R5, R3 | A | importa; mypy/ruff limpio si se agrega |
| F2.1b | **Test de contrato del ABC**, parametrizado por provider | 27 | Moderate | F2.1a | A | falla contra un provider que viole el contrato |
| F2.2a | `name_inference.py` — inferencia de FK por nombre (reusa `selection.py:tokenize`) | 33 | Moderate | F2.1b | A | devuelve `RelationalResult`; F2.1b verde |
| F2.2b | Scoring de confianza + `max_hints` | 24 | Low | F2.2a | A | confidence ∈ [0,1], hints ordenados |
| F2.2c | Correr el gate y registrar recall/precisión **por fixture** | 13 | Low | F2.2b, F1.4c | A | gate en 0, salida `--per-fixture` |
| F2.3 | Documentar **el residuo medido por dominio** | 15 | Low | F2.2c | H | `docs/residuo-relacional-por-dominio.md` con números por cada uno de los 5 dominios |

## F2.1b es la palanca de RRI más barata del programa

No es un test "de más": el conductor dominante de RRI en este repo es `T=4` ("no hay tests en el
área", peso 0.15), porque LocalDevEngine no tiene suite — solo runners de gate. Un test de contrato
parametrizado por provider baja T a 2 en **cinco tareas río abajo** (F2.2a, y F3.1/F3.2a/F3.2b/F3.2c
de P4) y saca a F3.1 y F3.2a de Med-high. Comparado con partir esas tareas en pedazos más chicos, es
menos trabajo y deja algo permanente.

## Por qué el piso va antes que cualquier modelo

Dos razones, y ninguna es demora:

**(a) Atribución.** Sin piso, cualquier mejora medida después podría ser de la heurística. Es el
mismo argumento que pone P2 antes de P3.

**(b) Validación del contrato del asiento contra un provider debuggeable offline.** Cuando entre un
provider con modelo, los bugs de integración y los del modelo no se mezclan.

## Las cifras existentes no autorizan ninguna proyección

Números medidos de esta heurística sobre los fixtures que ya existían: **100%/100%** recall/precisión
en `small`, **100%/75%** en `hostile_naming` (donde el único "falso positivo" *es* la relación
verdadera no declarada), **71%/75%** en `medium`.

**Tratarlos como predicción viola A2.** Esas tres fixtures tienen la misma forma —CRUD de negocio— y
la inferencia por nombre se apoya en una convención de esa misma forma (`orders.user_id → users`).
Medirla ahí y concluir algo sobre el caso general es exactamente el sobreajuste al fixture que A2
prohíbe. En `telemetry` (claves compuestas) y `logistics` (grafo con auto-referencia) **la señal de
la que depende puede directamente no existir**, y eso está sin medir.

Relaciones que la heurística ya falla en `medium`: `tasks→users`, `audit_log→users`,
`task_comments→users` — columnas tipo `assignee_id`/`actor_id`, donde el nombre de la columna no
contiene el de la tabla destino.

## Gate de cierre

```bash
python -m pytest tests/test_relational_contract.py                       # contrato del ABC
python tests/run_relational_gate.py --provider name_inference --per-fixture; echo $?   # 0
# y el documento del residuo existe con números por cada uno de los 5 dominios
```

El gate **no** es "seguir o parar" en el sentido binario: si el residuo es chico en los CRUD y grande
en `telemetry`/`logistics`, el nicho existe y quedó caracterizado por dominio — que es exactamente lo
que P4 necesita para evaluar el sesgo de A4. R3 escribe la acción para cada forma del residuo
—grande, chico, y desparejo entre dominios— **antes** de medirlo.

Auditoría externa de F2.3: Codex `sol-high` (1 de 8) — *¿el residuo está bien caracterizado, o hay
relaciones mal clasificadas?*

## Dependencias salientes

| Hacia | Artefacto | Verificación | Tipo |
|---|---|---|---|
| P4 | `context/relational/base.py` — el ABC y sus dataclasses | `rtj.py` implementa el mismo contrato | **Dura** |
| P4 | `tests/test_relational_contract.py` parametrizado | cubre `rtj.py` sin tests nuevos → `T` 4→2 en 5 tareas | **Dura** |
| P4 | `context/relational/name_inference.py` — el piso contra el que se compara | gate en 0 | **Dura** |
| **P4** | **`docs/residuo-relacional-por-dominio.md`** | el documento existe con números por dominio | **Dura — es el denominador de F3.4** |
| Repo | Q10 resuelto de forma determinista, sin modelo | — | — |

## Valor si el programa para acá

Q10 —el caso que motiva todo el programa— resuelto sin modelo, sin dependencias nuevas y sin VRAM.
Más un asiento listo para cualquier provider futuro.
