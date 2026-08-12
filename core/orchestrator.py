import asyncio
import logging
import re
import time
import uuid
from typing import Callable, Optional, List, Dict, Any, Tuple
import yaml
import os

from models.base import ModelCallError
from models.factory import ModelFactory
from memory.embeddings import EmbeddingService, EmbeddingTooLargeError
from memory.local_memory import LocalVectorMemory
from prompts.specialized_prompts import PromptRegistry
from core import receipt as receipt_mod
from context.schema import (
    SchemaSnapshot,
    check as check_conformance,
    render_schema_block,
    select_tables,
)
from core.pipeline.context import PipelineContext
from context.antares import (
    AntaresInvocationError,
    materialize_implementation,
    run_antares_query,
)
from dataclasses import asdict

_VERDICT_RE = re.compile(r"VERDICT:\s*(APPROVED|NEEDS_REVISION)", re.IGNORECASE)
_FEEDBACK_RE = re.compile(r"FEEDBACK:\s*(.*)", re.IGNORECASE | re.DOTALL)
_DEVIATION_RE = re.compile(r"DEVIATION:\s*(NONE|JUSTIFIED|UNEXPLAINED)", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"SUMMARY:\s*(.*)", re.IGNORECASE | re.DOTALL)


def _split_plan_sections(plan: str, section_names: Tuple[str, ...]) -> Optional["Dict[str, str]"]:
    """
    Splits an Architect plan into named sections on "## <name>" headers.
    Returns an ordered dict of {section_name: body} only if ALL of section_names
    are found as headers (in any order, no duplicates) — otherwise returns None,
    which callers must treat as "model didn't follow the format" and fall back
    to treating the plan as a single monolithic block. Small/mid models don't
    reliably follow formatting instructions (see the router's classification
    non-determinism), so this can never be the only path.
    """
    header_re = re.compile(
        r"^##\s*(" + "|".join(re.escape(n) for n in section_names) + r")\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    matches = list(header_re.finditer(plan))
    if len(matches) != len(section_names):
        return None
    found_names = {m.group(1).strip() for m in matches}
    canonical = {n.lower(): n for n in section_names}
    if {n.lower() for n in found_names} != set(canonical.keys()):
        return None

    sections: Dict[str, str] = {}
    for i, m in enumerate(matches):
        name = canonical[m.group(1).strip().lower()]
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(plan)
        if name in sections:
            return None  # duplicate header — ambiguous, bail to monolithic fallback
        sections[name] = plan[body_start:body_end].strip()
    return sections


def _join_plan_sections(sections: Dict[str, str], section_names: Tuple[str, ...]) -> str:
    """Reassembles a sections dict back into the same '## Name' plan text format."""
    return "\n\n".join(f"## {name}\n{sections[name]}" for name in section_names)

# Library convention: get a module logger and emit to it, but never call
# logging.basicConfig() or attach handlers here. Configuring handlers/levels
# is the application's job (see main.py) — doing it here would clobber the
# logging setup of anything that imports this package (e.g. a commercial
# agent embedding Orchestrator in its own service).
logger = logging.getLogger(__name__)


class Orchestrator:
    """
    The central brain of the system. Implements a state-driven workflow
    to manage tasks through different specialized models (Layers).
    """

    ROUTER_CATEGORIES = ("SIMPLE_TASK", "COMPLEX_ARCHITECTURE", "CODING_REQUEST", "ERROR_REACTION")
    FAST_PATH_CATEGORIES = ("SIMPLE_TASK", "ERROR_REACTION")

    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        timeout = self.config.get('pipeline', {}).get('request_timeout_seconds', 300.0)
        # LDE_OLLAMA_HOST lets a caller running its own Ollama on a non-default host/port
        # (e.g. fenix, see docs/plan-mitigation-fenix-outsourcing-controls.md paso A7)
        # override the hardcoded localhost default without editing settings.yaml.
        api_url = os.environ.get("LDE_OLLAMA_HOST", "http://localhost:11434/api")
        self.factory = ModelFactory(self.config, api_url=api_url)
        self.memory = LocalVectorMemory(
            self.config['storage']['vector_db_path'],
            dimension=self.config['embeddings']['dimension'],
        )
        self.embedder = EmbeddingService(
            self.config['embeddings']['model_name'], api_url=api_url, timeout=timeout
        )
        self.prompts = PromptRegistry()

    async def aclose(self) -> None:
        """Releases resources held by the Orchestrator (currently: the embedder's HTTP
        client). A caller embedding this as a library should use this or the async
        context manager instead of reaching into self.embedder directly."""
        await self.embedder.aclose()

    async def __aenter__(self) -> "Orchestrator":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def _call_model(
        self,
        *,
        role: str,
        stage: str,
        model,
        prompt: str,
        request_id: str,
        attempt: Optional[int] = None,
        on_chunk: Optional[Callable[[str, str, Optional[int]], None]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Calls a role model with its system prompt, logs the call, and returns
        (response, trace_entry). trace_entry is a plain dict the caller owns —
        it is never stored on `self`, so concurrent run_complex_task() calls on
        the same Orchestrator instance never share mutable state.

        If on_chunk is given, streams the call via model.generate_stream() and
        invokes on_chunk(text, stage, attempt) per fragment as it arrives — stage
        and attempt let the caller (e.g. the CLI) print a header once per distinct
        stage/attempt instead of one flat unlabeled stream. The full response is
        still assembled and returned exactly as generate() would, since callers
        feed it into later stages. Without on_chunk, behavior is unchanged
        (single non-streamed call).
        """
        start = time.monotonic()
        if on_chunk is not None:
            parts = []
            async for text in model.generate_stream(
                prompt,
                context={"system_prompt": self.prompts.get_system_prompt(role)}
            ):
                parts.append(text)
                on_chunk(text, stage, attempt)
            response = "".join(parts)
        else:
            response = await model.generate(
                prompt,
                context={"system_prompt": self.prompts.get_system_prompt(role)}
            )
        duration_ms = (time.monotonic() - start) * 1000

        entry = {
            "request_id": request_id,
            "stage": stage,
            "role": role,
            "model": model.name,
            "attempt": attempt,
            "duration_ms": round(duration_ms, 1),
            "verdict": None,
        }
        logger.info(
            "stage=%s role=%s model=%s attempt=%s duration_ms=%.1f",
            stage, role, model.name, attempt, duration_ms,
            extra={"request_id": request_id, "stage": stage, "role": role,
                   "model": model.name, "attempt": attempt}
        )
        return response, entry

    async def _get_router_decision(self, user_query: str, request_id: str, trace: List[Dict[str, Any]]) -> str:
        """Uses the Router model to classify the intent into one of ROUTER_CATEGORIES."""
        router_model = self.factory.create_role_model("router")
        prompt = f"Classify this query: {user_query}"
        response, entry = await self._call_model(
            role="router", stage="routing", model=router_model,
            prompt=prompt, request_id=request_id
        )
        response_upper = response.strip().upper()
        # Small router models don't always follow "output only the category" strictly, so we
        # can't require exact equality. But we can't just scan for any category either: they
        # ramble *after* the answer, naming other categories to rule them out ("goes beyond a
        # SIMPLE_TASK") or echoing the list from the system prompt. Picking the first match in
        # ROUTER_CATEGORIES declaration order made those replies resolve to SIMPLE_TASK — a
        # fast-path category — and silently skip RAG/Architect/Implementer/QA entirely.
        #
        # They do reliably *lead* with the answer, so a response that starts with a category is
        # taken as decisive. Anything less clear falls back to whichever category appears
        # earliest, preferring non-fast-path ones: routing a simple query through the full
        # pipeline only costs time, while wrongly taking the fast path silently drops the work.
        decision = next((c for c in self.ROUTER_CATEGORIES if response_upper.startswith(c)), None)
        if decision is None:
            hits = sorted(
                (c in self.FAST_PATH_CATEGORIES, response_upper.find(c), c)
                for c in self.ROUTER_CATEGORIES if c in response_upper
            )
            decision = hits[0][2] if hits else None
        if decision is None:
            logger.warning(
                "Unrecognized router decision %r — defaulting to COMPLEX_ARCHITECTURE",
                response_upper[:80], extra={"request_id": request_id, "stage": "routing"}
            )
            decision = "COMPLEX_ARCHITECTURE"
        entry["decision"] = decision
        trace.append(entry)
        logger.info("Router decision: %s", decision, extra={"request_id": request_id, "stage": "routing"})
        return decision

    async def _build_rag_context(
        self, user_query: str, request_id: str
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Retrieves relevant chunks, caps how many come from any single source
        (so one file can't consume the whole top_k), and formats each with its
        source attribution. Logs chunks_retrieved and every score, since that's
        the only way to tell whether a NEEDS_REVISION came from the plan or from
        noisy RAG context.

        Returns (pieces, stats) — formatted, score-ordered, and deliberately NOT
        truncated here. Truncation is _assemble_context's job, because RAG is the
        lowest-priority block in a budget shared with the schema block, the
        Manager outline and the prior-attempt report; cutting it in isolation
        (as this method used to) enforced a ceiling on one block while the
        assembled context grew unbounded. stats feeds the receipt's outcome.rag
        block (docs/plan-receipt-interface-callers.md hallazgo #2), with the
        used/chars fields filled in by the assembler once the real budget is known.
        """
        retrieval_cfg = self.config.get('retrieval', {})
        top_k = retrieval_cfg.get('top_k', 5)
        min_score = retrieval_cfg.get('min_score', 0.0)
        max_chunks_per_source = retrieval_cfg.get('max_chunks_per_source', 2)

        logger.info("Searching local context", extra={"request_id": request_id, "stage": "rag"})
        try:
            query_vec = await self.embedder.get_embedding(user_query)
            relevant_chunks = self.memory.search(query_vec, top_k=top_k, min_score=min_score)
        except EmbeddingTooLargeError:
            logger.warning(
                "User query too large to embed — proceeding without RAG",
                extra={"request_id": request_id, "stage": "rag"}
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
            pieces.append({
                "text": f"{header}{chunk['text']}\n",
                "source": source,
                "score": chunk.get("score", 0),
            })

        scores = [round(c.get("score", 0), 3) for c in relevant_chunks]
        sources = sorted({p["source"] for p in pieces})
        logger.info(
            "RAG: chunks_retrieved=%d chunks_eligible=%d scores=%s",
            len(relevant_chunks), len(pieces), scores,
            extra={"request_id": request_id, "stage": "rag"}
        )
        stats = {
            "ran": True,
            "chunks_retrieved": len(relevant_chunks),
            "chunks_eligible": len(pieces),
            "chunks_used": 0,       # filled by _assemble_context
            "context_chars": 0,     # filled by _assemble_context
            "scores": scores,
            "sources": sources,
        }
        return pieces, stats

    def _assemble_context(
        self,
        *,
        request_id: str,
        schema_block: str = "",
        rag_pieces: Optional[List[Dict[str, Any]]] = None,
        breakdown: Optional[str] = None,
        prior_report: Optional[str] = None,
        reserve_chars: int = 0,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        The single place where the context budget is enforced, over EVERY block
        that reaches a model prompt — not just the retrieved chunks.

        Priority order is fixed and deliberate, highest first:
          1. schema block     — deterministic, already capped by its own renderer
          2. Manager outline  — short, and the Architect's actual instructions
          3. prior-attempt report (macro-loop) — why this run exists at all
          4. RAG chunks       — probabilistic, and the only block that degrades
                                gracefully by having fewer of them

        reserve_chars holds room for a block that doesn't exist yet (the Manager
        outline is written against a context assembled before it), so the second
        assembly doesn't have to evict chunks the first one already showed.

        Returns (context, budget_stats); budget_stats becomes outcome.context_budget.
        """
        retrieval_cfg = self.config.get('retrieval', {})
        max_total = retrieval_cfg.get('max_context_chars', 3000)
        rag_pieces = rag_pieces or []

        blocks: List[str] = []
        used = 0
        stats = {
            "max_total_chars": max_total,
            "schema_chars": 0,
            "breakdown_chars": 0,
            "prior_report_chars": 0,
            "rag_chars": 0,
            "rag_pieces_included": 0,
            "rag_pieces_dropped": 0,
            "reserved_chars": reserve_chars,
            "over_budget": False,
        }

        if schema_block:
            blocks.append(schema_block)
            used += len(schema_block)
            stats["schema_chars"] = len(schema_block)

        if breakdown:
            piece = f"TASK BREAKDOWN (Manager):\n{breakdown}"
            blocks.append(piece)
            used += len(piece)
            stats["breakdown_chars"] = len(piece)

        if prior_report:
            piece = f"PREVIOUS ATTEMPT — MANAGER FINDINGS:\n{prior_report}"
            blocks.append(piece)
            used += len(piece)
            stats["prior_report_chars"] = len(piece)

        # Whatever is left after the deterministic/instructional blocks and the
        # reservation goes to retrieval. A negative remainder is not an error —
        # it means the higher-priority blocks alone filled the budget, and RAG
        # is correctly dropped rather than silently pushing past the ceiling.
        rag_budget = max_total - used - reserve_chars
        rag_parts: List[str] = []
        rag_chars = 0
        for piece in rag_pieces:
            text = piece["text"]
            if rag_chars + len(text) > rag_budget:
                stats["rag_pieces_dropped"] += 1
                continue
            rag_parts.append(text)
            rag_chars += len(text)

        stats["rag_chars"] = rag_chars
        stats["rag_pieces_included"] = len(rag_parts)

        rag_text = "".join(rag_parts) if rag_parts else "No existing local context found."
        blocks.insert(0 if not schema_block else 1, f"PROJECT CONTEXT (retrieved, may be incomplete):\n{rag_text}")

        context = "\n\n".join(b for b in blocks if b)
        stats["used_chars"] = len(context)
        stats["over_budget"] = len(context) > max_total

        if stats["over_budget"]:
            # Reported, not truncated: cutting mid-block would corrupt the schema
            # block's grammar or the outline's meaning. A caller seeing this knows
            # the run exceeded its own ceiling and by how much.
            logger.warning(
                "Context budget exceeded: %d chars assembled over max_context_chars=%d",
                len(context), max_total,
                extra={"request_id": request_id, "stage": "context_budget"}
            )
        logger.info(
            "Context assembled: total=%d/%d schema=%d breakdown=%d rag=%d (%d chunks, %d dropped)",
            stats["used_chars"], max_total, stats["schema_chars"], stats["breakdown_chars"],
            rag_chars, stats["rag_pieces_included"], stats["rag_pieces_dropped"],
            extra={"request_id": request_id, "stage": "context_budget"}
        )
        return context, stats

    def _build_schema_context(
        self, snapshot, user_query: str, request_id: str
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Selects and renders the deterministic schema block for this query.

        Synchronous and model-free on purpose: nothing here calls Ollama, so a
        schema block never costs a model swap and never fails the run. The
        snapshot is provided by the caller (see context/schema/base.py's
        SchemaProvider docstring for why the engine does not introspect a live
        database itself).
        """
        cfg = self.config.get('schema_grounding', {})
        selection = select_tables(
            snapshot,
            user_query,
            max_tables=cfg.get('max_tables', 12),
            fk_expansion_depth=cfg.get('fk_expansion_depth', 1),
            include_all_if_no_match=cfg.get('include_all_if_no_match', True),
        )
        schema_max_chars = cfg.get('max_chars', 4000)
        block, shown, dropped = render_schema_block(
            selection, snapshot, max_chars=schema_max_chars
        )
        stats = {
            "ran": True,
            "source": snapshot.source,
            "dialect": snapshot.dialect,
            "tables_in_snapshot": len(snapshot.tables),
            "tables_shown": shown,
            "tables_omitted": selection.omitted + dropped,
            "matched": selection.matched,
            "related_via_fk": selection.related,
            "strategy": selection.strategy,
            "degraded": selection.degraded or bool(dropped),
            "reason": selection.reason or ("budget_dropped_tables" if dropped else None),
            "block_chars": len(block),
            "max_chars": schema_max_chars,
            # True only when schema_grounding.max_chars is set below the authority
            # header + one table. The header is never dropped to fit (see
            # render_schema_block) — this reports the overflow instead of hiding it.
            "block_over_budget": len(block) > schema_max_chars,
            "conformance_check": {"ran": False},
        }
        logger.info(
            "Schema grounding: strategy=%s shown=%d/%d chars=%d",
            selection.strategy, len(shown), len(snapshot.tables), len(block),
            extra={"request_id": request_id, "stage": "schema_grounding"}
        )
        return block, stats

    def _parse_verdict(self, qa_response: str) -> Tuple[bool, str]:
        """
        Parses a QA Auditor response formatted as 'VERDICT: ...' / 'FEEDBACK: ...'.
        Fails closed: if VERDICT isn't recognized, treats it as not approved.
        """
        verdict_match = _VERDICT_RE.search(qa_response)
        feedback_match = _FEEDBACK_RE.search(qa_response)
        feedback = feedback_match.group(1).strip() if feedback_match else qa_response.strip()
        approved = bool(verdict_match) and verdict_match.group(1).upper() == "APPROVED"
        return approved, feedback

    def _parse_closing_report(self, report_text: str) -> Tuple[str, str]:
        """
        Parses the Manager's closing report ('DEVIATION: ...' / 'SUMMARY: ...').
        Unlike _parse_verdict, this fails SOFT: an unparseable report must never
        block the pipeline, since nothing downstream depends on it — it's a report,
        not a gate. Missing/unrecognized DEVIATION becomes "UNKNOWN" and the raw
        text is kept as the summary so a human can still read it.
        """
        deviation_match = _DEVIATION_RE.search(report_text)
        summary_match = _SUMMARY_RE.search(report_text)
        if not deviation_match:
            return "UNKNOWN", report_text.strip()
        summary = summary_match.group(1).strip() if summary_match else report_text.strip()
        return deviation_match.group(1).upper(), summary

    async def _run_security_triage(
        self,
        cwe_checks: Optional[List[Tuple[str, str]]],
        body: Dict[str, Any],
        output_contract: Optional[str],
        request_id: str,
    ) -> Dict[str, Any]:
        """
        Opt-in Antares security triage over the final implementation. Never
        propagates an exception — a failure here can only degrade its own
        outcome.security_triage block, never the pipeline's own status (I1,
        docs/plan-security-advisor-antares.md).
        """
        requested = [{"cwe_id": c, "rationale": r} for c, r in (cwe_checks or [])]
        if not cwe_checks:
            return {
                "ran": False, "terminal_state": "not-requested", "degraded": False,
                "requested": [], "stdout_sha256": None, "findings": [],
            }
        if body["outcome"]["fast_path"]:
            return {
                "ran": False, "terminal_state": "snapshot-unavailable", "degraded": True,
                "reason": "fast-path", "requested": requested, "stdout_sha256": None,
                "findings": [],
            }
        implementation = body["artifacts"].get("implementation")
        if not implementation:
            return {
                "ran": False, "terminal_state": "artifact-missing", "degraded": True,
                "requested": requested, "stdout_sha256": None, "findings": [],
            }
        cfg = self.config.get("security_triage", {})
        try:
            with materialize_implementation(implementation, output_contract) as mat:
                result = await run_antares_query(
                    mat.snapshot_dir, mat.data_dir, cwe_checks,
                    binary=cfg.get("binary", "antares"),
                    profile=cfg.get("profile"),
                    timeout_seconds=cfg.get("timeout_seconds", 300),
                )
            return {
                "ran": True, "terminal_state": result.terminal_state,
                "degraded": result.degraded, "requested": requested,
                "stdout_sha256": result.stdout_sha256,
                "findings": [asdict(f) for f in result.findings],
            }
        except AntaresInvocationError as e:
            logger.warning(
                "Security triage degraded: %s", e,
                extra={"request_id": request_id, "stage": "security_triage"}
            )
            return {
                "ran": True, "terminal_state": e.terminal_state, "degraded": True,
                "requested": requested, "stdout_sha256": None, "findings": [],
            }
        except Exception:
            logger.exception(
                "Unexpected error during security triage",
                extra={"request_id": request_id, "stage": "security_triage"}
            )
            return {
                "ran": True, "terminal_state": "internal-error", "degraded": True,
                "requested": requested, "stdout_sha256": None, "findings": [],
            }

    async def run_complex_task(
        self,
        user_query: str,
        on_chunk: Optional[Callable[[str, str, Optional[int]], None]] = None,
        prior_breakdown: Optional[str] = None,
        prior_report: Optional[str] = None,
        macro_iteration: int = 1,
        output_contract: Optional[str] = None,
        schema_snapshot: Optional[SchemaSnapshot] = None,
        cwe_checks: Optional[List[Tuple[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Main workflow: Router -> (fast path | RAG -> Manager -> Architect<->QA design gate
        -> Implementer<->QA implementation check -> Manager closing report).

        If on_chunk is given, it's invoked as on_chunk(text, stage, attempt) with text
        fragments as they stream in from the model, for every stage whose output is
        shown to the user directly (fast-path answer, design plan/revision,
        implementation, closing report) — not QA stages, whose raw text is never
        printed, only their parsed verdict/feedback. Useful for a CLI/UI to show live
        progress instead of a multi-minute silent wait per stage.

        prior_breakdown/prior_report/macro_iteration support the macro-loop (re-running
        the full pipeline once, with the previous closing report fed back as feedback):
        - prior_breakdown, if given, skips the Manager task_breakdown call and the Router
          call — re-classifying risks a fast-path misroute that would discard the whole
          prior attempt (see docs/plan-macro-loop-manager-hitl.md, hallazgo 5) — and is
          used as-is, so the second closing report stays comparable to the first (a fresh
          outline would move the baseline it's being measured against).
        - prior_report, if given, is folded into the RAG context as a
          "PREVIOUS ATTEMPT — MANAGER FINDINGS" block so the Architect starts from the
          gaps already found instead of rediscovering them.
        - macro_iteration is carried into the trace/log `request_id` context so separate
          passes are distinguishable when reading logs; it does not gate anything inside
          this method — the iteration cap (config: pipeline.max_macro_iterations) and the
          human confirmation both live in the caller (main.py's chat REPL), never here.
        - output_contract, if set to one of PromptRegistry.OUTPUT_CONTRACTS (currently only
          "fenix-tagged-file"), teaches the Implementer and the implementation-check QA a
          strict machine-parseable grammar instead of free prose, and makes QA reject
          grammar violations regardless of code correctness (see
          docs/plan-mitigation-fenix-outsourcing-controls.md, paso A3).
        - schema_snapshot, if given, adds a deterministic relational context block ahead
          of the retrieved chunks and runs a model-free identifier audit on the final
          implementation. It is a parsed SchemaSnapshot, not a path: loading and
          validating the caller's file is the CALLER's error to surface (main.py turns a
          SchemaSnapshotError into EXIT_USAGE), so a malformed snapshot never becomes a
          silently degraded run inside the pipeline. The engine never opens a database
          connection and never holds credentials — see docs/plan-schema-grounding.md §7.
        - cwe_checks, if given (a list of (cwe_id, rationale) pairs), runs the opt-in
          Antares security triage layer once against the final implementation, after
          the pipeline body has already returned successfully — never inside the
          asyncio.wait_for that bounds the main pipeline, and never able to turn a
          completed run into a failed one (see docs/plan-security-advisor-antares.md,
          invariant I1).

        Returns a receipt dict (see core/receipt.py / docs/plan-receipt-interface-callers.md):
        schema_version, request_id, status ("completed"|"failed"|"timeout"), query,
        query_sha256, timestamps, duration_ms, outcome (per-stage ran/results incl. rag,
        design_gate, implementation_check, closing_report), config_fingerprint, artifacts
        (plan/implementation/breakdown/closing_report text), trace, error. The legacy
        top-level keys (plan, implementation, fast_path, qa_approved, qa_feedback,
        breakdown, closing_report, deviation, request_id, trace, macro_iteration) are kept
        for compatibility with existing internal consumers (main.py's _print_result /
        _macro_rerun_available) — the receipt adds structure, it doesn't remove the old shape.
        """
        started_at = receipt_mod.now()
        request_id = uuid.uuid4().hex[:12]
        trace: List[Dict[str, Any]] = []
        max_run_seconds = self.config.get('pipeline', {}).get('max_run_seconds')

        logger.info(
            "run_complex_task started (macro_iteration=%d)", macro_iteration,
            extra={"request_id": request_id, "stage": "start"}
        )

        request_params = {
            "output_contract": output_contract,
            "schema_grounding": schema_snapshot is not None,
            "schema_tables": len(schema_snapshot.tables) if schema_snapshot is not None else 0,
            "cwe_checks_requested": [c for c, _ in (cwe_checks or [])],
        }

        try:
            if max_run_seconds:
                body = await asyncio.wait_for(
                    self._run_pipeline_body(
                        user_query, request_id, trace, on_chunk,
                        prior_breakdown, prior_report, macro_iteration, output_contract,
                        schema_snapshot,
                    ),
                    timeout=max_run_seconds,
                )
            else:
                body = await self._run_pipeline_body(
                    user_query, request_id, trace, on_chunk,
                    prior_breakdown, prior_report, macro_iteration, output_contract,
                    schema_snapshot,
                )
        except asyncio.TimeoutError:
            finished_at = receipt_mod.now()
            logger.error(
                "run_complex_task timed out after %ss", max_run_seconds,
                extra={"request_id": request_id, "stage": "timeout"}
            )
            last_entry = trace[-1] if trace else {}
            rec = receipt_mod.build_receipt(
                status="timeout", query=user_query, started_at=started_at, finished_at=finished_at,
                config=self.config, request_id=request_id, trace=trace, macro_iteration=macro_iteration,
                request_params=request_params,
                error={"stage": last_entry.get("stage"), "role": last_entry.get("role"),
                       "model": last_entry.get("model"),
                       "message": f"Pipeline exceeded max_run_seconds={max_run_seconds}"},
            )
            rec.update({
                "plan": None, "implementation": None, "fast_path": False,
                "qa_approved": None, "qa_feedback": None, "breakdown": None,
                "closing_report": None, "deviation": None, "macro_iteration": macro_iteration,
            })
            return rec
        except ModelCallError as e:
            finished_at = receipt_mod.now()
            failed_entry = trace[-1] if trace else {}
            logger.error(
                "run_complex_task failed: %s", e,
                extra={"request_id": request_id, "stage": failed_entry.get("stage")}
            )
            rec = receipt_mod.build_receipt(
                status="failed", query=user_query, started_at=started_at, finished_at=finished_at,
                config=self.config, request_id=request_id, trace=trace, macro_iteration=macro_iteration,
                request_params=request_params,
                error={"stage": failed_entry.get("stage"), "role": failed_entry.get("role"),
                       "model": failed_entry.get("model"), "message": str(e)},
            )
            rec.update({
                "plan": None, "implementation": None, "fast_path": False,
                "qa_approved": None, "qa_feedback": None, "breakdown": None,
                "closing_report": None, "deviation": None, "macro_iteration": macro_iteration,
            })
            return rec

        try:
            # orchestration_timeout_seconds is the deadline asyncio.wait_for cancels
            # against, not a hard kill: cancellation only requests that
            # _run_security_triage's current await point raise CancelledError, and
            # its synchronous filesystem cleanup plus invoke.py's own post-kill drain
            # still run to completion before that propagates. Elapsed time can exceed
            # this value — there is no hard ceiling in this PoC (see
            # docs/plan-security-advisor-antares.md's own "not a production design"
            # framing). Defaults to Antares's own timeout_seconds plus a fixed margin,
            # so a slow-but-legitimate Antares run is never cancelled before its own
            # configured timeout would have fired.
            requested_for_degraded = [
                {"cwe_id": c, "rationale": r} for c, r in (cwe_checks or [])
            ]
            security_triage_cfg = self.config.get("security_triage", {})
            security_triage_timeout = security_triage_cfg.get(
                "orchestration_timeout_seconds",
                security_triage_cfg.get("timeout_seconds", 300) + 30,
            )
            security_triage = await asyncio.wait_for(
                self._run_security_triage(cwe_checks, body, output_contract, request_id),
                timeout=security_triage_timeout,
            )
            body["outcome"]["security_triage"] = security_triage
        except asyncio.TimeoutError:
            logger.warning(
                "Security triage orchestration timed out",
                extra={"request_id": request_id, "stage": "security_triage"}
            )
            body["outcome"]["security_triage"] = {
                "ran": True, "terminal_state": "timeout", "degraded": True,
                "requested": requested_for_degraded, "stdout_sha256": None, "findings": [],
            }
        except asyncio.CancelledError:
            raise
        except Exception:
            # Defense in depth: _run_security_triage already normalizes its own
            # failures, but this covers config/body access and the wait_for wiring
            # itself — the last line before I1 (Antares can never turn a completed
            # run into a failed one).
            logger.exception(
                "Unexpected error orchestrating security triage",
                extra={"request_id": request_id, "stage": "security_triage"}
            )
            body["outcome"]["security_triage"] = {
                "ran": True, "terminal_state": "internal-error", "degraded": True,
                "requested": [], "stdout_sha256": None, "findings": [],
            }

        finished_at = receipt_mod.now()
        rec = receipt_mod.build_receipt(
            status="completed", query=user_query, started_at=started_at, finished_at=finished_at,
            config=self.config, request_id=request_id, trace=trace, macro_iteration=macro_iteration,
            request_params=request_params,
            outcome=body["outcome"], artifacts=body["artifacts"],
        )
        rec.update(body["legacy"])
        return rec

    async def _run_pipeline_body(
        self,
        user_query: str,
        request_id: str,
        trace: List[Dict[str, Any]],
        on_chunk: Optional[Callable[[str, str, Optional[int]], None]],
        prior_breakdown: Optional[str],
        prior_report: Optional[str],
        macro_iteration: int,
        output_contract: Optional[str],
        schema_snapshot: Optional[SchemaSnapshot] = None,
    ) -> Dict[str, Any]:
        """
        The actual pipeline logic, split out from run_complex_task so the latter can wrap
        it in asyncio.wait_for (timeout) and a try/except (failure receipt) without the
        control flow of the pipeline itself having to know about either concern. Returns
        {"outcome": ..., "artifacts": ..., "legacy": ...} — three views of the same run
        that run_complex_task combines into the final receipt.

        Shared state (query, trace, breakdown, plan, implementation, ...) lives on a
        PipelineContext (O3, docs/plan-p1-refactor-orchestrator.md) instead of loose
        locals, so later stage extractions (O4+) can pass `ctx` around instead of
        growing every stage's signature each time another stage needs one more field.
        """
        ctx = PipelineContext(
            user_query=user_query, request_id=request_id, trace=trace, on_chunk=on_chunk,
            prior_breakdown=prior_breakdown, prior_report=prior_report,
            macro_iteration=macro_iteration, output_contract=output_contract,
            schema_snapshot=schema_snapshot,
        )

        # 0. Router: classify and short-circuit simple/error-reaction queries.
        # Skipped entirely on a macro-loop re-entry (prior_breakdown given) — we already
        # know this is a full-pipeline task, and re-classifying risks a fast-path misroute
        # that would silently discard the whole prior attempt.
        if ctx.prior_breakdown is not None:
            ctx.decision = "COMPLEX_ARCHITECTURE"
            logger.info(
                "Macro-loop re-entry: skipping Router, forcing full pipeline",
                extra={"request_id": ctx.request_id, "stage": "routing"}
            )
        else:
            ctx.decision = await self._get_router_decision(ctx.user_query, ctx.request_id, ctx.trace)
        if ctx.decision in self.FAST_PATH_CATEGORIES:
            logger.info(
                "Router fast path (%s) — skipping RAG/Architect/Implementer/QA", ctx.decision,
                extra={"request_id": ctx.request_id, "stage": "fast_path"}
            )
            manager = self.factory.create_role_model("manager")
            answer, entry = await self._call_model(
                role="manager", stage="fast_path", model=manager,
                prompt=ctx.user_query, request_id=ctx.request_id, on_chunk=ctx.on_chunk
            )
            ctx.trace.append(entry)
            return {
                "outcome": {
                    "router_decision": ctx.decision,
                    "fast_path": True,
                    "rag": {"ran": False},
                    # A schema snapshot may have been supplied and still not used:
                    # the fast path builds no context at all. "ran": False keeps
                    # that distinguishable from "used and found nothing".
                    "schema_grounding": {"ran": False},
                    "context_budget": {"ran": False},
                    "design_gate": {"ran": False},
                    "implementation_check": {"ran": False},
                    "closing_report": {"ran": False},
                },
                "artifacts": {"implementation": answer},
                "legacy": {
                    "plan": None,
                    "implementation": answer,
                    "fast_path": True,
                    "qa_approved": None,
                    "qa_feedback": None,
                    "breakdown": None,
                    "closing_report": None,
                    "deviation": None,
                    "request_id": ctx.request_id,
                    "trace": ctx.trace,
                    "macro_iteration": ctx.macro_iteration,
                },
            }

        max_iterations = self.config.get('pipeline', {}).get('max_qa_iterations', 2)

        # 1a. Deterministic schema context (highest-authority block, model-free).
        if ctx.schema_snapshot is not None:
            ctx.schema_block, ctx.schema_stats = self._build_schema_context(
                ctx.schema_snapshot, ctx.user_query, ctx.request_id
            )

        # 1b. Context Retrieval (RAG) — lowest-priority block in the shared budget.
        ctx.rag_pieces, ctx.rag_stats = await self._build_rag_context(ctx.user_query, ctx.request_id)

        # Assembled once here for the Manager, reserving room for the outline it is
        # about to write, then assembled again below with the real outline. Without
        # the reservation the Manager would see chunks the Architect then loses.
        breakdown_reserve = self.config.get('retrieval', {}).get('breakdown_reserve_chars', 1200)
        ctx.context, _ = self._assemble_context(
            request_id=ctx.request_id, schema_block=ctx.schema_block, rag_pieces=ctx.rag_pieces,
            prior_report=ctx.prior_report, reserve_chars=breakdown_reserve,
        )

        # 2. Manager: break the goal into a step outline that guides the Architect.
        # On a macro-loop re-entry (prior_breakdown given), this call is skipped and the
        # prior outline is reused as-is — regenerating it here would move the baseline
        # the second closing report gets measured against, making the two reports
        # incomparable (see docs/plan-macro-loop-manager-hitl.md, "otras decisiones").
        manager = self.factory.create_role_model("manager")
        if ctx.prior_breakdown is not None:
            ctx.breakdown = ctx.prior_breakdown
            logger.info(
                "Macro-loop re-entry: reusing prior breakdown, skipping task_breakdown",
                extra={"request_id": ctx.request_id, "stage": "task_breakdown"}
            )
        else:
            ctx.breakdown, entry = await self._call_model(
                role="manager", stage="task_breakdown", model=manager,
                prompt=self.prompts.get_manager_breakdown_template(ctx.context, ctx.user_query),
                request_id=ctx.request_id
            )
            ctx.trace.append(entry)
        # Final assembly, now that every block exists. This is the context every
        # downstream stage sees, and the only one whose numbers reach the receipt.
        ctx.context, ctx.budget_stats = self._assemble_context(
            request_id=ctx.request_id, schema_block=ctx.schema_block, rag_pieces=ctx.rag_pieces,
            breakdown=ctx.breakdown, prior_report=ctx.prior_report,
        )
        ctx.rag_stats["chunks_used"] = ctx.budget_stats["rag_pieces_included"]
        ctx.rag_stats["context_chars"] = ctx.budget_stats["rag_chars"]

        # 3. Architecture Phase with QA design gate (pre-implementation)
        architect = self.factory.create_role_model("architect")
        qa_auditor = self.factory.create_role_model("qa_auditor")

        ctx.plan, entry = await self._call_model(
            role="architect", stage="design_plan", model=architect,
            prompt=self.prompts.get_architect_thinking_template(ctx.context, ctx.user_query),
            request_id=ctx.request_id, attempt=1, on_chunk=ctx.on_chunk
        )
        ctx.trace.append(entry)

        section_names = self.prompts.SECTION_NAMES
        sections = _split_plan_sections(ctx.plan, section_names)
        if sections is not None:
            # Sectioned design gate: each section is reviewed and — if rejected —
            # regenerated independently, instead of regenerating the whole plan for
            # a defect in one part of it. Falls back to the monolithic gate below
            # if the Architect ever stops following the "## Section" format (e.g.
            # on a revision reply), so a formatting slip can't strand the pipeline.
            logger.info(
                "Design gate: sectioned review (%d sections)", len(sections),
                extra={"request_id": ctx.request_id, "stage": "design_gate"}
            )
            all_approved = True
            for section_name in section_names:
                section_text = sections[section_name]
                section_approved = False
                for attempt in range(max_iterations + 1):
                    full_plan = _join_plan_sections(sections, section_names)
                    review, qa_entry = await self._call_model(
                        role="qa_auditor", stage="design_gate", model=qa_auditor,
                        prompt=self.prompts.get_section_review_template(
                            ctx.context, ctx.user_query, section_name, section_text, full_plan
                        ),
                        request_id=ctx.request_id, attempt=attempt + 1
                    )
                    section_approved, section_feedback = self._parse_verdict(review)
                    qa_entry["verdict"] = "APPROVED" if section_approved else "NEEDS_REVISION"
                    qa_entry["section"] = section_name
                    ctx.trace.append(qa_entry)
                    logger.info(
                        "Design gate [%s] attempt %d: %s", section_name, attempt + 1, qa_entry["verdict"],
                        extra={"request_id": ctx.request_id, "stage": "design_gate", "attempt": attempt + 1}
                    )
                    if section_approved:
                        break
                    if attempt == max_iterations:
                        logger.warning(
                            "Design gate [%s] not approved after %d revisions — keeping last version",
                            section_name, max_iterations,
                            extra={"request_id": ctx.request_id, "stage": "design_gate"}
                        )
                        break
                    section_text, entry = await self._call_model(
                        role="architect", stage="design_revision", model=architect,
                        prompt=self.prompts.get_section_revision_template(
                            ctx.context, ctx.user_query, section_name, section_text, section_feedback, full_plan
                        ),
                        request_id=ctx.request_id, attempt=attempt + 2, on_chunk=ctx.on_chunk
                    )
                    ctx.trace.append(entry)
                    sections[section_name] = section_text
                all_approved = all_approved and section_approved
            ctx.plan = _join_plan_sections(sections, section_names)
            logger.info(
                "Design gate sectioned result: %s", "APPROVED" if all_approved else "NEEDS_REVISION (partial)",
                extra={"request_id": ctx.request_id, "stage": "design_gate"}
            )
            section_attempts = {}
            for qa_entry in ctx.trace:
                if qa_entry.get("stage") == "design_gate" and "section" in qa_entry:
                    section_attempts.setdefault(qa_entry["section"], {"approved": False, "attempts": 0})
                    section_attempts[qa_entry["section"]]["attempts"] += 1
                    section_attempts[qa_entry["section"]]["approved"] = qa_entry["verdict"] == "APPROVED"
            ctx.design_gate_outcome = {
                "ran": True, "mode": "sectioned", "approved": all_approved,
                "sections": section_attempts,
            }
        else:
            logger.info(
                "Design gate: Architect didn't follow the section format — falling back to monolithic review",
                extra={"request_id": ctx.request_id, "stage": "design_gate"}
            )
            for attempt in range(max_iterations + 1):
                review, qa_entry = await self._call_model(
                    role="qa_auditor", stage="design_gate", model=qa_auditor,
                    prompt=self.prompts.get_design_review_template(ctx.context, ctx.user_query, ctx.plan),
                    request_id=ctx.request_id, attempt=attempt + 1
                )
                design_approved, design_feedback = self._parse_verdict(review)
                qa_entry["verdict"] = "APPROVED" if design_approved else "NEEDS_REVISION"
                ctx.trace.append(qa_entry)
                logger.info(
                    "Design gate attempt %d: %s", attempt + 1, qa_entry["verdict"],
                    extra={"request_id": ctx.request_id, "stage": "design_gate", "attempt": attempt + 1}
                )
                if design_approved:
                    break
                if attempt == max_iterations:
                    logger.warning(
                        "Design gate not approved after %d revisions — proceeding with last plan",
                        max_iterations, extra={"request_id": ctx.request_id, "stage": "design_gate"}
                    )
                    break
                ctx.plan, entry = await self._call_model(
                    role="architect", stage="design_revision", model=architect,
                    prompt=self.prompts.get_architect_revision_template(
                        ctx.context, ctx.user_query, ctx.plan, design_feedback
                    ),
                    request_id=ctx.request_id, attempt=attempt + 2, on_chunk=ctx.on_chunk
                )
                ctx.trace.append(entry)
            ctx.design_gate_outcome = {"ran": True, "mode": "monolithic", "approved": design_approved}

        # 4. Implementation Phase with post-implementation QA check
        implementer = self.factory.create_role_model("implementer")

        ctx.implementation, entry = await self._call_model(
            role="implementer", stage="implementation", model=implementer,
            prompt=self.prompts.get_implementer_task_template(
                ctx.plan, ctx.context, output_contract=ctx.output_contract
            ),
            request_id=ctx.request_id, attempt=1, on_chunk=ctx.on_chunk
        )
        ctx.trace.append(entry)

        for attempt in range(max_iterations + 1):
            review, qa_entry = await self._call_model(
                role="qa_auditor", stage="implementation_check", model=qa_auditor,
                prompt=self.prompts.get_qa_review_template(
                    ctx.user_query, ctx.plan, ctx.implementation, output_contract=ctx.output_contract
                ),
                request_id=ctx.request_id, attempt=attempt + 1
            )
            ctx.implementation_check_attempts += 1
            ctx.qa_approved, ctx.qa_feedback = self._parse_verdict(review)
            qa_entry["verdict"] = "APPROVED" if ctx.qa_approved else "NEEDS_REVISION"
            ctx.trace.append(qa_entry)
            logger.info(
                "Implementation check attempt %d: %s", attempt + 1, qa_entry["verdict"],
                extra={"request_id": ctx.request_id, "stage": "implementation_check", "attempt": attempt + 1}
            )
            if ctx.qa_approved:
                ctx.qa_feedback = None
                break
            if attempt == max_iterations:
                logger.warning(
                    "Implementation not approved by QA after %d revisions",
                    max_iterations, extra={"request_id": ctx.request_id, "stage": "implementation_check"}
                )
                break
            # Design-level feedback loop: QA's implementation findings go back to the Architect first.
            ctx.plan, entry = await self._call_model(
                role="architect", stage="design_revision", model=architect,
                prompt=self.prompts.get_architect_revision_template(
                    ctx.context, ctx.user_query, ctx.plan, ctx.qa_feedback
                ),
                request_id=ctx.request_id, attempt=attempt + 2, on_chunk=ctx.on_chunk
            )
            ctx.trace.append(entry)
            ctx.implementation, entry = await self._call_model(
                role="implementer", stage="implementation", model=implementer,
                prompt=self.prompts.get_implementer_task_template(
                    ctx.plan, ctx.context, output_contract=ctx.output_contract
                ),
                request_id=ctx.request_id, attempt=attempt + 2, on_chunk=ctx.on_chunk
            )
            ctx.trace.append(entry)

        # 5. Manager closing report: compares the final result against the Manager's OWN
        # original outline (step 2) — nothing else in the pipeline ever revisits it. Gated
        # by config so its cost (an extra prompt carrying the full plan+implementation) can
        # be A/B'd against a baseline run with it off. Placed right after the implementation-
        # check loop deliberately: both `break` paths above just called qa_auditor, and
        # manager/qa_auditor share a model tag (see config/settings.yaml) — this call finds
        # its model already loaded under Ollama's single-slot config, so it costs generation
        # time only, not a model swap.
        closing_report_ran = self.config.get('pipeline', {}).get('closing_report', True)
        if closing_report_ran:
            max_impl_chars = self.config.get('pipeline', {}).get(
                'closing_report_max_implementation_chars', 8000
            )
            impl_for_report = ctx.implementation
            if len(impl_for_report) > max_impl_chars:
                impl_for_report = (
                    impl_for_report[:max_impl_chars]
                    + "\n\n[... implementation truncated for closing report ...]"
                )
            ctx.closing_report, entry = await self._call_model(
                role="manager", stage="closing_report", model=manager,
                prompt=self.prompts.get_manager_closing_report_template(
                    ctx.user_query, ctx.breakdown, ctx.plan, impl_for_report
                ),
                request_id=ctx.request_id, on_chunk=ctx.on_chunk
            )
            ctx.deviation, ctx.summary = self._parse_closing_report(ctx.closing_report)
            entry["deviation"] = ctx.deviation
            ctx.trace.append(entry)
            logger.info(
                "Closing report: deviation=%s", ctx.deviation,
                extra={"request_id": ctx.request_id, "stage": "closing_report"}
            )

        # Deterministic conformance check (docs/plan-schema-conformance.md).
        # Runs last, on the final implementation, and never gates anything in
        # `report` mode (the only mode built so far — `enforce` is C.7,
        # deferred) — it is a measurement the caller can reproduce from
        # (implementation, snapshot) without trusting this process at all.
        # That reproducibility is the point: every other signal in the receipt
        # is this pipeline grading its own work. AST-based (segmentation.py +
        # extraction.py), not the regex-based check_identifiers() it replaces —
        # see docs/fase3-decision.md for why that instrument was unusable.
        if ctx.schema_snapshot is not None and self.config.get('schema_grounding', {}).get(
            'identifier_check', True
        ):
            allow_new_objects = self.config.get('schema_grounding', {}).get(
                'allow_new_objects', True
            )
            conformance_report = check_conformance(
                ctx.implementation or "", ctx.schema_snapshot, allow_new_objects=allow_new_objects
            )
            ctx.schema_stats["conformance_check"] = conformance_report.to_dict()
            logger.info(
                "Conformance check: verdict=%s violations=%d checked=%d",
                conformance_report.verdict, len(conformance_report.violations),
                conformance_report.regions_checked,
                extra={"request_id": ctx.request_id, "stage": "schema_grounding"}
            )

        return {
            "outcome": {
                "router_decision": ctx.decision,
                "fast_path": False,
                "rag": ctx.rag_stats,
                "schema_grounding": ctx.schema_stats,
                "context_budget": {"ran": True, **ctx.budget_stats},
                "design_gate": ctx.design_gate_outcome,
                "implementation_check": {
                    "ran": True, "approved": ctx.qa_approved,
                    "attempts": ctx.implementation_check_attempts, "feedback": ctx.qa_feedback,
                },
                "closing_report": (
                    {"ran": True, "deviation": ctx.deviation, "summary": ctx.summary}
                    if closing_report_ran else {"ran": False}
                ),
            },
            "artifacts": {
                "breakdown": ctx.breakdown, "plan": ctx.plan, "implementation": ctx.implementation,
                "closing_report": ctx.closing_report,
            },
            "legacy": {
                "plan": ctx.plan,
                "implementation": ctx.implementation,
                "fast_path": False,
                "qa_approved": ctx.qa_approved,
                "qa_feedback": ctx.qa_feedback,
                "breakdown": ctx.breakdown,
                "closing_report": ctx.closing_report,
                "deviation": ctx.deviation,
                "request_id": ctx.request_id,
                "trace": ctx.trace,
                "macro_iteration": ctx.macro_iteration,
            },
        }
