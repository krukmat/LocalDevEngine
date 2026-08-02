import httpx
import json
from typing import Dict, Any, Optional
from models.base import BaseModel

class OllamaModel(BaseModel):
    """
    Concrete implementation of BaseModel for the Ollama API.
    Uses HTTP requests to interact with a local Ollama server.
    """

    def __init__(self, name: str, role: str, capabilities: list[str], api_url: str = "http://localhost:11434/api",
                 timeout: float = 300.0, think: Optional[bool] = None):
        super().__init__(name, role)
        self._capabilities = capabilities
        self.api_url = api_url
        # Thinking-capable models (e.g. qwen3.6) can spend a long time reasoning before
        # emitting any "response" text, and a cold local model swap can itself take well
        # over a minute — 300s is a floor, not a ceiling; tune via config for your hardware.
        self.timeout = timeout
        # None = let Ollama/the model use its own default. True/False forces the "think"
        # field on /api/generate, letting settings.yaml turn off slow chain-of-thought
        # reasoning per role if it's not worth the latency for your hardware.
        self.think = think

    @property
    def capabilities(self) -> list[str]:
        return self._capabilities

    async def generate(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Sends a request to the Ollama generation endpoint.
        """
        payload = {
            "model": self.name,
            "prompt": prompt,
            "stream": False
        }
        if context and "system_prompt" in context:
            # /api/generate accepts a top-level "system" field that overrides
            # the model's Modelfile SYSTEM prompt for this request only.
            payload["system"] = context["system_prompt"]
        if self.think is not None:
            payload["think"] = self.think

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # Using /api/generate for simple text responses as requested by prompt
                response = await client.post(f"{self.api_url}/generate", json=payload, timeout=self.timeout)
                response.raise_for_status()
                return response.json().get("response", "")
            except httpx.HTTPError as e:
                return f"Error calling Ollama API: {str(e) or type(e).__name__}"

    async def load(self):
        """
        In a real scenario, this might involve an explicit 'pull' or ensuring 
        the model is in the cache. Since we are using a server, we can do
        a dummy call to ensure it's ready and warming up memory.
        """
        async with httpx.AsyncClient() as client:
            try:
                # We send a minimal request just to check availability/warmup
                await client.post(f"{self.api_url}/generate", json={
                    "model": self.name,
                    "prompt": "ping",
                    "stream": False
                }, timeout=10.0)
            except Exception:
                pass  # Just ensuring we know it's there

    async def unload(self):
        """
        Ollama doesn't have a direct 'unload' API like some other engines, 
        but we can rely on its automatic management or provide the concept for future APIs.
        """
        pass

    def __repr__(self) -> str:
        return f"<OllamaModel: {self.name} ({self.role})>"
