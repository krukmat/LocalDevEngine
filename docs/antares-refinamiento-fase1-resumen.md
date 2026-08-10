# Antares — Resumen de la fase 1 de refinamiento (para evaluación posterior)

**Estado:** registro de discusión, no una decisión ni un plan de implementación. Nada de
lo descrito acá está construido; el único artefacto tocado es una anotación dentro de
[docs/antares-advisor-portability-guide.md](antares-advisor-portability-guide.md) (§10,
pregunta 1).

**Propósito de este documento.** [antares-advisor-portability-guide.md](antares-advisor-portability-guide.md)
llegó como artefacto de conocimiento con diez preguntas abiertas en su §10, cada una
explícitamente dejada para que "el agente que adapta" la resuelva contra el código real
de este repo. Esta fase 1 tomó **una sola** de esas diez preguntas y la trabajó hasta
tener una dirección candidata concreta — sin implementarla, sin cerrarla formalmente.
Este documento existe para que esa dirección pueda evaluarse después (por vos, o por
otra sesión) sin tener que reconstruir la discusión desde la guía completa.

---

## 1. Alcance de esta fase

Se trabajó exclusivamente la **pregunta 1 de §10**: *"¿Quién provee el CWE (I2)?"*. Las
otras nueve preguntas de §10 — disposición cuando el revisor puede ser un modelo (#2),
qué stage boundaries son los touchpoints (#3), de dónde sale el snapshot navegable (#4),
ejecución propia vs. delegada al CLI (#5), dónde vive el artefacto (#6), retención de
trazas (#7), presupuesto de residencia (#8), qué lenguajes soporta la clausura (#9), si el
índice de retrieval puede informar la selección de seeds (#10) — **no se tocaron**. Siguen
exactamente como las dejó la guía original.

La razón para arrancar por la #1 y no por otra: es la que determina si el mecanismo
completo es siquiera legítimo bajo I2 ("el CWE viene de afuera del modelo, nunca de un
sweep genérico"). Sin resolver esto, ninguna otra pregunta de diseño tiene sentido —
estarías diseñando cómo ejecutar algo que todavía no sabés si está justificado disparar.

---

## 2. La pregunta

> Este pipeline no tiene humano en el loop por request. Un CWE propuesto por un modelo
> viola I2 *a menos que* esté restringido a elegir de una watchlist curada por humanos.
> ¿Un stage propone-desde-watchlist, o solo dispara la watchlist y las corridas
> hypothesis-driven son invocadas por un operador?

El problema real detrás de la pregunta: I2 exige que el CWE "venga de afuera del
modelo", pero este pipeline —a diferencia del repo fuente (`dubbridge`)— no tiene un
punto de aprobación humana síncrona en el camino normal de una request.

---

## 3. Dirección candidata discutida

**No es una watchlist.** Es tratar este motor como una caja negra que un llamador
no-humano (el ejemplo concreto que se usó: Claude Code actuando sobre un pedido real de
un humano) comisiona al estilo consultora: el llamador declara qué CWEs quiere
verificados **como parte de la request misma**, de la misma manera que
`--output-contract` ya es hoy un parámetro que aporta el llamador.

Esto cae en la rama **"hypothesis-driven, operator-invoked"** de la pregunta original,
no en la rama de watchlist. En términos de la tabla de transferencia (§4 de la guía), la
fuente del CWE es la **L1 task-specific hypothesis binding** (marcada `COPY` en esa
tabla) — no una etapa nueva de "proponer CWE" agregada al pipeline.

### Por qué satisface I2

I2 distingue explícitamente entre "hipótesis de seguridad humana/de agente" y "sweep
genérico para satisfacer ceremonia". La calificación de "humano/agente" no exige que el
humano esté sincrónicamente presente en esta request puntual — exige que el CWE esté
atado a un pedido real, no fabricado por un modelo interno del pipeline para llenar un
casillero. Un caller no-humano actuando sobre un pedido humano real (Claude Code
resolviendo una tarea que un humano le dio) cae del lado correcto de esa distinción: la
justificación no la inventa el pipeline, la trae quien hace la request.

**Condición no negociable para que esto siga siendo cierto:** una lista desnuda de
CWE-ids no alcanza como input. Cada entrada necesita un **rationale provisto por el
llamador** (por qué ese CWE importa para esta request puntual) — sin eso, el mecanismo
degrada silenciosamente en exactamente el sweep no justificado que I2 existe para
prevenir. Esto no es un detalle de implementación, es la bisagra que hace que la
dirección sea legítima o no.

**Coexistencia, no reemplazo.** Esta dirección no reemplaza una watchlist curada si en
algún momento se construye una — la tabla de transferencia contempla ambas fuentes L1
(entrada de watchlist vs. hipótesis del llamador) como coexistentes, no mutuamente
excluyentes.

---

## 4. Boceto de forma (no implementado)

Únicamente para fijar cómo se vería, sin comprometer nombres de flags ni de campos:

```
python main.py ask --json \
  --cwe-check "CWE-89:queries build SQL from the new user-facing filter param" \
  --cwe-check "CWE-306:new endpoint has no auth check in the diff" \
  "<query>"
```

- Un `--cwe-check` por CWE, forma `CWE-ID:rationale`; el rationale es obligatorio, no
  opcional — es la parte que hace cumplir I2.
- Se acumulan en una lista, viajan en la request igual que `output_contract` hoy.
- El orchestrator los pasaría tal cual al advisor — ningún LLM del pipeline los ve antes
  de que exista un resultado sobre el que evaluarlos; el QA Auditor, si llega a
  interactuar con esto, solo recibiría el resultado ya calculado como contexto (mismo
  patrón que se había conversado para un escenario de watchlist).
- En el recibo: algo en la línea de `outcome.security_triage: {ran, requested: [{cwe_id,
  rationale}], findings: [...], degraded: bool}` — mismo patrón `ran: true|false` que ya
  usan `rag`/`design_gate`/`implementation_check` en `core/receipt.py`.
- Convive con una watchlist futura sin pisarla: si algún día existe
  `config/cwe_watchlist.yaml`, esas entradas dispararían aparte, con su propio `ran` en
  el recibo, sin fusionarse con las declaradas por el llamador.

Nada de esto está en código. Es forma discutida para fijar la idea, no una interfaz
comprometida.

---

## 5. Lo que esta fase NO resuelve — y por qué bloquea todo lo demás

La pregunta 1 tiene una respuesta candidata razonable. La pregunta **4** ("¿de dónde
sale el snapshot?") no se tocó, y es la que realmente bloquea que cualquiera de esto se
pueda construir:

Antares necesita un **árbol de directorio real** contra el cual correr `grep`/`find`/`cat`.
El Implementer de este pipeline produce código como **texto dentro de un recibo**, no
necesariamente un árbol materializado en disco. Hasta que se decida si el touchpoint
post-implementación materializa un árbol temporal, escanea solo el árbol fuente ya
ingerido (baseline pre-cambio), o directamente no corre en ese seam — el boceto de la
sección 4 no tiene sobre qué ejecutarse.

**Conclusión de esta fase:** la pregunta 1 quedó con una dirección candidata razonable
y documentada; el diseño como un todo sigue bloqueado por la pregunta 4, no por la 1.

---

## 6. Próximos pasos sugeridos (para fase 2, si se decide continuar)

1. Resolver la pregunta 4 (fuente del snapshot) — es el bloqueante real.
2. Recién con eso resuelto, decidir la forma concreta de `outcome.security_triage` y si
   el resultado vive dentro del recibo existente o al lado (pregunta 6).
3. Definir qué pasa si `--cwe-check` se declara pero el touchpoint elegido en la
   pregunta 4 no tiene snapshot disponible en esa corrida — degradado explícito, igual
   que cualquier otro `ran: false` del recibo.
4. Recién después de eso tiene sentido tocar las preguntas 2 (disposición), 3
   (touchpoints), 5 (ejecución propia vs. CLI) — dependen de que 4 esté resuelta.

## 7. Estado de implementación al cierre de esta fase

- Cero cambios de código relacionados a Antares en este repo.
- Un único archivo tocado: [antares-advisor-portability-guide.md](antares-advisor-portability-guide.md),
  §10 pregunta 1, anotado como "discutido pero no decidido ni implementado".
- Este documento es el primer artefacto que existe fuera de esa anotación inline.
