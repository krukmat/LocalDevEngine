"""Execution engine behind :class:`core.orchestrator.Orchestrator` (O9).

The public Orchestrator remains the compatibility facade.  This module owns the
per-request control flow so the facade does not need to know the implementation
stages' ordering or receipt-assembly details.
"""
import asyncio
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from context.schema import SchemaSnapshot
from core import receipt as receipt_mod
from core.pipeline.context import PipelineContext
from core.pipeline.context_stages import (
    ContextAssemblyStage,
    RagContextStage,
    RouterStage,
    SchemaContextStage,
)
from core.pipeline.design_gate import DesignGateDependencies, select_design_gate
from core.pipeline.impl_stages import (
    ClosingReportStage,
    ConformanceStage,
    ImplementationDependencies,
    ImplementationStage,
)
from core.pipeline.review_loop import ReviewLoop
from models.base import ModelCallError


ModelCaller = Callable[..., Awaitable[Tuple[str, Dict[str, Any]]]]
VerdictParser = Callable[[str], Tuple[bool, str]]
ClosingReportParser = Callable[[str], Tuple[str, str]]
SecurityTriage = Callable[
    [Optional[List[Tuple[str, str]]], Dict[str, Any], Optional[str], str],
    Awaitable[Dict[str, Any]],
]


