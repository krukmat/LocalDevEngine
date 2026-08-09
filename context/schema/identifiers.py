"""
Deterministic identifier check — the measurement instrument, not a feature.

Everything else in the receipt is self-reported by the same pipeline being
audited, so `qa_approved: true` is only ever a claim. This check is different:
it is pure string comparison against an artifact the CALLER supplied, with no
model in the loop, so the caller can recompute the exact same answer from the
implementation text and the snapshot it already has. That makes it the one
signal in the receipt that can raise a caller's confidence rather than only
lower it (docs/plan-schema-grounding.md §2, Fase 2).

Conservative by design. It only looks at positions that are unambiguously
relational — after FROM/JOIN/INTO/UPDATE/TABLE, and `prefix.column` where the
prefix resolves to a known table or a table alias bound in the same text. A
`self.config` or `payload.id` is never counted. The cost of that choice is
recall: real invented columns written outside those positions are missed. The
benefit is that a non-zero `unknown` result is worth acting on, which a noisy
checker would not be.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .base import SchemaSnapshot

_IDENT = r"[A-Za-z_][A-Za-z0-9_$]*"
_QUOTED = r"[\"'`\[]?"

# A table reference in an unambiguous relational position.
_TABLE_REF_RE = re.compile(
    rf"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+{_QUOTED}({_IDENT}(?:\.{_IDENT})?){_QUOTED}",
    re.IGNORECASE,
)

# `FROM users u` / `JOIN orders AS o` — alias binding, so `u.email` can be checked.
_ALIAS_RE = re.compile(
    rf"\b(?:FROM|JOIN|UPDATE)\s+{_QUOTED}({_IDENT}(?:\.{_IDENT})?){_QUOTED}\s+"
    rf"(?:AS\s+)?({_IDENT})\b",
    re.IGNORECASE,
)

_DOTTED_RE = re.compile(rf"\b({_IDENT})\.({_IDENT})\b")

# Words that follow FROM/JOIN in prose or in non-SQL code and are never tables.
_NOT_A_TABLE = {
    "select", "where", "the", "a", "an", "this", "that", "it", "import", "type",
    "typing", "dataclasses", "abc", "os", "sys", "re", "json", "yaml",
}

# Aliases that are almost always a language construct, not a table alias.
_NOT_AN_ALIAS = {"self", "cls", "this", "super", "where", "on", "set", "select", "values"}


@dataclass
class IdentifierCheck:
    ran: bool = True
    known_tables: List[str] = field(default_factory=list)
    unknown_tables: List[str] = field(default_factory=list)
    known_columns: List[str] = field(default_factory=list)
    unknown_columns: List[str] = field(default_factory=list)
    checked: int = 0

    @property
    def unknown_count(self) -> int:
        return len(self.unknown_tables) + len(self.unknown_columns)

    def to_dict(self) -> Dict[str, object]:
        return {
            "ran": self.ran,
            "checked": self.checked,
            "unknown_count": self.unknown_count,
            "known_tables": self.known_tables,
            "unknown_tables": self.unknown_tables,
            "known_columns": self.known_columns,
            "unknown_columns": self.unknown_columns,
        }


def _clean(name: str) -> str:
    return name.strip().strip("\"'`[]")


def check_identifiers(text: str, snapshot: SchemaSnapshot) -> IdentifierCheck:
    """
    Compares relational identifiers found in `text` against the snapshot.

    Note what "unknown" means and does not mean: it means the identifier is not
    in the snapshot the caller provided. If the snapshot is partial — because
    selection omitted tables, or because the caller exported a subset — an
    identifier can be flagged while being perfectly real. The receipt reports
    which tables were actually shown for exactly this reason.
    """
    if not text or not snapshot.tables:
        return IdentifierCheck(ran=False)

    result = IdentifierCheck()

    # 1. Alias bindings first, so dotted refs can resolve through them.
    aliases: Dict[str, str] = {}
    for match in _ALIAS_RE.finditer(text):
        table_name = _clean(match.group(1))
        alias = _clean(match.group(2))
        if alias.lower() in _NOT_AN_ALIAS or table_name.lower() in _NOT_A_TABLE:
            continue
        table = snapshot.get(table_name)
        if table is not None:
            aliases[alias.lower()] = table.qualified_name

    # 2. Table references.
    seen_tables: Set[str] = set()
    for match in _TABLE_REF_RE.finditer(text):
        raw = _clean(match.group(1))
        if not raw or raw.lower() in _NOT_A_TABLE:
            continue
        key = raw.lower()
        if key in seen_tables:
            continue
        seen_tables.add(key)
        result.checked += 1
        table = snapshot.get(raw)
        if table is not None:
            result.known_tables.append(table.qualified_name)
        else:
            result.unknown_tables.append(raw)

    # 3. Dotted column references, only where the prefix resolves to a real table.
    seen_columns: Set[str] = set()
    for match in _DOTTED_RE.finditer(text):
        prefix = _clean(match.group(1))
        column = _clean(match.group(2))
        if not prefix or not column:
            continue
        prefix_key = prefix.lower()
        table_name = aliases.get(prefix_key)
        table = snapshot.get(table_name) if table_name else snapshot.get(prefix)
        if table is None:
            continue  # not relational — a module, an object, an unrelated attribute
        ref = f"{table.qualified_name}.{column}"
        if ref.lower() in seen_columns:
            continue
        seen_columns.add(ref.lower())
        result.checked += 1
        if table.has_column(column):
            result.known_columns.append(ref)
        else:
            result.unknown_columns.append(ref)

    result.known_tables.sort()
    result.unknown_tables.sort()
    result.known_columns.sort()
    result.unknown_columns.sort()
    return result
