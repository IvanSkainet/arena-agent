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
import ntpath
import os
import signal
import subprocess
import sys
import time
import weakref
from pathlib import Path
from typing import Any, AsyncGenerator, Callable

from arena.exec import win_job

ACTIVE_PROCESSES: dict[str, dict[str, Any]] = {}

# The Job Object of each Windows command that is still being cleaned up after.
_JOBS: weakref.WeakKeyDictionary[Any, Any] = weakref.WeakKeyDictionary()
_CREATE_SUSPENDED = 0x00000004


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


def _new_job() -> Any:
    """The job a Windows command runs in; None where a process group does that work."""
    if sys.platform != "win32":
        return None
    return win_job.CommandJob.create()


def _job_of(proc: Any) -> Any:
    try:
        return _JOBS.get(proc)
    except TypeError:  # cannot be weakly referenced, so it was never registered
        return None


def _quietly(*steps: Callable[[], None]) -> bool:
    """Run cleanup steps that must not raise; report whether all of them worked."""
    worked = True
    for step in steps:
        try:
            step()
        except OSError:
            worked = False
    return worked


async def _spawn_shell(cmd: str, cwd: Path, env: dict[str, str]) -> Any:
    """Start the command. On Windows it starts inside a job it cannot leave.

    The process is created suspended, put into the job and only then allowed
    to run, so nothing it starts can be outside the job. A command that
    cannot be held is not run at all: letting it run would bring back the
    survivors this exists to prevent, and would do it silently.
    """
    job = _new_job()
    kwargs = _process_group_kwargs()
    if job is not None:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | _CREATE_SUSPENDED
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(cwd), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **kwargs)
    except BaseException:
        if job is not None:
            _quietly(job.close)
        raise
    if job is None:
        return proc
    try:
        # No await between the spawn and here: a cancellation that arrived in
        # between would leave a suspended process that nothing owns.
        job.hold(proc.pid)
    except OSError:
        _quietly(proc.kill, job.close)
        await _wait_for_exit(proc)
        await _release_pipes(proc)
        raise
    _JOBS[proc] = job
    return proc


def _release_job(proc: Any, completed: bool) -> None:
    """The command is over. Whatever it left running stays if it completed, dies if not."""
    job = _job_of(proc)
    if job is None:
        return
    del _JOBS[proc]
    # A job that cannot be disarmed is closed armed: that kills what is left,
    # which is the safer of the two mistakes.
    _quietly(job.disarm if completed else job.terminate, job.close)


def _kill_process_tree(proc: Any) -> None:
    """Kill the child and everything it started. Never raises.

    ``CREATE_NEW_PROCESS_GROUP`` does not make ``Process.kill()`` recursive on
    Windows. v4.169.43 proved that live: a timed-out ``cmd.exe`` died while its
    PowerShell child kept serializing diagnostic objects for three hours,
    reaching 44.5 GiB private bytes. ``taskkill /T`` kills the tree it finds
    when it looks, so a command started by this module is killed through its
    Job Object instead (#516). ``taskkill /T`` remains for a process that has
    no job, and the direct kill remains the fallback for both.
    """
    job = _job_of(proc)
    if job is not None and _quietly(job.terminate):
        return
    pid = getattr(proc, "pid", None)
    if pid:
        killer = _kill_windows_tree if sys.platform == "win32" else _kill_posix_group
        if killer(pid):
            return
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass


def _windows_taskkill() -> str:
    """Do not search a command's working directory for a privileged utility."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    if not ntpath.isabs(root):
        raise OSError("SystemRoot must be an absolute Windows path")
    return ntpath.join(root, "System32", "taskkill.exe")


def _kill_windows_tree(pid: int) -> bool:
    try:
        killed = subprocess.run(  # nosec B603 -- fixed argv, no shell
            [_windows_taskkill(), "/PID", str(pid), "/T", "/F"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return killed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _kill_posix_group(pid: int) -> bool:
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
        return True
    except OSError:
        return False


async def _terminate_if_running(proc: Any) -> None:
    """Cancellation/shutdown cleanup for a child not handled by timeout."""
    if proc is None or getattr(proc, "returncode", None) is not None:
        return
    _kill_process_tree(proc)
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except (asyncio.TimeoutError, ProcessLookupError, OSError):
        pass


def _decode_limited(data: bytes, decode: Callable[[bytes], str], limit: int) -> tuple[str, bool]:
    text = decode(data) if data else ""
    encoded = text.encode("utf-8", "replace")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", "replace"), True


class _StreamBudget:
    """Count every byte while emitting at most the per-stream budget."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.totals = {"stdout": 0, "stderr": 0}
        self.truncated = False

    def consume(self, tag: str, chunk: bytes) -> dict[str, Any] | None:
        before = self.totals[tag]
        self.totals[tag] += len(chunk)
        room = max(0, self.limit - before)
        if len(chunk) > room:
            self.truncated = True
        emit = chunk[:room]
        if emit:
            return {"type": tag, "data": emit}
        return None


async def _buffered_output(proc: Any, timeout: int) -> tuple[bytes, bytes, bool]:
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout, stderr, False
    except asyncio.TimeoutError:
        _kill_process_tree(proc)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            stdout, stderr = b"", b""
        return stdout, stderr, True


async def _wait_for_exit(proc: Any) -> int:
    try:
        return await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        return proc.returncode if proc.returncode is not None else -1


