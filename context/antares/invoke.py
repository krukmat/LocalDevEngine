"""
Invokes the official Antares CLI as a subprocess — one call per request,
carrying all requested CWEs. See docs/plan-security-advisor-antares.md (T4, P5).
"""
import asyncio
import hashlib
import json
import os
import shutil
from typing import List, Optional, Tuple

from .base import AntaresFinding, AntaresInvocationError, AntaresResult

_MAX_OUTPUT_BYTES = 1024 * 1024


async def _drain(stream: Optional[asyncio.StreamReader]) -> None:
    if stream is None:
        return
    try:
        while not stream.at_eof():
            if not await stream.read(65536):
                break
    except Exception:
        pass


async def _cleanup(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(
                asyncio.gather(proc.wait(), _drain(proc.stdout), _drain(proc.stderr)),
                timeout=5,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await asyncio.gather(proc.wait(), _drain(proc.stdout), _drain(proc.stderr))
    else:
        await asyncio.gather(_drain(proc.stdout), _drain(proc.stderr))


class _SharedBudget:
    def __init__(self, limit: int):
        self.remaining = limit


async def _read_capped(stream: asyncio.StreamReader, budget: _SharedBudget) -> bytes:
    chunks = []
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            break
        chunks.append(chunk)
        budget.remaining -= len(chunk)
        if budget.remaining < 0:
            raise AntaresInvocationError(
                "captured output exceeded 1 MiB",
                terminal_state="output-too-large",
            )
    return b"".join(chunks)


def _normalize_finding(raw: dict, target_dir: str) -> AntaresFinding:
    try:
        if not isinstance(raw, dict):
            raise ValueError(f"finding is not an object: {raw!r}")
        file_path = raw["file_path"]
        title = raw["title"]
        cwe_ids = raw["cwe_ids"]
        likelihood = raw["likelihood_of_exploit"]
        submission_rank = raw.get("submission_rank")
        if not isinstance(file_path, str) or not isinstance(title, str):
            raise ValueError("file_path/title must be strings")
        if not isinstance(cwe_ids, list) or not all(isinstance(c, str) for c in cwe_ids):
            raise ValueError("cwe_ids must be a list of strings")
        if not isinstance(likelihood, str):
            raise ValueError("likelihood_of_exploit must be a string")
        if submission_rank is not None and type(submission_rank) is not int:
            raise ValueError("submission_rank must be an int or null")

        resolved_target = os.path.realpath(target_dir)
        resolved_file = os.path.realpath(os.path.join(target_dir, file_path))
        if os.path.commonpath([resolved_target, resolved_file]) != resolved_target:
            raise ValueError(f"file_path escapes target dir: {file_path}")
        relative_path = os.path.relpath(resolved_file, resolved_target)

        return AntaresFinding(
            title=title,
            file_path=relative_path,
            cwe_ids=cwe_ids,
            likelihood_of_exploit=likelihood,
            submission_rank=submission_rank,
        )
    except (KeyError, TypeError, ValueError) as e:
        raise AntaresInvocationError(
            f"malformed finding: {e}",
            terminal_state="output-malformed",
        )


async def run_antares_query(
    target_dir: str,
    data_dir: str,
    cwe_checks: List[Tuple[str, str]],
    *,
    binary: str,
    profile: Optional[str],
    timeout_seconds: int,
) -> AntaresResult:
    resolved_binary = shutil.which(binary)
    if resolved_binary is None:
        raise AntaresInvocationError(
            f"binary not found on PATH: {binary}",
            terminal_state="binary-unavailable",
        )

    request = {
        "target": target_dir,
        "cwe_ids": [cwe_id for cwe_id, _ in cwe_checks],
        "query": "\n".join(f"{cwe_id}: {rationale}" for cwe_id, rationale in cwe_checks),
    }
    if profile:
        request["profile"] = profile
    stdin_payload = json.dumps(request).encode("utf-8")

    env = os.environ.copy()
    env["ANTARES_DATA_DIR"] = data_dir

    try:
        proc = await asyncio.create_subprocess_exec(
            resolved_binary, "tool", "query", "--stdin",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=target_dir,
            env=env,
        )
    except OSError as e:
        raise AntaresInvocationError(
            f"failed to spawn antares: {e}",
            terminal_state="execution-failed",
        )

    budget = _SharedBudget(_MAX_OUTPUT_BYTES)

    async def _talk_to_process():
        proc.stdin.write(stdin_payload)
        await proc.stdin.drain()
        proc.stdin.close()
        stdout_task = asyncio.ensure_future(_read_capped(proc.stdout, budget))
        stderr_task = asyncio.ensure_future(_read_capped(proc.stderr, budget))
        try:
            stdout_bytes, stderr_bytes = await asyncio.gather(stdout_task, stderr_task)
        except BaseException:
            for t in (stdout_task, stderr_task):
                if not t.done():
                    t.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        await proc.wait()
        return stdout_bytes, stderr_bytes

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            _talk_to_process(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        await _cleanup(proc)
        raise AntaresInvocationError(
            "antares invocation timed out",
            terminal_state="timeout",
        )
    except AntaresInvocationError:
        await _cleanup(proc)
        raise
    except (BrokenPipeError, ConnectionResetError, OSError) as e:
        await _cleanup(proc)
        raise AntaresInvocationError(
            f"I/O error communicating with antares: {e}",
            terminal_state="execution-failed",
        )
    except asyncio.CancelledError:
        await asyncio.shield(_cleanup(proc))
        raise

    if proc.returncode not in (0, 2):
        raise AntaresInvocationError(
            f"antares exited {proc.returncode}: {stderr_bytes[:500]!r}",
            terminal_state="execution-failed",
        )

    try:
        stdout_text = stdout_bytes.decode("utf-8")
        body = json.loads(stdout_text)
        if not isinstance(body, dict):
            raise ValueError(f"top-level output is not an object: {body!r}")
        raw_findings = body["findings"]
        if not isinstance(raw_findings, list):
            raise ValueError("findings must be a list")
        findings = [_normalize_finding(f, target_dir) for f in raw_findings]
    except AntaresInvocationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        raise AntaresInvocationError(
            f"antares output malformed: {e}",
            terminal_state="output-malformed",
        )

    return AntaresResult(
        findings=findings,
        terminal_state="completed",
        degraded=False,
        stdout_sha256=hashlib.sha256(stdout_bytes).hexdigest(),
    )
