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
| **Continuous**| **Copilot** | `granite-code:8b` | Latency / Syntax | Real-time autocomplete and syntax corrections. **Not yet wired into the CLI** — its system prompt exists in `prompts/specialized_prompts.py`, but no call site invokes it yet. |

Model tags are a config choice tuned to the hardware this was built on (`config/settings.yaml`), not a hard requirement — swap them for whatever fits your GPU. The pipeline shape (Router → RAG → Manager → Architect↔QA → Implementer↔QA) stays the same regardless.

---
*(See [CLAUDE.md](CLAUDE.md) for architecture internals, and [README.md](README.md) for quick start / usage.)*