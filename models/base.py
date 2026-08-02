from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

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
        """
        pass

    @abstractmethod
    async def load(self):
        """Prepares/loads the model into VRAM."""
        pass

    @abstractmethod
    async def unload(self):
        """Unloads the model from VRAM to free resources."""
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.name} ({self.role})>"
