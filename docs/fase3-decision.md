# Fase 3 — Decisión del gate empírico (tarea 3.5)

**Fecha:** 2026-08-09 (revisado el mismo día tras una primera pasada insuficiente — ver nota
al final)
**Depende de:** tarea 3.4 (18 corridas completas, crudas en
[tests/results/schema_ab/raw/](../tests/results/schema_ab/raw/), resumen en
[tests/results/schema_ab/summary.json](../tests/results/schema_ab/summary.json)).

## Criterio, tal como quedó fijado en `plan-schema-grounding.md` §5.2 antes de medir

> Sobre las 3 fixtures, la corrida **con** `--schema-file` debe producir estrictamente menos
> identificadores desconocidos que la corrida **sin** él, en al menos 2 de las 3, y ninguna
> regresión en la tercera.
>
> Si no se cumple: no se construye nada más de esta capa.

## Paso 1 — aplicación literal del criterio

De las 9 combinaciones (fixture, query), 3 quedaron fuera de comparación por motivos ajenos a
la hipótesis: `small/generic` resolvió a fast path (`outcome.schema_grounding.ran=false`,
nunca se ejercitó el bloque); `medium/generic` falló en ambos lados por infraestructura
(`status=failed`, desconexión de Ollama en el QA Auditor / falla de conexión);
`hostile_naming/generic` sin schema dio `status=timeout` a los 1500s sin contraparte completa.

Quedan 6 pares comparables (`table_name` y `column_only` por fixture):

| Fixture | with total | without total | ¿Mejora estricta? |
|---|---:|---:|---|
| small | 22 | 16 | **No — empeora** |
| medium | 16 | 19 | Sí |
| hostile_naming | 9 | 25 | Sí |

Aplicado literalmente: 2 de 3 mejoran, pero `small` no empata ni mejora — empeora. La cláusula
"ninguna regresión en la tercera" no se cumple. **Esto ya alcanza para un NO-GO mecánico.**

## Paso 2 — por qué esa aplicación literal no es la historia completa

Una primera versión de este documento se detuvo acá y atribuyó la regresión de `small` a que
`check_identifiers()` cuenta imports de Python como identificadores de schema. Esa lectura
usó solo la mitad de la evidencia disponible: el script de 3.3 únicamente vuelca
`unknown_tables`/`unknown_columns` al `summary.json` para el lado **sin** schema (para el lado
**con**, el número vive en el recibo pero no se extrae al resumen). Sacar una conclusión de
causa raíz sin mirar los recibos crudos del lado `with` fue un error de rigor, no solo de
redacción — corregido acá revisando los 18 recibos crudos directamente.

**Primer hallazgo: el instrumento no solo tiene ruido, falla en su función básica.** En 4 de
7 corridas `with` donde `identifier_check.ran=true`, `unknown_count == checked` — el 100% de
lo revisado salió "desconocido", incluyendo `small/table_name`, donde el modelo escribió
clases SQLAlchemy para `orders`/`order_items` (las tablas exactas que el bloque de schema le
mostró) y aun así `known_tables: []`. El checker no está reconociendo uso correcto de tablas
que el propio bloque acababa de darle — no es una cuestión de ruido ocasional, es que su
capacidad de detectar "esto sí está en el schema" está fallando en la mayoría de las corridas
con schema.

**Segundo hallazgo: clasificando a mano cada identificador "desconocido" de los 18 recibos**
(comparado contra los 3 archivos de fixture reales), casi todo cae en tres categorías ajenas a
la hipótesis:

1. **Imports y objetos de catálogo SQL** — `sqlalchemy.orm`, `pydantic`, `fastapi`,
   `psycopg2`, `alembic`, `pg_class`, `pg_index`, `information_schema.columns`,
   `information_schema.statistics`. Tokens reales, cero relación con el schema del usuario.
2. **Palabras sueltas en inglés que el extractor tomó como identificador**, y nombres de
   archivo — `and`, `to`, `if`, `of`, `was`, `with`, `within`, `request`, `name`, `e`,
   `orders.py`, `tasks.py`, `Cliente.py`.
3. **Campos que la propia query pide agregar** — p. ej. `due_date` en "Add a due date field
   to tasks". Por definición no están en el schema todavía; marcarlos "desconocido" es
   estructuralmente inevitable y no distingue con vs. sin schema.

Después de descartar las tres categorías, sobreviven **exactamente 2 eventos genuinos de
nombrado de schema en las 18 corridas**, y apuntan en direcciones opuestas:

- **Sin schema** (`hostile_naming/table_name`, ver
  [raw](../tests/results/schema_ab/raw/hostile_naming__table_name__without.json)): el modelo
  escribió `Cliente.id`, adivinando la convención genérica. La PK real de `Cliente` en el
  fixture es `id_cliente` (nombrado hostil deliberado). Es exactamente la clase de error que
  el schema grounding existe para prevenir, y ocurrió cuando el bloque no estaba.
