"""
Which tables from the snapshot go into the prompt.

Convention-agnostic by requirement, not preference: this engine is generic, so
the selector cannot assume snake_case, cannot assume English pluralization, and
cannot assume any naming convention linking a query word to a table. It
tokenizes both sides the same way and matches. Where it is unsure, it INCLUDES —
a table shown unnecessarily costs prompt budget, a table omitted wrongly makes
the model invent it, and only the second failure is silent.

No scores are produced for the prompt. The relevance number computed here orders
and truncates the selection; it never reaches the rendered block, because a
score on a deterministic fact would invite the model to weigh it like retrieval
(docs/plan-schema-grounding.md §2).
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .base import SchemaSnapshot, Table

_NON_ALNUM_RE = re.compile(r"[^0-9a-zA-Z]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# Words that match too many tables to carry signal. Deliberately short: an
# aggressive stoplist in a generic engine risks dropping a real table name
# (a table literally called "user" or "data" is common).
_STOPWORDS = {
    "a", "an", "and", "the", "of", "for", "to", "in", "on", "with", "by", "from",
    "is", "are", "be", "que", "de", "la", "el", "los", "las", "un", "una", "y",
    "add", "create", "make", "new", "use", "using", "need", "want", "please",
    "code", "function", "method", "class", "file", "test", "implement",
}

# Tokens shorter than this never match on their own — "id", "at", "no" appear in
# almost every schema and would select everything.
_MIN_TOKEN_LEN = 3


def tokenize(text: str) -> Set[str]:
    """Splits text into lowercase tokens across separators AND camelCase humps,
    so `orderItems`, `order_items` and `order items` all yield {order, items}."""
    if not text:
        return set()
    spaced = _CAMEL_BOUNDARY_RE.sub(" ", text)
    tokens = set()
    for raw in _NON_ALNUM_RE.split(spaced):
        token = raw.strip().lower()
        if len(token) >= _MIN_TOKEN_LEN and token not in _STOPWORDS:
            tokens.add(token)
    return tokens


def _variants(token: str) -> Set[str]:
    """Crude, language-agnostic singular/plural folding. Intentionally dumb: it
    only strips/adds a trailing 's'/'es', which covers the overwhelming majority
    of table naming without encoding English morphology the engine can't assume."""
    out = {token}
    if token.endswith("ies") and len(token) > 4:
        out.add(token[:-3] + "y")
    if token.endswith("es") and len(token) > 3:
        out.add(token[:-2])
    if token.endswith("s") and len(token) > 3:
        out.add(token[:-1])
    else:
        out.add(token + "s")
    return out


def _fold(tokens: Set[str]) -> Set[str]:
    folded: Set[str] = set()
    for t in tokens:
        folded |= _variants(t)
    return folded


@dataclass
class SelectionResult:
    """What the selector decided, in a form the receipt can report verbatim."""
    tables: List[Table] = field(default_factory=list)
    matched: List[str] = field(default_factory=list)      # hit by a query token
    related: List[str] = field(default_factory=list)      # pulled in by FK closure
    omitted: List[str] = field(default_factory=list)      # in snapshot, left out
    strategy: str = "none"                                 # lexical | all | none
    degraded: bool = False
    reason: Optional[str] = None


def select_tables(
    snapshot: SchemaSnapshot,
    query: str,
    *,
    max_tables: int = 12,
    fk_expansion_depth: int = 1,
    include_all_if_no_match: bool = True,
) -> SelectionResult:
    """
    Picks the tables worth asserting for this query.

    Lexical match on table names and column names, then FK closure (both
    directions — a table referenced BY a match matters as much as one that
    references it). With no match at all, falls back to the whole snapshot when
    it is small enough to be worth it; the renderer's char cap is the real
    backstop, so this only has to avoid the pathological case.
    """
    query_tokens = _fold(tokenize(query))
    if not query_tokens:
        query_tokens = set()

    scores: Dict[str, float] = {}
    for table in snapshot.tables:
        name_tokens = _fold(tokenize(table.qualified_name))
        score = 3.0 * len(query_tokens & name_tokens)
        column_hits = 0
        for column in table.columns:
            if query_tokens & _fold(tokenize(column.name)):
                column_hits += 1
        # Column hits are capped: a wide table would otherwise outrank a table
        # whose *name* the user actually said, purely by having more columns.
        score += min(column_hits, 3) * 1.0
        if score > 0:
            scores[table.qualified_name] = score

    if not scores:
        if include_all_if_no_match:
            selected = list(snapshot.tables)[:max_tables]
            omitted = [t.qualified_name for t in snapshot.tables[max_tables:]]
            return SelectionResult(
                tables=selected,
                matched=[],
                related=[],
                omitted=omitted,
                strategy="all",
                degraded=True,
                reason="no_lexical_match_included_all",
            )
        return SelectionResult(
            strategy="none", degraded=True, reason="no_lexical_match"
        )

    matched_names = sorted(scores, key=lambda n: (-scores[n], n))
    related_names: List[str] = []

    # FK closure. Depth is configurable but 1 is the honest default: depth 2 in a
    # normalized schema tends to reach most of the database, which turns "grounded
    # context" back into "everything", losing the point of selecting at all.
    frontier = set(matched_names)
    seen = set(matched_names)
    for _ in range(max(fk_expansion_depth, 0)):
        next_frontier: Set[str] = set()
        for name in frontier:
            table = snapshot.get(name)
            if table is None:
                continue
            for fk in table.foreign_keys:
                target = snapshot.get(fk.references_table)
                if target is not None and target.qualified_name not in seen:
                    next_frontier.add(target.qualified_name)
            # Reverse direction: tables pointing AT this one.
            for other in snapshot.tables:
                if other.qualified_name in seen:
                    continue
                for fk in other.foreign_keys:
                    target = snapshot.get(fk.references_table)
                    if target is not None and target.qualified_name == table.qualified_name:
                        next_frontier.add(other.qualified_name)
                        break
        if not next_frontier:
            break
        seen |= next_frontier
        related_names.extend(sorted(next_frontier))
        frontier = next_frontier

    ordered = matched_names + related_names
    kept = ordered[:max_tables]
    kept_set = set(kept)
    omitted = [t.qualified_name for t in snapshot.tables if t.qualified_name not in kept_set]

    tables = [snapshot.get(n) for n in kept]
    tables = [t for t in tables if t is not None]

    return SelectionResult(
        tables=tables,
        matched=[n for n in matched_names if n in kept_set],
        related=[n for n in related_names if n in kept_set],
        omitted=omitted,
        strategy="lexical",
        degraded=bool(omitted),
        reason="max_tables_reached" if len(ordered) > max_tables else None,
    )
