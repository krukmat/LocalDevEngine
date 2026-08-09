"""
SchemaProvider backed by a file the caller already produced.

Accepts JSON or YAML (PyYAML is already a dependency — no new requirements for
this layer). Normalization is permissive about *shape* and strict about
*identity*: only table names and column names are mandatory, everything else has
a defined default, and unknown keys are ignored so a caller can carry extra
metadata without this parser rejecting it. What is never tolerated is an
unnamed table or column — that would silently produce a schema block asserting
facts about an entity nobody can refer to.
"""
import json
import os
from typing import Any, Dict, List, Optional

import yaml

from .base import (
    Column,
    ForeignKey,
    SchemaProvider,
    SchemaSnapshot,
    SchemaSnapshotError,
    Table,
)

# Cap on file size. A snapshot is metadata, not data — anything this large is
# either a mistake (a data dump instead of a schema) or something that could
# never fit a prompt budget anyway.
MAX_SNAPSHOT_BYTES = 5_000_000


def _require_str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaSnapshotError(f"{where}: expected a non-empty string, got {value!r}")
    return value.strip()


def _as_str_list(value: Any, where: str) -> List[str]:
    """Accepts a bare string or a list of strings — composite keys are lists, and
    single-column keys are written both ways by real-world generators."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [_require_str(v, f"{where}[{i}]") for i, v in enumerate(value)]
    raise SchemaSnapshotError(f"{where}: expected a string or list of strings, got {value!r}")


def _parse_column(raw: Any, where: str) -> Column:
    if isinstance(raw, str):
        # Shorthand: a bare string is just a column name of unknown type.
        return Column(name=_require_str(raw, where))
    if not isinstance(raw, dict):
        raise SchemaSnapshotError(f"{where}: expected an object or a string, got {type(raw).__name__}")

    name = _require_str(raw.get("name"), f"{where}.name")
    type_ = raw.get("type") or raw.get("data_type") or "unknown"
    if not isinstance(type_, str):
        type_ = str(type_)

    # nullable defaults to True: "we were not told" must not render as NOT NULL,
    # which would be this layer asserting a constraint it does not know about.
    nullable = raw.get("nullable")
    if nullable is None:
        nullable = raw.get("is_nullable")
    if isinstance(nullable, str):
        nullable = nullable.strip().upper() not in ("NO", "FALSE", "N", "0")
    nullable = True if nullable is None else bool(nullable)

    pk = raw.get("primary_key")
    if pk is None:
        pk = raw.get("is_primary_key")

    default = raw.get("default")
    if default is not None and not isinstance(default, str):
        default = str(default)

    comment = raw.get("comment") or raw.get("description")
    if comment is not None and not isinstance(comment, str):
        comment = str(comment)

    return Column(
        name=name,
        type=type_.strip() or "unknown",
        nullable=nullable,
        primary_key=bool(pk),
        default=default,
        comment=comment.strip() if comment else None,
    )


def _parse_foreign_key(raw: Any, where: str) -> ForeignKey:
    if not isinstance(raw, dict):
        raise SchemaSnapshotError(f"{where}: expected an object, got {type(raw).__name__}")

    columns = _as_str_list(raw.get("columns") or raw.get("column"), f"{where}.columns")
    if not columns:
        raise SchemaSnapshotError(f"{where}.columns: a foreign key must name at least one column")

    references = raw.get("references")
    if isinstance(references, dict):
        ref_table = _require_str(references.get("table"), f"{where}.references.table")
        ref_columns = _as_str_list(
            references.get("columns") or references.get("column"), f"{where}.references.columns"
        )
    else:
        ref_table = _require_str(
            raw.get("references_table") or raw.get("referenced_table") or references,
            f"{where}.references_table",
        )
        ref_columns = _as_str_list(
            raw.get("references_columns") or raw.get("referenced_columns"),
            f"{where}.references_columns",
        )

    return ForeignKey(columns=columns, references_table=ref_table, references_columns=ref_columns)


def _parse_table(raw: Any, where: str) -> Table:
    if not isinstance(raw, dict):
        raise SchemaSnapshotError(f"{where}: expected an object, got {type(raw).__name__}")

    name = _require_str(raw.get("name") or raw.get("table"), f"{where}.name")
    schema = raw.get("schema") or raw.get("schema_name")
    if schema is not None and not isinstance(schema, str):
        schema = str(schema)

    raw_columns = raw.get("columns")
    if raw_columns is None:
        raise SchemaSnapshotError(f"{where}.columns: missing (a table with no columns asserts nothing)")
    if not isinstance(raw_columns, list):
        raise SchemaSnapshotError(f"{where}.columns: expected a list, got {type(raw_columns).__name__}")
    columns = [_parse_column(c, f"{where}.columns[{i}]") for i, c in enumerate(raw_columns)]

    seen = set()
    for c in columns:
        key = c.name.lower()
        if key in seen:
            raise SchemaSnapshotError(f"{where}: duplicate column {c.name!r}")
        seen.add(key)

    # Primary key can arrive table-level, column-level, or both. Normalize to
    # table-level and mirror it back onto the columns so the renderer has one
    # source of truth regardless of how the caller wrote it.
    pk = _as_str_list(raw.get("primary_key") or raw.get("primary_keys"), f"{where}.primary_key")
    pk_from_columns = [c.name for c in columns if c.primary_key]
    for name_ in pk_from_columns:
        if name_ not in pk:
            pk.append(name_)
    lowered_pk = {p.lower() for p in pk}
    for c in columns:
        c.primary_key = c.name.lower() in lowered_pk

    raw_fks = raw.get("foreign_keys") or raw.get("foreign_key") or []
    if not isinstance(raw_fks, list):
        raise SchemaSnapshotError(f"{where}.foreign_keys: expected a list, got {type(raw_fks).__name__}")
    fks = [_parse_foreign_key(fk, f"{where}.foreign_keys[{i}]") for i, fk in enumerate(raw_fks)]

    comment = raw.get("comment") or raw.get("description")
    if comment is not None and not isinstance(comment, str):
        comment = str(comment)

    return Table(
        name=name,
        columns=columns,
        schema=schema.strip() if schema else None,
        comment=comment.strip() if comment else None,
        primary_key=pk,
        foreign_keys=fks,
    )


def parse_snapshot(data: Any, source: Optional[str] = None) -> SchemaSnapshot:
    """Normalizes an already-decoded JSON/YAML document into the IR."""
    if isinstance(data, list):
        # Shorthand: a bare list of tables, with no envelope.
        data = {"tables": data}
    if not isinstance(data, dict):
        raise SchemaSnapshotError(
            f"root: expected an object with a 'tables' key (or a list of tables), "
            f"got {type(data).__name__}"
        )

    raw_tables = data.get("tables")
    if raw_tables is None:
        raise SchemaSnapshotError("root.tables: missing")
    if not isinstance(raw_tables, list):
        raise SchemaSnapshotError(f"root.tables: expected a list, got {type(raw_tables).__name__}")
    if not raw_tables:
        raise SchemaSnapshotError("root.tables: empty (nothing to ground on)")

    tables = [_parse_table(t, f"tables[{i}]") for i, t in enumerate(raw_tables)]

    seen: Dict[str, int] = {}
    for i, t in enumerate(tables):
        key = t.qualified_name.lower()
        if key in seen:
            raise SchemaSnapshotError(
                f"tables[{i}]: duplicate table {t.qualified_name!r} (also at tables[{seen[key]}])"
            )
        seen[key] = i

    dialect = data.get("dialect")
    if dialect is not None and not isinstance(dialect, str):
        dialect = str(dialect)

    return SchemaSnapshot(
        tables=tables,
        dialect=dialect.strip() if dialect else None,
        source=source,
    )


class SnapshotFileProvider(SchemaProvider):
    """Loads a snapshot from a JSON or YAML file supplied by the caller."""

    def __init__(self, path: str):
        self.path = path

    def load(self) -> SchemaSnapshot:
        try:
            size = os.path.getsize(self.path)
        except OSError as e:
            raise SchemaSnapshotError(f"could not read schema file {self.path!r}: {e}") from e
        if size > MAX_SNAPSHOT_BYTES:
            raise SchemaSnapshotError(
                f"schema file {self.path!r} is {size} bytes, over the {MAX_SNAPSHOT_BYTES} limit — "
                "a snapshot should be schema metadata, not a data dump"
            )

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            raise SchemaSnapshotError(f"could not read schema file {self.path!r}: {e}") from e

        ext = os.path.splitext(self.path)[1].lower()
        # JSON is a subset of YAML 1.2, but PyYAML's parser gives worse errors on
        # JSON input, so try the matching parser first and only then fall back.
        parsers = (
            [("json", json.loads), ("yaml", yaml.safe_load)]
            if ext == ".json"
            else [("yaml", yaml.safe_load), ("json", json.loads)]
        )
        data = None
        errors = []
        for label, parse in parsers:
            try:
                data = parse(text)
                break
            except Exception as e:  # json.JSONDecodeError / yaml.YAMLError
                errors.append(f"{label}: {e}")
        else:
            raise SchemaSnapshotError(
                f"schema file {self.path!r} is neither valid JSON nor YAML — " + " | ".join(errors)
            )

        return parse_snapshot(data, source=self.path)
