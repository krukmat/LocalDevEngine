#!/usr/bin/env python3
"""
C.5 gate runner (docs/plan-schema-conformance.md §6, §8.2).

Runs context/schema/conformance.py:check() against every case in
tests/fixtures/schema/conformance_corpus/labels.json and compares the
resulting violations (type + detail, order-independent) against the
hand-labeled expectation. Entirely offline: no Ollama call, milliseconds not
minutes — the corpus was extracted once from real Fase 3 receipts plus seeded
cases, so this can be rerun on every change to the verifier.

Gate criterion (§6): zero false positives on clean cases, 100% detection of
seeded/labeled violations. Exit code is the number of cases with a diff
(0 = pass), so `python tests/run_conformance_gate.py; echo $?` is scriptable.

Reusable by design (§8.4): pass --corpus to point at a different labels.json
without touching this file, so a future corpus for other pattern coverage
doesn't need its own one-off runner.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context.schema.conformance import check
from context.schema.snapshot import parse_snapshot


def _violation_key(v):
    return (v.get("type") if isinstance(v, dict) else v.type,
            v.get("detail") if isinstance(v, dict) else v.detail)


def run_gate(corpus_dir: Path) -> int:
    labels_path = corpus_dir / "labels.json"
    labels = json.loads(labels_path.read_text())

    snapshot_dir = corpus_dir.parent
    snapshot_cache = {}

    failures = []
    total = 0

    for case in labels["cases"]:
        total += 1
        case_id = case["id"]
        impl_path = corpus_dir / case["implementation_file"]
        implementation = impl_path.read_text()

        fixture_name = case["snapshot_fixture"]
        if fixture_name not in snapshot_cache:
            snapshot_cache[fixture_name] = parse_snapshot(
                json.loads((snapshot_dir / fixture_name).read_text())
            )
        snapshot = snapshot_cache[fixture_name]
        allow_new_objects = case.get("allow_new_objects", True)

        report = check(implementation, snapshot, allow_new_objects=allow_new_objects)

        expected = case["expected_violations"]
        # "(any)" as a detail means: assert the type/count only, not the exact
        # wording (used for SyntaxError messages and untyped-fence labels that
        # are legitimately free-form) — see labels.json's notes per case.
        actual_keys = [(v.type, v.detail) for v in report.violations]
        expected_keys = [(e["type"], e["detail"]) for e in expected]

        def _matches(actual_list, expected_list):
            if len(actual_list) != len(expected_list):
                return False
            remaining = list(actual_list)
            for etype, edetail in expected_list:
                match_idx = None
                for i, (atype, adetail) in enumerate(remaining):
                    if atype != etype:
                        continue
                    if edetail == "(any)" or adetail == edetail:
                        match_idx = i
                        break
                if match_idx is None:
                    return False
                remaining.pop(match_idx)
            return True

        if not _matches(actual_keys, expected_keys):
            failures.append(
                {
                    "case_id": case_id,
                    "expected": expected_keys,
                    "actual": actual_keys,
                }
            )

    print(f"Ran {total} cases from {labels_path}")
    if not failures:
        print("PASS — 0 false positives, 100% detection over the labeled corpus.")
        return 0

    print(f"FAIL — {len(failures)}/{total} case(s) diverged from expected violations:\n")
    for f in failures:
        print(f"  {f['case_id']}")
        print(f"    expected: {f['expected']}")
        print(f"    actual:   {f['actual']}")
    return len(failures)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        default="tests/fixtures/schema/conformance_corpus",
        help="Directory containing labels.json and the implementation_file paths it references.",
    )
    args = parser.parse_args()
    corpus_dir = Path(args.corpus)
    if not corpus_dir.is_absolute():
        corpus_dir = Path(__file__).resolve().parent.parent / corpus_dir
    return run_gate(corpus_dir)


if __name__ == "__main__":
    sys.exit(main())
