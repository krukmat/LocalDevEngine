"""Implementation, closing-report and conformance stages for the pipeline (O8)."""
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Tuple

from context.schema import check as check_conformance

from core.pipeline.base import PipelineStage
from core.pipeline.context import PipelineContext
from core.pipeline.review_loop import ReviewLoop


ModelCaller = Callable[..., Awaitable[Tuple[str, Dict[str, Any]]]]
ClosingReportParser = Callable[[str], Tuple[str, str]]


@dataclass(frozen=True)
class ImplementationDependencies:
    """Collaborators for the implementation and post-implementation QA loop."""

    call_model: ModelCaller
    prompts: Any
    review_loop: ReviewLoop
    architect: Any
    qa_auditor: Any
    implementer: Any
    max_iterations: int
    logger: Any


class ImplementationStage(PipelineStage):
    """Generate implementation and run the bounded implementation QA loop."""

    def __init__(self, dependencies: ImplementationDependencies):
        self.dependencies = dependencies

    async def run(self, ctx: PipelineContext) -> None:
        deps = self.dependencies
        ctx.implementation, entry = await deps.call_model(
            role="implementer", stage="implementation", model=deps.implementer,
            prompt=deps.prompts.get_implementer_task_template(
                ctx.plan, ctx.context, output_contract=ctx.output_contract
            ),
            request_id=ctx.request_id, attempt=1, on_chunk=ctx.on_chunk,
        )
        ctx.trace.append(entry)

        async def review_implementation(artifact: Tuple[str, str], attempt: int) -> Tuple[str, Dict[str, Any]]:
            plan, implementation = artifact
            return await deps.call_model(
                role="qa_auditor", stage="implementation_check", model=deps.qa_auditor,
                prompt=deps.prompts.get_qa_review_template(
                    ctx.user_query, plan, implementation, output_contract=ctx.output_contract,
                ),
                request_id=ctx.request_id, attempt=attempt + 1,
            )

        async def revise_implementation(
            artifact: Tuple[str, str], qa_feedback: str, attempt: int,
        ) -> Tuple[str, str]:
            plan, _implementation = artifact
            revised_plan, revision_entry = await deps.call_model(
                role="architect", stage="design_revision", model=deps.architect,
                prompt=deps.prompts.get_architect_revision_template(
                    ctx.context, ctx.user_query, plan, qa_feedback,
                ),
                request_id=ctx.request_id, attempt=attempt + 2, on_chunk=ctx.on_chunk,
            )
            ctx.trace.append(revision_entry)
            revised_implementation, implementation_entry = await deps.call_model(
                role="implementer", stage="implementation", model=deps.implementer,
                prompt=deps.prompts.get_implementer_task_template(
                    revised_plan, ctx.context, output_contract=ctx.output_contract,
                ),
                request_id=ctx.request_id, attempt=attempt + 2, on_chunk=ctx.on_chunk,
            )
            ctx.trace.append(implementation_entry)
            return revised_plan, revised_implementation

        def record_implementation_review(
            qa_entry: Dict[str, Any], qa_approved: bool, qa_feedback: str, attempt: int,
        ) -> None:
            ctx.implementation_check_attempts += 1
            ctx.qa_approved, ctx.qa_feedback = qa_approved, qa_feedback
            qa_entry["verdict"] = "APPROVED" if qa_approved else "NEEDS_REVISION"
            ctx.trace.append(qa_entry)
            deps.logger.info(
                "Implementation check attempt %d: %s", attempt + 1, qa_entry["verdict"],
                extra={"request_id": ctx.request_id, "stage": "implementation_check", "attempt": attempt + 1},
            )

        result = await deps.review_loop.run(
            artifact=(ctx.plan, ctx.implementation), max_iterations=deps.max_iterations,
            review=review_implementation, revise=revise_implementation,
            record_review=record_implementation_review,
        )
        ctx.plan, ctx.implementation = result.artifact
        if result.approved:
            ctx.qa_feedback = None
        else:
            deps.logger.warning(
                "Implementation not approved by QA after %d revisions",
                deps.max_iterations,
                extra={"request_id": ctx.request_id, "stage": "implementation_check"},
            )
        ctx.outcomes.record("implementation_check", {
            "ran": True, "approved": ctx.qa_approved,
            "attempts": ctx.implementation_check_attempts, "feedback": ctx.qa_feedback,
        })


class ClosingReportStage(PipelineStage):
    """Have the Manager compare the final artifacts to its original outline."""

    def __init__(
        self, *, config: Dict[str, Any], call_model: ModelCaller, prompts: Any,
        manager: Any, parse_report: ClosingReportParser, logger: Any,
    ):
        self.config = config
        self.call_model = call_model
        self.prompts = prompts
        self.manager = manager
        self.parse_report = parse_report
        self.logger = logger

    async def run(self, ctx: PipelineContext) -> None:
        if not self.config.get("pipeline", {}).get("closing_report", True):
            ctx.outcomes.record("closing_report", {"ran": False})
            return
        max_impl_chars = self.config.get("pipeline", {}).get(
            "closing_report_max_implementation_chars", 8000,
        )
        impl_for_report = ctx.implementation
        if len(impl_for_report) > max_impl_chars:
            impl_for_report = (
                impl_for_report[:max_impl_chars]
                + "\n\n[... implementation truncated for closing report ...]"
            )
        ctx.closing_report, entry = await self.call_model(
            role="manager", stage="closing_report", model=self.manager,
            prompt=self.prompts.get_manager_closing_report_template(
                ctx.user_query, ctx.breakdown, ctx.plan, impl_for_report,
            ),
            request_id=ctx.request_id, on_chunk=ctx.on_chunk,
        )
        ctx.deviation, ctx.summary = self.parse_report(ctx.closing_report)
        entry["deviation"] = ctx.deviation
        ctx.trace.append(entry)
        self.logger.info(
            "Closing report: deviation=%s", ctx.deviation,
            extra={"request_id": ctx.request_id, "stage": "closing_report"},
        )
        ctx.outcomes.record("closing_report", {
            "ran": True, "deviation": ctx.deviation, "summary": ctx.summary,
        })


class ConformanceStage(PipelineStage):
    """Run the deterministic schema check on the final implementation when enabled."""

    def __init__(self, *, config: Dict[str, Any], logger: Any):
        self.config = config
        self.logger = logger

    async def run(self, ctx: PipelineContext) -> None:
        if ctx.schema_snapshot is None or not self.config.get("schema_grounding", {}).get(
            "identifier_check", True,
        ):
            return
        allow_new_objects = self.config.get("schema_grounding", {}).get(
            "allow_new_objects", True,
        )
        conformance_report = check_conformance(
            ctx.implementation or "", ctx.schema_snapshot, allow_new_objects=allow_new_objects,
        )
        ctx.schema_stats["conformance_check"] = conformance_report.to_dict()
        ctx.outcomes.update(
            "schema_grounding", conformance_check=ctx.schema_stats["conformance_check"],
        )
        self.logger.info(
            "Conformance check: verdict=%s violations=%d checked=%d",
            conformance_report.verdict, len(conformance_report.violations),
            conformance_report.regions_checked,
            extra={"request_id": ctx.request_id, "stage": "schema_grounding"},
        )
