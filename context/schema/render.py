"""
Rendering the selected tables into a prompt block.

Two rules shape everything here:

1. **No scores, ever.** Retrieved chunks carry `(score=0.412)` because they are
   suggestions whose relevance is uncertain. A schema fact is not uncertain, and
   attaching a number to it invites the model to weigh it the same way.
2. **The authority is stated in the text, not implied by position.** The model
   cannot see which Python module produced which part of its prompt. If the
   deterministic block is not labelled as deterministic, it is just more prose.
"""
from typing import List, Optional, Tuple

from .base import SchemaSnapshot, Table
from .selection import SelectionResult

_HEADER = (
    "=== DETERMINISTIC SCHEMA (AUTHORITATIVE) ===\n"
    "The structural facts below were supplied by the caller from the real database\n"
    "schema. They are ASSERTED, not retrieved, and carry no relevance score: unlike\n"
    "the project context above, they are not suggestions.\n"
    "Rules you must follow:\n"
    "  - Do NOT invent tables, columns, types or relations that are absent here.\n"
    "  - If something you need is missing from this block, say so explicitly in your\n"
    "    output instead of assuming it exists.\n"
    "  - Where this block and the retrieved project context disagree, this block wins.\n"
)

_FOOTER = "=== END DETERMINISTIC SCHEMA ===\n"


def _render_column(column, name_width: int, type_width: int) -> str:
    flags = []
    if column.primary_key:
        flags.append("PK")
    null = "NOT NULL" if not column.nullable else "NULL"
    line = f"  {column.name.ljust(name_width)}  {column.type.ljust(type_width)}  {null}"
    if flags:
        line += "  " + " ".join(f"[{f}]" for f in flags)
    if column.default:
        line += f"  DEFAULT {column.default}"
    if column.comment:
        line += f"  -- {column.comment}"
    return line


def render_table(table: Table) -> str:
    name_width = max((len(c.name) for c in table.columns), default=4)
    type_width = max((len(c.type) for c in table.columns), default=7)
    lines = [f"TABLE {table.qualified_name}"]
    if table.comment:
        lines.append(f"  -- {table.comment}")
    for column in table.columns:
        lines.append(_render_column(column, name_width, type_width))
    if table.primary_key:
        lines.append(f"  PRIMARY KEY ({', '.join(table.primary_key)})")
    for fk in table.foreign_keys:
        target = fk.references_table
        if fk.references_columns:
            target += f"({', '.join(fk.references_columns)})"
        lines.append(f"  FOREIGN KEY ({', '.join(fk.columns)}) -> {target}")
    return "\n".join(lines)


def render_schema_block(
    selection: SelectionResult,
    snapshot: SchemaSnapshot,
    *,
    max_chars: int = 4000,
) -> Tuple[str, List[str], List[str]]:
    """
    Renders the selected tables, dropping whole tables from the end (lowest
    priority first, since selection.tables is already ordered) until the block
    fits max_chars.

    Returns (block_text, rendered_table_names, dropped_table_names). Dropping is
    reported rather than silent: a table the selector wanted but the budget cut
    is exactly the case where the model is most likely to invent it.

    There is an irreducible floor: the authority header plus one table. Below
    that, max_chars is deliberately exceeded rather than honored, because a
    schema block stripped of its header is not a cheaper schema block — it is
    indistinguishable from the retrieved prose around it, which is the one thing
    this layer exists to prevent. The caller sees the overflow as
    outcome.schema_grounding.block_over_budget rather than having it hidden.
    """
    if not selection.tables:
        return "", [], []

    def _build(kept: List, dropped_names: List[str]) -> str:
        summary = f"# tables shown: {len(kept)} of {len(snapshot.tables)} in the snapshot"
        if snapshot.dialect:
            summary += f" | dialect: {snapshot.dialect}"
        if selection.strategy == "all":
            summary += " | no table name matched the request, so the whole snapshot is shown"
        elif selection.related:
            summary += f" | {len(selection.related)} included via foreign-key closure"

        not_shown = selection.omitted + dropped_names
        if not_shown:
            preview = ", ".join(not_shown[:12])
            if len(not_shown) > 12:
                preview += f", ... (+{len(not_shown) - 12} more)"
            summary += (
                f"\n# NOT shown (exist in the database, details unavailable here): {preview}"
                f"\n# If you need one of these, state that you need it — do not guess its columns."
            )
        bodies = "\n\n".join(render_table(t) for t in kept)
        return _HEADER + summary + "\n\n" + bodies + "\n" + _FOOTER

    # Shrink-to-fit rather than pack-with-a-reserve: the summary line grows with the
    # number of omitted tables, so dropping a table changes the size of the header
    # block itself. Estimating that in advance is what made an earlier version
    # overshoot max_chars; measuring the real assembled block cannot. Bounded by
    # max_tables (a dozen at most), so the repeated rendering is free.
    kept = list(selection.tables)
    dropped: List[str] = []
    block = _build(kept, dropped)
    while len(block) > max_chars and len(kept) > 1:
        dropped.insert(0, kept.pop().qualified_name)
        block = _build(kept, dropped)

    return block, [t.qualified_name for t in kept], dropped
