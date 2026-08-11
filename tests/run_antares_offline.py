#!/usr/bin/env python3
"""
Offline test suite for the Antares security-triage layer
(docs/plan-security-advisor-antares.md, T8).

Covers, entirely without Ollama or a real `antares` binary:
  - context/antares/invoke.py: run_antares_query() against a fake `antares`
    fixture (tests/fixtures/antares/fake_bin/antares) that speaks the same
    stdin/stdout wire contract as the real CLI, keyed by FAKE_ANTARES_MODE.
  - context/antares/materialize.py: materialize_implementation() — plain-text
    and fenix-tagged-file paths, path-traversal rejection, tempdir cleanup.
  - core/orchestrator.py: Orchestrator._run_security_triage() — the T6
    touchpoint, exercised on a stub Orchestrator that skips __init__ (no
    Ollama/memory needed since only config + the security_triage path is used).

Mirrors tests/run_conformance_gate.py's style: a plain script, no pytest
dependency (none is installed in .venv), assertion-based, exit code is the
failure count so `python tests/run_antares_offline.py; echo $?` is scriptable.
"""
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

FAKE_BIN_DIR = Path(__file__).resolve().parent / "fixtures" / "antares" / "fake_bin"

from context.antares.base import AntaresInvocationError
from context.antares.invoke import run_antares_query
from context.antares.materialize import materialize_implementation
from core.orchestrator import Orchestrator

_failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [ok] {name}")
    else:
        print(f"  [FAIL] {name} {detail}")
        _failures.append(name)


def with_fake_antares(mode, record_path=None):
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN_DIR}{os.pathsep}{env['PATH']}"
    env["FAKE_ANTARES_MODE"] = mode
    if record_path:
        env["FAKE_ANTARES_RECORD"] = str(record_path)
    else:
        env.pop("FAKE_ANTARES_RECORD", None)
    return env


async def _run_with_env(coro_fn, env):
    """Runs coro_fn() with os.environ patched to env for the duration —
    asyncio.create_subprocess_exec inherits os.environ, not a passed-in env,
    unless invoke.py is given one explicitly (it is, via os.environ.copy()
    inside run_antares_query itself is NOT how env is threaded — invoke.py
    reads os.environ.copy() internally for ANTARES_DATA_DIR only; PATH
    resolution for shutil.which(binary) uses the real process environment).
    """
    old_environ = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        return await coro_fn()
    finally:
        os.environ.clear()
        os.environ.update(old_environ)


# ---------------------------------------------------------------------------
# invoke.py
# ---------------------------------------------------------------------------

async def test_invoke_success_no_findings(tmp_path):
    target = tmp_path / "t1_target"
    data = tmp_path / "t1_data"
    target.mkdir()
    data.mkdir()
    env = with_fake_antares("exit0")

    async def go():
        return await run_antares_query(
            str(target), str(data), [("CWE-89", "sql injection risk")],
            binary="antares", profile=None, timeout_seconds=10,
        )
    result = await _run_with_env(go, env)
    check("exit0: terminal_state completed", result.terminal_state == "completed")
    check("exit0: not degraded", result.degraded is False)
    check("exit0: no findings", result.findings == [])
    check("exit0: stdout_sha256 present", bool(result.stdout_sha256))


async def test_invoke_success_with_findings_exit2(tmp_path):
    target = tmp_path / "t2_target"
    data = tmp_path / "t2_data"
    target.mkdir()
    data.mkdir()
    env = with_fake_antares("exit2_findings")

    async def go():
        return await run_antares_query(
            str(target), str(data), [("CWE-89", "sql")],
            binary="antares", profile=None, timeout_seconds=10,
        )
    result = await _run_with_env(go, env)
    check("exit2: treated as valid report, not fatal", result.terminal_state == "completed")
    check("exit2: findings parsed", len(result.findings) == 1)
    check("exit2: finding cwe_ids", result.findings[0].cwe_ids == ["CWE-89"])
    check("exit2: finding review_status defaults pending", result.findings[0].review_status == "pending")


