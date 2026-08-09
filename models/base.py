from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Any, Optional


class ModelCallError(RuntimeError):
    """Raised when a model call fails (HTTP/transport error) instead of returning
    the error text as if it were generated content."""

    def __init__(self, message: str, partial: str = ""):
        super().__init__(message)
        self.partial = partial


class BaseModel(ABC):
    """
    Abstract Base Class for all AI models in the orchestrator.
    Implements the Strategy Pattern to allow different providers (Ollama, OpenAI, etc.)
    and different model implementations.
    """

    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role

    @property
    @abstractmethod
    def capabilities(self) -> list[str]:
        """Returns the capabilities of this model (e.g., ['coding', 'vision'])."""
        pass

    @abstractmethod
    async def generate(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Generates a response based on a prompt and optional context.
        Implements the core interaction with the model.

        Raises:
            ModelCallError: if the call fails (HTTP/transport error). Never returns
                the error text as if it were generated content.
        """
        pass

    @abstractmethod
    def generate_stream(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> AsyncIterator[str]:
        """
        Same call as generate(), but yields response text incrementally as it's
        produced instead of waiting for the full completion. Callers that need the
        full text (e.g. the orchestrator feeding one stage's output into the next
        stage's prompt) should join the yielded chunks themselves.

        Raises:
            ModelCallError: if the call fails (HTTP/transport error), raised from
                inside the async generator at the point the failure occurs.
        """
        pass

    @abstractmethod
    async def load(self):
        """Prepares/loads the model into VRAM."""
        pass

    @abstractmethod
    async def unload(self):
        """Unloads the model from VRAM to free resources.

        Raises:
            ModelCallError: if the call fails (HTTP/transport error).
        """
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.name} ({self.role})>"
