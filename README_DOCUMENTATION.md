# 🧠 LocalDevEngine: Documentation & Architecture (Part 1)

Welcome to the **LocalDevEngine** official documentation. This project implements a **Stacked Intelligence Architecture**, designed to provide sophisticated AI-driven development workflows on local hardware by orchestrating specialized models in a hierarchical, self-correcting pipeline.

## 🏗️ Architecture Overview

Unlike standard LLM interfaces that use a single model for all tasks, `LocalDevEngine` uses an **Orchestrator (Manager)** that delegates specific parts of the software development lifecycle to different models based on their strengths (**Philosophy: The right tool for the right job**). This approach optimizes VRAM usage and maximizes reasoning quality.

### 📊 Model Hierarchy & Responsibilities

| Layer | Role | Recommended Model | Primary Strength | Responsibility |
| :--- | :--- | :--- | :--- | :---|
| **Layer 0** | **Memory (RAG)** | `nomic-embed-text` | Semantic Embedding | Providing local codebase context to the stack. |
| **Layer 1** | **Router** | `phi-3-mini` | Fast Classification | Determining if a task is simple or requires full orchestration. |
| **Layer 2** | **Manager** | `gemma4:26b-it` | Orchestration / Logic | Coordinating transitions, state management, and tool calling. |
| **Layer 3** | **Architect** | `qwen3.6:27b` | Deep Reasoning | Creating structural plans and technical blueprints (Thinking Mode). |
| **Layer 4** | **Implementer** | `qwen3.6:35b-a3b` | High-Fidelity Coding | Transforming architectural plans into production-ready code. |
| **Layer 5** | **QA Auditor** | `gemma4 / qwen` | Critical Verification | Comparing implementation vs requirements/plan for compliance. |
| **Continuous**| **Copilot** | `granite-code:8b` | Latency / Syntax | Real-time autocomplete and syntax corrections. |

---
*(Part 1 complete)*