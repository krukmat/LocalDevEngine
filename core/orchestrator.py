import logging
import re
import time
from typing import Callable, Optional, List, Dict, Any, Tuple
import yaml
import os

from models.factory import ModelFactory
from memory.embeddings import EmbeddingService
from memory.local_memory import LocalVectorMemory
from prompts.specialized_prompts import PromptRegistry
from context.schema import (
    SchemaSnapshot,
)
from core.pipeline.context import PipelineContext
from core.pipeline.context_stages import RouterStage
from core.pipeline.runner import PipelineRunner
from context.antares import (
    AntaresInvocationError,
    materialize_implementation,
    run_antares_query,
)
from dataclasses import asdict

_VERDICT_RE = re.compile(r"VERDICT:\s*(APPROVED|NEEDS_REVISION)", re.IGNORECASE)
_FEEDBACK_RE = re.compile(r"FEEDBACK:\s*(.*)", re.IGNORECASE | re.DOTALL)
_DEVIATION_RE = re.compile(r"DEVIATION:\s*(NONE|JUSTIFIED|UNEXPLAINED)", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"SUMMARY:\s*(.*)", re.IGNORECASE | re.DOTALL)


# Library convention: get a module logger and emit to it, but never call
# logging.basicConfig() or attach handlers here. Configuring handlers/levels
# is the application's job (see main.py) — doing it here would clobber the
# logging setup of anything that imports this package (e.g. a commercial
# agent embedding Orchestrator in its own service).
logger = logging.getLogger(__name__)


