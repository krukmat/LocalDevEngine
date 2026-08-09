"""
AST-based extraction of schema definitions/references from typed regions.

Replaces regex scraping (identifiers.py) with a real parser for the one
surface the evidence supports today: SQLAlchemy declarative ORM in Python
(docs/plan-schema-conformance.md §2.4 — the pattern-coverage scope decision,
and §5 — the ast-only, sqlglot-deferred decision).

What this recognizes, and nothing else:
  - `class X(Base): __tablename__ = "orders"`      -> Definition("orders")
  - `Column(...)` / `mapped_column(...)` inside such a class body -> Definition
    of that column, scoped to the enclosing table
  - `Session.query(Model)` / `select(Model)` where `Model` is a name bound to a
    class whose body contains `__tablename__` -> Reference("orders")
  - `some_var.column_name` where `some_var` is a query/select result on a known
    model, or the model class itself -> Reference("orders.column_name")

Anything else in a "python" region — raw psycopg2, Django ORM, string-built
SQL, f-strings — is not recognized. It produces no findings, which is exactly
right: absence of a false Reference is not the same as verifying the region,
so the caller (extraction driver in C.4/orchestrator wiring) is responsible
for treating a python region with zero findings as still worth flagging if it
contains none of the known patterns at all. See UNPARSEABLE_REGION/
UNTYPED_REGION in the conformance report (§3) for the region-level half of
that story; this module only concerns itself with regions it CAN parse.

A "sql" region is never parsed here — sqlglot was explicitly deferred (§5).
Every sql region becomes a caller-visible UNPARSEABLE_REGION upstream.
"""
import ast
from dataclasses import dataclass
from typing import List, Optional, Union

from .segmentation import Region


@dataclass
class Definition:
    kind: str  # "table" | "column"
    name: str  # table name, or "table.column" for a column
    line: int


@dataclass
class Reference:
    kind: str  # "table" | "column"
    name: str  # table name, or "table.column" for a column
    line: int


@dataclass
class ParseFailure:
    reason: str
    line: int


Finding = Union[Definition, Reference]


def _literal_str(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_column_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else None)
    return name in ("Column", "mapped_column")


class _DeclarativeModelVisitor(ast.NodeVisitor):
    """
    First pass: finds every class that declares __tablename__, and the columns
    assigned in its body via Column(...)/mapped_column(...). Building this table
    first (definitions before references, matching the in-order symbol-table
    rule in §3) lets the second pass resolve `Model.query(...)`/`select(Model)`
    by class name without needing a whole-program symbol table.
    """

    def __init__(self) -> None:
        self.definitions: List[Definition] = []
        # class name -> table name, so a later reference to `Order` resolves.
        self.model_to_table: dict = {}
        # table name -> set of declared column names, for column reference checks.
        self.table_columns: dict = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        table_name: Optional[str] = None
        table_line: Optional[int] = None
        columns: List[str] = []

        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                if "__tablename__" in targets:
                    literal = _literal_str(stmt.value)
                    if literal:
                        table_name = literal
                        table_line = stmt.lineno
                    continue
                if _is_column_call(stmt.value):
                    for t in targets:
                        columns.append((t, stmt.lineno))
            elif isinstance(stmt, ast.AnnAssign):
                if isinstance(stmt.target, ast.Name) and stmt.value is not None and _is_column_call(stmt.value):
                    columns.append((stmt.target.id, stmt.lineno))

        if table_name:
            self.definitions.append(Definition(kind="table", name=table_name, line=table_line))
            self.model_to_table[node.name] = table_name
            col_set = self.table_columns.setdefault(table_name, set())
            for col_name, col_line in columns:
                col_set.add(col_name)
                self.definitions.append(
                    Definition(kind="column", name=f"{table_name}.{col_name}", line=col_line)
                )

        self.generic_visit(node)


