from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseMemory(ABC):
    """
    Abstract Base Class for Memory/RAG components.
    Allows swapping simple local storage with professional vector databases.
    """

    @abstractmethod
    def add_text(self, text: str, metadata: Dict[str, Any]) -> None:
        """Embeds and stores a piece of text."""
        pass

    @abstractmethod
    def search(self, query_embedding: List[float], top_k: int = 3) -> List[Dict[str, Any]]:
        """Searches for the most similar text chunks given an embedding."""
        pass

    @abstractmethod
    def get_all_chunks(self) -> List[Dict[str, Any]]:
        """Retrieves all stored content (for debugging/re-indexing)."""
        pass
