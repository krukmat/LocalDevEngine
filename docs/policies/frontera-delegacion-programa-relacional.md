# Frontera de delegación — Programa capa relacional

Entregable de **R4** en [plan-p0-metodo-y-medicion.md](../plan-p0-metodo-y-medicion.md), parte de
[programa-capa-relacional.md](../programa-capa-relacional.md). Lista las clases de tarea que **no**
puede ejecutar el factory sobre sí mismo, con su razón. Es G2, escrito.

**Nota de proceso:** este documento es H (humano) por G2 — mismo principio que R1 y R5. El borrador
de abajo lo redactó Claude Code por instrucción directa del usuario; sigue pendiente de revisión y
confirmación humana antes de tratarlo como gobernante real.

## La regla, tal como está fijada en el programa

> G2 · El factory no puede ser su propio juez. RRI mide riesgo de *implementación*, no validez de
> *instrumento* — no tiene variable para "si esta etiqueta está mal, todas las mediciones
> mienten". Por eso esta regla queda fuera del cálculo y por encima de él.

RRI decide **cómo** delegar una tarea ya aceptada como delegable (banda → ruta de ejecución). G2
decide **si** delegarla es válido en primer lugar. Son capas distintas: una tarea puede puntuar
Low en RRI y seguir siendo no-delegable si cae en una de las clases de abajo.

## Las cuatro clases no delegables

### Clase 1 — Etiquetar el corpus (es la verdad de referencia)

**Por qué:** `labels.json` es contra qué se mide todo lo demás. Si el agente que etiqueta es el
mismo tipo de sistema que después se evalúa contra esas etiquetas, el gate deja de ser una medición
independiente — mide la consistencia del agente consigo mismo, no la calidad real de la selección o
inferencia relacional.

**Dónde aplica:**
- P2 / F1.1c, F1.1d — `labels.json` de los 5 fixtures. Marcadas `Ej.=A+H` (agente propone, humano
  confirma), no `A` puro — es la excepción explícita a "no delegable": un agente **puede proponer**
  etiquetas, la confirmación es humana.

### Clase 2 — Leer el resultado de un gate y decidir continuar/parar

**Por qué:** un gate devuelve un número o un exit code; decidir qué significa ese número para el
proyecto (¿el instrumento sirve? ¿el residuo es aceptable? ¿hay sesgo de dominio?) es juicio, no
cómputo. Es la lección de `fase3-decision.md` en forma de regla: el NO-GO de esa fase no fue un
fallo de cálculo, fue una lectura humana de que el instrumento no sostenía lo que el número parecía
decir.

**Dónde aplica:**
- P2 / F1.3 — validación del instrumento contra el fallo ya documentado.
- P3 / F2.3 — ¿el residuo está bien caracterizado, o hay relaciones mal clasificadas?
- P4 / F3.4 — el gate de cierre del programa entero: ¿la mejora se sostiene por dominio, o es
  sesgo de RelBench?
- Todo punto de reflexión de cierre de cada proyecto (continuar / ajustar / parar contra su
  propio R3).

**Matiz:** el auditor externo (Codex `sol-high`) puede dar una segunda lectura independiente sobre
si el gate *mide lo que dice medir* — pero la decisión de continuar/parar sigue siendo humana en
los tres casos de arriba. Auditar no es decidir (tabla explícita en `programa-capa-relacional.md`
§"Auditor externo").

### Clase 3 — Verificar afirmaciones sobre RT-J contra fuentes externas

**Por qué:** el engine es local (`LDE_OLLAMA_HOST` apunta a un servidor Ollama sin acceso a red
saliente por diseño). Leer qué publica un modelo externo, verificar sus métricas de benchmark, o
confirmar los términos exactos de su licencia requiere fuentes fuera del repo — el factory no tiene
la capacidad estructural de hacerlo, no es una cuestión de juicio.

**Dónde aplica:**
- P4 / F0.1a-d — calibración de encoding/encuadre/decoding contra la interfaz real que RT-J
  publica.
- P4 / F0.2 — métrica primaria y secundarias, que dependen de qué reporta RT-J.
- Cualquier verificación de S5.1/S5.4 del registro de supuestos (R1) — las cifras de benchmark de
  RT-J y los términos de `cc-by-nc-sa-4.0`.

### Clase 4 — P0 entero

**Por qué:** P0 produce las reglas con las que se juzga todo lo demás (anchor rubric, registro de
supuestos, esta misma frontera). Un factory que escribe su propia frontera de delegación sin
supervisión humana está, por definición, decidiendo qué puede decidir solo — es circular en el
sentido más literal de la regla G2.

**Dónde aplica:** R1, R4, R5, y la configuración del auditor externo — las cuatro tareas de P0, sin
excepción.

## Una quinta clase, distinta en naturaleza: G1, no G2

No es "el factory no debe juzgarse" — es "el factory no puede *leer* el archivo para hacer el
trabajo". Se documenta acá porque en la práctica produce el mismo resultado (tarea no delegable a
un agente local) aunque la causa sea otra.

**Dónde aplica:**
- P1 / O1-O5 — el refactor de `core/orchestrator.py` no se puede delegar a un agente local porque
  el archivo mide 1122 líneas, por encima del umbral de 500 que el propio proyecto existe para
  resolver. Circular sin salida elegante: la primera pasada es humana o cloud; desde O5 en
  adelante los módulos extraídos ya están bajo el umbral y vuelven a ser delegables con
  normalidad.
- P4 / F3.3b, F4.3 — mientras P1 no cierre, tocan directamente `core/orchestrator.py` y heredan la
  misma restricción. Si P1 cierra primero, estas dos tareas reapuntan a
  `core/pipeline/context_stages.py` y bajan a Moderate delegable.

## Lo que SÍ se delega, para que la frontera no se lea como "todo es humano"

De las 51 tareas del programa: **25 son puramente `A`** (agente, sin intervención), **2 son
`A+H`** (agente propone, humano confirma — Clase 1 de arriba), y **24 son `H` o `H/cloud`** — de
las cuales 3 son P0 entero (Clase 4), 5 cruzan Clase 2, 5 cruzan Clase 3, y 5 cruzan G1 (O1-O5, y
F3.3b/F4.3 condicionalmente). El resto de las tareas `H` son puntos de reflexión de cierre de
proyecto, que son en sí mismos una instancia de Clase 2.

La frontera no crece con el tamaño del programa — crece con cuántas tareas tocan una de estas
cuatro clases (o G1). Una tarea Low o Moderate que no toca ninguna es delegable sin más trámite que
su propia banda RRI.

## Gate de cierre

Con las cuatro clases de arriba (más la quinta, G1, documentada por separado porque su causa es
distinta), el criterio de R4 — "lista las clases de tarea no delegables con su razón" — está
satisfecho.