class _ReferenceVisitor(ast.NodeVisitor):
    """
    Second pass: `.query(Model)` / `select(Model)` -> table reference;
    `Model.column` or `alias.column` where alias is bound to a query/select of a
    known model -> column reference. Runs after the definition pass so
    references can resolve against `model_to_table`/`table_columns`, matching
    the definitions-before-references rule in §3.
    """

    def __init__(self, model_to_table: dict, table_columns: dict) -> None:
        self.model_to_table = model_to_table
        self.table_columns = table_columns
        self.references: List[Reference] = []
        # local var name -> table name, for `orders = session.query(Order)` then `orders.foo`
        self._bound: dict = {}

    def _model_name_from_arg(self, node: ast.AST) -> Optional[str]:
        # Falls back to the raw identifier when it isn't a class this document
        # defined with __tablename__ — e.g. `session.query(Subscription)` where
        # `Subscription` was never defined anywhere in the output. That case is
        # exactly what UNKNOWN_TABLE_REF exists to catch (§3); resolving only
        # against model_to_table and silently emitting nothing here would make
        # the checker blind to a query against a class it never saw defined.
        if isinstance(node, ast.Name):
            return self.model_to_table.get(node.id, node.id)
        return None

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        is_query = isinstance(func, ast.Attribute) and func.attr == "query"
        is_select = isinstance(func, ast.Name) and func.id == "select"
        if (is_query or is_select) and node.args:
            table = self._model_name_from_arg(node.args[0])
            if table:
                self.references.append(Reference(kind="table", name=table, line=node.lineno))
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        table = None
        if isinstance(node.value, ast.Call):
            func = node.value.func
            is_query = isinstance(func, ast.Attribute) and func.attr == "query"
            is_select = isinstance(func, ast.Name) and func.id == "select"
            if (is_query or is_select) and node.value.args:
                table = self._model_name_from_arg(node.value.args[0])
        if table:
            for t in node.targets:
                if isinstance(t, ast.Name):
                    self._bound[t.id] = table
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Emitted whenever the prefix resolves to a known model/alias, regardless
        # of whether node.attr is a column this pass has seen — resolving
        # "known vs. unknown" against snapshot ∪ prior-definitions is C.4's job
        # (the in-order symbol table in §3), not this extractor's. Gating on
        # table_columns here would silently drop exactly the case that matters:
        # a reference to a column that was never defined (the Cliente.id / real
        # PK id_cliente mismatch from Fase 3).
        #
        # Dunder attributes (`__table__`, `__tablename__`, `__mapper__`, ...) are
        # SQLAlchemy machinery, never a user column — `Task.__table__.select()`
        # is a real pattern seen in Fase 3 receipts and must not be reported as
        # a reference to a column literally named "__table__".
        if node.attr.startswith("__") and node.attr.endswith("__"):
            self.generic_visit(node)
            return
        table = None
        if isinstance(node.value, ast.Name):
            base = node.value.id
            table = self.model_to_table.get(base) or self._bound.get(base)
        if table:
            self.references.append(
                Reference(kind="column", name=f"{table}.{node.attr}", line=node.lineno)
            )
        self.generic_visit(node)


def extract_python(
    region: Region,
    model_to_table: Optional[dict] = None,
    table_columns: Optional[dict] = None,
) -> Union[List[Finding], ParseFailure]:
    """
    Parses a "python"-kind Region. Returns a ParseFailure if `ast.parse` itself
    fails (e.g. the region is a fragment, not a full module — common when the
    Implementer's fence mixes prose ellipses like `# ... existing fields ...`
    into what is otherwise valid code) rather than raising, so the caller
    always gets a typed result to report as UNPARSEABLE_REGION.

    `model_to_table`/`table_columns` are optional accumulators the caller can
    thread across multiple regions in document order (see `extract_document`),
    so a model defined in one fenced block resolves references made in a later
    one — the Implementer routinely splits `class Order` and its usage into
    separate code fences within one response. Mutated in place; a fresh dict is
    used per call if not supplied.
    """
    try:
        tree = ast.parse(region.text)
    except SyntaxError as e:
        return ParseFailure(reason=f"SyntaxError: {e.msg}", line=(e.lineno or 1) + region.start_line - 1)

    def_visitor = _DeclarativeModelVisitor()
    def_visitor.visit(tree)

    combined_model_to_table = dict(model_to_table or {})
    combined_model_to_table.update(def_visitor.model_to_table)
    combined_table_columns = {k: set(v) for k, v in (table_columns or {}).items()}
    for table, cols in def_visitor.table_columns.items():
        combined_table_columns.setdefault(table, set()).update(cols)

    ref_visitor = _ReferenceVisitor(combined_model_to_table, combined_table_columns)
    ref_visitor.visit(tree)

    if model_to_table is not None:
        model_to_table.update(def_visitor.model_to_table)
    if table_columns is not None:
        for table, cols in def_visitor.table_columns.items():
            table_columns.setdefault(table, set()).update(cols)

    findings: List[Finding] = list(def_visitor.definitions) + list(ref_visitor.references)
    for f in findings:
        f.line += region.start_line - 1
    return findings


def extract_document(regions: List[Region]) -> List[Union[List[Finding], ParseFailure]]:
    """
    Runs extract_python over every "python" region in `regions`, in order,
    threading one model_to_table/table_columns accumulator across all of them.
    Non-"python" regions are skipped here — segmentation + region-kind routing
    (python/sql/untyped/prose -> which extractor, or UNPARSEABLE_REGION/
    UNTYPED_REGION) is the conformance report's job (§3, built in C.4), not
    this module's. Returns one result per python region, same order as input.
    """
    model_to_table: dict = {}
    table_columns: dict = {}
    results: List[Union[List[Finding], ParseFailure]] = []
    for region in regions:
        if region.kind != "python":
            continue
        results.append(extract_python(region, model_to_table, table_columns))
    return results
