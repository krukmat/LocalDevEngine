"""
Deterministic relational context — the intermediate representation (IR).

Deliberately kept out of memory/: the vector store holds *probabilistic* context
(retrieved, scored, possibly wrong). A schema snapshot is the opposite kind of
source — it ASSERTS structural facts instead of suggesting relevant ones. That
difference is why a snapshot is never embedded, never scored, and never ingested
into the vector store (doing so would re-probabilize it). See
docs/plan-schema-grounding.md §2.

The IR is dialect-agnostic on purpose: this engine is generic, so there is no
privileged database and no reference dialect. `dialect` is carried for display
only — nothing in selection, rendering or the identifier check branches on it.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Bumped when the accepted snapshot shape changes incompatibly. A caller writing
# a snapshot file stamps this so a mismatch is a loud error, not silent misreading.
IR_VERSION = "1.0"


class SchemaSnapshotError(ValueError):
    """
    A caller-supplied snapshot could not be parsed into the IR.

    Always carries a concrete location ("tables[3].columns[1]: missing 'name'"),
    because the caller is the only one who can fix it and it is fixing a file it
    generated. Never swallowed into a degraded run — see the CLI's EXIT_USAGE path.
    """


@dataclass
class Column:
    name: str
    type: str = "unknown"
    nullable: bool = True
    primary_key: bool = False
    default: Optional[str] = None
    comment: Optional[str] = None


@dataclass
class ForeignKey:
    columns: List[str]
    references_table: str
    references_columns: List[str] = field(default_factory=list)


@dataclass
class Table:
    name: str
    columns: List[Column] = field(default_factory=list)
    schema: Optional[str] = None
    comment: Optional[str] = None
    primary_key: List[str] = field(default_factory=list)
    foreign_keys: List[ForeignKey] = field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name

    def column_names(self) -> List[str]:
        return [c.name for c in self.columns]

    def has_column(self, name: str) -> bool:
        lowered = name.lower()
        return any(c.name.lower() == lowered for c in self.columns)


@dataclass
class SchemaSnapshot:
    tables: List[Table] = field(default_factory=list)
    dialect: Optional[str] = None
    source: Optional[str] = None

    def __post_init__(self) -> None:
        # Two lookup keys per table (bare and qualified) so a query or an
        # implementation can refer to "users" or "public.users" interchangeably —
        # the caller's snapshot may qualify names even when its SQL doesn't.
        self._by_name: Dict[str, Table] = {}
        for t in self.tables:
            self._by_name[t.name.lower()] = t
            self._by_name[t.qualified_name.lower()] = t

    def get(self, name: str) -> Optional[Table]:
        """Case-insensitive lookup accepting bare or schema-qualified names."""
        return self._by_name.get(name.strip().strip('"\'`[]').lower())

    def has_table(self, name: str) -> bool:
        return self.get(name) is not None

    def table_names(self) -> List[str]:
        return [t.qualified_name for t in self.tables]


class SchemaProvider(ABC):
    """
    Strategy for obtaining a SchemaSnapshot, mirroring models/base.py's BaseModel
    and memory/base.py's BaseMemory.

    The only implementation for now reads a file the caller already produced
    (context/schema/snapshot.py). That is a deliberate design choice, not a
    placeholder: an engine that introspects a live database has to hold
    credentials, open connections, and decide a connection policy per dialect —
    all of which a generic engine would be doing on behalf of a caller who
    already has that access. Keeping the engine snapshot-only makes it stateless
    and credential-free. See docs/plan-schema-grounding.md §7.
    """

    @abstractmethod
    def load(self) -> SchemaSnapshot:
        """Returns the snapshot, or raises SchemaSnapshotError."""
        raise NotImplementedError
