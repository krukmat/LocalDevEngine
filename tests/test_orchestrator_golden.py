"""
O1 (docs/plan-p1-refactor-orchestrator.md): golden receipt for core/orchestrator.py.

Captures the full receipt for fixed inputs with every model call stubbed —
no Ollama, no network, no real vector store. This is P1's regression net: the
refactor (O2-O9) is required to reproduce these receipts byte-for-byte before
any extracted module is considered correct. Offline, like every other gate
runner in this repo (tests/run_conformance_gate.py, tests/run_antares_offline.py).

Run: python -m pytest tests/test_orchestrator_golden.py -v
     python tests/test_orchestrator_golden.py   (prints PASS/FAIL, no pytest needed)
"""
import asyncio
import copy
import inspect
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.orchestrator import Orchestrator  # noqa: E402
from core.pipeline.context import OutcomeRecorder  # noqa: E402
from context.schema.snapshot import parse_snapshot  # noqa: E402
from models.base import BaseModel  # noqa: E402

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "orchestrator_golden")

# Fields whose value is inherently non-reproducible run to run and must be
# excluded before comparing (or diffing) two receipts.
_VOLATILE_KEYS = {"request_id", "started_at", "finished_at", "duration_ms"}


class FakeModel(BaseModel):
    """A BaseModel that returns pre-scripted, deterministic text instead of
    calling Ollama. `responses` is consumed in order; the last entry repeats
    once exhausted, so a retry loop (design gate, implementation check) that
    calls the same role more times than scripted still gets a defined answer
    instead of an IndexError."""

    def __init__(self, role: str, responses):
        super().__init__(name=f"fake-{role}", role=role)
        self._responses = list(responses)
        self._call_count = 0

    @property
    def capabilities(self):
        return ["fake"]

    def _next(self) -> str:
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        return self._responses[idx]

    async def generate(self, prompt, context=None):
        return self._next()

    async def generate_stream(self, prompt, context=None):
        text = self._next()
        yield text

    async def load(self):
        pass

    async def unload(self):
        pass


# Scripted responses per role. Chosen so the pipeline exercises the sectioned
# design gate (four "## <Section>" headers matching PromptRegistry.SECTION_NAMES)
# approved on the first pass, and an implementation approved on the first pass,
# so the golden run is short and has no dependence on max_qa_iterations behavior
# (that path gets its own scenario below).
SECTION_NAMES = ("Data Model", "API/Interface", "Error Handling", "Dependencies/Integration")

_PLAN_TEXT = "\n\n".join(f"## {name}\nPlan detail for {name}." for name in SECTION_NAMES)

SCENARIOS = {
    "simple_task_fast_path": {
        "query": "What does HTTP 404 mean?",
        "roles": {
            "router": ["SIMPLE_TASK"],
            "manager": ["HTTP 404 means Not Found: the server can't find the requested resource."],
        },
    },
    "coding_request_approved_first_pass": {
        "query": "Add a health check endpoint to the API.",
        "roles": {
            "router": ["CODING_REQUEST"],
            "manager": [
                "1. Add a /health route.\n2. Return 200 with a status payload.",  # task_breakdown
                "DEVIATION: NONE\nSUMMARY: Implemented exactly as planned.",       # closing_report
            ],
            "architect": [_PLAN_TEXT],
            "qa_auditor": [
                "VERDICT: APPROVED\nFEEDBACK: Data Model section looks correct.",
                "VERDICT: APPROVED\nFEEDBACK: API/Interface section looks correct.",
                "VERDICT: APPROVED\nFEEDBACK: Error Handling section looks correct.",
                "VERDICT: APPROVED\nFEEDBACK: Dependencies/Integration section looks correct.",
                "VERDICT: APPROVED\nFEEDBACK: Implementation matches the plan.",
            ],
            "implementer": ["def health():\n    return {'status': 'ok'}, 200"],
        },
    },
}

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "settings.yaml")


