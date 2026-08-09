#!/usr/bin/env python3
"""
Fase 3 A/B script (docs/plan-schema-grounding.md sec 5.2, task 3.3).

Runs each (fixture, query) pair from tests/fixtures/schema/queries.json twice --
once with --schema-file, once without -- saves both raw receipts, and computes
outcome.schema_grounding.identifier_check.unknown_count for both sides so they're
comparable: the WITH side reads it straight from the receipt (the engine ran the
check itself, against the snapshot it was given); the WITHOUT side has no
schema_snapshot inside that run to check against, so this script recomputes
check_identifiers() offline against the same fixture snapshot the WITH run used --
this is the "for the run without schema, compute the same number offline against
the snapshot that wasn't passed" step task 3.3 calls for.

Router-match guard: the Router (phi3:mini) is a separate, upstream, model-backed
stage that runs before schema grounding is even reached -- if it resolves to a
fast-path category (SIMPLE_TASK/ERROR_REACTION), the rest of the pipeline
(including schema grounding) never runs at all, regardless of --schema-file. A
real WITH/WITHOUT validation pair showed the same query classified differently
across the two runs (config/settings.yaml now pins router temperature to 0.0 to
reduce this, but greedy decoding can still vary on ambiguous prompts). So before
spending a full pipeline run on either side, this script probes the Router alone
(cheap: one small-model call, no full pipeline) up to ROUTER_MATCH_MAX_ATTEMPTS
times until the same query classifies identically twice in a row -- approximating
"the WITH and WITHOUT runs would have taken the same path" without needing to
run both full pipelines just to find out after the fact. A pair that never
converges is recorded with router_matched=false and still run once, flagged in
the summary rather than silently trusted.

This script only runs pairs and records numbers. Applying the pre-fixed
continuation criterion (task 3.5, plan sec 5.2) is a separate, deliberate step --
read summary.json's per-fixture totals once this has run, don't automate the
decision itself.

Usage:
  python tests/run_schema_ab.py --dry-run              # print the 18 commands, call nothing
  python tests/run_schema_ab.py --only small            # just one fixture (6 runs)
  python tests/run_schema_ab.py --only small:table_name # just one (fixture, query) pair (2 runs)
  python tests/run_schema_ab.py                         # the full 3x3x2 = 18-run sweep
"""
import argparse
import asyncio
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from context.schema.snapshot import SnapshotFileProvider  # noqa: E402
from context.schema.identifiers import check_identifiers  # noqa: E402
from core.orchestrator import Orchestrator  # noqa: E402

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "schema"
QUERIES_FILE = FIXTURES_DIR / "queries.json"
RESULTS_DIR = REPO_ROOT / "tests" / "results" / "schema_ab"
RAW_DIR = RESULTS_DIR / "raw"
CONFIG_PATH = REPO_ROOT / "config" / "settings.yaml"

# How many consecutive-pair probes of the Router alone (cheap: one small-model
# call each) to try before giving up on getting two matching classifications in
# a row for the same query. Router temperature is pinned to 0.0 in
# config/settings.yaml, so in practice this rarely needs more than 1-2 attempts;
# this cap only guards against prompts genuinely on a classification boundary.
ROUTER_MATCH_MAX_ATTEMPTS = 5

# Buffer above pipeline.max_run_seconds (config/settings.yaml, currently 1500s) so
# this subprocess timeout never fires before the engine's own asyncio.wait_for does
# -- a subprocess TimeoutExpired would look like a crash, not the "timeout" status
# the receipt is designed to report on its own.
SUBPROCESS_TIMEOUT_SECONDS = 1500 + 180

# Always the project's venv interpreter, not sys.executable -- this script may
# itself be invoked with a system Python that lacks the project's dependencies
# (numpy etc.), and main.py needs the real ones regardless of how this script ran.
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python3"


def run_one(query: str, schema_file: Optional[Path], out_path: Path) -> dict:
    cmd = [
        str(VENV_PYTHON), str(REPO_ROOT / "main.py"), "ask",
        "--json", "--quiet", "--out", str(out_path),
    ]
    if schema_file is not None:
        cmd += ["--schema-file", str(schema_file)]
    cmd.append(query)
    started = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=REPO_ROOT, timeout=SUBPROCESS_TIMEOUT_SECONDS,
            capture_output=True, text=True,
        )
        returncode = proc.returncode
        stderr_tail = proc.stderr[-2000:]
    except subprocess.TimeoutExpired as e:
        returncode = None
        stderr_tail = (e.stderr or "")[-2000:] if e.stderr else "(subprocess hard timeout, no receipt expected)"
    elapsed = time.time() - started
    return {"returncode": returncode, "elapsed_s": round(elapsed, 1), "stderr_tail": stderr_tail}


async def wait_for_stable_router_decision(query: str) -> tuple[Optional[str], int]:
    """Calls the Router alone (no full pipeline) repeatedly until the same query
    classifies identically twice in a row, or ROUTER_MATCH_MAX_ATTEMPTS is hit.
    Returns (decision_or_None, attempts_used). decision is None if it never
    stabilized -- the caller should still run the pair but flag it as unmatched."""
    async with Orchestrator(str(CONFIG_PATH)) as orch:
        previous = None
        for attempt in range(1, ROUTER_MATCH_MAX_ATTEMPTS + 1):
            trace = []
            decision = await orch._get_router_decision(query, str(uuid.uuid4()), trace)
            if decision == previous:
                return decision, attempt
            previous = decision
        return None, ROUTER_MATCH_MAX_ATTEMPTS


