"""Router and context-preparation stages for the orchestration pipeline."""
from typing import Any, Awaitable, Callable, Dict, List, Tuple

from context.schema import render_schema_block, select_tables
from memory.embeddings import EmbeddingTooLargeError

from core.pipeline.base import PipelineStage
from core.pipeline.context import PipelineContext


ModelCaller = Callable[..., Awaitable[Tuple[str, Dict[str, Any]]]]


class RouterStage(PipelineStage):
    """Classify a request, preserving the pipeline's conservative fallback."""

    def __init__(self, *, factory: Any, call_model: ModelCaller, categories: Tuple[str, ...],
                 fast_path_categories: Tuple[str, ...], logger: Any):
        self.factory = factory
        self.call_model = call_model
        self.categories = categories
        self.fast_path_categories = fast_path_categories
        self.logger = logger

    async def run(self, ctx: PipelineContext) -> None:
        if ctx.prior_breakdown is not None:
            ctx.decision = "COMPLEX_ARCHITECTURE"
            self.logger.info(
                "Macro-loop re-entry: skipping Router, forcing full pipeline",
                extra={"request_id": ctx.request_id, "stage": "routing"},
            )
            return

        router_model = self.factory.create_role_model("router")
        response, entry = await self.call_model(
            role="router", stage="routing", model=router_model,
            prompt=f"Classify this query: {ctx.user_query}", request_id=ctx.request_id,
        )
        response_upper = response.strip().upper()
        decision = next((c for c in self.categories if response_upper.startswith(c)), None)
        if decision is None:
            hits = sorted(
                (c in self.fast_path_categories, response_upper.find(c), c)
                for c in self.categories if c in response_upper
            )
            decision = hits[0][2] if hits else None
        if decision is None:
            self.logger.warning(
                "Unrecognized router decision %r — defaulting to COMPLEX_ARCHITECTURE",
                response_upper[:80], extra={"request_id": ctx.request_id, "stage": "routing"},
            )
            decision = "COMPLEX_ARCHITECTURE"
        entry["decision"] = decision
        ctx.trace.append(entry)
        self.logger.info(
            "Router decision: %s", decision,
            extra={"request_id": ctx.request_id, "stage": "routing"},
        )
        ctx.decision = decision


class SchemaContextStage(PipelineStage):
    """Build the deterministic, caller-supplied schema context block."""

    def __init__(self, *, config: Dict[str, Any], logger: Any):
        self.config = config
        self.logger = logger

    async def run(self, ctx: PipelineContext) -> None:
        if ctx.schema_snapshot is None:
            ctx.outcomes.record("schema_grounding", {"ran": False})
            return
        cfg = self.config.get("schema_grounding", {})
        selection = select_tables(
            ctx.schema_snapshot, ctx.user_query,
            max_tables=cfg.get("max_tables", 12),
            fk_expansion_depth=cfg.get("fk_expansion_depth", 1),
            include_all_if_no_match=cfg.get("include_all_if_no_match", True),
        )
        schema_max_chars = cfg.get("max_chars", 4000)
        block, shown, dropped = render_schema_block(
            selection, ctx.schema_snapshot, max_chars=schema_max_chars,
        )
        ctx.schema_block = block
        ctx.schema_stats = {
            "ran": True, "source": ctx.schema_snapshot.source,
            "dialect": ctx.schema_snapshot.dialect,
            "tables_in_snapshot": len(ctx.schema_snapshot.tables),
            "tables_shown": shown,
            "tables_omitted": selection.omitted + dropped,
            "matched": selection.matched, "related_via_fk": selection.related,
            "strategy": selection.strategy,
            "degraded": selection.degraded or bool(dropped),
            "reason": selection.reason or ("budget_dropped_tables" if dropped else None),
            "block_chars": len(block), "max_chars": schema_max_chars,
            "block_over_budget": len(block) > schema_max_chars,
            "conformance_check": {"ran": False},
        }
        ctx.outcomes.record("schema_grounding", ctx.schema_stats)
        self.logger.info(
            "Schema grounding: strategy=%s shown=%d/%d chars=%d",
            selection.strategy, len(shown), len(ctx.schema_snapshot.tables), len(block),
            extra={"request_id": ctx.request_id, "stage": "schema_grounding"},
        )


