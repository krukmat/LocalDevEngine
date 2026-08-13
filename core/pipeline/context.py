"""
PipelineContext (O3, docs/plan-p1-refactor-orchestrator.md): Parameter Object for the
state _run_pipeline_body threads through router -> context assembly -> design gate ->
implementation loop -> closing report. Objectifying this state is what lets O5-O9 pull
each stage out into its own module without every extraction changing that stage's
function signature every time a later stage needs one more field.

No behavior lives here. Fields are grouped by when they're known: inputs are set once
at construction (mirroring _run_pipeline_body's own parameters), everything else starts
at its natural "not yet run" value and is filled in by the stage that produces it.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from context.schema import SchemaSnapshot


@dataclass
class OutcomeRecorder:
    """Own the per-stage receipt data while the pipeline is running.

    Each stage records whether it ran at the point where that fact is known.
    The Orchestrator can then add its two run-wide values (router decision and
    fast-path flag) without reconstructing stage results from unrelated locals.
    """

    _stages: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def record(self, stage: str, data: Dict[str, Any]) -> None:
        if "ran" not in data:
            raise ValueError(f"Outcome for {stage!r} must declare 'ran'")
        self._stages[stage] = deepcopy(data)

    def update(self, stage: str, **data: Any) -> None:
        if stage not in self._stages:
            raise KeyError(f"Cannot update unrecorded outcome stage {stage!r}")
        self._stages[stage].update(deepcopy(data))

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return deepcopy(self._stages)


@dataclass
class PipelineContext:
    # --- Inputs (set once, from _run_pipeline_body's own parameters) ---
    user_query: str
    request_id: str
    trace: List[Dict[str, Any]]
    on_chunk: Optional[Callable[[str, str, Optional[int]], None]]
    prior_breakdown: Optional[str]
    prior_report: Optional[str]
    macro_iteration: int
    output_contract: Optional[str]
    schema_snapshot: Optional[SchemaSnapshot] = None
    outcomes: OutcomeRecorder = field(default_factory=OutcomeRecorder)

    # --- Router ---
    decision: Optional[str] = None

    # --- Context assembly ---
    schema_block: str = ""
    schema_stats: Dict[str, Any] = field(default_factory=lambda: {"ran": False})
    rag_pieces: List[Any] = field(default_factory=list)
    rag_stats: Dict[str, Any] = field(default_factory=dict)
    context: str = ""
    budget_stats: Dict[str, Any] = field(default_factory=dict)

    # --- Manager task breakdown ---
    breakdown: Optional[str] = None

    # --- Architect / design gate ---
    plan: Optional[str] = None
    design_gate_outcome: Optional[Dict[str, Any]] = None

    # --- Implementer / implementation check ---
    implementation: Optional[str] = None
    qa_approved: bool = False
    qa_feedback: Optional[str] = None
    implementation_check_attempts: int = 0

    # --- Manager closing report ---
    closing_report: Optional[str] = None
    deviation: Optional[str] = None
    summary: Optional[str] = None