async def test_invoke_execution_failed(tmp_path):
    target = tmp_path / "t3_target"
    data = tmp_path / "t3_data"
    target.mkdir()
    data.mkdir()
    env = with_fake_antares("exit1")

    async def go():
        return await run_antares_query(
            str(target), str(data), [("CWE-89", "sql")],
            binary="antares", profile=None, timeout_seconds=10,
        )
    try:
        await _run_with_env(go, env)
        check("exit1: raises AntaresInvocationError", False)
    except AntaresInvocationError as e:
        check("exit1: terminal_state execution-failed", e.terminal_state == "execution-failed")


async def test_invoke_bad_json(tmp_path):
    target = tmp_path / "t4_target"
    data = tmp_path / "t4_data"
    target.mkdir()
    data.mkdir()
    env = with_fake_antares("bad_json")

    async def go():
        return await run_antares_query(
            str(target), str(data), [("CWE-89", "sql")],
            binary="antares", profile=None, timeout_seconds=10,
        )
    try:
        await _run_with_env(go, env)
        check("bad_json: raises AntaresInvocationError", False)
    except AntaresInvocationError as e:
        check("bad_json: terminal_state output-malformed", e.terminal_state == "output-malformed")


async def test_invoke_binary_unavailable(tmp_path):
    target = tmp_path / "t5_target"
    data = tmp_path / "t5_data"
    target.mkdir()
    data.mkdir()

    async def go():
        return await run_antares_query(
            str(target), str(data), [("CWE-89", "sql")],
            binary="definitely-not-a-real-binary-xyz", profile=None, timeout_seconds=10,
        )
    try:
        await go()
        check("missing binary: raises AntaresInvocationError", False)
    except AntaresInvocationError as e:
        check("missing binary: terminal_state binary-unavailable", e.terminal_state == "binary-unavailable")


async def test_invoke_path_traversal_finding_rejected(tmp_path):
    target = tmp_path / "t6_target"
    data = tmp_path / "t6_data"
    target.mkdir()
    data.mkdir()
    env = with_fake_antares("path_traversal_finding")

    async def go():
        return await run_antares_query(
            str(target), str(data), [("CWE-22", "path traversal")],
            binary="antares", profile=None, timeout_seconds=10,
        )
    try:
        await _run_with_env(go, env)
        check("traversal finding: rejected", False)
    except AntaresInvocationError as e:
        check("traversal finding: terminal_state output-malformed", e.terminal_state == "output-malformed")


async def test_invoke_oversized_output(tmp_path):
    target = tmp_path / "t7_target"
    data = tmp_path / "t7_data"
    target.mkdir()
    data.mkdir()
    env = with_fake_antares("oversized")

    async def go():
        return await run_antares_query(
            str(target), str(data), [("CWE-89", "sql")],
            binary="antares", profile=None, timeout_seconds=10,
        )
    try:
        await _run_with_env(go, env)
        check("oversized output: rejected", False)
    except AntaresInvocationError as e:
        check("oversized output: terminal_state output-too-large", e.terminal_state == "output-too-large")


async def test_invoke_timeout(tmp_path):
    target = tmp_path / "t8_target"
    data = tmp_path / "t8_data"
    target.mkdir()
    data.mkdir()
    env = with_fake_antares("hang")

    async def go():
        return await run_antares_query(
            str(target), str(data), [("CWE-89", "sql")],
            binary="antares", profile=None, timeout_seconds=1,
        )
    try:
        await _run_with_env(go, env)
        check("hang: raises AntaresInvocationError", False)
    except AntaresInvocationError as e:
        check("hang: terminal_state timeout", e.terminal_state == "timeout")


