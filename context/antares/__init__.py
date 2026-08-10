"""
Antares security triage: opt-in (--cwe-check) advisor layer over the final
implementation. See docs/plan-security-advisor-antares.md.

Public surface grows as context/antares/invoke.py lands.
"""
from .base import AntaresFinding, AntaresInvocationError, AntaresResult
from .materialize import MaterializedImplementation, materialize_implementation

__all__ = [
    "AntaresFinding",
    "AntaresInvocationError",
    "AntaresResult",
    "MaterializedImplementation",
    "materialize_implementation",
]
