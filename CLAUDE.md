# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

LocalDevEngine (internal package name `dev_orchestrator`) is a "Stacked Intelligence Architecture": a local, Ollama-backed orchestrator that routes a coding task through a pipeline of specialized models instead of using one model for everything, to optimize VRAM usage and reasoning quality per stage.

See [README_DOCUMENTATION.md](README_DOCUMENTATION.md) for the model-hierarchy table (Router → Manager → Architect → Implementer → QA Auditor, plus a Copilot autocomplete layer and a `nomic-embed-text` RAG layer). The doc is explicitly partial ("Part 1 complete") — only the architecture overview exists, no install/usage docs.

## Current state: not runnable

This is a scaffold, not a working system. Do not assume `python main.py ...` works — it currently fails on the first import. Known blocking issues, in case you're asked to fix or continue this project:

- **Every module imports from a `dev_orchestrator.*` package that does not exist on disk.** e.g. `core/orchestrator.py` does `from dev_orchestrator.models.factory import ModelFactory`, but the actual packages live at the repo root (`core/`, `models/`, `memory/`, `prompts/`, `config/`) with no `dev_orchestrator/` wrapper directory anywhere.
- **No `__init__.py` in any package directory**, so even fixing the import prefix isn't enough to make these regular packages.
- `main.py` hardcodes `config_path = "dev_orchestrator/config/settings.yaml"` — same nonexistent-path problem.
- `memory/local_memory.py`: `add_text()` reads `embedding.size` (the raw `List[float]` argument, which has no `.size`) instead of `emb.size` (the NumPy-converted array) — crashes on the very first indexed file.
- `memory/local_memory.py`: `search()` reads `self.metadata`, but the instance attribute set in `__init__`/`_load` is `self._metadata` — `AttributeError` as soon as anything has been indexed.
- `core/ingestor.py` `_process_file()` has garbled dead code referencing a nonexistent `os.pathed_basename` / `os.path.aped_basename`; the `hasattr` guard is always false so it silently falls through to `os.path.basename`, but it should just be simplified.
- No dependency manifest (`requirements.txt`/`pyproject.toml`) despite depending on `httpx`, `numpy`, and `PyYAML`.
- No tests, no `.git` repo, no lint/build tooling configured anywhere in the tree.

If asked to make this runnable: fix the import prefix (either physically create/rename to a `dev_orchestrator` root package, or strip the prefix from every import to match the actual flat layout — the latter is less invasive), add `__init__.py` files, fix the two `local_memory.py` bugs above, and add a dependency manifest.

## Architecture

**Design patterns**: `models/base.py` defines `BaseModel` as an ABC (Strategy pattern) so providers other than Ollama could be added later; `models/factory.py`'s `ModelFactory` (Factory pattern) reads `config/settings.yaml` and builds a role-specific `OllamaModel` instance on demand via `create_role_model(role_name)`. `memory/base.py` similarly defines `BaseMemory` as an ABC so the local NumPy vector store (`memory/local_memory.py`) could be swapped for a real vector DB.

**Request flow** (`core/orchestrator.py: Orchestrator.run_complex_task`):
1. Embed the user query (`memory/embeddings.py: EmbeddingService`, calls Ollama's `/api/embeddings`) and retrieve top-k similar chunks from `LocalVectorMemory` (cosine similarity over an in-memory NumPy matrix persisted to `.vector_store/embeddings.npy` + `metadata.json`).
2. Instantiate role models on demand through `ModelFactory` — one `OllamaModel` per pipeline stage, each hitting Ollama's `/api/generate` (non-chat endpoint, no system-prompt wiring yet — see `OllamaModel.generate`).
3. Build stage prompts via `prompts/specialized_prompts.py: PromptRegistry` (per-role system prompts in `get_system_prompt`, plus dedicated templates `get_architect_thinking_template` / `get_implementer_task_template`).
4. Architect produces a plan from (context + goal); Implementer produces code from (plan + context). Both are returned to the caller as `{"plan": ..., "implementation": ...}`.

**Gaps between the documented design and the code**: the Router (`_get_router_decision`) and Manager stages are implemented but never actually invoked/consumed inside `run_complex_task` — the pipeline unconditionally goes straight to Architect → Implementer, there's no branching on task complexity, and there's no QA Auditor stage at all despite it being documented as Layer 5.

**Ingestion** (`core/ingestor.py: DataIngestor.ingest_directory`): walks a directory (skipping `node_modules`, `.git`, `__pycache__`, `venv`), and for each file matching `.py/.js/.ts/.md/.sql/.html`, embeds the *entire file content as a single chunk* (no semantic chunking yet — noted as a known simplification in the code) and stores it via `LocalVectorMemory.add_text`.

**Config** (`config/settings.yaml`): single source of truth for which Ollama model tag backs each role (`router`, `manager`, `architect`, `implementer`, `copilot`), plus the embedding model/dimension and storage paths. Model tags here (e.g. `gemma4:26b-a4b-it-qat`, `phi-3:mini`) are the real Ollama tags to use, and differ slightly from the simplified names in the README table (e.g. `gemma4:26b-it`, `phi-3-mini`) — prefer `settings.yaml` as authoritative when the two disagree.

All Ollama calls assume a local server at `http://localhost:11434/api` (hardcoded default in `EmbeddingService`, `ModelFactory`, `OllamaModel`).
