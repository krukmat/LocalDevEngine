"""
Splits Implementer output into typed regions before any extraction runs.

This is the recall guard for the conformance verifier (docs/plan-schema-conformance.md
§2.4): prose is never analyzed, so `INTO the`/`within`/`TABLE of` — the prose matches
that made the old regex-based check_identifiers() noisy — cannot occur here by
construction. A fenced code block with no declared language is not silently
skipped either; it becomes an UNTYPED region so the caller sees it was not
checked, rather than assuming it was clean.

Pure text parsing, no model, no I/O.
"""
import re
from dataclasses import dataclass
from typing import List, Optional

# ```python ... ``` / ```sql ... ``` / ``` ... ``` (no language tag) / ```text ... ```
_FENCE_RE = re.compile(
    r"^[ \t]*```[ \t]*(?P<lang>[A-Za-z0-9_+\-]*)[ \t]*\r?\n"
    r"(?P<body>.*?)"
    r"^[ \t]*```[ \t]*$",
    re.DOTALL | re.MULTILINE,
)

# Languages this layer knows how to type. Everything else (bash, yaml, json,
# text, ...) still gets its own region — it is just not a candidate for the
# Python/SQL extractors, and downstream (C.3) reports it as UNTYPED_REGION
# rather than pretending it was PYTHON or SQL.
_LANG_ALIASES = {
    "python": "python",
    "py": "python",
    "python3": "python",
    "sql": "sql",
    "postgresql": "sql",
    "postgres": "sql",
    "mysql": "sql",
    "sqlite": "sql",
    "plpgsql": "sql",
    "tsql": "sql",
}


@dataclass
class Region:
    kind: str  # "python" | "sql" | "untyped" | "prose"
    text: str
    start_line: int  # 1-indexed, inclusive, in the original text
    end_line: int  # 1-indexed, inclusive
    declared_lang: Optional[str] = None  # exactly what followed ``` , if anything


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def segment(text: str) -> List[Region]:
    """
    Splits `text` into an ordered list of Regions covering the whole input.

    Fenced code blocks (```lang ... ```) become "python", "sql", or "untyped"
    regions depending on the declared language. Everything outside a fence is a
    "prose" region — the extractor (C.3) never looks inside those, which is the
    mechanism that keeps this verifier from repeating check_identifiers()'s
    false positives on plain English.
    """
    if not text:
        return []

    regions: List[Region] = []
    pos = 0
    for match in _FENCE_RE.finditer(text):
        if match.start() > pos:
            prose = text[pos:match.start()]
            if prose.strip():
                regions.append(
                    Region(
                        kind="prose",
                        text=prose,
                        start_line=_line_of(text, pos),
                        end_line=_line_of(text, match.start()),
                    )
                )

        raw_lang = (match.group("lang") or "").strip()
        # An empty declared_lang is ALSO untyped, same as an unrecognized one —
        # both mean "no eligible parser", which is the fact C.3 needs, not
        # whether a string happened to follow the fence.
        kind = _LANG_ALIASES.get(raw_lang.lower(), "untyped")

        body = match.group("body")
        regions.append(
            Region(
                kind=kind,
                text=body,
                start_line=_line_of(text, match.start()) ,
                end_line=_line_of(text, match.end()),
                declared_lang=raw_lang or None,
            )
        )
        pos = match.end()

    if pos < len(text):
        prose = text[pos:]
        if prose.strip():
            regions.append(
                Region(
                    kind="prose",
                    text=prose,
                    start_line=_line_of(text, pos),
                    end_line=_line_of(text, len(text)),
                )
            )

    return regions
