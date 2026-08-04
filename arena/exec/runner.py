"""Async subprocess execution helper for /v1/exec.

v4.3.0: Added ``run_shell_command_stream`` — an async generator that
yields ``(stream, chunk)`` tuples as bytes arrive from the child
subprocess, so /v1/exec/stream can push NDJSON events to the agent
in real time instead of buffering the full output. Same lifecycle
tracking (``ACTIVE_PROCESSES``), same timeout/max-output semantics,
same truncation contract as :func:`run_shell_command`.
"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, AsyncIterator, Callable

ACTIVE_PROCESSES: dict[str, dict[str, Any]] = {}


def _process_group_kwargs() -> dict[str, Any]:
    """Start the child as its own process group / job so it can be killed whole.

    Without this, killing a timed-out command only signals the shell. Any
    grandchild it spawned (the usual case: ``bash -c "<something>"``) survives,
    reparents to init, and keeps running on the user's machine long after the
    request that created it is gone.
    """
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _kill_process_tree(proc: Any) -> None:
    """Kill the child and everything it started. Never raises."""
    pid = getattr(proc, "pid", None)
    if sys.platform != "win32" and pid:
        try:
            # Negative pid = the whole process group created above.
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass  # fall through to the single-process kill
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass


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
            **_process_group_kwargs(),
        )
        ACTIVE_PROCESSES[request_id] = {"cmd": cmd, "pid": proc.pid, "start": time.time()}
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode
        except asyncio.TimeoutError:
            timed_out = True
            # Kill the whole group, not just the shell. `proc.kill()` signals
            # the shell alone, so `bash -c "sleep 300"` left the sleep running
            # with PPID 1 -- a leaked process on the user's machine, outliving
            # the request that asked for it. It also kept the stdout pipe
            # open, so the 5s drain below always ran to full length: a
            # timeout=1 request consistently took 6s. Measured before the fix
            # (overshoot was a flat 5s at timeout=1,2,3,5) and after.
            _kill_process_tree(proc)
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


async def run_shell_command_stream(
    *,
    request_id: str,
    cmd: str,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    max_output: int,
) -> AsyncIterator[dict[str, Any]]:
    """Run a shell command and yield stream events as bytes arrive.

    Yielded event shapes (all dicts, JSON-serializable):

    - ``{"type": "start",  "pid": int}`` — once, after the process is spawned.
    - ``{"type": "stdout", "data": bytes}`` — each stdout chunk, raw bytes.
    - ``{"type": "stderr", "data": bytes}`` — each stderr chunk, raw bytes.
    - ``{"type": "exit",   "exit_code": int, "duration_sec": float,
          "stdout_bytes": int, "stderr_bytes": int, "truncated": bool,
          "timed_out": bool, "error": str | None}`` — always terminal.

    Byte-level chunks are surfaced verbatim so the caller (the /v1/exec/stream
    handler) can decide how to decode / re-frame them. The runner enforces
    ``max_output`` per stream (further bytes are counted but not emitted) and
    the wall-clock ``timeout`` (kills the process, drains remaining, and
    emits ``timed_out=True`` in the exit event). ``ACTIVE_PROCESSES`` gets the
    same start/pop lifecycle as :func:`run_shell_command` so ``/v1/ps`` and
    ``/v1/kill`` continue to work against streamed jobs.
    """
    t0 = time.time()
    timed_out = False
    stdout_bytes_total = 0
    stderr_bytes_total = 0
    truncated = False
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_process_group_kwargs(),
        )
        ACTIVE_PROCESSES[request_id] = {"cmd": cmd, "pid": proc.pid, "start": time.time()}
        yield {"type": "start", "pid": proc.pid}

        # Two reader tasks push chunks onto a shared queue. A ``None`` sentinel
        # per stream signals EOF. This lets us interleave stdout+stderr in the
        # order the OS produced them without one blocking the other.
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        _CHUNK = 4096

        async def _pump(stream: asyncio.StreamReader, tag: str) -> None:
            try:
                while True:
                    chunk = await stream.read(_CHUNK)
                    if not chunk:
                        break
                    await queue.put((tag, chunk))
            finally:
                await queue.put((tag, None))

        stdout_task = asyncio.create_task(_pump(proc.stdout, "stdout"))  # type: ignore[arg-type]
        stderr_task = asyncio.create_task(_pump(proc.stderr, "stderr"))  # type: ignore[arg-type]

        deadline = t0 + max(timeout, 1)
        eofs_seen = 0
        while eofs_seen < 2:
            remaining = deadline - time.time()
            if remaining <= 0:
                timed_out = True
                break
            try:
                tag, chunk = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                timed_out = True
                break
            if chunk is None:
                eofs_seen += 1
                continue
            if tag == "stdout":
                if stdout_bytes_total < max_output:
                    room = max_output - stdout_bytes_total
                    emit = chunk if len(chunk) <= room else chunk[:room]
                    stdout_bytes_total += len(chunk)
                    if len(chunk) > room:
                        truncated = True
                    if emit:
                        yield {"type": "stdout", "data": emit}
                else:
                    stdout_bytes_total += len(chunk)
                    truncated = True
            else:
                if stderr_bytes_total < max_output:
                    room = max_output - stderr_bytes_total
                    emit = chunk if len(chunk) <= room else chunk[:room]
                    stderr_bytes_total += len(chunk)
                    if len(chunk) > room:
                        truncated = True
                    if emit:
                        yield {"type": "stderr", "data": emit}
                else:
                    stderr_bytes_total += len(chunk)
                    truncated = True

        if timed_out:
            # Same reason as the buffered path: signalling only the shell
            # leaves grandchildren running and holding the pipes open.
            _kill_process_tree(proc)
            # Drain remaining pump output briefly so the tasks can exit.
            try:
                await asyncio.wait_for(
                    asyncio.gather(stdout_task, stderr_task, return_exceptions=True),
                    timeout=5,
                )
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

        try:
            exit_code = await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            exit_code = proc.returncode if proc.returncode is not None else -1

        duration = round(time.time() - t0, 3)
        yield {
            "type": "exit",
            "exit_code": exit_code,
            "duration_sec": duration,
            "stdout_bytes": stdout_bytes_total,
            "stderr_bytes": stderr_bytes_total,
            "truncated": truncated,
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
