import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "1.0"


def query_sha256(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def build_config_fingerprint(config: Dict[str, Any]) -> Dict[str, Any]:
    """Snapshot of the config knobs that change what a receipt's signals mean.
    A caller comparing this against its own expected config can tell "the gate
    ran and approved" apart from "the gate was off by config" (see
    docs/plan-mitigation-fenix-outsourcing-controls.md, paso A4 / control B2)."""
    roles = config.get("roles", {})
    pipeline = config.get("pipeline", {})
    retrieval = config.get("retrieval", {})
    return {
        "models": {role: cfg.get("model_name") for role, cfg in roles.items()},
        "max_qa_iterations": pipeline.get("max_qa_iterations", 2),
        "closing_report_enabled": pipeline.get("closing_report", True),
        "retrieval": {
            "top_k": retrieval.get("top_k", 5),
            "min_score": retrieval.get("min_score", 0.0),
            "max_context_chars": retrieval.get("max_context_chars", 3000),
        },
    }


def build_receipt(
    *,
    status: str,
    query: str,
    started_at: datetime,
    finished_at: datetime,
    config: Dict[str, Any],
    request_id: str,
    trace: List[Dict[str, Any]],
    macro_iteration: int = 1,
    outcome: Optional[Dict[str, Any]] = None,
    artifacts: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Single construction point for the receipt shape (see
    docs/plan-receipt-interface-callers.md). Both the success path and the
    failure/timeout path of run_complex_task call this, so the CLI and any
    library caller always see the same object regardless of outcome.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "status": status,
        "query": query,
        "query_sha256": query_sha256(query),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_ms": round((finished_at - started_at).total_seconds() * 1000, 1),
        "macro_iteration": macro_iteration,
        "outcome": outcome or {},
        "config_fingerprint": build_config_fingerprint(config),
        "artifacts": artifacts or {},
        "trace": trace,
        "error": error,
    }


def now() -> datetime:
    return datetime.now(timezone.utc)
