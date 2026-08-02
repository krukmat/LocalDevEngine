import httpx
from typing import List, Optional, Tuple


class EmbeddingTooLargeError(RuntimeError):
    """
    Raised when /api/embed rejects an input with HTTP 400 because it exceeds
    the model's context window (truncate=False makes this a hard error
    instead of a silent truncation). Callers can react by splitting the
    input and retrying, instead of treating it as a generic failure.
    """


class EmbeddingService:
    """
    Handles the generation of embeddings using a local Ollama instance.
    Used by Memory for indexing and Orchestrator for querying.

    Uses /api/embed (not the legacy /api/embeddings) with truncate=False:
    oversized input fails loud with EmbeddingTooLargeError instead of being
    silently truncated, and the endpoint accepts batched input natively.
    """

    def __init__(self, model_name: str, api_url: str = "http://localhost:11434/api", timeout: float = 300.0):
        self.model_name = model_name
        self.api_url = api_url
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _embed(self, input_: List[str]) -> Tuple[List[List[float]], Optional[int]]:
        payload = {
            "model": self.model_name,
            "input": input_,
            "truncate": False,
        }
        try:
            response = await self._client.post(f"{self.api_url}/embed", json=payload, timeout=self.timeout)
            if response.status_code == 400:
                raise EmbeddingTooLargeError(
                    f"Input exceeds the context window of model {self.model_name} "
                    f"({len(input_)} item(s), longest {max((len(t) for t in input_), default=0)} chars)."
                )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as e:
            raise RuntimeError(f"Failed to generate embedding with model {self.model_name}: {str(e) or type(e).__name__}")

        embeddings = data.get("embeddings")
        if not embeddings or len(embeddings) != len(input_) or any(not e for e in embeddings):
            raise RuntimeError(
                f"Model {self.model_name} returned an unexpected embeddings shape "
                f"(expected {len(input_)} non-empty vectors, got {embeddings!r})"
            )
        return embeddings, data.get("prompt_eval_count")

    async def get_embedding(self, text: str) -> List[float]:
        """Embeds a single piece of text. Returns a list of floats."""
        embeddings, _ = await self._embed([text])
        return embeddings[0]

    async def get_embeddings(self, texts: List[str]) -> Tuple[List[List[float]], Optional[int]]:
        """
        Embeds a batch of texts in one request.
        Returns (embeddings, prompt_eval_count) — prompt_eval_count is the
        real token count for the whole batch, straight from Ollama.
        """
        return await self._embed(texts)

    def __repr__(self) -> str:
        return f"<EmbeddingService: {self.model_name}>"
