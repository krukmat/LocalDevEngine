"""
Materializes a final implementation into an ephemeral temp tree so Antares has
a real directory to scan. See docs/plan-security-advisor-antares.md (T3, P4).
"""
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass

from .base import AntaresInvocationError

_FENIX_FILE_BLOCK = re.compile(
    r"=== FILE START ===\s*"
    r"PATH:\s*(?P<path>.+?)\s*"
    r"ACTION:\s*(?P<action>create|modify|delete)\s*"
    r"--- CONTENT ---\n(?P<content>.*?)"
    r"\n=== FILE END ===",
    re.DOTALL,
)


@dataclass
class MaterializedImplementation:
    snapshot_dir: str
    data_dir: str


def _write_contained(snapshot_dir: str, relative_path: str, content: str) -> None:
    if os.path.isabs(relative_path):
        raise AntaresInvocationError(
            f"absolute path rejected: {relative_path}",
            terminal_state="path-traversal-rejected",
        )
    resolved_snapshot = os.path.realpath(snapshot_dir)
    target = os.path.realpath(os.path.join(snapshot_dir, relative_path))
    if os.path.commonpath([resolved_snapshot, target]) != resolved_snapshot:
        raise AntaresInvocationError(
            f"path escapes snapshot dir: {relative_path}",
            terminal_state="path-traversal-rejected",
        )
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as f:
        f.write(content)


def _materialize_fenix_tagged_file(snapshot_dir: str, implementation: str) -> None:
    matches = list(_FENIX_FILE_BLOCK.finditer(implementation))
    if not matches:
        raise AntaresInvocationError(
            "no FILE START/END blocks found in fenix-tagged-file output",
            terminal_state="unparseable-output-contract",
        )
    for match in matches:
        if match.group("action") == "delete":
            continue
        _write_contained(snapshot_dir, match.group("path"), match.group("content"))


@contextmanager
def materialize_implementation(implementation: str, output_contract: str = None):
    with tempfile.TemporaryDirectory() as tmp:
        snapshot_dir = os.path.join(tmp, "snapshot")
        data_dir = os.path.join(tmp, "antares-data")
        os.makedirs(snapshot_dir)
        os.makedirs(data_dir)
        if output_contract == "fenix-tagged-file":
            _materialize_fenix_tagged_file(snapshot_dir, implementation)
        else:
            with open(os.path.join(snapshot_dir, "implementation.txt"), "w") as f:
                f.write(implementation)
        yield MaterializedImplementation(snapshot_dir, data_dir)
