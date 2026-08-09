#!/usr/bin/env python3
"""
Cheap pre-check for Fase 3 (docs/plan-schema-grounding.md sec 5.2): calls only
the Router (phi3:mini) against the three "generic" test queries from
tests/fixtures/schema/queries.json to see whether any would hit the fast path
(FAST_PATH_CATEGORIES = SIMPLE_TASK, ERROR_REACTION) before committing to the
full 18-run/3-7.5h sweep (task 3.4). A fast-path hit means that (fixture, query)
pair's WITH/WITHOUT runs never reach schema grounding or produce an
`implementation`, silently contributing no signal to the A/B comparison.

This does not touch main.py's CLI or write receipts -- it instantiates the
Orchestrator directly and calls the router in isolation, so each check costs
one small-model call instead of a full pipeline run.

Usage: .venv/bin/python3 tests/check_router_classification.py
"""
import asyncio
import json
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.orchestrator import Orchestrator  # noqa: E402

QUERIES_FILE = REPO_ROOT / "tests" / "fixtures" / "schema" / "queries.json"
CONFIG_PATH = REPO_ROOT / "config" / "settings.yaml"


async def main():
    queries = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    generic = [
        (fixture, entry["query"])
        for fixture, entries in queries.items()
        if not fixture.startswith("_")
        for entry in entries
        if entry["kind"] == "generic"
    ]

    async with Orchestrator(str(CONFIG_PATH)) as orch:
        print(f"Checking {len(generic)} generic queries against the Router...\n")
        any_fast_path = False
        for fixture, query in generic:
            trace = []
            decision = await orch._get_router_decision(query, str(uuid.uuid4()), trace)
            is_fast_path = decision in orch.FAST_PATH_CATEGORIES
            any_fast_path = any_fast_path or is_fast_path
            flag = "  <-- FAST PATH (would skip schema grounding)" if is_fast_path else ""
            print(f"[{fixture}] {query!r}\n  -> {decision}{flag}\n")

    if any_fast_path:
        print("RESULT: at least one generic query would hit the fast path.")
        sys.exit(1)
    else:
        print("RESULT: no generic query hit the fast path -- safe to proceed with the full sweep.")


if __name__ == "__main__":
    asyncio.run(main())
