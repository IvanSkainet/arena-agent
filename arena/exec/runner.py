"""Async subprocess execution helper for /v1/exec."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable

ACTIVE_PROCESSES: dict[str, dict[str, Any]] = {}


async def run_shell_command(
    *,
    request_id: str,
    cmd: str,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    max_output: int,
    decode_output_fn: Callable[[bytes], str],
) -> dict[str, Any]:
    """Run a shell command, track active process, decode/truncate output."""
    t0 = time.time()
    timed_out = False
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        ACTIVE_PROCESSES[request_id] = {"cmd": cmd, "pid": proc.pid, "start": time.time()}
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                stdout_bytes, stderr_bytes = b"", b""
            exit_code = proc.returncode if proc.returncode is not None else -1

        duration = round(time.time() - t0, 3)
        stdout = decode_output_fn(stdout_bytes) if stdout_bytes else ""
        stderr = decode_output_fn(stderr_bytes) if stderr_bytes else ""
        truncated = False
        if len(stdout.encode("utf-8", "replace")) > max_output:
            stdout = stdout.encode("utf-8", "replace")[:max_output].decode("utf-8", "replace")
            truncated = True
        if len(stderr.encode("utf-8", "replace")) > max_output:
            stderr = stderr.encode("utf-8", "replace")[:max_output].decode("utf-8", "replace")
            truncated = True
        return {
            "ok": (not timed_out) and exit_code == 0,
            "request_id": request_id,
            "exit_code": exit_code,
            "duration_sec": duration,
            "cwd": str(cwd),
            "stdout": stdout,
            "stderr": stderr,
            "truncated": truncated,
            "stdout_bytes": len(stdout_bytes) if stdout_bytes else 0,
            "stderr_bytes": len(stderr_bytes) if stderr_bytes else 0,
            "timed_out": timed_out,
            "error": f"timeout after {timeout}s" if timed_out else None,
        }
    finally:
        ACTIVE_PROCESSES.pop(request_id, None)


def active_processes_snapshot(*, max_cmd_len: int = 200) -> list[dict[str, Any]]:
    now = time.time()
    return [
        {
            "request_id": request_id,
            "pid": info["pid"],
            "cmd": info["cmd"][:max_cmd_len],
            "uptime_sec": round(now - info["start"], 1),
        }
        for request_id, info in ACTIVE_PROCESSES.items()
    ]
