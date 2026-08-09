import httpx
import json
from typing import AsyncIterator, Dict, Any, Optional, Union
from models.base import BaseModel, ModelCallError

class OllamaModel(BaseModel):
    """
    Concrete implementation of BaseModel for the Ollama API.
    Uses HTTP requests to interact with a local Ollama server.
    """

    def __init__(self, name: str, role: str, capabilities: list[str], api_url: str = "http://localhost:11434/api",
                 timeout: float = 300.0, think: Optional[bool] = None, temperature: Optional[float] = None,
                 keep_alive: Optional[Union[str, int, float]] = None):
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
        # None = Ollama/model default (usually 0.8). Lower values reduce sampling
        # randomness — used for the router, whose classification should be stable
        # for the same input rather than creative.
        self.temperature = temperature
        # None = Ollama's own default (~5m idle retention). Accepts a duration string
        # ("10m", "1h"), a plain number of seconds, 0 (unload right after this response),
        # or a negative number (keep loaded indefinitely). No role sets this yet — see
        # docs/plan-model-lifecycle-keep-alive.md.
        self.keep_alive = keep_alive

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
        if self.temperature is not None:
            payload["options"] = {"temperature": self.temperature}
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # Using /api/generate for simple text responses as requested by prompt
                response = await client.post(f"{self.api_url}/generate", json=payload, timeout=self.timeout)
                response.raise_for_status()
                return response.json().get("response", "")
            except httpx.HTTPError as e:
                # Never return the error as if it were generated content — a caller
                # (e.g. QA auditing the "plan") must not be able to mistake a failed
                # call for real output.
                raise ModelCallError(str(e) or type(e).__name__) from e

    async def generate_stream(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> AsyncIterator[str]:
        """
        Streams the Ollama generation endpoint via NDJSON (stream: true). Each line
        is a JSON object with a "response" fragment and a "done" flag; the last line
        also carries the same fields /api/generate returns non-streamed, but we only
        need "response" and "done" here.
        """
        payload = {
            "model": self.name,
            "prompt": prompt,
            "stream": True,
        }
        if context and "system_prompt" in context:
            payload["system"] = context["system_prompt"]
        if self.think is not None:
            payload["think"] = self.think
        if self.temperature is not None:
            payload["options"] = {"temperature": self.temperature}
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream("POST", f"{self.api_url}/generate", json=payload, timeout=self.timeout) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        text = chunk.get("response", "")
                        if text:
                            yield text
                        if chunk.get("done"):
                            break
            except httpx.HTTPError as e:
                raise ModelCallError(str(e) or type(e).__name__) from e

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
            except httpx.HTTPError:
                pass  # Just ensuring we know it's there

    async def unload(self):
        """
        Evicts the model from VRAM immediately via Ollama's documented mechanism:
        a generate call with keep_alive: 0 and no prompt. This forces eviction now,
        overriding whatever self.keep_alive (or Ollama's own default) would otherwise
        retain — that's the whole point of calling this explicitly.

        Raises:
            ModelCallError: if the call fails (HTTP/transport error).
        """
        payload = {"model": self.name, "keep_alive": 0, "stream": False}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(f"{self.api_url}/generate", json=payload, timeout=self.timeout)
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise ModelCallError(str(e) or type(e).__name__) from e

    def __repr__(self) -> str:
        return f"<OllamaModel: {self.name} ({self.role})>"