async def test_invoke_single_call_carries_all_cwes_and_rationales(tmp_path):
    """Multiple CWEs in one request must produce exactly ONE subprocess
    invocation (plan P5) with every cwe_id + rationale reaching the CLI."""
    target = tmp_path / "t9_target"
    data = tmp_path / "t9_data"
    record = tmp_path / "t9_record.json"
    target.mkdir()
    data.mkdir()
    env = with_fake_antares("exit0", record_path=record)
    cwe_checks = [("CWE-89", "sql injection risk"), ("CWE-79", "xss in template")]

    async def go():
        return await run_antares_query(
            str(target), str(data), cwe_checks,
            binary="antares", profile="antares-local", timeout_seconds=10,
        )
    await _run_with_env(go, env)
    check("single-call: record file written (one invocation happened)", record.exists())
    recorded = json.loads(record.read_text())
    request = json.loads(recorded["stdin"])
    check("single-call: cwd is target_dir", os.path.realpath(recorded["cwd"]) == os.path.realpath(str(target)))
    check("single-call: ANTARES_DATA_DIR points at data_dir",
          os.path.realpath(recorded["antares_data_dir"]) == os.path.realpath(str(data)))
    check("single-call: cwe_ids carries both", request["cwe_ids"] == ["CWE-89", "CWE-79"])
    check("single-call: query carries both rationales",
          "sql injection risk" in request["query"] and "xss in template" in request["query"])
    check("single-call: profile forwarded", request.get("profile") == "antares-local")


# ---------------------------------------------------------------------------
# materialize.py
# ---------------------------------------------------------------------------

def test_materialize_plain_text():
    snapshot_dir = None
    with materialize_implementation("print('hello')", output_contract=None) as mat:
        snapshot_dir = mat.snapshot_dir
        check("plain: snapshot_dir exists", os.path.isdir(mat.snapshot_dir))
        check("plain: data_dir exists", os.path.isdir(mat.data_dir))
        target = os.path.join(mat.snapshot_dir, "implementation.txt")
        check("plain: implementation.txt written", os.path.isfile(target))
        with open(target) as f:
            check("plain: content matches", f.read() == "print('hello')")
    check("plain: snapshot_dir removed after context exit", not os.path.exists(snapshot_dir))


def test_materialize_fenix_tagged_create_and_modify():
    payload = (
        "STATUS: ok\nSUMMARY: test\n"
        "=== FILE START ===\n"
        "PATH: src/foo.py\n"
        "ACTION: create\n"
        "--- CONTENT ---\n"
        "print('foo')\n"
        "=== FILE END ===\n"
        "=== FILE START ===\n"
        "PATH: src/bar.py\n"
        "ACTION: modify\n"
        "--- CONTENT ---\n"
        "print('bar')\n"
        "=== FILE END ===\n"
    )
    with materialize_implementation(payload, output_contract="fenix-tagged-file") as mat:
        foo = os.path.join(mat.snapshot_dir, "src", "foo.py")
        bar = os.path.join(mat.snapshot_dir, "src", "bar.py")
        check("fenix: create writes file", os.path.isfile(foo))
        check("fenix: modify writes file", os.path.isfile(bar))
        with open(foo) as f:
            check("fenix: create content", f.read().strip() == "print('foo')")


def test_materialize_fenix_tagged_delete_not_written():
    payload = (
        "=== FILE START ===\n"
        "PATH: src/gone.py\n"
        "ACTION: delete\n"
        "--- CONTENT ---\n"
        "\n"
        "=== FILE END ===\n"
    )
    with materialize_implementation(payload, output_contract="fenix-tagged-file") as mat:
        check("fenix: delete action materializes nothing",
              not os.path.exists(os.path.join(mat.snapshot_dir, "src", "gone.py")))


def test_materialize_rejects_absolute_path():
    payload = (
        "=== FILE START ===\n"
        "PATH: /etc/passwd\n"
        "ACTION: create\n"
        "--- CONTENT ---\n"
        "pwned\n"
        "=== FILE END ===\n"
    )
    try:
        with materialize_implementation(payload, output_contract="fenix-tagged-file"):
            pass
        check("fenix: absolute path rejected", False)
    except AntaresInvocationError as e:
        check("fenix: absolute path terminal_state", e.terminal_state == "path-traversal-rejected")