class Orchestrator:
    """
    The central brain of the system. Implements a state-driven workflow
    to manage tasks through different specialized models (Layers).
    """

    ROUTER_CATEGORIES = ("SIMPLE_TASK", "COMPLEX_ARCHITECTURE", "CODING_REQUEST", "ERROR_REACTION")
    FAST_PATH_CATEGORIES = ("SIMPLE_TASK", "ERROR_REACTION")

    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        timeout = self.config.get('pipeline', {}).get('request_timeout_seconds', 300.0)
        # LDE_OLLAMA_HOST lets a caller running its own Ollama on a non-default host/port
        # (e.g. fenix, see docs/plan-mitigation-fenix-outsourcing-controls.md paso A7)
        # override the hardcoded localhost default without editing settings.yaml.
        api_url = os.environ.get("LDE_OLLAMA_HOST", "http://localhost:11434/api")
        self.factory = ModelFactory(self.config, api_url=api_url)
        self.memory = LocalVectorMemory(
            self.config['storage']['vector_db_path'],
            dimension=self.config['embeddings']['dimension'],
        )
        self.embedder = EmbeddingService(
            self.config['embeddings']['model_name'], api_url=api_url, timeout=timeout
        )
        self.prompts = PromptRegistry()
        self._pipeline_runner = PipelineRunner(
            config=self.config, factory=self.factory, memory=self.memory, embedder=self.embedder,
            prompts=self.prompts, call_model=self._call_model,
            parse_verdict=self._parse_verdict, parse_closing_report=self._parse_closing_report,
            run_security_triage=self._run_security_triage,
            router_categories=self.ROUTER_CATEGORIES,
            fast_path_categories=self.FAST_PATH_CATEGORIES, logger=logger,
        )

    async def aclose(self) -> None:
        """Releases resources held by the Orchestrator (currently: the embedder's HTTP
        client). A caller embedding this as a library should use this or the async
        context manager instead of reaching into self.embedder directly."""
        await self.embedder.aclose()

    async def __aenter__(self) -> "Orchestrator":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def _call_model(
        self,
        *,
        role: str,
        stage: str,
        model,
        prompt: str,
        request_id: str,
        attempt: Optional[int] = None,
        on_chunk: Optional[Callable[[str, str, Optional[int]], None]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Calls a role model with its system prompt, logs the call, and returns
        (response, trace_entry). trace_entry is a plain dict the caller owns —
        it is never stored on `self`, so concurrent run_complex_task() calls on
        the same Orchestrator instance never share mutable state.

        If on_chunk is given, streams the call via model.generate_stream() and
        invokes on_chunk(text, stage, attempt) per fragment as it arrives — stage
        and attempt let the caller (e.g. the CLI) print a header once per distinct
        stage/attempt instead of one flat unlabeled stream. The full response is
        still assembled and returned exactly as generate() would, since callers
        feed it into later stages. Without on_chunk, behavior is unchanged
        (single non-streamed call).
        """
        start = time.monotonic()
        if on_chunk is not None:
            parts = []
            async for text in model.generate_stream(
                prompt,
                context={"system_prompt": self.prompts.get_system_prompt(role)}
            ):
                parts.append(text)
                on_chunk(text, stage, attempt)
            response = "".join(parts)
        else:
            response = await model.generate(
                prompt,
                context={"system_prompt": self.prompts.get_system_prompt(role)}
            )
        duration_ms = (time.monotonic() - start) * 1000

        entry = {
            "request_id": request_id,
            "stage": stage,
            "role": role,
            "model": model.name,
            "attempt": attempt,
            "duration_ms": round(duration_ms, 1),
            "verdict": None,
        }
        logger.info(
            "stage=%s role=%s model=%s attempt=%s duration_ms=%.1f",
            stage, role, model.name, attempt, duration_ms,
            extra={"request_id": request_id, "stage": stage, "role": role,
                   "model": model.name, "attempt": attempt}
        )
        return response, entry

    async def _get_router_decision(self, user_query: str, request_id: str, trace: List[Dict[str, Any]]) -> str:
        """Compatibility adapter for diagnostic callers of the extracted router stage."""
        ctx = PipelineContext(
            user_query=user_query, request_id=request_id, trace=trace, on_chunk=None,
            prior_breakdown=None, prior_report=None, macro_iteration=1, output_contract=None,
        )
        stage = RouterStage(
            factory=self.factory, call_model=self._call_model,
            categories=self.ROUTER_CATEGORIES, fast_path_categories=self.FAST_PATH_CATEGORIES,
            logger=logger,
        )
        await stage.run(ctx)
        return ctx.decision or "COMPLEX_ARCHITECTURE"

    def _parse_verdict(self, qa_response: str) -> Tuple[bool, str]:
        """
        Parses a QA Auditor response formatted as 'VERDICT: ...' / 'FEEDBACK: ...'.
        Fails closed: if VERDICT isn't recognized, treats it as not approved.
        """
        verdict_match = _VERDICT_RE.search(qa_response)
        feedback_match = _FEEDBACK_RE.search(qa_response)
        feedback = feedback_match.group(1).strip() if feedback_match else qa_response.strip()
        approved = bool(verdict_match) and verdict_match.group(1).upper() == "APPROVED"
        return approved, feedback

    def _parse_closing_report(self, report_text: str) -> Tuple[str, str]:
        """
        Parses the Manager's closing report ('DEVIATION: ...' / 'SUMMARY: ...').
        Unlike _parse_verdict, this fails SOFT: an unparseable report must never
        block the pipeline, since nothing downstream depends on it — it's a report,
        not a gate. Missing/unrecognized DEVIATION becomes "UNKNOWN" and the raw
        text is kept as the summary so a human can still read it.
        """
        deviation_match = _DEVIATION_RE.search(report_text)
        summary_match = _SUMMARY_RE.search(report_text)
        if not deviation_match:
            return "UNKNOWN", report_text.strip()
        summary = summary_match.group(1).strip() if summary_match else report_text.strip()
        return deviation_match.group(1).upper(), summary

    async def _run_security_triage(
        self,
        cwe_checks: Optional[List[Tuple[str, str]]],
        body: Dict[str, Any],
        output_contract: Optional[str],
        request_id: str,
    ) -> Dict[str, Any]:
        """
        Opt-in Antares security triage over the final implementation. Never
        propagates an exception — a failure here can only degrade its own
        outcome.security_triage block, never the pipeline's own status (I1,
        docs/plan-security-advisor-antares.md).
        """
        requested = [{"cwe_id": c, "rationale": r} for c, r in (cwe_checks or [])]
        if not cwe_checks:
            return {
                "ran": False, "terminal_state": "not-requested", "degraded": False,
                "requested": [], "stdout_sha256": None, "findings": [],
            }
        if body["outcome"]["fast_path"]:
            return {
                "ran": False, "terminal_state": "snapshot-unavailable", "degraded": True,
                "reason": "fast-path", "requested": requested, "stdout_sha256": None,
                "findings": [],
            }
        implementation = body["artifacts"].get("implementation")
        if not implementation:
            return {
                "ran": False, "terminal_state": "artifact-missing", "degraded": True,
                "requested": requested, "stdout_sha256": None, "findings": [],
            }
        cfg = self.config.get("security_triage", {})
        try:
            with materialize_implementation(implementation, output_contract) as mat:
                result = await run_antares_query(
                    mat.snapshot_dir, mat.data_dir, cwe_checks,
                    binary=cfg.get("binary", "antares"),
                    profile=cfg.get("profile"),
                    timeout_seconds=cfg.get("timeout_seconds", 300),
                )
            return {
                "ran": True, "terminal_state": result.terminal_state,
                "degraded": result.degraded, "requested": requested,
                "stdout_sha256": result.stdout_sha256,
                "findings": [asdict(f) for f in result.findings],
            }
        except AntaresInvocationError as e:
            logger.warning(
                "Security triage degraded: %s", e,
                extra={"request_id": request_id, "stage": "security_triage"}
            )
            return {
                "ran": True, "terminal_state": e.terminal_state, "degraded": True,
                "requested": requested, "stdout_sha256": None, "findings": [],
            }
        except Exception:
            logger.exception(
                "Unexpected error during security triage",
                extra={"request_id": request_id, "stage": "security_triage"}
            )
            return {
                "ran": True, "terminal_state": "internal-error", "degraded": True,
                "requested": requested, "stdout_sha256": None, "findings": [],
            }

    async def run_complex_task(
        self,
        user_query: str,
        on_chunk: Optional[Callable[[str, str, Optional[int]], None]] = None,
        prior_breakdown: Optional[str] = None,
        prior_report: Optional[str] = None,
        macro_iteration: int = 1,
        output_contract: Optional[str] = None,
        schema_snapshot: Optional[SchemaSnapshot] = None,
        cwe_checks: Optional[List[Tuple[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Run a task through the pipeline while preserving the public API."""
        return await self._pipeline_runner.run_complex_task(
            user_query, on_chunk=on_chunk, prior_breakdown=prior_breakdown,
            prior_report=prior_report, macro_iteration=macro_iteration,
            output_contract=output_contract, schema_snapshot=schema_snapshot,
            cwe_checks=cwe_checks,
        )
