# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

LocalDevEngine (internal package name `dev_orchestrator`) is a "Stacked Intelligence Architecture": a local, Ollama-backed orchestrator that routes a coding task through a pipeline of specialized models instead of using one model for everything, to optimize VRAM usage and reasoning quality per stage.

See [README_DOCUMENTATION.md](README_DOCUMENTATION.md) for the original model-hierarchy table. The doc is still explicitly partial ("Part 1 complete") and its model names/tags are a simplified sketch — `config/settings.yaml` is authoritative for real Ollama tags when the two disagree (see Config below).

## Current state: runnable, verified end-to-end

`python main.py ask "<query>"` and `python main.py chat` work against a local Ollama server. The full pipeline (Router → RAG → Manager → Architect↔QA design gate → Implementer↔QA implementation check) has been run live to completion multiple times, including a full smoke test that closed with `Implementation check attempt 3: APPROVED`.

What got this from scaffold to runnable, across 11 commits on `main` (`git log --oneline`):
- Flat imports fixed (no `dev_orchestrator.*` prefix — the repo root packages import directly), `__init__.py` added to `core/`, `memory/`, `models/`, `prompts/`, and `main.py`'s hardcoded config path corrected to `config/settings.yaml`.
- `memory/local_memory.py`'s `self.metadata`/`embedding.size` bugs are gone — the store was rewritten with atomic `.npy`+`.json` writes (temp file + `os.replace`), shape/dimension validation on load, float32, and normalized vectors so `search()`'s `np.dot` really is cosine similarity.
- `requirements.txt` exists (`httpx`, `numpy`, `PyYAML`).
- The RAG/ingestion pipeline was rebuilt from scratch per `/Users/matias/.claude/plans/streamed-dancing-mango.md` (fully complete): structural chunking (`core/chunking.py`), `/api/embed` with `truncate:false` instead of the silently-truncating old endpoint, per-source replace instead of duplicate-on-reingest, and a retrieval budget (`top_k`, `min_score`, `max_context_chars`, `max_chunks_per_source`) enforced in the orchestrator.
- Router and Manager are now actually wired into `run_complex_task` (see Request flow below) — they were dead code in the original scaffold.
- A QA Auditor stage exists at two gates: pre-implementation (design gate) and post-implementation (implementation check) — the original scaffold had none.