class PipelineRunner:
    """Run one request while preserving the Orchestrator's public contract."""

    def __init__(
        self, *, config: Dict[str, Any], factory: Any, memory: Any, embedder: Any,
        prompts: Any, call_model: ModelCaller, parse_verdict: VerdictParser,
        parse_closing_report: ClosingReportParser, run_security_triage: SecurityTriage,
        router_categories: Tuple[str, ...], fast_path_categories: Tuple[str, ...], logger: Any,
    ):
        self.config = config
        self.factory = factory
        self.memory = memory
        self.embedder = embedder
        self.prompts = prompts
        self.call_model = call_model
        self.parse_verdict = parse_verdict
        self.parse_closing_report = parse_closing_report
        self.run_security_triage = run_security_triage
        self.router_categories = router_categories
        self.fast_path_categories = fast_path_categories
        self.logger = logger

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
        """Execute a request and return the exact receipt exposed by the facade."""
        started_at = receipt_mod.now()
        request_id = uuid.uuid4().hex[:12]
        trace: List[Dict[str, Any]] = []
        max_run_seconds = self.config.get("pipeline", {}).get("max_run_seconds")

        self.logger.info(
            "run_complex_task started (macro_iteration=%d)", macro_iteration,
            extra={"request_id": request_id, "stage": "start"},
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
                        user_query, request_id, trace, on_chunk, prior_breakdown,
                        prior_report, macro_iteration, output_contract, schema_snapshot,
                    ),
                    timeout=max_run_seconds,
                )
            else:
                body = await self._run_pipeline_body(
                    user_query, request_id, trace, on_chunk, prior_breakdown, prior_report,
                    macro_iteration, output_contract, schema_snapshot,
                )
        except asyncio.TimeoutError:
            return self._failed_receipt(
                status="timeout", query=user_query, started_at=started_at, request_id=request_id,
                trace=trace, macro_iteration=macro_iteration, request_params=request_params,
                error_message=f"Pipeline exceeded max_run_seconds={max_run_seconds}",
            )
        except ModelCallError as error:
            self.logger.error(
                "run_complex_task failed: %s", error,
                extra={"request_id": request_id, "stage": (trace[-1] if trace else {}).get("stage")},
            )
            return self._failed_receipt(
                status="failed", query=user_query, started_at=started_at, request_id=request_id,
                trace=trace, macro_iteration=macro_iteration, request_params=request_params,
                error_message=str(error),
            )

        await self._record_security_triage(cwe_checks, body, output_contract, request_id)
        finished_at = receipt_mod.now()
        receipt = receipt_mod.build_receipt(
            status="completed", query=user_query, started_at=started_at, finished_at=finished_at,
            config=self.config, request_id=request_id, trace=trace, macro_iteration=macro_iteration,
            request_params=request_params, outcome=body["outcome"], artifacts=body["artifacts"],
        )
        receipt.update(body["legacy"])
        return receipt

    def _failed_receipt(
        self, *, status: str, query: str, started_at: str, request_id: str,
        trace: List[Dict[str, Any]], macro_iteration: int, request_params: Dict[str, Any],
        error_message: str,
    ) -> Dict[str, Any]:
        finished_at = receipt_mod.now()
        last_entry = trace[-1] if trace else {}
        if status == "timeout":
            self.logger.error(
                "run_complex_task timed out after %ss", self.config.get("pipeline", {}).get("max_run_seconds"),
                extra={"request_id": request_id, "stage": "timeout"},
            )
        receipt = receipt_mod.build_receipt(
            status=status, query=query, started_at=started_at, finished_at=finished_at,
            config=self.config, request_id=request_id, trace=trace, macro_iteration=macro_iteration,
            request_params=request_params,
            error={
                "stage": last_entry.get("stage"), "role": last_entry.get("role"),
                "model": last_entry.get("model"), "message": error_message,
            },
        )
        receipt.update({
            "plan": None, "implementation": None, "fast_path": False,
            "qa_approved": None, "qa_feedback": None, "breakdown": None,
            "closing_report": None, "deviation": None, "macro_iteration": macro_iteration,
        })
        return receipt

    async def _record_security_triage(
        self, cwe_checks: Optional[List[Tuple[str, str]]], body: Dict[str, Any],
        output_contract: Optional[str], request_id: str,
    ) -> None:
        """Keep triage outside the bounded pipeline and unable to fail its receipt."""
        requested_for_degraded = [{"cwe_id": c, "rationale": r} for c, r in (cwe_checks or [])]
        security_triage_cfg = self.config.get("security_triage", {})
        security_triage_timeout = security_triage_cfg.get(
            "orchestration_timeout_seconds", security_triage_cfg.get("timeout_seconds", 300) + 30,
        )
        try:
            body["outcome"]["security_triage"] = await asyncio.wait_for(
                self.run_security_triage(cwe_checks, body, output_contract, request_id),
                timeout=security_triage_timeout,
            )
        except asyncio.TimeoutError:
            self.logger.warning(
                "Security triage orchestration timed out",
                extra={"request_id": request_id, "stage": "security_triage"},
            )
            body["outcome"]["security_triage"] = {
                "ran": True, "terminal_state": "timeout", "degraded": True,
                "requested": requested_for_degraded, "stdout_sha256": None, "findings": [],
            }
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger.exception(
                "Unexpected error orchestrating security triage",
                extra={"request_id": request_id, "stage": "security_triage"},
            )
            body["outcome"]["security_triage"] = {
                "ran": True, "terminal_state": "internal-error", "degraded": True,
                "requested": [], "stdout_sha256": None, "findings": [],
            }

    async def _run_pipeline_body(
        self, user_query: str, request_id: str, trace: List[Dict[str, Any]],
        on_chunk: Optional[Callable[[str, str, Optional[int]], None]],
        prior_breakdown: Optional[str], prior_report: Optional[str], macro_iteration: int,
        output_contract: Optional[str], schema_snapshot: Optional[SchemaSnapshot] = None,
    ) -> Dict[str, Any]:
        """Run the ordered stages and return outcome, artifacts and legacy views."""
        ctx = PipelineContext(
            user_query=user_query, request_id=request_id, trace=trace, on_chunk=on_chunk,
            prior_breakdown=prior_breakdown, prior_report=prior_report,
            macro_iteration=macro_iteration, output_contract=output_contract,
            schema_snapshot=schema_snapshot,
        )
        router_stage = RouterStage(
            factory=self.factory, call_model=self.call_model,
            categories=self.router_categories, fast_path_categories=self.fast_path_categories,
            logger=self.logger,
        )
        schema_stage = SchemaContextStage(config=self.config, logger=self.logger)
        rag_stage = RagContextStage(
            config=self.config, memory=self.memory, embedder=self.embedder, logger=self.logger,
        )
        context_assembly_stage = ContextAssemblyStage(config=self.config, logger=self.logger)

        await router_stage.run(ctx)
        if ctx.decision in self.fast_path_categories:
            self.logger.info(
                "Router fast path (%s) — skipping RAG/Architect/Implementer/QA", ctx.decision,
                extra={"request_id": ctx.request_id, "stage": "fast_path"},
            )
            manager = self.factory.create_role_model("manager")
            answer, entry = await self.call_model(
                role="manager", stage="fast_path", model=manager, prompt=ctx.user_query,
                request_id=ctx.request_id, on_chunk=ctx.on_chunk,
            )
            ctx.trace.append(entry)
            for stage in (
                "rag", "schema_grounding", "context_budget", "design_gate",
                "implementation_check", "closing_report",
            ):
                ctx.outcomes.record(stage, {"ran": False})
            outcome = ctx.outcomes.snapshot()
            outcome.update({"router_decision": ctx.decision, "fast_path": True})
            return {
                "outcome": outcome, "artifacts": {"implementation": answer},
                "legacy": {
                    "plan": None, "implementation": answer, "fast_path": True,
                    "qa_approved": None, "qa_feedback": None, "breakdown": None,
                    "closing_report": None, "deviation": None, "request_id": ctx.request_id,
                    "trace": ctx.trace, "macro_iteration": ctx.macro_iteration,
                },
            }

        max_iterations = self.config.get("pipeline", {}).get("max_qa_iterations", 2)
        review_loop = ReviewLoop(self.parse_verdict)
        await schema_stage.run(ctx)
        await rag_stage.run(ctx)
        await context_assembly_stage.run(ctx)

        manager = self.factory.create_role_model("manager")
        if ctx.prior_breakdown is not None:
            ctx.breakdown = ctx.prior_breakdown
            self.logger.info(
                "Macro-loop re-entry: reusing prior breakdown, skipping task_breakdown",
                extra={"request_id": ctx.request_id, "stage": "task_breakdown"},
            )
        else:
            ctx.breakdown, entry = await self.call_model(
                role="manager", stage="task_breakdown", model=manager,
                prompt=self.prompts.get_manager_breakdown_template(ctx.context, ctx.user_query),
                request_id=ctx.request_id,
            )
            ctx.trace.append(entry)
        await context_assembly_stage.run(ctx)

        architect = self.factory.create_role_model("architect")
        qa_auditor = self.factory.create_role_model("qa_auditor")
        ctx.plan, entry = await self.call_model(
            role="architect", stage="design_plan", model=architect,
            prompt=self.prompts.get_architect_thinking_template(ctx.context, ctx.user_query),
            request_id=ctx.request_id, attempt=1, on_chunk=ctx.on_chunk,
        )
        ctx.trace.append(entry)
        design_gate = select_design_gate(
            ctx.plan or "",
            DesignGateDependencies(
                call_model=self.call_model, prompts=self.prompts, review_loop=review_loop,
                architect=architect, qa_auditor=qa_auditor, max_iterations=max_iterations,
                section_names=self.prompts.SECTION_NAMES, logger=self.logger,
            ),
        )
        await design_gate.run(ctx)

        implementer = self.factory.create_role_model("implementer")
        implementation_stage = ImplementationStage(ImplementationDependencies(
            call_model=self.call_model, prompts=self.prompts, review_loop=review_loop,
            architect=architect, qa_auditor=qa_auditor, implementer=implementer,
            max_iterations=max_iterations, logger=self.logger,
        ))
        await implementation_stage.run(ctx)
        closing_report_stage = ClosingReportStage(
            config=self.config, call_model=self.call_model, prompts=self.prompts, manager=manager,
            parse_report=self.parse_closing_report, logger=self.logger,
        )
        await closing_report_stage.run(ctx)
        await ConformanceStage(config=self.config, logger=self.logger).run(ctx)

        outcome = ctx.outcomes.snapshot()
        outcome.update({"router_decision": ctx.decision, "fast_path": False})
        return {
            "outcome": outcome,
            "artifacts": {
                "breakdown": ctx.breakdown, "plan": ctx.plan,
                "implementation": ctx.implementation, "closing_report": ctx.closing_report,
            },
            "legacy": {
                "plan": ctx.plan, "implementation": ctx.implementation, "fast_path": False,
                "qa_approved": ctx.qa_approved, "qa_feedback": ctx.qa_feedback,
                "breakdown": ctx.breakdown, "closing_report": ctx.closing_report,
                "deviation": ctx.deviation, "request_id": ctx.request_id, "trace": ctx.trace,
                "macro_iteration": ctx.macro_iteration,
            },
        }
