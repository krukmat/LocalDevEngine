# T9/T10 — smoke test end-to-end y checklist de verificación manual (cerrado)

**Fecha:** 2026-08-11
**Depende de:** T1–T8 completas (`docs/plan-security-advisor-antares.md`).
**Corridas crudas:** [tests/results/security_triage_t9/](../tests/results/security_triage_t9/)
(tres receipts + stderr logs de `python main.py ask --json --output-contract
fenix-tagged-file --cwe-check ...` contra Ollama + Antares reales, sin mocks).

## T9 — smoke test end-to-end

Criterio fijado en el plan (§Verificación, punto 3): con `antares` instalado,
`outcome.security_triage.ran == true`, receipt JSON válido con
`schema_version: "1.2"`, sin directorios temporales al terminar.

Tres corridas reales, no forzadas a mano:

1. **`attempt1_timeout_receipt.json`** — `status: "timeout"`. El pipeline nunca
   llegó a la implementación: el design gate entró en revisiones sucesivas
   (`API/Interface` y `Error Handling` llegaron a intento 3 con
   `NEEDS_REVISION`) y agotó `max_run_seconds=1500`. `outcome` queda `{}` —
   `security_triage` nunca se menciona, porque el bloque de triage vive
   estrictamente después de que `_run_pipeline_body` retorna
   (`core/orchestrator.py` ~L670), y acá nunca retornó. No es un fallo de
   Antares ni algo que T9/T10 deba cubrir; se conserva como evidencia de que
   un timeout de pipeline no dejó el receipt en un estado inconsistente.
   **Nota aparte, no perseguida acá:** el trace muestra intento 3 en dos
   secciones pese a `config_fingerprint.max_qa_iterations: 2` — posible
   desvío del loop de QA por sección, ajeno al alcance de este documento.

2. **`attempt2_fastpath_receipt.json`** — `status: "completed"`. El Router
   clasificó una query con firma completa como `SIMPLE_TASK` y tomó el fast
   path (36s). Esto ejercitó orgánicamente la celda "fast-path" de la matriz
   de estados: `security_triage = {ran: false, terminal_state:
   "snapshot-unavailable", degraded: true, reason: "fast-path"}`, tal como
   está codificado en `orchestrator.py` L484-489.

3. **`attempt3_success_receipt.json`** — `status: "completed"`,
   `schema_version: "1.2"`, `security_triage.ran == true`,
   `terminal_state: "completed"`, `degraded: false`. Un finding: CWE-89 sobre
   `users_repository.py`, pese a que la implementación usa el patrón
   parametrizado correcto (`cursor.execute("... WHERE id = ?", (user_id,))`)
   — casi con certeza un falso positivo de Antares (esperable dado el F1
   0.209 documentado en `antares-advisor-portability-guide.md`). El finding
   quedó con `review_status: "pending"`, sin afectar `qa_approved` del
   pipeline ni el `status` del receipt — es exactamente el caso para el que
   existen I1/I3/I10 (advisory-only, disposición humana obligatoria,
   disposición ≠ ground truth).

Verificación de "sin directorios temporales": búsqueda en `/tmp` y
`/private/var/folders` tras las tres corridas, sin ningún `snapshot_dir` ni
`antares-data` colgado — `materialize_implementation` limpia correctamente al
salir del context manager incluso en el caso timeout (T8 ya cubre esto por
unidad; acá se confirmó en vivo).

**T9: cerrado, criterio cumplido.**

## T10 — checklist de verificación manual

Los tres puntos del plan (§Verificación, puntos 3-6, más el grep de I5),
verificados el 2026-08-11:

1. **I5 (no shell)** — grep de `shell=True`/`os.system`/`create_subprocess_shell`
   sobre `context/`, `core/`, `main.py`: único hit es `main.py` (comando
   `clear` del REPL, string literal hardcodeado, preexistente, sin relación
   con Antares ni con input del modelo). `context/antares/invoke.py` usa
   `asyncio.create_subprocess_exec` con argv explícito (L131) — cumple I5 por
   construcción, sin excepciones.

2. **Matriz de estados del receipt** — cubierta en dos capas:
   - A nivel unitario (`tests/run_antares_offline.py`, corrido el
     2026-08-11 con el venv del proyecto): 47/47 casos pasan, incluyendo las
     5 celdas (`not-requested`, `fast-path`, `artifact-missing`, éxito con/sin
     findings, degradado por cada `terminal_state`).
   - A nivel end-to-end (T9, arriba): confirmación orgánica real de
     `fast-path` y de éxito-con-findings contra Ollama + Antares reales, no
     solo contra el `FakeOrchestrator`.

3. **`status: "completed"` con binario ausente** — confirmado por lectura de
   código (el bloque de triage en `run_complex_task`, L670-727, corre en su
   propio `try/except` después de que `status="completed"` ya está fijado en
   el `build_receipt` final sin leer nada del resultado de la triage — no
   existe camino de código para que una falla de Antares cambie `status`) y
   por el test `"orch: binary-missing never raises (I1)"`. **No** se ejecutó
   una corrida end-to-end real con `antares` fuera del PATH — la garantía es
   estructural (I1 por construcción), no observacional, y se documenta como
   tal en vez de sobre-afirmar cobertura que no se corrió.

4. **Contrato del receipt** (title/CWE/path relativo/`review_status:
   "pending"` en cada finding) — confirmado en `attempt3_success_receipt.json`
   punto por punto y en el test `"orch: success findings normalized"`.

**T10: cerrado.** Única salvedad explícita: el punto 3 se apoya en garantía
estructural + test unitario, no en una corrida en vivo con el binario
ausente — suficiente dado que el código no tiene ninguna rama que pueda
violarlo, pero se deja registrado para no confundir "verificado por
construcción" con "observado en producción".
