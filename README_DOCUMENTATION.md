# 🧠 LocalDevEngine: Documentation & Architecture

Welcome to the **LocalDevEngine** official documentation. This project implements a **Stacked Intelligence Architecture**, providing sophisticated AI-driven development workflows on local hardware by orchestrating specialized models in a hierarchical, self-correcting pipeline.

For a shorter, general-audience overview with a flow diagram, see [README.md](README.md). This document is the detailed reference.

## 🏗️ Architecture Overview

Unlike standard LLM interfaces that use a single model for all tasks, `LocalDevEngine` uses an **Orchestrator** that delegates specific parts of the software development lifecycle to different models based on their strengths (**Philosophy: The right tool for the right job**). This approach optimizes VRAM usage and maximizes reasoning quality.

Every layer below except Copilot is implemented and wired into `core/orchestrator.py: Orchestrator.run_complex_task` — this is running architecture, not a proposal. See [CLAUDE.md](CLAUDE.md) for the full request-flow breakdown and implementation notes.

### 📊 Model Hierarchy & Responsibilities

| Layer | Role | Model Tag (`config/settings.yaml`) | Primary Strength | Responsibility |
| :--- | :--- | :--- | :--- | :---|
| **Layer 0** | **Memory (RAG)** | `nomic-embed-text:latest` | Semantic Embedding | Providing local codebase context to the stack. |
| **Layer 1** | **Router** | `phi3:mini` | Fast Classification | Determining if a task is simple or requires full orchestration. |
| **Layer 2** | **Manager** | `gemma4:26b-a4b-it-qat` | Orchestration / Logic | Turning a goal into an ordered step outline for the Architect — or, for simple questions and error reactions, answering directly on the Router's fast path (see [README.md](README.md)'s diagram). |
| **Layer 3** | **Architect** | `qwen3.6:35b-a3b` | Deep Reasoning | Creating structural plans and technical blueprints, phased by section (Data Model, API/Interface, Error Handling, Dependencies/Integration). |
| **Layer 4** | **Implementer** | `qwen3.6:35b-a3b` | High-Fidelity Coding | Transforming architectural plans into production-ready code. |
| **Layer 5** | **QA Auditor** | `gemma4:26b-a4b-it-qat` | Critical Verification | Gating the design *before* implementation, then reviewing the implementation against the approved plan. Shares its model tag with the Manager — chosen because it reliably follows the strict VERDICT/FEEDBACK format an auditor needs, while staying an independent pass from the Architect/Implementer. |
| **Layer 6** | **Manager (closing report)** | `gemma4:26b-a4b-it-qat` | Self-audit | After QA approves the implementation, the Manager compares the final plan/code against its *own* original outline and classifies each step as COVERED / ADAPTED / DROPPED / ADDED, rolling up to a `DEVIATION: NONE / JUSTIFIED / UNEXPLAINED` verdict. Toggleable via `pipeline.closing_report`. See [docs/plan-macro-loop-manager-hitl.md](docs/plan-macro-loop-manager-hitl.md). |
| **Continuous**| **Copilot** | `granite-code:8b` | Latency / Syntax | Real-time autocomplete and syntax corrections. **Not yet wired into the CLI** — its system prompt exists in `prompts/specialized_prompts.py`, but no call site invokes it yet. |

### 🔁 Human-gated macro-loop

An `UNEXPLAINED`/`UNKNOWN` closing-report deviation — or QA failing to approve after `max_qa_iterations` — doesn't retry automatically. In the interactive `chat` REPL (never the scriptable `ask` command, which must stay non-blocking), it offers a human-confirmed re-run of the **entire pipeline**, with the closing report folded into the RAG context as prior-attempt feedback. The re-run reuses the original Manager outline and skips the Router (re-classifying risks a fast-path misroute that would discard the whole first attempt), so the second closing report stays comparable to the first. Capped at `pipeline.max_macro_iterations` extra passes regardless of what the human confirms. See `_maybe_offer_macro_rerun` in `main.py` and `core/orchestrator.py: Orchestrator.run_complex_task`'s `prior_breakdown`/`prior_report`/`macro_iteration` parameters.

**Caveat:** this was built without running the empirical gate the design plan itself calls for (4 real queries checked for a genuine `DROPPED` case before deciding the macro-loop was worth building) — an explicit scope call, documented in [CLAUDE.md](CLAUDE.md), not an oversight.

Model tags are a config choice tuned to the hardware this was built on (`config/settings.yaml`), not a hard requirement — swap them for whatever fits your GPU. The pipeline shape (Router → RAG → Manager → Architect↔QA → Implementer↔QA) stays the same regardless.

---
*(See [CLAUDE.md](CLAUDE.md) for architecture internals, and [README.md](README.md) for quick start / usage.)*