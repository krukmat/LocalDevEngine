"""Reusable retry mechanics for the pipeline's QA review loops (O6)."""
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Generic, Tuple, TypeVar


Artifact = TypeVar("Artifact")
ReviewCall = Callable[[Artifact, int], Awaitable[Tuple[str, Dict[str, Any]]]]
RevisionCall = Callable[[Artifact, str, int], Awaitable[Artifact]]
VerdictParser = Callable[[str], Tuple[bool, str]]
ReviewRecorder = Callable[[Dict[str, Any], bool, str, int], None]


@dataclass
class ReviewLoopResult(Generic[Artifact]):
    artifact: Artifact
    approved: bool
    feedback: str
    attempts: int


class ReviewLoop(Generic[Artifact]):
    """Template Method for review → verdict → revision retry cycles.

    The callers own their prompts, model calls, trace shape, logging and the
    meaning of a revision. This class owns only the common retry mechanics.
    """

    def __init__(self, parse_verdict: VerdictParser):
        self._parse_verdict = parse_verdict

    async def run(
        self,
        *,
        artifact: Artifact,
        max_iterations: int,
        review: ReviewCall[Artifact],
        revise: RevisionCall[Artifact],
        record_review: ReviewRecorder,
    ) -> ReviewLoopResult[Artifact]:
        for attempt in range(max_iterations + 1):
            response, entry = await review(artifact, attempt)
            approved, feedback = self._parse_verdict(response)
            record_review(entry, approved, feedback, attempt)
            if approved or attempt == max_iterations:
                return ReviewLoopResult(
                    artifact=artifact,
                    approved=approved,
                    feedback=feedback,
                    attempts=attempt + 1,
                )
            artifact = await revise(artifact, feedback, attempt)

        raise AssertionError("ReviewLoop always returns from its bounded loop")
