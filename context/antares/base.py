"""
Antares security triage — normalized result shapes for the opt-in
(--cwe-check) advisor layer. See docs/plan-security-advisor-antares.md.

Mirrors context/schema/base.py: this is the IR a caller-facing layer
returns, kept independent of how it was produced (invoke.py, T4) or
consumed (core/orchestrator.py, T6).
"""
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class AntaresFinding:
    title: str
    file_path: str
    cwe_ids: List[str]
    likelihood_of_exploit: str
    submission_rank: Optional[int]
    review_status: str = "pending"


@dataclass
class AntaresResult:
    findings: List[AntaresFinding]
    terminal_state: str
    degraded: bool
    stdout_sha256: Optional[str]


class AntaresInvocationError(RuntimeError):
    """Carries terminal_state as a typed attribute, mirroring
    ModelCallError.partial (models/base.py), so the orchestrator normalizes
    it into outcome.security_triage without parsing the exception message."""

    def __init__(self, message: str, terminal_state: str):
        super().__init__(message)
        self.terminal_state = terminal_state
