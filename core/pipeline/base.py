"""Shared interfaces for the pipeline stages extracted from Orchestrator."""
from abc import ABC, abstractmethod

from core.pipeline.context import PipelineContext


class PipelineStage(ABC):
    """A pipeline operation that reads and updates one shared context."""

    @abstractmethod
    async def run(self, ctx: PipelineContext) -> None:
        """Run this stage against ``ctx``."""