async def _finish_stream_pumps(proc: Any, pumps: list[asyncio.Task], timed_out: bool) -> None:
    if not timed_out:
        await asyncio.gather(*pumps, return_exceptions=True)
        return
    _kill_process_tree(proc)
    try:
        await asyncio.wait_for(asyncio.gather(*pumps, return_exceptions=True), timeout=5)
    except asyncio.TimeoutError:
        pass


async def _cancel_pumps(pumps: list[asyncio.Task | None]) -> None:
    active = [task for task in pumps if task is not None]
    for task in active:
        task.cancel()
    await asyncio.gather(*active, return_exceptions=True)


# How long cleanup waits for a dead child's pipes to report end-of-file.
# A process that escaped the tree kill can still hold a pipe open; cleanup
# must not wait for it forever.
_PIPE_RELEASE_TIMEOUT = 2.0


async def _read_to_eof(stream: asyncio.StreamReader) -> None:
    while await stream.read(65536):
        pass


# asyncio closes a subprocess transport only after the process has exited and
# every pipe has reported end-of-file. A reader that was paused because nobody
# consumed its output never reads again, so without this the transport stays
# open until the garbage collector destroys it (#593).
async def _release_pipes(proc: Any) -> None:
    """Read a finished child's pipes to end-of-file so asyncio closes them."""
    streams = [s for s in (getattr(proc, "stdout", None), getattr(proc, "stderr", None)) if s is not None]
    if not streams:
        return
    drained = asyncio.gather(*(_read_to_eof(s) for s in streams), return_exceptions=True)
    try:
        await asyncio.wait_for(drained, timeout=_PIPE_RELEASE_TIMEOUT)
    except asyncio.TimeoutError:
        pass


async def _stop_reading(proc: Any, pumps: list[asyncio.Task | None]) -> None:
    """Cancel the output pumps of a finished child and release its pipes."""
    await _cancel_pumps(pumps)
    await _release_pipes(proc)


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
    # Completed means the command ended by itself and its output was read to
    # the end. Anything else -- timeout, cancellation, a failure in here --
    # leaves nothing of the command running.
    completed = False
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await _spawn_shell(cmd, cwd, env)
        ACTIVE_PROCESSES[request_id] = {"cmd": cmd, "pid": proc.pid, "start": time.time()}
        stdout_bytes, stderr_bytes, timed_out = await _buffered_output(proc, timeout)
        completed = not timed_out
        exit_code = proc.returncode if proc.returncode is not None else -1

        duration = round(time.time() - t0, 3)
        stdout, stdout_truncated = _decode_limited(stdout_bytes, decode_output_fn, max_output)
        stderr, stderr_truncated = _decode_limited(stderr_bytes, decode_output_fn, max_output)
        truncated = stdout_truncated or stderr_truncated
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
        # A timeout is not the only abnormal exit: bridge shutdown, client
        # disconnect, and task cancellation all unwind through here. Before
        # v4.169.44 those paths removed bookkeeping but left the OS process.
        await _terminate_if_running(proc)
        _release_job(proc, completed)
        ACTIVE_PROCESSES.pop(request_id, None)


async def _pump_stream_output(stream: asyncio.StreamReader, tag: str, queue: asyncio.Queue) -> None:
    try:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            await queue.put((tag, chunk))
    except asyncio.CancelledError:
        # Cleanup has stopped consuming the bounded queue. Waiting to
        # enqueue an EOF marker here can deadlock aclose() forever.
        raise
    except Exception:
        await queue.put((tag, None))
        raise
    await queue.put((tag, None))


async def run_shell_command_stream(
    *,
    request_id: str,
    cmd: str,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    max_output: int,
) -> AsyncGenerator[dict[str, Any], None]:
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
    completed = False
    budget = _StreamBudget(max_output)
    proc: asyncio.subprocess.Process | None = None
    stdout_task: asyncio.Task | None = None
    stderr_task: asyncio.Task | None = None
    try:
        proc = await _spawn_shell(cmd, cwd, env)
        ACTIVE_PROCESSES[request_id] = {"cmd": cmd, "pid": proc.pid, "start": time.time()}
        yield {"type": "start", "pid": proc.pid}

        # Two reader tasks push chunks onto a shared queue. A ``None`` sentinel
        # per stream signals EOF. This lets us interleave stdout+stderr in the
        # order the OS produced them without one blocking the other.
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        stdout_task = asyncio.create_task(_pump_stream_output(proc.stdout, "stdout", queue))  # type: ignore[arg-type]
        stderr_task = asyncio.create_task(_pump_stream_output(proc.stderr, "stderr", queue))  # type: ignore[arg-type]

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
            event = budget.consume(tag, chunk)
            if event is not None:
                yield event

        await _finish_stream_pumps(proc, [stdout_task, stderr_task], timed_out)
        exit_code = await _wait_for_exit(proc)
        completed = not timed_out

        duration = round(time.time() - t0, 3)
        yield {
            "type": "exit",
            "exit_code": exit_code,
            "duration_sec": duration,
            "stdout_bytes": budget.totals["stdout"],
            "stderr_bytes": budget.totals["stderr"],
            "truncated": budget.truncated,
            "timed_out": timed_out,
            "error": f"timeout after {timeout}s" if timed_out else None,
        }
    finally:
        await _terminate_if_running(proc)
        _release_job(proc, completed)
        await _stop_reading(proc, [stdout_task, stderr_task])
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
