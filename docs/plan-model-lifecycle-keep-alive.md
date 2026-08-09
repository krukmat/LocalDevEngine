# Plan: `OllamaModel.unload()` real + knob `keep_alive` por rol

## Contexto

Un análisis del pipeline confirmó que `models/factory.py: ModelFactory.create_role_model()` crea una instancia nueva de `OllamaModel` en cada una de las 7 llamadas del orchestrator, y que nada llama `.load()` o `.unload()` en ningún punto del flujo real. `OllamaModel.load()` (ollama_model.py) hacía un ping de 10s con `except Exception: pass`, nunca invocado desde el orchestrator. `OllamaModel.unload()` era literalmente `pass`. Ningún payload hacia Ollama fijaba `keep_alive`, así que el servidor usaba su propio default (~5min de retención por inactividad).

**Importante:** esto NO era la causa de la latencia de swap entre stages del pipeline (`phi3`→`gemma4`→`qwen3.6`→`gemma4`→`qwen3.6`→`gemma4`). Ese swap es reactivo — Ollama corre con un único slot (`-np 1`), así que cuando llega una request para un modelo distinto al cargado, Ollama descarga el actual y carga el nuevo por su cuenta, sin que el código de este repo lo ordene o pueda evitarlo. Y es intencional: el QA auditor comparte tag con el manager pero se mantiene independiente del architect/implementer a propósito (ver comentario de `qa_auditor` en `config/settings.yaml`) — esa independencia es lo que hace que el gate valga algo, y alternar de modelo en cada gate es el costo de esa propiedad, no un bug. Arreglar el swap en sí requeriría tuning del lado del servidor Ollama (`OLLAMA_MAX_LOADED_MODELS`, fuera de este repo) o debilitar esa independencia — ninguna de las dos es el objetivo acá.

Lo que sí era un bug de higiene: `load()`/`unload()` aparentaban controlar el ciclo de vida del modelo y no controlaban nada. Este plan cierra esa brecha de forma acotada — se evaluaron tres alcances (solo el knob de config; + auto-unload tras `ask`; + auto-unload en `ask` y cada turno de `chat`) y se eligió el más chico: **`unload()` real + knob `keep_alive`, sin wiring automático en el orchestrator.** `unload()` queda disponible como primitiva correcta para un futuro llamador — hoy nadie la invoca todavía, pero al menos ya no miente sobre lo que hace.

## Qué se construye

1. `OllamaModel.unload()` implementado de verdad, vía el mecanismo documentado de Ollama: una llamada a `/api/generate` con `keep_alive: 0` y sin `prompt` descarga el modelo de inmediato.
2. Un knob opcional `roles.<role>.keep_alive` en `config/settings.yaml`, mismo patrón que `think`/`temperature`: ausente = no se manda la key, aplica el default de Ollama. Threaded a través de `ModelFactory.create_role_model()` → `OllamaModel.__init__` → payload de `generate()`/`generate_stream()`.
3. `load()` recibe un fix barato de honestidad (angostar el `except Exception` a `except httpx.HTTPError`) pero sigue sin llamador — mismo gap preexistente que tenía `unload()`, no se le busca un caso de uso nuevo.

## Forma exacta del payload

Contrato real de `keep_alive` en Ollama:
- String de duración (Go duration): `"10m"`, `"1h30m"`, etc.
- Número plano: segundos.
- `0`: descarga el modelo inmediatamente después de esta respuesta.
- Negativo (ej. `-1`): mantenerlo cargado indefinidamente.
- Ausente: default del servidor (~5min de retención por inactividad).

El payload documentado por Ollama para forzar un unload inmediato es `{"model": "<name>", "keep_alive": 0}`, sin campo `prompt` — así quedó implementado en `OllamaModel.unload()`.

## Tareas (por archivo)

- **`models/ollama_model.py`**: import de `Union`; quinto parámetro `keep_alive` en `__init__`; condicional `if self.keep_alive is not None: payload["keep_alive"] = self.keep_alive` en `generate()` y `generate_stream()`; `unload()` reimplementado con el payload de arriba y manejo de errores idéntico a `generate()` (`ModelCallError`, nunca silencioso); `load()` angostado a `except httpx.HTTPError`.
- **`models/base.py`**: docstring de `unload()` documenta que puede levantar `ModelCallError`. Sin cambio de firma.
- **`models/factory.py`**: `create_role_model()` lee `role_cfg.get('keep_alive')` y lo pasa al constructor.
- **`config/settings.yaml`**: comentario preámbulo arriba de `roles:` documentando el knob y su contrato de valores. Ningún rol lo fija — fijar uno sería un cambio de comportamiento real, fuera de este alcance.
- **`CLAUDE.md`**: dos adiciones — en el párrafo de Config, mención del knob `keep_alive`; en la oración sobre el costo de swap del slot único, una segunda oración aclarando que el gap se angosta (primitivas reales, sin wiring) pero no se cierra.

## Verificación (manual, smoke-test — el repo no tiene suite automatizada)

1. `ollama list` — confirmar que el tag del rol a probar está descargado localmente.
2. `python main.py ask "<query trivial que rutee a ese rol>"` para cargarlo.
3. `curl -s localhost:11434/api/ps` (o `ollama ps`) — confirmar el modelo cargado con TTL (`Until`) ~5min (baseline sin `keep_alive`).
4. Probar `unload()` directo (no hay llamador en el orchestrator):
   ```
   python -c "import asyncio; from models.ollama_model import OllamaModel; \
   m = OllamaModel(name='<tag>', role='test', capabilities=[]); asyncio.run(m.unload())"
   ```
   Re-consultar `ollama ps` — el modelo debe desaparecer antes de los 5 minutos.
5. Probar el knob `keep_alive`: fijar temporalmente `keep_alive: "1m"` en un rol, correr una query para ese rol, chequear que `ollama ps` refleje ~1min en vez de ~5min. Revertir el cambio temporal — ningún rol debe quedar con `keep_alive` seteado al cerrar esta tarea.
6. Caso de falla: apuntar `api_url` a un puerto muerto y confirmar que `unload()` levanta `ModelCallError` en vez de colgarse o fallar en silencio.

## Fuera de alcance

- Sin cambios en `core/orchestrator.py`: ningún auto-unload al final de una corrida, ningún flag nuevo en `pipeline.*`, ningún tracking de "último modelo usado".
- Sin cambios en `core/receipt.py` / `config_fingerprint`: `build_config_fingerprint()` solo snapshotea `model_name` por rol hoy — `think`/`temperature` tampoco están fingerprinteados (gap preexistente, separado). `keep_alive` se suma a esa misma exclusión consciente, no se arregla acá.
- No resuelve la latencia de swap entre stages en sí (requiere tuning de `OLLAMA_MAX_LOADED_MODELS` del lado del servidor Ollama, fuera de este repo).
- Sin tests automatizados — decisión deliberada y preexistente del proyecto.
- `create_embedding_model()` en `models/factory.py` no se toca — `embeddings:` es un namespace de config separado de `roles:`. Ollama's `/api/embed` también acepta `keep_alive`, pero es una extensión futura, no parte de este alcance.