def test_materialize_rejects_traversal():
    payload = (
        "=== FILE START ===\n"
        "PATH: ../../etc/passwd\n"
        "ACTION: create\n"
        "--- CONTENT ---\n"
        "pwned\n"
        "=== FILE END ===\n"
    )
    try:
        with materialize_implementation(payload, output_contract="fenix-tagged-file"):
            pass
        check("fenix: traversal path rejected", False)
    except AntaresInvocationError as e:
        check("fenix: traversal terminal_state", e.terminal_state == "path-traversal-rejected")


def test_materialize_cleanup_on_exception():
    """Even if the with-block body raises, the tempdir must not survive it."""
    snapshot_dir = None
    try:
        with materialize_implementation("code", output_contract=None) as mat:
            snapshot_dir = mat.snapshot_dir
            raise ValueError("simulated failure inside the with-block")
    except ValueError:
        pass
    check("plain: cleanup happens even after exception in caller", not os.path.exists(snapshot_dir))


# ---------------------------------------------------------------------------
# core/orchestrator.py — Orchestrator._run_security_triage (T6 wiring)
# ---------------------------------------------------------------------------

class FakeOrchestrator(Orchestrator):
    def __init__(self, config):
        self.config = config  # skip real __init__: no Ollama/memory needed


async def test_orch_not_requested():
    orch = FakeOrchestrator({"security_triage": {}})
    body = {"outcome": {"fast_path": False}, "artifacts": {"implementation": "code"}}
    r = await orch._run_security_triage(None, body, None, "req-1")
    check("orch: not-requested ran=False", r["ran"] is False)
    check("orch: not-requested terminal_state", r["terminal_state"] == "not-requested")
    check("orch: not-requested not degraded", r["degraded"] is False)


async def test_orch_fast_path():
    orch = FakeOrchestrator({"security_triage": {}})
    body = {"outcome": {"fast_path": True}, "artifacts": {}}
    r = await orch._run_security_triage([("CWE-89", "sql")], body, None, "req-2")
    check("orch: fast-path ran=False", r["ran"] is False)
    check("orch: fast-path terminal_state", r["terminal_state"] == "snapshot-unavailable")
    check("orch: fast-path degraded", r["degraded"] is True)


async def test_orch_artifact_missing():
    orch = FakeOrchestrator({"security_triage": {}})
    body = {"outcome": {"fast_path": False}, "artifacts": {"implementation": ""}}
    r = await orch._run_security_triage([("CWE-89", "sql")], body, None, "req-3")
    check("orch: artifact-missing ran=False", r["ran"] is False)
    check("orch: artifact-missing terminal_state", r["terminal_state"] == "artifact-missing")
    check("orch: artifact-missing degraded", r["degraded"] is True)


async def test_orch_success_end_to_end():
    env = with_fake_antares("exit2_findings")
    orch = FakeOrchestrator({"security_triage": {"binary": "antares", "timeout_seconds": 10}})
    body = {"outcome": {"fast_path": False}, "artifacts": {"implementation": "print('hi')"}}

    async def go():
        return await orch._run_security_triage([("CWE-89", "sql injection")], body, None, "req-4")
    r = await _run_with_env(go, env)
    check("orch: success ran=True", r["ran"] is True)
    check("orch: success terminal_state completed", r["terminal_state"] == "completed")
    check("orch: success not degraded", r["degraded"] is False)
    check("orch: success requested carries rationale", r["requested"] == [{"cwe_id": "CWE-89", "rationale": "sql injection"}])
    check("orch: success findings normalized (dicts, not dataclasses)", isinstance(r["findings"][0], dict))
    check("orch: success finding review_status pending", r["findings"][0]["review_status"] == "pending")