- **Con schema** (`small/table_name`, ver
  [raw](../tests/results/schema_ab/raw/small__table_name__with.json)): pedido = "Add a
  discount code field to orders". El bloque de schema mostrado (`tables_shown: [order_items,
  orders, products, users]`, `matched: [order_items, orders]`) es correcto y completo. Aun
  así, el modelo inventó una tabla nueva `discount_codes` — ausente del bloque autoritativo
  que se le acababa de dar y que el prompt le dice explícitamente que gana sobre lo inventado.
  La corrida **sin** schema para la misma query, en cambio, agregó columnas `discount_code`/
  `discount_amount` directamente sobre `orders` — la interpretación mínima y correcta de lo
  pedido.

## Paso 3 — qué significa esto para el criterio

Con 2 eventos genuinos en 18 corridas — uno a favor de la hipótesis, uno en contra — no hay
base estadística para leer el resultado como "el schema ayuda" ni como "el schema no ayuda".
El criterio del §5.2 asume que `unknown_count` mide invenciones reales de schema; la auditoría
de este paso muestra que, tal como está implementado hoy, `check_identifiers()` no sostiene esa
asunción: sobre-marca ruido sintáctico (imports, catálogo SQL, palabras sueltas) y
sub-reconoce uso correcto (los `known_tables=[]` en corridas donde el modelo sí usó las tablas
mostradas). El criterio numérico falla mecánicamente (Paso 1) **y**, de forma independiente,
la evidencia que ese número dice resumir no es confiable en ninguna dirección (Paso 2).

## Veredicto: **NO-GO**

Se mantiene el NO-GO del Paso 1, pero por la razón correcta: no es que se haya medido un
efecto negativo limpio del schema grounding — es que ni el criterio pre-fijado ni la evidencia
subyacente alcanzan para afirmar que la capa ayuda, que es lo que el gate exige para continuar
("debe producir... menos... en al menos 2 de las 3, y ninguna regresión en la tercera" — la
carga de la prueba es demostrar mejora, no descartar empeoramiento). Por regla del propio plan
(§5.2): *"no se construye nada más de esta capa"*.

Este es un NO-GO más cauteloso que el de la primera versión de este documento, no uno más
débil: antes se leía como "el schema grounding mide peor en un caso", ahora se lee como "esta
medición, tal como está construida, no puede decir si el schema grounding ayuda o no" — y bajo
esa incertidumbre, la regla del plan sigue resolviendo en no avanzar.

## Qué se necesitaría antes de reintentar este gate (revisado)

No alcanza con "hacer que `check_identifiers()` ignore imports" (lo que decía la primera
versión de este documento). El hallazgo del Paso 2 pide más:

1. **Filtrar ruido de precisión**: descartar tokens que sean rutas de import/módulos
   (`import`/`from ... import`, atributos con puntos que resuelven a paquetes conocidos de la
   stdlib o requirements.txt), objetos de catálogo SQL (`pg_*`, `information_schema.*`), y
   nombres de archivo.
2. **Arreglar el problema de recall**: investigar por qué `known_tables`/`known_columns` sale
   vacío en 4 de 7 corridas `with` pese a uso correcto y verificado de las tablas mostradas —
   esto no es un problema de "demasiados falsos positivos", es que el detector de uso
   *correcto* casi no dispara, lo cual también infla `unknown_count` por otro camino.
3. **Excluir identificadores que la propia query pide crear**: un campo/tabla nueva pedido
   explícitamente no es una invención — es la tarea. El checker necesita distinguir "el modelo
   referenció algo que debería preexistir y no existe" de "el modelo creó lo que se le pidió
   crear".
4. Recién con eso corregido, repetir la medición sobre las mismas 3 fixtures/9 queries bajo el
   mismo criterio pre-fijado (u otro, fijado de nuevo antes de correr, si el rediseño del
   checker lo amerita).

El caso `discount_codes` (Paso 2) también merece seguimiento propio independiente del checker:
es evidencia directa, no ruido, de que el modelo puede desviarse del schema mostrado incluso
cuando el bloque es correcto y la instrucción de autoridad es explícita — vale la pena
conservarlo como caso de prueba manual aunque la capa no avance a Fase 4.

## Qué significa esto para la Fase 4

Sin cambios respecto de la primera versión: por regla del plan (§5.3, encabezado: *"Ninguno
de estos se toca hasta que 3.5 concluya que sí"*), **ninguna tarea de Fase 4 se empieza** (ni
4.1 QA gateando, ni 4.2 `chat` con schema, ni 4.3 macro-rerun reenviando parámetros, ni 4.4
providers de introspección viva). La capa queda como está: opt-in, sin costo para quien no la
usa, sin revertir lo construido en Fases 0/R/1/2.
