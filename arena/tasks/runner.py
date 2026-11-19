"""Background JSON-file task runner runtime."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from arena.private_state import private_directory, write_private_json
from arena.tasks.queue import reclaim_interrupted_tasks


@dataclass(frozen=True)
class TaskRunnerContext:
    inbox: Path
    running: Path
    done: Path
    failed: Path
    blocked_reason: Callable[[str], str | None]
    cleanup_mcp_sessions: Callable[[], int]
    utc_now: Callable[[], str]
    log_info: Callable[..., None]
    log_error: Callable[..., None]


@dataclass(frozen=True)
class TaskRunnerRuntime:
    move_atomic: Callable[[Path, Path], None]
    ensure_dirs: Callable[[], None]
    run_one: Callable[[Path], Any]
    runner_loop: Callable[[web.Application], Any]


def move_atomic(src: Path, dst: Path) -> None:
    """Atomically move a file, replacing destination if it exists."""
    try:
        dst.unlink(missing_ok=True)
        src.rename(dst)
    except OSError:
        shutil.copy2(str(src), str(dst))
        try:
            src.unlink()
        except OSError:
            pass




def kill_worker_tree(pid: int) -> None:
    """Last-resort cleanup for a worker that did not honor its lease EOF."""
    import psutil

    try:
        worker = psutil.Process(pid)
        descendants = worker.children(recursive=True)
    except psutil.NoSuchProcess:
        return
    for process in reversed(descendants):
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    try:
        worker.kill()
    except psutil.NoSuchProcess:
        pass
    psutil.wait_procs(descendants, timeout=5)


async def _task_process_output(process, timeout: int) -> tuple[bytes, bytes]:
    """Read output without communicate(), which would close the owner lease."""
    readers = asyncio.gather(process.stdout.read(), process.stderr.read(), process.wait())
    try:
        stdout, stderr, _ = await asyncio.wait_for(readers, timeout=timeout + 5)
        return stdout, stderr
    except (asyncio.TimeoutError, asyncio.CancelledError):
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=12)
        except asyncio.TimeoutError:
            kill_worker_tree(process.pid)
            await process.wait()
        raise
    finally:
        process.stdin.close()


def _owner_creation_time() -> float | None:
    try:
        import psutil
    except ModuleNotFoundError as exc:
        if exc.name != "psutil":
            raise
        return None  # The supported Termux bootstrap installs psutil optionally.
    return psutil.Process().create_time()


def _reclaim_quietly(ctx_: TaskRunnerContext, when: str) -> None:
    """Never let recovery of old records stop new work from running."""
    try:
        result = reclaim_interrupted_tasks(
            running=ctx_.running, failed=ctx_.failed, done=ctx_.done, now_fn=ctx_.utc_now
        )
    except Exception as e:  # pragma: no cover - defensive, would hide new work
        ctx_.log_error("[TaskRunner] Reclaim (%s) failed: %s", when, e)
        return
    for error in result.get("errors", []):
        ctx_.log_error("[TaskRunner] Reclaim (%s): %s", when, error)
    if result.get("reclaimed"):
        ctx_.log_info(
            "[TaskRunner] Reclaimed %d interrupted task(s) %s: %s",
            len(result["reclaimed"]), when, ", ".join(result["reclaimed"][:5]),
        )



def _truncate_output(stdout: str, stderr: str, limit: int) -> tuple[str, str, bool]:
    """Apply the same output budget to both streams and report truncation."""
    truncated = False
    if len(stdout.encode("utf-8", "replace")) > limit:
        stdout = stdout[:limit]
        truncated = True
    if len(stderr.encode("utf-8", "replace")) > limit:
        stderr = stderr[:limit]
        truncated = True
    return stdout, stderr, truncated


def _read_submission(path: Path, ctx: TaskRunnerContext) -> dict | None:
    try:
        task = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        ctx.log_error("[TaskRunner] Failed to read %s: %s", path, exc)
        return None
    return task if isinstance(task, dict) else {"invalid_submission": task}


def _prepare_task(task: dict, running_path: Path) -> tuple[Path, int, int]:
    task["owner_created_at"] = _owner_creation_time()
    cwd = Path(task.get("cwd") or str(Path.home())).expanduser().resolve()
    task["cwd"] = str(cwd)
    write_private_json(running_path, task)
    timeout = int(task.get("timeout") or 3600)
    limit = int(task.get("max_output") or 2_000_000)
    if min(timeout, limit) <= 0:
        raise ValueError("timeout and max_output must be positive")
    command = task.get("cmd")
    if not isinstance(command, str):
        raise ValueError("cmd must be a nonempty string")
    if not command.strip():
        raise ValueError("cmd must be a nonempty string")
    return cwd, timeout, limit


def _task_environment(task: dict) -> dict[str, str]:
    env = os.environ.copy()
    if isinstance(task.get("env"), dict):
        env.update({str(k): str(v) for k, v in task["env"].items()})
    return env


async def _execute_worker(task: dict, running_path: Path, cwd: Path, timeout: int):
    worker = Path(__file__).with_name("process_worker.py")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-I", str(worker), str(running_path.resolve()),
        cwd=str(cwd), env=_task_environment(task),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await _task_process_output(proc, timeout)
        return stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace"), proc.returncode
    except asyncio.TimeoutError:
        return "", "timeout", 124


@dataclass(frozen=True)
class _TaskOutcome:
    stdout: str
    stderr: str
    exit_code: int | None
    duration: float
    limit: int


def _finish_task(ctx: TaskRunnerContext, task: dict, running_path: Path,
                    outcome: _TaskOutcome) -> None:
    stdout, stderr, truncated = _truncate_output(outcome.stdout, outcome.stderr, outcome.limit)
    exit_code, duration = outcome.exit_code, outcome.duration
    state = "done" if exit_code == 0 else "failed"
    task.update({
        "finished_at": ctx.utc_now(), "duration_sec": duration,
        "exit_code": exit_code, "stdout": stdout, "stderr": stderr,
        "truncated": truncated, "state": state})
    dest = (ctx.done if exit_code == 0 else ctx.failed) / running_path.name
    write_private_json(dest, task)
    try:
        running_path.unlink()
    except FileNotFoundError:
        pass
    ctx.log_info("[TaskRunner] %s: %s exit=%s dur=%ss", task.get("id") or running_path.stem,
                    state, exit_code, duration)


def _record_blocked_task(ctx: TaskRunnerContext, task: dict, running_path: Path, reason: str) -> None:
    task.update(state="failed", exit_code=-1, stderr=f"blocked: {reason}")
    write_private_json(running_path, task)
    move_atomic(running_path, ctx.failed / running_path.name)


def _cleanup_sessions(ctx: TaskRunnerContext) -> None:
    try:
        removed = ctx.cleanup_mcp_sessions()
        if removed:
            ctx.log_info("[TaskRunner] Cleaned %d stale MCP sessions", removed)
    except Exception:
        pass


def make_task_runner_runtime(ctx: TaskRunnerContext) -> TaskRunnerRuntime:
    def task_ensure_dirs() -> None:
        for p in [ctx.inbox, ctx.running, ctx.done, ctx.failed]:
            private_directory(p)

    async def task_run_one(task_path: Path) -> bool:
        """Process a single task JSON file asynchronously."""
        task = _read_submission(task_path, ctx)
        if task is None:
            return False
        rp = ctx.running / task_path.name
        try:
            task_path.rename(rp)
        except FileNotFoundError:
            return False

        task["started_at"] = ctx.utc_now()
        task["state"] = "running"
        # Who claimed it, so a later start can tell "still running elsewhere"
        # from "left behind by a process that no longer exists" (#B-032).
        task["pid"] = os.getpid()
        t0 = time.time()
        max_output = 2_000_000
        try:
            cwd, timeout, max_output = _prepare_task(task, rp)
            blk = ctx.blocked_reason(task["cmd"])
            if blk:
                _record_blocked_task(ctx, task, rp, blk)
                return True

            stdout, stderr, exit_code = await _execute_worker(task, rp, cwd, timeout)
        except Exception as e:
            stdout, stderr = "", repr(e)
            exit_code = 125

        outcome = _TaskOutcome(stdout, stderr, exit_code, round(time.time() - t0, 3), max_output)
        _finish_task(ctx, task, rp, outcome)
        return True

    async def task_runner_loop(app: web.Application):
        """Background task: watches INBOX for new tasks every 5 seconds."""
        task_ensure_dirs()
        ctx.log_info("[TaskRunner] Watching %s", ctx.inbox)
        _reclaim_quietly(ctx, "at startup")
        while True:
            try:
                task_ensure_dirs()
                _reclaim_quietly(ctx, "on tick")
                for p in sorted(ctx.inbox.glob("*.json"))[:3]:
                    await task_run_one(p)
            except Exception as e:
                ctx.log_error("[TaskRunner] Loop error: %s", e)
            _cleanup_sessions(ctx)
            await asyncio.sleep(5)

    return TaskRunnerRuntime(
        move_atomic=move_atomic,
        ensure_dirs=task_ensure_dirs,
        run_one=task_run_one,
        runner_loop=task_runner_loop,
    )