def load_receipt(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="Limit to one fixture, optionally fixture:kind (e.g. small or small:table_name)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would run without invoking Ollama")
    args = parser.parse_args()

    if not args.dry_run and not VENV_PYTHON.exists():
        print(f"ERROR: venv interpreter not found at {VENV_PYTHON}", file=sys.stderr)
        sys.exit(1)

    queries = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    only_fixture, only_kind = None, None
    if args.only:
        parts = args.only.split(":", 1)
        only_fixture = parts[0]
        only_kind = parts[1] if len(parts) > 1 else None

    summary = {}
    for fixture, entries in queries.items():
        if fixture.startswith("_"):
            continue
        if only_fixture and fixture != only_fixture:
            continue
        schema_path = FIXTURES_DIR / f"{fixture}.json"
        snapshot = SnapshotFileProvider(str(schema_path)).load()
        fixture_results = []

        for entry in entries:
            kind = entry["kind"]
            query = entry["query"]
            if only_kind and kind != only_kind:
                continue

            with_out = RAW_DIR / f"{fixture}__{kind}__with.json"
            without_out = RAW_DIR / f"{fixture}__{kind}__without.json"

            print(f"[{fixture}/{kind}] WITH schema: {query!r}")
            if args.dry_run:
                print(f"  (dry-run) would write {with_out}")
                print(f"[{fixture}/{kind}] WITHOUT schema: {query!r}")
                print(f"  (dry-run) would write {without_out}")
                continue

            router_decision, router_attempts = asyncio.run(wait_for_stable_router_decision(query))
            router_matched = router_decision is not None
            if router_matched:
                print(f"  router stable after {router_attempts} attempt(s): {router_decision}")
            else:
                print(f"  WARNING: router did not stabilize in {ROUTER_MATCH_MAX_ATTEMPTS} attempts -- running anyway, flagged as unmatched")

            meta = run_one(query, schema_path, with_out)
            print(f"  returncode={meta['returncode']} elapsed={meta['elapsed_s']}s")

            print(f"[{fixture}/{kind}] WITHOUT schema: {query!r}")
            meta = run_one(query, None, without_out)
            print(f"  returncode={meta['returncode']} elapsed={meta['elapsed_s']}s")

            with_receipt = load_receipt(with_out)
            without_receipt = load_receipt(without_out)

            row = {
                "kind": kind, "query": query,
                "router_matched": router_matched,
                "router_decision": router_decision,
                "router_attempts": router_attempts,
            }

            if with_receipt is None:
                row["with_error"] = "no receipt written"
            else:
                row["with_fast_path"] = bool(with_receipt.get("fast_path"))
                ic = (with_receipt.get("outcome") or {}).get("schema_grounding", {}).get("identifier_check", {})
                row["with_unknown_count"] = ic.get("unknown_count")

            if without_receipt is None:
                row["without_error"] = "no receipt written"
            else:
                row["without_fast_path"] = bool(without_receipt.get("fast_path"))
                implementation = without_receipt.get("implementation") or ""
                check = check_identifiers(implementation, snapshot)
                row["without_unknown_count"] = check.unknown_count
                row["without_unknown_tables"] = check.unknown_tables
                row["without_unknown_columns"] = check.unknown_columns

            fixture_results.append(row)
            print(f"  unknown_count: with={row.get('with_unknown_count')} without={row.get('without_unknown_count')}")

        if fixture_results:
            summary[fixture] = fixture_results

    if args.dry_run:
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = RESULTS_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSummary written to {summary_path}")

    print_totals(summary)


def print_totals(summary: dict):
    """Prints the per-fixture totals the sec 5.2 criterion gets applied to by a
    human in task 3.5. Deliberately does not compute or print a PASS/FAIL verdict
    -- the plan is explicit that the criterion must be applied as a separate,
    considered step, not folded into the same script that produced the numbers."""
    print("\n--- Per-fixture totals (sum of unknown_count across the fixture's queries) ---")
    for fixture, rows in summary.items():
        with_vals = [r.get("with_unknown_count") for r in rows if r.get("with_unknown_count") is not None]
        without_vals = [r.get("without_unknown_count") for r in rows if r.get("without_unknown_count") is not None]
        with_total = sum(with_vals)
        without_total = sum(without_vals)
        note = ""
        if len(with_vals) < len(rows) or len(without_vals) < len(rows):
            note = "  [INCOMPLETE: fewer counted queries than expected -- check errors/fast_path above]"
        elif any(r.get("with_fast_path") or r.get("without_fast_path") for r in rows):
            note = "  [WARNING: at least one query hit the fast path -- no implementation was generated for it]"
        elif any(not r.get("router_matched") for r in rows):
            note = "  [WARNING: router never stabilized for at least one query -- WITH/WITHOUT may have taken different paths]"
        print(f"{fixture}: with={with_total} without={without_total}{note}")


if __name__ == "__main__":
    main()
