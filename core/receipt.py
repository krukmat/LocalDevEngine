import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# 1.0 -> 1.1: outcome gained schema_grounding and context_budget blocks, outcome.rag
# gained chunks_eligible (and its context_chars now reports what actually reached the
# prompt, not what one stage produced in isolation), and config_fingerprint gained a
# "request" sub-block for per-request parameters. All additive — a 1.0 consumer reading
# only the keys it knows keeps working.
# 1.1 -> 1.2: outcome gains security_triage (see docs/plan-security-advisor-antares.md),
# config_fingerprint gains a security_triage config block, and request_params gains
# cwe_checks_requested. Additive — a 1.1 consumer reading only known keys keeps working.
SCHEMA_VERSION = "1.2"


def query_sha256(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def build_config_fingerprint(
    config: Dict[str, Any], request_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Snapshot of the knobs that change what a receipt's signals mean.
    A caller comparing this against its own expected config can tell "the gate
    ran and approved" apart from "the gate was off by config" (see
    docs/plan-mitigation-fenix-outsourcing-controls.md, paso A4 / control B2).

    Config alone was not enough: output_contract and schema grounding are chosen
    per REQUEST, so a caller reading only config could not tell whether the
    contract it asked for was actually in force. request_params closes that —
    same purpose, different lifetime, hence its own sub-block rather than being
    flattened in with the config knobs."""
    roles = config.get("roles", {})
    pipeline = config.get("pipeline", {})
    retrieval = config.get("retrieval", {})
    schema_cfg = config.get("schema_grounding", {})
    security_cfg = config.get("security_triage", {})
    return {
        "models": {role: cfg.get("model_name") for role, cfg in roles.items()},
        "max_qa_iterations": pipeline.get("max_qa_iterations", 2),
        "closing_report_enabled": pipeline.get("closing_report", True),
        "retrieval": {
            "top_k": retrieval.get("top_k", 5),
            "min_score": retrieval.get("min_score", 0.0),
            "max_context_chars": retrieval.get("max_context_chars", 3000),
            "breakdown_reserve_chars": retrieval.get("breakdown_reserve_chars", 1200),
        },
        "schema_grounding": {
            "max_tables": schema_cfg.get("max_tables", 12),
            "max_chars": schema_cfg.get("max_chars", 4000),
            "fk_expansion_depth": schema_cfg.get("fk_expansion_depth", 1),
            "identifier_check": schema_cfg.get("identifier_check", True),
            "allow_new_objects": schema_cfg.get("allow_new_objects", True),
        },
        "security_triage": {
            "binary": security_cfg.get("binary", "antares"),
            "profile": security_cfg.get("profile"),
            "timeout_seconds": security_cfg.get("timeout_seconds", 300),
        },
        "request": request_params or {},
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
    request_params: Optional[Dict[str, Any]] = None,
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
        "config_fingerprint": build_config_fingerprint(config, request_params),
        "artifacts": artifacts or {},
        "trace": trace,
        "error": error,
    }


def now() -> datetime:
    return datetime.now(timezone.utc)
