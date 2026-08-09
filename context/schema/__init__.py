"""
Schema grounding: deterministic relational context for the pipeline.

Public surface, in the order the orchestrator uses it:

    provider  = SnapshotFileProvider(path)      # caller-supplied JSON/YAML
    snapshot  = provider.load()                 # -> SchemaSnapshot (or SchemaSnapshotError)
    selection = select_tables(snapshot, query)  # lexical match + FK closure
    block, shown, dropped = render_schema_block(selection, snapshot)
    report    = check(implementation, snapshot, allow_new_objects)  # typed conformance report

`check` (conformance.py) is the AST-based verifier from
docs/plan-schema-conformance.md — it replaces `check_identifiers` on the
orchestrator's path (core/orchestrator.py). `check_identifiers` is kept
importable for now but is no longer wired into any request: Fase 3
(docs/fase3-decision.md) found its regex approach both over-flags (Python
imports matching SQL keywords) and under-recognizes (SQLAlchemy declarative
syntax), which `check`'s typed, AST-based report was built to fix — see
docs/plan-schema-conformance.md §1 for the full diagnosis.

See docs/plan-schema-grounding.md (selection/render) and
docs/plan-schema-conformance.md (check).
"""
from .base import (
    IR_VERSION,
    Column,
    ForeignKey,
    SchemaProvider,
    SchemaSnapshot,
    SchemaSnapshotError,
    Table,
)
from .conformance import ConformanceReport, Violation, check
from .identifiers import IdentifierCheck, check_identifiers
from .render import render_schema_block, render_table
from .selection import SelectionResult, select_tables, tokenize
from .snapshot import SnapshotFileProvider, parse_snapshot

__all__ = [
    "IR_VERSION",
    "Column",
    "ForeignKey",
    "SchemaProvider",
    "SchemaSnapshot",
    "SchemaSnapshotError",
    "Table",
    "ConformanceReport",
    "Violation",
    "check",
    "IdentifierCheck",
    "check_identifiers",
    "render_schema_block",
    "render_table",
    "SelectionResult",
    "select_tables",
    "tokenize",
    "SnapshotFileProvider",
    "parse_snapshot",
]