Known gaps, in case you're asked to continue this project:
- **No automated tests.** Verification so far has been live smoke tests against the real Ollama server plus inline one-off sanity scripts (e.g. for `_split_plan_sections`), not a pytest suite — a deliberate choice for this stage of the project, not an oversight.
- **No lint/build tooling configured.**
- **QA stages never stream.** `on_chunk` is wired for every model-output stage the user actually reads (fast path, design plan/revision, implementation) but deliberately not for `qa_auditor` calls, since only the parsed VERDICT/FEEDBACK is surfaced, never the raw QA response text.
- **Etapa (d)** (reporting truncated/reviewed sections in `main.py`'s output) was evaluated and explicitly deprioritized — see git log message on `dedd185` and prior conversation — not started.
- `run_simple_query` in `core/orchestrator.py` (if still present) is dead code, not on the `main.py` call path — the real fast path is the `FAST_PATH_CATEGORIES` branch inside `run_complex_task`.

## Architecture

**Design patterns**: `models/base.py` defines `BaseModel` as an ABC (Strategy pattern) so providers other than Ollama could be added later, now including a `generate_stream()` abstract method alongside `generate()`. `models/factory.py`'s `ModelFactory` (Factory pattern) reads `config/settings.yaml` and builds a role-specific `OllamaModel` instance on demand via `create_role_model(role_name)`. `memory/base.py` similarly defines `BaseMemory` as an ABC so the local NumPy vector store (`memory/local_memory.py`) could be swapped for a real vector DB; its `add_text` signature now matches the real implementation (`text, metadata, embedding`).

**Request flow** (`core/orchestrator.py: Orchestrator.run_complex_task`):
1. **Router** (`_get_router_decision`) classifies the query into `SIMPLE_TASK` / `COMPLEX_ARCHITECTURE` / `CODING_REQUEST` / `ERROR_REACTION`. `SIMPLE_TASK` and `ERROR_REACTION` take a **fast path**: a single Manager call answers directly, skipping RAG/Architect/Implementer/QA entirely.
2. For the full pipeline: **RAG** (`_build_rag_context`) embeds the query via `EmbeddingService` (`/api/embed`, `truncate:false`), retrieves top-k chunks from `LocalVectorMemory` (cosine similarity), caps chunks per source, attributes each chunk with its file path + score, and truncates to `max_context_chars`. Every retrieval logs `chunks_retrieved`/`chunks_used`/`context_chars`/scores.
3. **Manager** (`get_manager_breakdown_template`) turns the goal + RAG context into a short step outline, appended to the context budget.
4. **Architect** produces a plan via `get_architect_thinking_template`, which now forces exactly four `## <Name>` sections (`PromptRegistry.SECTION_NAMES`: Data Model, API/Interface, Error Handling, Dependencies/Integration). `_split_plan_sections()` parses them back out.
   - If parsing succeeds: a **sectioned design gate** reviews and — if rejected — regenerates *one section at a time* (`get_section_review_template`/`get_section_revision_template`), each pass seeing the full plan for cross-section consistency. Verified live to regenerate a rejected section in ~29-73s vs. 50-150s for a full-plan regen.
   - If the model doesn't follow the format (returns `None`): falls back unchanged to the original **monolithic design gate** (`get_design_review_template`/`get_architect_revision_template`), looped up to `max_qa_iterations`.
5. **Implementer** (`get_implementer_task_template`) produces code from the approved plan + context, then a post-implementation QA check (`get_qa_review_template`, no longer takes an unused `context` param) can send it back through an Architect revision → re-implementation loop, also up to `max_qa_iterations`.
6. Returns `{"plan", "implementation", "fast_path", "qa_approved", "qa_feedback", "request_id", "trace"}` — `trace` is a full per-stage audit list (role, model, attempt, verdict, duration_ms), useful for a caller embedding this as a library without parsing logs.

**Streaming**: every stage whose raw output the user actually sees (fast path, design plan/revision — sectioned, monolithic, and post-implementation — and implementation) accepts an `on_chunk(text, stage, attempt)` callback threaded through `_call_model` → `model.generate_stream()` (NDJSON over Ollama's `stream:true`). `main.py`'s `_make_stage_printer()` uses this to print colored stage headers (keyed by `(stage, attempt)` since a stage like `design_revision` can run multiple times) and stream text live instead of waiting for the full response.

**Ingestion** (`core/ingestor.py: DataIngestor.ingest_directory` + `core/chunking.py: chunk_file`): walks a directory (exact-name dir pruning, not substring — `.git` no longer matches `mi.github/`), sorted for reproducible ordering. Each matching file is split by structure (`.py` on `def`/`class`/`@` at column 0, `.md` on headers, else paragraph breaks) into chunks capped at `max_chunk_chars`, with a two-stage fallback (line windows → character windows) for oversized units. Chunks are embedded in batches and written via `LocalVectorMemory.replace_source` — embed-then-replace, not remove-then-embed, so a mid-ingest crash can't leave a source's old chunks deleted with nothing to replace them. Oversized embed batches bisect to find the offending chunk. Returns an `IngestSummary` with indexed/skipped/failed counts and per-failure reasons — no more silently-inflated file counts.

**Config** (`config/settings.yaml`): single source of truth for the Ollama model tag per role, retrieval budget, and storage paths. Current mapping: `router`→`phi3:mini`, `manager`→`gemma4:26b-a4b-it-qat`, `architect`→`qwen3.6:35b-a3b` (`think: false`), `implementer`→`qwen3.6:35b-a3b` (`think: false`), `qa_auditor`→`gemma4:26b-a4b-it-qat` (same tag as manager — an MoE swap chosen because it respects the VERDICT/FEEDBACK format far faster than the dense model it replaced; see inline comments in the YAML for the measured numbers behind each model choice). These differ from the README's simplified names (e.g. `qwen3.6:27b`, `gemma4:26b-it`) — trust `settings.yaml`.

All Ollama calls assume a local server at `http://localhost:11434/api` (hardcoded default in `EmbeddingService`, `ModelFactory`, `OllamaModel`). Ollama's single-slot (`-np 1`) config means role-swapping between models forces an unload+reload, which is a real latency factor independent of any of the above.