def _build_orchestrator(tmp_dir: str, roles: dict) -> Orchestrator:
    orch = Orchestrator(_CONFIG_PATH)
    orch.memory.storage_dir = tmp_dir  # empty dir -> search() returns [] with no disk state to load

    def _fake_create_role_model(role_name: str):
        if role_name not in roles:
            raise AssertionError(
                f"Scenario didn't script role {role_name!r} but the pipeline called it"
            )
        return FakeModel(role_name, roles[role_name])

    orch.factory.create_role_model = _fake_create_role_model

    async def _fake_get_embedding(text: str):
        # A non-zero constant vector: LocalVectorMemory._normalize rejects an
        # all-zero query (division by zero), same as it would for real Ollama
        # output, so this fake must stay a valid unit-normalizable vector too.
        vec = [0.0] * orch.memory.dimension
        vec[0] = 1.0
        return vec

    orch.embedder.get_embedding = _fake_get_embedding
    return orch


def _strip_volatile(obj):
    """Recursively removes run-specific fields (ids/timestamps/durations) and
    every trace entry's duration_ms, so two runs of the same scenario compare
    equal regardless of wall-clock timing or the random request_id."""
    if isinstance(obj, dict):
        return {
            k: _strip_volatile(v)
            for k, v in obj.items()
            if k not in _VOLATILE_KEYS
        }
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    return obj


