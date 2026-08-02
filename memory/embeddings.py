import httpx
from typing import List, Optional

class EmbeddingService:
    """
    Handles the generation of embeddings using a local Ollama instance.
    Used by Memory for indexing and Orchestrator for querying.
    """

    def __init__(self, model_name: str, api_url: str = "http://localhost:11434/api", timeout: float = 300.0):
        self.model_name = model_name
        self.api_url = api_url
        self.timeout = timeout

    async def get_embedding(self, text: str) -> List[float]:
        """
        Sends a request to Ollama to generate an embedding for the given text.
        Returns a list of floats representing the semantic vector.
        """
        payload = {
            "model": self.model_name,
            "prompt": text
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # Ollama /api/embeddings endpoint returns {"embedding": [...]}
                response = await client.post(f"{self.api_url}/embeddings", json=payload, timeout=self.timeout)
                response.raise_for_status()
                return response.json().get("embedding", [])
            except (httpx.HTTPError, ValueError) as e:
                raise RuntimeError(f"Failed to generate embedding with model {self.model_name}: {str(e) or type(e).__name__}")

    def __repr__(self) -> str:
        return f"<EmbeddingService: {self.model_name}>"
