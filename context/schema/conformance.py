"""
Typed conformance report — replaces identifiers.py's check_identifiers().

check(implementation, snapshot) -> ConformanceReport is the pure function
described in docs/plan-schema-conformance.md §3: given (implementation text,
SchemaSnapshot), the verdict is deterministic and independently recomputable
by the caller. No model, no I/O, no network — same contract as
context/schema/identifiers.py before it, but built on segmentation.py +
extraction.py (real parsing) instead of regex.

Symbol resolution walks the document in order (§3's "definiciones vs.
referencias"): a reference resolves against `snapshot ∪ definitions seen so
far`, so "add a new table and use it" is NEW_OBJECT_DEFINED + valid
references, not two violations.

allow_new_objects (config/settings.yaml schema_grounding.allow_new_objects,
default true — docs/plan-schema-conformance.md §4) only changes whether
NEW_OBJECT_DEFINED is *reported as a violation*; in `report` mode (the only
mode C.1-C.6 builds) nothing is gated on it either way.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Set

from .base import SchemaSnapshot
from .extraction import Definition, ParseFailure, Reference, extract_python
from .segmentation import Region, segment

# Violation type constants (docs/plan-schema-conformance.md §3).
UNKNOWN_TABLE_REF = "UNKNOWN_TABLE_REF"
UNKNOWN_COLUMN_REF = "UNKNOWN_COLUMN_REF"
NEW_OBJECT_DEFINED = "NEW_OBJECT_DEFINED"
UNPARSEABLE_REGION = "UNPARSEABLE_REGION"
UNTYPED_REGION = "UNTYPED_REGION"


@dataclass
class Violation:
    type: str
    detail: str  # e.g. "discount_codes" or "clientes.id"
    line: int

    def to_dict(self) -> Dict[str, object]:
        return {"type": self.type, "detail": self.detail, "line": self.line}


@dataclass
class ConformanceReport:
    ran: bool = True
    verdict: str = "CONFORME"  # "CONFORME" | "NO_CONFORME"
    violations: List[Violation] = field(default_factory=list)
    regions_checked: int = 0
    regions_unparseable: int = 0
    regions_untyped: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "ran": self.ran,
            "verdict": self.verdict,
            "violations": [v.to_dict() for v in self.violations],
            "regions_checked": self.regions_checked,
            "regions_unparseable": self.regions_unparseable,
            "regions_untyped": self.regions_untyped,
        }


def _known_table_name(snapshot: SchemaSnapshot, name: str) -> bool:
    return snapshot.has_table(name)


def _known_column(snapshot: SchemaSnapshot, table: str, column: str) -> bool:
    t = snapshot.get(table)
    return t is not None and t.has_column(column)


def check(
    implementation: str,
    snapshot: SchemaSnapshot,
    allow_new_objects: bool = True,
) -> ConformanceReport:
    """
    Segments `implementation`, extracts definitions/references from every
    "python" region (in order, one shared symbol table — see extraction.py's
    extract_document), resolves each reference against
    `snapshot ∪ definitions_seen_so_far`, and returns a typed report.

    "sql" regions are never parsed (sqlglot deferred, §5): each becomes an
    UNPARSEABLE_REGION violation. "untyped" regions (no declared/recognized
    fence language) become UNTYPED_REGION. Prose is never inspected — it is
    not a region kind this function iterates over at all.
    """
    if not implementation or not implementation.strip():
        return ConformanceReport(ran=False, verdict="CONFORME")
    if not snapshot.tables:
        return ConformanceReport(ran=False, verdict="CONFORME")

    regions = segment(implementation)
    report = ConformanceReport()

    # table name -> set of columns defined in the output so far (not the
    # snapshot) — the "definitions_previas" half of §3's `snapshot ∪
    # definiciones_previas` resolution rule.
    defined_tables: Set[str] = set()
    defined_columns: Dict[str, Set[str]] = {}
    model_to_table: dict = {}
    table_columns: dict = {}

    for region in regions:
        if region.kind == "sql":
            report.regions_unparseable += 1
            report.violations.append(
                Violation(type=UNPARSEABLE_REGION, detail="sql region (sqlglot deferred, see §5)", line=region.start_line)
            )
            continue
        if region.kind == "untyped":
            report.regions_untyped += 1
            report.violations.append(
                Violation(type=UNTYPED_REGION, detail=region.declared_lang or "(no language declared)", line=region.start_line)
            )
            continue
        if region.kind != "python":
            continue  # "prose" — never analyzed, by design (§2.4)

        report.regions_checked += 1
        result = extract_python(region, model_to_table, table_columns)
        if isinstance(result, ParseFailure):
            report.regions_unparseable += 1
            report.violations.append(
                Violation(type=UNPARSEABLE_REGION, detail=result.reason, line=result.line)
            )
            continue

        for finding in result:
            if isinstance(finding, Definition):
                if finding.kind == "table":
                    table = finding.name
                    if not _known_table_name(snapshot, table):
                        defined_tables.add(table.lower())
                        if not allow_new_objects:
                            report.violations.append(
                                Violation(type=NEW_OBJECT_DEFINED, detail=table, line=finding.line)
                            )
                    else:
                        defined_tables.add(table.lower())
                else:  # column
                    table, _, column = finding.name.partition(".")
                    defined_columns.setdefault(table.lower(), set()).add(column.lower())
                    if not _known_column(snapshot, table, column) and not allow_new_objects:
                        report.violations.append(
                            Violation(type=NEW_OBJECT_DEFINED, detail=finding.name, line=finding.line)
                        )
                continue

            # Reference
            if finding.kind == "table":
                table = finding.name
                known = _known_table_name(snapshot, table) or table.lower() in defined_tables
                if not known:
                    report.violations.append(
                        Violation(type=UNKNOWN_TABLE_REF, detail=table, line=finding.line)
                    )
            else:  # column reference "table.column"
                table, _, column = finding.name.partition(".")
                known = _known_column(snapshot, table, column) or column.lower() in defined_columns.get(table.lower(), set())
                # A reference to a column on a table that isn't known/defined at
                # all is a table-level problem, already caught when the table
                # itself is unresolvable; here we only need the column check
                # once the table resolves (known table, unknown column).
                table_known = _known_table_name(snapshot, table) or table.lower() in defined_tables
                if table_known and not known:
                    report.violations.append(
                        Violation(type=UNKNOWN_COLUMN_REF, detail=finding.name, line=finding.line)
                    )
                elif not table_known:
                    report.violations.append(
                        Violation(type=UNKNOWN_TABLE_REF, detail=table, line=finding.line)
                    )

    report.verdict = "NO_CONFORME" if any(
        v.type in (UNKNOWN_TABLE_REF, UNKNOWN_COLUMN_REF, UNPARSEABLE_REGION, UNTYPED_REGION)
        or (v.type == NEW_OBJECT_DEFINED and not allow_new_objects)
        for v in report.violations
    ) else "CONFORME"

    return report