async def _run_scenario(scenario: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp_dir:
        orch = _build_orchestrator(tmp_dir, scenario["roles"])
        try:
            receipt = await orch.run_complex_task(scenario["query"])
        finally:
            await orch.aclose()
    return receipt


def _golden_path(name: str) -> str:
    return os.path.join(GOLDEN_DIR, f"{name}.json")


def capture_goldens():
    """Writes golden fixtures to disk. Run manually once (or after a deliberate,
    reviewed behavior change) — never automatically from the test itself, or a
    regression would silently rewrite its own baseline."""
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    for name, scenario in SCENARIOS.items():
        receipt = asyncio.run(_run_scenario(scenario))
        stripped = _strip_volatile(receipt)
        with open(_golden_path(name), "w") as f:
            json.dump(stripped, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"wrote {_golden_path(name)}")


def test_goldens_exist():
    for name in SCENARIOS:
        assert os.path.exists(_golden_path(name)), (
            f"Missing golden fixture for {name!r} — run "
            f"`python tests/test_orchestrator_golden.py --capture` once to create it."
        )


def test_scenarios_match_golden():
    for name, scenario in SCENARIOS.items():
        golden_file = _golden_path(name)
        assert os.path.exists(golden_file), (
            f"Missing golden fixture for {name!r} — run "
            f"`python tests/test_orchestrator_golden.py --capture` once to create it."
        )
        with open(golden_file) as f:
            expected = json.load(f)
        actual = _strip_volatile(asyncio.run(_run_scenario(scenario)))
        assert actual == expected, (
            f"Receipt for scenario {name!r} no longer matches its golden fixture.\n"
            f"Expected:\n{json.dumps(expected, indent=2, sort_keys=True)}\n\n"
            f"Actual:\n{json.dumps(actual, indent=2, sort_keys=True)}"
        )


def test_run_simple_query_is_deleted():
    """O2: run_simple_query was dead code (verified by the pre-O2 version of
    this test, which required exactly 2 occurrences — the def and its
    docstring self-reference — in core/orchestrator.py and zero in main.py)
    and has now been removed. This guards against it silently coming back."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for relpath in ("main.py", "core/orchestrator.py"):
        with open(os.path.join(repo_root, relpath)) as f:
            text = f.read()
        assert "run_simple_query" not in text, (
            f"{relpath} still references run_simple_query — O2 deleted it, "
            "it should not reappear."
        )


def test_orchestrator_is_a_thin_facade():
    """O9: retain the caller contract while keeping pipeline control flow outside it."""
    signature = inspect.signature(Orchestrator.run_complex_task)
    assert list(signature.parameters) == [
        "self", "user_query", "on_chunk", "prior_breakdown", "prior_report",
        "macro_iteration", "output_contract", "schema_snapshot", "cwe_checks",
    ]
    source = inspect.getsource(Orchestrator.run_complex_task)
    assert "self._pipeline_runner.run_complex_task" in source
    assert len(source.splitlines()) <= 20


def test_context_stages_cover_schema_and_macro_reentry():
    """O5: extracted context stages preserve schema and macro-loop behavior."""
    schema = parse_snapshot({
        "schema_version": "1.0",
        "dialect": "postgres",
        "tables": [{
            "name": "users",
            "columns": [{"name": "id", "type": "integer", "primary_key": True}],
        }],
    }, source="test-schema")
    roles = copy.deepcopy(SCENARIOS["coding_request_approved_first_pass"]["roles"])
    with tempfile.TemporaryDirectory() as tmp_dir:
        orch = _build_orchestrator(tmp_dir, roles)
        try:
            receipt = asyncio.run(orch.run_complex_task(
                "Add a health check endpoint to the API.", schema_snapshot=schema,
            ))
        finally:
            asyncio.run(orch.aclose())
    assert receipt["status"] == "completed"
    assert receipt["outcome"]["schema_grounding"]["ran"] is True
    assert receipt["outcome"]["schema_grounding"]["conformance_check"]["ran"] is True
    assert receipt["outcome"]["rag"]["ran"] is True

    macro_roles = {
        "manager": ["DEVIATION: NONE\nSUMMARY: Reused prior outline."],
        "architect": [_PLAN_TEXT],
        "qa_auditor": ["VERDICT: APPROVED"] * 5,
        "implementer": ["implementation"],
    }
    with tempfile.TemporaryDirectory() as tmp_dir:
        orch = _build_orchestrator(tmp_dir, macro_roles)
        try:
            receipt = asyncio.run(orch.run_complex_task(
                "Retry task", prior_breakdown="1. Prior outline", prior_report="Prior findings",
            ))
        finally:
            asyncio.run(orch.aclose())
    assert receipt["status"] == "completed"
    assert receipt["outcome"]["router_decision"] == "COMPLEX_ARCHITECTURE"
    assert receipt["breakdown"] == "1. Prior outline"


def test_outcome_recorder_and_disabled_closing_report():
    """O8: stages own receipt data and skipped closing stays explicit."""
    recorder = OutcomeRecorder()
    recorded = {"ran": True, "details": {"attempts": 1}}
    recorder.record("implementation_check", recorded)
    recorded["details"]["attempts"] = 99
    snapshot = recorder.snapshot()
    snapshot["implementation_check"]["details"]["attempts"] = 77
    assert recorder.snapshot() == {
        "implementation_check": {"ran": True, "details": {"attempts": 1}},
    }

    roles = copy.deepcopy(SCENARIOS["coding_request_approved_first_pass"]["roles"])
    roles["manager"] = roles["manager"][:1]
    with tempfile.TemporaryDirectory() as tmp_dir:
        orch = _build_orchestrator(tmp_dir, roles)
        orch.config["pipeline"]["closing_report"] = False
        try:
            receipt = asyncio.run(orch.run_complex_task("Build feature"))
        finally:
            asyncio.run(orch.aclose())
    assert receipt["outcome"]["closing_report"] == {"ran": False}
    assert receipt["closing_report"] is None
    assert not any(entry["stage"] == "closing_report" for entry in receipt["trace"])


def test_review_loops_cover_sectioned_and_monolithic_revisions():
    """O6/O7: both design-gate strategies retain the retry and trace contract."""
    sectioned_roles = {
        "router": ["CODING_REQUEST"],
        "manager": ["1. Outline", "DEVIATION: NONE\nSUMMARY: Done."],
        "architect": [_PLAN_TEXT, "Revised data model section."],
        "qa_auditor": [
            "VERDICT: NEEDS_REVISION\nFEEDBACK: Add the missing field.",
            "VERDICT: APPROVED\nFEEDBACK: Fixed.",
            "VERDICT: APPROVED", "VERDICT: APPROVED", "VERDICT: APPROVED",
            "VERDICT: APPROVED\nFEEDBACK: Implementation matches.",
        ],
        "implementer": ["implementation"],
    }
    receipt = asyncio.run(_run_scenario({"query": "Build feature", "roles": sectioned_roles}))
    design_entries = [entry for entry in receipt["trace"] if entry["stage"] == "design_gate"]
    assert [(entry["section"], entry["attempt"], entry["verdict"]) for entry in design_entries] == [
        ("Data Model", 1, "NEEDS_REVISION"),
        ("Data Model", 2, "APPROVED"),
        ("API/Interface", 1, "APPROVED"),
        ("Error Handling", 1, "APPROVED"),
        ("Dependencies/Integration", 1, "APPROVED"),
    ]
    assert receipt["outcome"]["design_gate"]["approved"] is True
    assert receipt["outcome"]["design_gate"]["sections"]["Data Model"] == {
        "approved": True, "attempts": 2,
    }

    monolithic_roles = {
        "router": ["CODING_REQUEST"],
        "manager": ["1. Outline", "DEVIATION: NONE\nSUMMARY: Done."],
        "architect": ["Unsectioned plan.", "Revised unsectioned plan."],
        "qa_auditor": [
            "VERDICT: NEEDS_REVISION\nFEEDBACK: Clarify the API.",
            "VERDICT: APPROVED\nFEEDBACK: Clear now.",
            "VERDICT: APPROVED\nFEEDBACK: Implementation matches.",
        ],
        "implementer": ["implementation"],
    }
    receipt = asyncio.run(_run_scenario({"query": "Build feature", "roles": monolithic_roles}))
    design_entries = [entry for entry in receipt["trace"] if entry["stage"] == "design_gate"]
    assert [(entry["attempt"], entry["verdict"]) for entry in design_entries] == [
        (1, "NEEDS_REVISION"), (2, "APPROVED"),
    ]
    assert receipt["outcome"]["design_gate"] == {
        "ran": True, "mode": "monolithic", "approved": True,
    }


def test_review_loop_covers_implementation_retry_and_exhaustion():
    """O6 characterization: implementation retries and exhausted QA stay fail-closed."""
    implementation_retry_roles = {
        "router": ["CODING_REQUEST"],
        "manager": ["1. Outline", "DEVIATION: NONE\nSUMMARY: Done."],
        "architect": [_PLAN_TEXT, _PLAN_TEXT],
        "qa_auditor": ["VERDICT: APPROVED"] * 4 + [
            "VERDICT: NEEDS_REVISION\nFEEDBACK: Correct the handler.",
            "VERDICT: APPROVED\nFEEDBACK: Correct now.",
        ],
        "implementer": ["first implementation", "revised implementation"],
    }
    receipt = asyncio.run(_run_scenario({"query": "Build feature", "roles": implementation_retry_roles}))
    implementation_entries = [
        entry for entry in receipt["trace"] if entry["stage"] == "implementation_check"
    ]
    assert [(entry["attempt"], entry["verdict"]) for entry in implementation_entries] == [
        (1, "NEEDS_REVISION"), (2, "APPROVED"),
    ]
    assert receipt["outcome"]["implementation_check"] == {
        "ran": True, "approved": True, "attempts": 2, "feedback": None,
    }
    assert receipt["implementation"] == "revised implementation"

    exhausted_roles = {
        "router": ["CODING_REQUEST"],
        "manager": ["1. Outline", "DEVIATION: NONE\nSUMMARY: Done."],
        "architect": ["Unsectioned plan."],
        "qa_auditor": [
            "VERDICT: NEEDS_REVISION\nFEEDBACK: Still incomplete.",
            "VERDICT: NEEDS_REVISION\nFEEDBACK: Still incomplete.",
            "VERDICT: NEEDS_REVISION\nFEEDBACK: Still incomplete.",
            "VERDICT: APPROVED\nFEEDBACK: Implementation matches.",
        ],
        "implementer": ["implementation"],
    }
    receipt = asyncio.run(_run_scenario({"query": "Build feature", "roles": exhausted_roles}))
    design_entries = [entry for entry in receipt["trace"] if entry["stage"] == "design_gate"]
    assert [(entry["attempt"], entry["verdict"]) for entry in design_entries] == [
        (1, "NEEDS_REVISION"), (2, "NEEDS_REVISION"), (3, "NEEDS_REVISION"),
    ]
    assert receipt["outcome"]["design_gate"] == {
        "ran": True, "mode": "monolithic", "approved": False,
    }


if __name__ == "__main__":
    if "--capture" in sys.argv:
        capture_goldens()
    else:
        failures = []
        for fn in (
            test_goldens_exist, test_scenarios_match_golden, test_run_simple_query_is_deleted,
            test_context_stages_cover_schema_and_macro_reentry,
            test_outcome_recorder_and_disabled_closing_report,
            test_review_loops_cover_sectioned_and_monolithic_revisions,
            test_review_loop_covers_implementation_retry_and_exhaustion,
        ):
            try:
                fn()
                print(f"PASS {fn.__name__}")
            except AssertionError as e:
                failures.append(fn.__name__)
                print(f"FAIL {fn.__name__}: {e}")
        sys.exit(1 if failures else 0)
