"""
Schema grounding: deterministic relational context for the pipeline.

Public surface, in the order the orchestrator uses it:

    provider  = SnapshotFileProvider(path)      # caller-supplied JSON/YAML
    snapshot  = provider.load()                 # -> SchemaSnapshot (or SchemaSnapshotError)
    selection = select_tables(snapshot, query)  # lexical match + FK closure
    block, shown, dropped = render_schema_block(selection, snapshot)
    check     = check_identifiers(implementation, snapshot)   # deterministic audit

See docs/plan-schema-grounding.md.
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
