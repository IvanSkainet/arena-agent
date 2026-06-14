"""Background JSON-file task runner runtime."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web


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
        if dst.exists():
            dst.unlink()
        src.rename(dst)
    except OSError:
        shutil.copy2(str(src), str(dst))
        try:
            src.unlink()
        except OSError:
            pass


def make_task_runner_runtime(ctx: TaskRunnerContext) -> TaskRunnerRuntime:
    def task_ensure_dirs() -> None:
        for p in [ctx.inbox, ctx.running, ctx.done, ctx.failed]:
            p.mkdir(parents=True, exist_ok=True)

    async def task_run_one(task_path: Path) -> bool:
        """Process a single task JSON file asynchronously."""
        try:
            task = json.loads(task_path.read_text(encoding="utf-8"))
        except Exception as e:
            ctx.log_error("[TaskRunner] Failed to read %s: %s", task_path, e)
            return False

        tid = task.get("id") or task_path.stem
        rp = ctx.running / task_path.name
        try:
            task_path.rename(rp)
        except FileNotFoundError:
            return False

        task["started_at"] = ctx.utc_now()
        task["state"] = "running"
        rp.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        cwd = Path(task.get("cwd") or str(Path.home())).expanduser()
        timeout = int(task.get("timeout") or 3600)
        blk = ctx.blocked_reason(task["cmd"])
        if blk:
            task["state"] = "failed"
            task["exit_code"] = -1
            task["stderr"] = f"blocked: {blk}"
            rp.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            move_atomic(rp, ctx.failed / rp.name)
            return True

        env = os.environ.copy()
        if isinstance(task.get("env"), dict):
            env.update({str(k): str(v) for k, v in task["env"].items()})

        t0 = time.time()
        try:
            proc = await asyncio.create_subprocess_shell(
                task["cmd"], cwd=str(cwd), env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                stdout = stdout.decode("utf-8", "replace")
                stderr = stderr.decode("utf-8", "replace")
                exit_code = proc.returncode
            except asyncio.TimeoutError:
                proc.kill()
                stdout, stderr = "", "timeout"
                exit_code = 124
        except Exception as e:
            stdout, stderr = "", repr(e)
            exit_code = 125

        duration = round(time.time() - t0, 3)
        max_output = int(task.get("max_output") or 2_000_000)
        truncated = False
        if len(stdout.encode("utf-8", "replace")) > max_output:
            stdout = stdout[:max_output]
            truncated = True
        if len(stderr.encode("utf-8", "replace")) > max_output:
            stderr = stderr[:max_output]
            truncated = True

        state = "done" if exit_code == 0 else "failed"
        task.update({
            "finished_at": ctx.utc_now(), "duration_sec": duration,
            "exit_code": exit_code, "stdout": stdout, "stderr": stderr,
            "truncated": truncated, "state": state,
        })
        dest = (ctx.done if exit_code == 0 else ctx.failed) / task_path.name
        dest.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            rp.unlink()
        except FileNotFoundError:
            pass

        ctx.log_info("[TaskRunner] %s: %s exit=%s dur=%ss", tid, state, exit_code, duration)
        return True

    async def task_runner_loop(app: web.Application):
        """Background task: watches INBOX for new tasks every 5 seconds."""
        task_ensure_dirs()
        ctx.log_info("[TaskRunner] Watching %s", ctx.inbox)
        while True:
            try:
                task_ensure_dirs()
                for p in sorted(ctx.inbox.glob("*.json"))[:3]:
                    await task_run_one(p)
            except Exception as e:
                ctx.log_error("[TaskRunner] Loop error: %s", e)
            try:
                removed = ctx.cleanup_mcp_sessions()
                if removed:
                    ctx.log_info("[TaskRunner] Cleaned %d stale MCP sessions", removed)
            except Exception:
                pass
            await asyncio.sleep(5)

    return TaskRunnerRuntime(
        move_atomic=move_atomic,
        ensure_dirs=task_ensure_dirs,
        run_one=task_run_one,
        runner_loop=task_runner_loop,
    )
