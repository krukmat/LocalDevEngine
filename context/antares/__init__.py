"""
Antares security triage: opt-in (--cwe-check) advisor layer over the final
implementation. See docs/plan-security-advisor-antares.md.

Public surface grows as context/antares/{materialize,invoke}.py land.
"""
from .base import AntaresFinding, AntaresInvocationError, AntaresResult

__all__ = [
    "AntaresFinding",
    "AntaresInvocationError",
    "AntaresResult",
]
