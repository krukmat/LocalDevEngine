import asyncio
import logging
import re
import time
import uuid
from typing import Optional, List, Dict, Any, Tuple
import yaml
import os

from models.factory import ModelFactory
from memory.embeddings import EmbeddingService
from memory.local_memory import LocalVectorMemory
from prompts.specialized_prompts import PromptRegistry

_VERDICT_RE = re.compile(r"VERDICT:\s*(APPROVED|NEEDS_REVISION)", re.IGNORECASE)
_FEEDBACK_RE = re.compile(r"FEEDBACK:\s*(.*)", re.IGNORECASE | re.DOTALL)

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
        self.factory = ModelFactory(self.config)
        self.memory = LocalVectorMemory(self.config['storage']['vector_db_path'])
        self.embedder = EmbeddingService(self.config['embeddings']['model_name'], timeout=timeout)
        self.prompts = PromptRegistry()

    async def _call_model(
        self,
        *,
        role: str,
        stage: str,
        model,
        prompt: str,
        request_id: str,
        attempt: Optional[int] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Calls a role model with its system prompt, logs the call, and returns
        (response, trace_entry). trace_entry is a plain dict the caller owns —
        it is never stored on `self`, so concurrent run_complex_task() calls on
        the same Orchestrator instance never share mutable state.
        """
        start = time.monotonic()
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
        """Uses the Router model to classify the intent into one of ROUTER_CATEGORIES."""
        router_model = self.factory.create_role_model("router")
        prompt = f"Classify this query: {user_query}"
        response, entry = await self._call_model(
            role="router", stage="routing", model=router_model,
            prompt=prompt, request_id=request_id
        )
        response_upper = response.strip().upper()
        # Small router models don't always follow "output only the category" strictly, so we
        # can't require exact equality. But we can't just scan for any category either: they
        # ramble *after* the answer, naming other categories to rule them out ("goes beyond a
        # SIMPLE_TASK") or echoing the list from the system prompt. Picking the first match in
        # ROUTER_CATEGORIES declaration order made those replies resolve to SIMPLE_TASK — a
        # fast-path category — and silently skip RAG/Architect/Implementer/QA entirely.
        #
        # They do reliably *lead* with the answer, so a response that starts with a category is
        # taken as decisive. Anything less clear falls back to whichever category appears
        # earliest, preferring non-fast-path ones: routing a simple query through the full
        # pipeline only costs time, while wrongly taking the fast path silently drops the work.
        decision = next((c for c in self.ROUTER_CATEGORIES if response_upper.startswith(c)), None)
        if decision is None:
            hits = sorted(
                (c in self.FAST_PATH_CATEGORIES, response_upper.find(c), c)
                for c in self.ROUTER_CATEGORIES if c in response_upper
            )
            decision = hits[0][2] if hits else None
        if decision is None:
            logger.warning(
                "Unrecognized router decision %r — defaulting to COMPLEX_ARCHITECTURE",
                response_upper[:80], extra={"request_id": request_id, "stage": "routing"}
            )
            decision = "COMPLEX_ARCHITECTURE"
        entry["decision"] = decision
        trace.append(entry)
        logger.info("Router decision: %s", decision, extra={"request_id": request_id, "stage": "routing"})
        return decision

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

    async def run_complex_task(self, user_query: str) -> Dict[str, Any]:
        """
        Main workflow: Router -> (fast path | RAG -> Manager -> Architect<->QA design gate
        -> Implementer<->QA implementation check).

        Returns a dict including "trace" (a list of per-stage event dicts: role, model,
        attempt, verdict, duration_ms) and "request_id", so a caller embedding this as a
        library gets a full structured audit record without parsing any logs.
        """
        request_id = uuid.uuid4().hex[:12]
        trace: List[Dict[str, Any]] = []
        logger.info("run_complex_task started", extra={"request_id": request_id, "stage": "start"})

        # 0. Router: classify and short-circuit simple/error-reaction queries
        decision = await self._get_router_decision(user_query, request_id, trace)
        if decision in self.FAST_PATH_CATEGORIES:
            logger.info(
                "Router fast path (%s) — skipping RAG/Architect/Implementer/QA", decision,
                extra={"request_id": request_id, "stage": "fast_path"}
            )
            manager = self.factory.create_role_model("manager")
            answer, entry = await self._call_model(
                role="manager", stage="fast_path", model=manager,
                prompt=user_query, request_id=request_id
            )
            trace.append(entry)
            return {
                "plan": None,
                "implementation": answer,
                "fast_path": True,
                "qa_approved": None,
                "qa_feedback": None,
                "request_id": request_id,
                "trace": trace,
            }

        max_iterations = self.config.get('pipeline', {}).get('max_qa_iterations', 2)

        # 1. Context Retrieval (RAG)
        logger.info("Searching local context", extra={"request_id": request_id, "stage": "rag"})
        query_vec = await self.embedder.get_embedding(user_query)
        relevant_chunks = self.memory.search(query_vec)
        context = "\n".join([c['text'] for c in relevant_chunks])
        if not context:
            context = "No existing local context found."

        # 2. Manager: break the goal into a step outline that guides the Architect
        manager = self.factory.create_role_model("manager")
        breakdown, entry = await self._call_model(
            role="manager", stage="task_breakdown", model=manager,
            prompt=self.prompts.get_manager_breakdown_template(context, user_query),
            request_id=request_id
        )
        trace.append(entry)
        context = f"{context}\n\nTASK BREAKDOWN (Manager):\n{breakdown}"
        logger.info("Context assembled (%d chars)", len(context), extra={"request_id": request_id, "stage": "task_breakdown"})

        # 3. Architecture Phase with QA design gate (pre-implementation)
        architect = self.factory.create_role_model("architect")
        qa_auditor = self.factory.create_role_model("qa_auditor")

        plan, entry = await self._call_model(
            role="architect", stage="design_plan", model=architect,
            prompt=self.prompts.get_architect_thinking_template(context, user_query),
            request_id=request_id, attempt=1
        )
        trace.append(entry)

        for attempt in range(max_iterations + 1):
            review, qa_entry = await self._call_model(
                role="qa_auditor", stage="design_gate", model=qa_auditor,
                prompt=self.prompts.get_design_review_template(context, user_query, plan),
                request_id=request_id, attempt=attempt + 1
            )
            design_approved, design_feedback = self._parse_verdict(review)
            qa_entry["verdict"] = "APPROVED" if design_approved else "NEEDS_REVISION"
            trace.append(qa_entry)
            logger.info(
                "Design gate attempt %d: %s", attempt + 1, qa_entry["verdict"],
                extra={"request_id": request_id, "stage": "design_gate", "attempt": attempt + 1}
            )
            if design_approved:
                break
            if attempt == max_iterations:
                logger.warning(
                    "Design gate not approved after %d revisions — proceeding with last plan",
                    max_iterations, extra={"request_id": request_id, "stage": "design_gate"}
                )
                break
            plan, entry = await self._call_model(
                role="architect", stage="design_revision", model=architect,
                prompt=self.prompts.get_architect_revision_template(context, user_query, plan, design_feedback),
                request_id=request_id, attempt=attempt + 2
            )
            trace.append(entry)

        # 4. Implementation Phase with post-implementation QA check
        implementer = self.factory.create_role_model("implementer")

        implementation, entry = await self._call_model(
            role="implementer", stage="implementation", model=implementer,
            prompt=self.prompts.get_implementer_task_template(plan, context),
            request_id=request_id, attempt=1
        )
        trace.append(entry)

        qa_approved = False
        qa_feedback = None
        for attempt in range(max_iterations + 1):
            review, qa_entry = await self._call_model(
                role="qa_auditor", stage="implementation_check", model=qa_auditor,
                prompt=self.prompts.get_qa_review_template(context, user_query, plan, implementation),
                request_id=request_id, attempt=attempt + 1
            )
            qa_approved, qa_feedback = self._parse_verdict(review)
            qa_entry["verdict"] = "APPROVED" if qa_approved else "NEEDS_REVISION"
            trace.append(qa_entry)
            logger.info(
                "Implementation check attempt %d: %s", attempt + 1, qa_entry["verdict"],
                extra={"request_id": request_id, "stage": "implementation_check", "attempt": attempt + 1}
            )
            if qa_approved:
                qa_feedback = None
                break
            if attempt == max_iterations:
                logger.warning(
                    "Implementation not approved by QA after %d revisions",
                    max_iterations, extra={"request_id": request_id, "stage": "implementation_check"}
                )
                break
            # Design-level feedback loop: QA's implementation findings go back to the Architect first.
            plan, entry = await self._call_model(
                role="architect", stage="design_revision", model=architect,
                prompt=self.prompts.get_architect_revision_template(context, user_query, plan, qa_feedback),
                request_id=request_id, attempt=attempt + 2
            )
            trace.append(entry)
            implementation, entry = await self._call_model(
                role="implementer", stage="implementation", model=implementer,
                prompt=self.prompts.get_implementer_task_template(plan, context),
                request_id=request_id, attempt=attempt + 2
            )
            trace.append(entry)

        return {
            "plan": plan,
            "implementation": implementation,
            "fast_path": False,
            "qa_approved": qa_approved,
            "qa_feedback": qa_feedback,
            "request_id": request_id,
            "trace": trace,
        }

    async def run_simple_query(self, user_query: str) -> str:
        """Standalone quick-answer workflow (also used internally as the Router fast path)."""
        request_id = uuid.uuid4().hex[:12]
        logger.info("run_simple_query started", extra={"request_id": request_id, "stage": "fast_path"})
        manager = self.factory.create_role_model("manager")
        answer, _entry = await self._call_model(
            role="manager", stage="fast_path", model=manager,
            prompt=user_query, request_id=request_id
        )
        return answer