class RagContextStage(PipelineStage):
    """Retrieve and format the untrimmed RAG pieces for the shared budget."""

    def __init__(self, *, config: Dict[str, Any], memory: Any, embedder: Any, logger: Any):
        self.config = config
        self.memory = memory
        self.embedder = embedder
        self.logger = logger

    async def run(self, ctx: PipelineContext) -> None:
        retrieval_cfg = self.config.get("retrieval", {})
        top_k = retrieval_cfg.get("top_k", 5)
        min_score = retrieval_cfg.get("min_score", 0.0)
        max_chunks_per_source = retrieval_cfg.get("max_chunks_per_source", 2)
        self.logger.info("Searching local context", extra={"request_id": ctx.request_id, "stage": "rag"})
        try:
            query_vec = await self.embedder.get_embedding(ctx.user_query)
            relevant_chunks = self.memory.search(query_vec, top_k=top_k, min_score=min_score)
        except EmbeddingTooLargeError:
            self.logger.warning(
                "User query too large to embed — proceeding without RAG",
                extra={"request_id": ctx.request_id, "stage": "rag"},
            )
            relevant_chunks = []

        per_source_count: Dict[str, int] = {}
        pieces: List[Dict[str, Any]] = []
        for chunk in relevant_chunks:
            source = chunk.get("source", "?")
            if per_source_count.get(source, 0) >= max_chunks_per_source:
                continue
            per_source_count[source] = per_source_count.get(source, 0) + 1
            header = f"# {source} (score={chunk.get('score', 0):.3f})\n"
            pieces.append({"text": f"{header}{chunk['text']}\n", "source": source,
                           "score": chunk.get("score", 0)})
        scores = [round(c.get("score", 0), 3) for c in relevant_chunks]
        sources = sorted({p["source"] for p in pieces})
        self.logger.info(
            "RAG: chunks_retrieved=%d chunks_eligible=%d scores=%s",
            len(relevant_chunks), len(pieces), scores,
            extra={"request_id": ctx.request_id, "stage": "rag"},
        )
        ctx.rag_pieces = pieces
        ctx.rag_stats = {
            "ran": True, "chunks_retrieved": len(relevant_chunks),
            "chunks_eligible": len(pieces), "chunks_used": 0, "context_chars": 0,
            "scores": scores, "sources": sources,
        }
        ctx.outcomes.record("rag", ctx.rag_stats)


class ContextAssemblyStage(PipelineStage):
    """Apply the shared context budget before and after the Manager outline."""

    def __init__(self, *, config: Dict[str, Any], logger: Any):
        self.config = config
        self.logger = logger

    async def run(self, ctx: PipelineContext) -> None:
        retrieval_cfg = self.config.get("retrieval", {})
        max_total = retrieval_cfg.get("max_context_chars", 3000)
        reserve_chars = 0 if ctx.breakdown is not None else retrieval_cfg.get("breakdown_reserve_chars", 1200)
        blocks: List[str] = []
        used = 0
        stats = {
            "max_total_chars": max_total, "schema_chars": 0, "breakdown_chars": 0,
            "prior_report_chars": 0, "rag_chars": 0, "rag_pieces_included": 0,
            "rag_pieces_dropped": 0, "reserved_chars": reserve_chars, "over_budget": False,
        }
        if ctx.schema_block:
            blocks.append(ctx.schema_block)
            used += len(ctx.schema_block)
            stats["schema_chars"] = len(ctx.schema_block)
        if ctx.breakdown:
            piece = f"TASK BREAKDOWN (Manager):\n{ctx.breakdown}"
            blocks.append(piece)
            used += len(piece)
            stats["breakdown_chars"] = len(piece)
        if ctx.prior_report:
            piece = f"PREVIOUS ATTEMPT — MANAGER FINDINGS:\n{ctx.prior_report}"
            blocks.append(piece)
            used += len(piece)
            stats["prior_report_chars"] = len(piece)
        rag_budget = max_total - used - reserve_chars
        rag_parts: List[str] = []
        rag_chars = 0
        for piece in ctx.rag_pieces:
            text = piece["text"]
            if rag_chars + len(text) > rag_budget:
                stats["rag_pieces_dropped"] += 1
                continue
            rag_parts.append(text)
            rag_chars += len(text)
        stats["rag_chars"] = rag_chars
        stats["rag_pieces_included"] = len(rag_parts)
        rag_text = "".join(rag_parts) if rag_parts else "No existing local context found."
        blocks.insert(0 if not ctx.schema_block else 1,
                      f"PROJECT CONTEXT (retrieved, may be incomplete):\n{rag_text}")
        ctx.context = "\n\n".join(b for b in blocks if b)
        stats["used_chars"] = len(ctx.context)
        stats["over_budget"] = len(ctx.context) > max_total
        if stats["over_budget"]:
            self.logger.warning(
                "Context budget exceeded: %d chars assembled over max_context_chars=%d",
                len(ctx.context), max_total,
                extra={"request_id": ctx.request_id, "stage": "context_budget"},
            )
        self.logger.info(
            "Context assembled: total=%d/%d schema=%d breakdown=%d rag=%d (%d chunks, %d dropped)",
            stats["used_chars"], max_total, stats["schema_chars"], stats["breakdown_chars"],
            rag_chars, stats["rag_pieces_included"], stats["rag_pieces_dropped"],
            extra={"request_id": ctx.request_id, "stage": "context_budget"},
        )
        if ctx.breakdown is not None:
            ctx.budget_stats = stats
            ctx.rag_stats["chunks_used"] = stats["rag_pieces_included"]
            ctx.rag_stats["context_chars"] = stats["rag_chars"]
            ctx.outcomes.record("rag", ctx.rag_stats)
            ctx.outcomes.record("context_budget", {"ran": True, **ctx.budget_stats})
