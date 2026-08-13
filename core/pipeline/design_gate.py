"""Strategies for the Architect plan's pre-implementation QA gate (O7)."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
import re
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence, Tuple

from core.pipeline.context import PipelineContext
from core.pipeline.review_loop import ReviewLoop


ModelCaller = Callable[..., Awaitable[Tuple[str, Dict[str, Any]]]]


def split_plan_sections(
    plan: str, section_names: Sequence[str],
) -> Optional[Dict[str, str]]:
    """Return all named plan sections, or ``None`` for the monolithic fallback."""
    header_re = re.compile(
        r"^##\s*(" + "|".join(re.escape(name) for name in section_names) + r")\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    matches = list(header_re.finditer(plan))
    if len(matches) != len(section_names):
        return None
    canonical = {name.lower(): name for name in section_names}
    if {match.group(1).strip().lower() for match in matches} != set(canonical):
        return None

    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        name = canonical[match.group(1).strip().lower()]
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(plan)
        if name in sections:
            return None
        sections[name] = plan[match.end():body_end].strip()
    return sections


def join_plan_sections(sections: Dict[str, str], section_names: Sequence[str]) -> str:
    """Reassemble sections in the canonical prompt order."""
    return "\n\n".join(f"## {name}\n{sections[name]}" for name in section_names)


@dataclass(frozen=True)
class DesignGateDependencies:
    """Collaborators shared by the interchangeable design-gate strategies."""

    call_model: ModelCaller
    prompts: Any
    review_loop: ReviewLoop
    architect: Any
    qa_auditor: Any
    max_iterations: int
    section_names: Sequence[str]
    logger: Any


class DesignGate(ABC):
    """Strategy for reviewing and revising an Architect plan."""

    @abstractmethod
    async def run(self, ctx: PipelineContext) -> None:
        """Update ``ctx.plan`` and ``ctx.design_gate_outcome`` in place."""


class SectionedDesignGate(DesignGate):
    """Review each required plan section independently."""

    def __init__(self, dependencies: DesignGateDependencies, sections: Dict[str, str]):
        self.dependencies = dependencies
        self.sections = sections

    async def run(self, ctx: PipelineContext) -> None:
        deps = self.dependencies
        deps.logger.info(
            "Design gate: sectioned review (%d sections)", len(self.sections),
            extra={"request_id": ctx.request_id, "stage": "design_gate"},
        )
        all_approved = True
        for section_name in deps.section_names:
            async def review_section(section_text: str, attempt: int) -> Tuple[str, Dict[str, Any]]:
                self.sections[section_name] = section_text
                full_plan = join_plan_sections(self.sections, deps.section_names)
                return await deps.call_model(
                    role="qa_auditor", stage="design_gate", model=deps.qa_auditor,
                    prompt=deps.prompts.get_section_review_template(
                        ctx.context, ctx.user_query, section_name, section_text, full_plan,
                    ),
                    request_id=ctx.request_id, attempt=attempt + 1,
                )

            async def revise_section(section_text: str, feedback: str, attempt: int) -> str:
                full_plan = join_plan_sections(self.sections, deps.section_names)
                revised_section, entry = await deps.call_model(
                    role="architect", stage="design_revision", model=deps.architect,
                    prompt=deps.prompts.get_section_revision_template(
                        ctx.context, ctx.user_query, section_name, section_text, feedback, full_plan,
                    ),
                    request_id=ctx.request_id, attempt=attempt + 2, on_chunk=ctx.on_chunk,
                )
                ctx.trace.append(entry)
                return revised_section

            def record_section_review(
                qa_entry: Dict[str, Any], approved: bool, _feedback: str, attempt: int,
            ) -> None:
                qa_entry["verdict"] = "APPROVED" if approved else "NEEDS_REVISION"
                qa_entry["section"] = section_name
                ctx.trace.append(qa_entry)
                deps.logger.info(
                    "Design gate [%s] attempt %d: %s", section_name, attempt + 1, qa_entry["verdict"],
                    extra={"request_id": ctx.request_id, "stage": "design_gate", "attempt": attempt + 1},
                )

            result = await deps.review_loop.run(
                artifact=self.sections[section_name], max_iterations=deps.max_iterations,
                review=review_section, revise=revise_section, record_review=record_section_review,
            )
            self.sections[section_name] = result.artifact
            if not result.approved:
                deps.logger.warning(
                    "Design gate [%s] not approved after %d revisions — keeping last version",
                    section_name, deps.max_iterations,
                    extra={"request_id": ctx.request_id, "stage": "design_gate"},
                )
            all_approved = all_approved and result.approved

        ctx.plan = join_plan_sections(self.sections, deps.section_names)
        deps.logger.info(
            "Design gate sectioned result: %s",
            "APPROVED" if all_approved else "NEEDS_REVISION (partial)",
            extra={"request_id": ctx.request_id, "stage": "design_gate"},
        )
        section_attempts: Dict[str, Dict[str, Any]] = {}
        for entry in ctx.trace:
            if entry.get("stage") == "design_gate" and "section" in entry:
                attempts = section_attempts.setdefault(entry["section"], {"approved": False, "attempts": 0})
                attempts["attempts"] += 1
                attempts["approved"] = entry["verdict"] == "APPROVED"
        ctx.design_gate_outcome = {
            "ran": True, "mode": "sectioned", "approved": all_approved,
            "sections": section_attempts,
        }
        ctx.outcomes.record("design_gate", ctx.design_gate_outcome)


class MonolithicDesignGate(DesignGate):
    """Review and revise the full plan when its section grammar is unavailable."""

    def __init__(self, dependencies: DesignGateDependencies):
        self.dependencies = dependencies

    async def run(self, ctx: PipelineContext) -> None:
        deps = self.dependencies
        deps.logger.info(
            "Design gate: Architect didn't follow the section format — falling back to monolithic review",
            extra={"request_id": ctx.request_id, "stage": "design_gate"},
        )

        async def review_design(plan: str, attempt: int) -> Tuple[str, Dict[str, Any]]:
            return await deps.call_model(
                role="qa_auditor", stage="design_gate", model=deps.qa_auditor,
                prompt=deps.prompts.get_design_review_template(ctx.context, ctx.user_query, plan),
                request_id=ctx.request_id, attempt=attempt + 1,
            )

        async def revise_design(plan: str, feedback: str, attempt: int) -> str:
            revised_plan, entry = await deps.call_model(
                role="architect", stage="design_revision", model=deps.architect,
                prompt=deps.prompts.get_architect_revision_template(
                    ctx.context, ctx.user_query, plan, feedback,
                ),
                request_id=ctx.request_id, attempt=attempt + 2, on_chunk=ctx.on_chunk,
            )
            ctx.trace.append(entry)
            return revised_plan

        def record_design_review(
            qa_entry: Dict[str, Any], approved: bool, _feedback: str, attempt: int,
        ) -> None:
            qa_entry["verdict"] = "APPROVED" if approved else "NEEDS_REVISION"
            ctx.trace.append(qa_entry)
            deps.logger.info(
                "Design gate attempt %d: %s", attempt + 1, qa_entry["verdict"],
                extra={"request_id": ctx.request_id, "stage": "design_gate", "attempt": attempt + 1},
            )

        result = await deps.review_loop.run(
            artifact=ctx.plan or "", max_iterations=deps.max_iterations,
            review=review_design, revise=revise_design, record_review=record_design_review,
        )
        ctx.plan = result.artifact
        if not result.approved:
            deps.logger.warning(
                "Design gate not approved after %d revisions — proceeding with last plan",
                deps.max_iterations,
                extra={"request_id": ctx.request_id, "stage": "design_gate"},
            )
        ctx.design_gate_outcome = {"ran": True, "mode": "monolithic", "approved": result.approved}
        ctx.outcomes.record("design_gate", ctx.design_gate_outcome)


def select_design_gate(plan: str, dependencies: DesignGateDependencies) -> DesignGate:
    """Select the strongest applicable strategy without changing the fallback rule."""
    sections = split_plan_sections(plan, dependencies.section_names)
    if sections is not None:
        return SectionedDesignGate(dependencies, sections)
    return MonolithicDesignGate(dependencies)