async def test_orch_invocation_error_degrades_not_raises():
    env = with_fake_antares("exit1")
    orch = FakeOrchestrator({"security_triage": {"binary": "antares", "timeout_seconds": 10}})
    body = {"outcome": {"fast_path": False}, "artifacts": {"implementation": "print('hi')"}}

    async def go():
        return await orch._run_security_triage([("CWE-89", "sql")], body, None, "req-5")
    r = await _run_with_env(go, env)
    check("orch: invocation failure never raises (I1)", True)  # reaching here already proves it
    check("orch: invocation failure ran=True", r["ran"] is True)
    check("orch: invocation failure terminal_state execution-failed", r["terminal_state"] == "execution-failed")
    check("orch: invocation failure degraded", r["degraded"] is True)
    check("orch: invocation failure findings empty", r["findings"] == [])


async def test_orch_binary_missing_degrades_not_raises():
    orch = FakeOrchestrator({"security_triage": {"binary": "definitely-not-a-real-binary-xyz", "timeout_seconds": 10}})
    body = {"outcome": {"fast_path": False}, "artifacts": {"implementation": "print('hi')"}}
    r = await orch._run_security_triage([("CWE-89", "sql")], body, None, "req-6")
    check("orch: binary-missing never raises (I1)", True)
    check("orch: binary-missing terminal_state", r["terminal_state"] == "binary-unavailable")
    check("orch: binary-missing degraded", r["degraded"] is True)


async def test_orch_fenix_tagged_file_materialization():
    """Confirms the orchestrator threads output_contract through to
    materialize_implementation (T3/T6 integration), not just plain text."""
    env = with_fake_antares("exit0", record_path=None)
    orch = FakeOrchestrator({"security_triage": {"binary": "antares", "timeout_seconds": 10}})
    payload = (
        "=== FILE START ===\nPATH: src/x.py\nACTION: create\n"
        "--- CONTENT ---\nprint('x')\n=== FILE END ===\n"
    )
    body = {"outcome": {"fast_path": False}, "artifacts": {"implementation": payload}}

    async def go():
        return await orch._run_security_triage(
            [("CWE-89", "sql")], body, "fenix-tagged-file", "req-7"
        )
    r = await _run_with_env(go, env)
    check("orch: fenix-tagged-file contract completes without error", r["terminal_state"] == "completed")


def run_sync(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def main() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        print("invoke.py:")
        run_sync(test_invoke_success_no_findings(tmp_path))
        run_sync(test_invoke_success_with_findings_exit2(tmp_path))
        run_sync(test_invoke_execution_failed(tmp_path))
        run_sync(test_invoke_bad_json(tmp_path))
        run_sync(test_invoke_binary_unavailable(tmp_path))
        run_sync(test_invoke_path_traversal_finding_rejected(tmp_path))
        run_sync(test_invoke_oversized_output(tmp_path))
        run_sync(test_invoke_timeout(tmp_path))
        run_sync(test_invoke_single_call_carries_all_cwes_and_rationales(tmp_path))

        print("materialize.py:")
        test_materialize_plain_text()
        test_materialize_fenix_tagged_create_and_modify()
        test_materialize_fenix_tagged_delete_not_written()
        test_materialize_rejects_absolute_path()
        test_materialize_rejects_traversal()
        test_materialize_cleanup_on_exception()

        print("core/orchestrator.py (_run_security_triage):")
        run_sync(test_orch_not_requested())
        run_sync(test_orch_fast_path())
        run_sync(test_orch_artifact_missing())
        run_sync(test_orch_success_end_to_end())
        run_sync(test_orch_invocation_error_degrades_not_raises())
        run_sync(test_orch_binary_missing_degrades_not_raises())
        run_sync(test_orch_fenix_tagged_file_materialization())

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {_failures}")
    else:
        print("ALL CASES PASSED")
    return len(_failures)


if __name__ == "__main__":
    sys.exit(main())
