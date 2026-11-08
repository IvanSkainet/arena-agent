"""Task queue runtime helpers.

These helpers own JSON task-file manipulation. They do not know about aiohttp or
bridge globals; callers pass queue directory paths explicitly.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# Narrow seam for deterministic concurrency and failure tests.
_link = os.link


def list_tasks(
    *,
    inbox: Path,
    running: Path,
    done: Path,
    failed: Path,
    status: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """List task JSON files across queue directories."""
    tasks: list[dict[str, Any]] = []
    dirs = {"inbox": inbox, "running": running, "done": done, "failed": failed}
    if status and status in dirs:
        scan_dirs = [(status, dirs[status])]
    else:
        scan_dirs = [("inbox", inbox), ("running", running), ("done", done), ("failed", failed)]

    for state_name, scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for path in sorted(scan_dir.glob("*.json"))[:limit]:
            try:
                task = json.loads(path.read_text(encoding="utf-8"))
                task["id"] = task.get("id", path.stem)
                task["state"] = state_name
                task["file"] = str(path)
                task.pop("stdout", None)
                task.pop("stderr", None)
                tasks.append(task)
            except Exception:
                tasks.append({"id": path.stem, "state": state_name, "file": str(path), "error": "unreadable"})
            if len(tasks) >= limit:
                break
    return {"ok": True, "count": len(tasks), "tasks": tasks}


def submit_task(
    data: dict[str, Any],
    *,
    inbox: Path,
    default_cwd: str,
    now_fn: Callable[[], str],
) -> dict[str, Any]:
    """Create a task JSON file in the inbox."""
    task_id = str(uuid.uuid4())[:8]
    cmd = data.get("cmd", "")
    title = data.get("title", "")
    if title and not cmd:
        cmd = f"# {title}"
    task = {
        "id": task_id,
        "cmd": cmd,
        "title": title or cmd,
        "description": data.get("description", ""),
        "priority": data.get("priority", "normal"),
        "cwd": data.get("cwd", default_cwd),
        "timeout": data.get("timeout", 3600),
        "env": data.get("env", {}),
        "state": "inbox",
        "created_at": now_fn(),
    }
    inbox.mkdir(parents=True, exist_ok=True)
    task_path = inbox / f"{task_id}.json"
    task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "task_id": task_id, "task": task}


def clean_tasks(*, done: Path, failed: Path, older_than_seconds: int = 86400) -> dict[str, Any]:
    """Remove completed/failed task files older than older_than_seconds."""
    removed = 0
    cutoff = time.time() - older_than_seconds
    for scan_dir in [done, failed]:
        if not scan_dir.exists():
            continue
        for path in scan_dir.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except Exception:
                pass
    return {"ok": True, "removed": removed}


def pid_is_alive(pid: int) -> bool:
    """Best-effort liveness check that never raises on an unusable pid.

    ``PermissionError`` means the process exists and belongs to someone else --
    alive for our purposes. Anything we cannot interpret is treated as alive,
    because the cost of a wrong "alive" is a stuck entry that the operator can
    see, while the cost of a wrong "dead" is killing a task that is still
    running under another bridge.
    """
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _windows_pid_is_alive(pid: int) -> bool:
    """Query a Windows process without signalling or terminating it.

    Access denied and unrecognised errors are treated as alive: reclaiming
    the record is unsafe unless the system positively reports a dead PID.
    """
    import ctypes
    from ctypes import wintypes

    try:
        kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return getattr(ctypes, "get_last_error")() != 87  # ERROR_INVALID_PARAMETER: no such PID
        try:
            exit_code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    except (AttributeError, OSError, ValueError, OverflowError):
        return True


def reclaim_interrupted_tasks(
    *,
    running: Path,
    failed: Path,
    now_fn: Callable[[], str],
    done: Path | None = None,
    alive: Callable[[int], bool] = pid_is_alive,
    grace_seconds: int = 60,
) -> dict[str, Any]:
    """Move tasks whose owner died out of ``running``, so they stop lying.

    A task file is written into ``running/`` when a bridge claims it and
    removed when the run finishes. If the bridge is killed in between, nothing
    ever removes it: `GET /v1/tasks` reports `running` for work that no process
    is doing, `/health` stays green, and `/v1/tasks/clean` only trims
    `done/`+`failed/`, so the record is immortal. Missions have
    `/v1/mission/recover`; tasks had nothing.

    Ownership is decided by the ``pid`` recorded when the task was claimed:

    * pid alive  -> leave it alone (a second bridge on the same home is the
      normal case, and killing its work would be worse than a stale entry);
    * pid dead   -> `failed` with ``reason: interrupted``;
    * no pid     -> a record from an older version; reclaim only once it is
      older than its own timeout plus ``grace_seconds``, so a slow task from a
      previous release is not stolen mid-run.

    Unreadable or malformed records, and records with unusable ownership or
    timing metadata, are left in place for inspection: they may be observed
    during a live claim or write and cannot safely be declared interrupted.
    """
    reclaimed: list[str] = []
    errors: list[str] = []
    done = done if done is not None else running.parent / "done"
    if not running.exists():
        return {"ok": True, "reclaimed": reclaimed}
    failed.mkdir(parents=True, exist_ok=True, mode=0o700)
    now_epoch = time.time()
    for path in sorted(running.glob("*.json")):
        task: dict[str, Any] = {}
        try:
            task = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            # A claimant may be writing this file right now. Never reclaim an
            # unreadable record without evidence that its owner is dead.
            continue
        if not isinstance(task, dict):
            continue
        pid = task.get("pid")
        if pid is None:
            if not _past_its_deadline(task, now_epoch, grace_seconds):
                continue
        elif isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            continue
        elif alive(pid):
            continue
        task["reason"] = "interrupted"
        task["state"] = "failed"
        if not isinstance(task.get("id"), str) or not task["id"]:
            task["id"] = path.stem
        task["finished_at"] = now_fn()
        target = failed / path.name
        try:
            # If a previous owner wrote its final result before crashing,
            # do not replace it with an "interrupted" outcome.
            if (done / path.name).exists():
                continue
            if not _publish_failed_task(target, task):
                continue  # an existing failed result or another sweeper won
            path.unlink()
        except OSError as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        reclaimed.append(task["id"])
    result: dict[str, Any] = {"ok": not errors, "reclaimed": reclaimed}
    if errors:
        result["errors"] = errors
    return result


def _publish_failed_task(target: Path, task: dict[str, Any]) -> bool:
    """Publish a complete private record atomically, without overwriting one."""
    fd, temp_name = tempfile.mkstemp(prefix=".reclaim-", dir=target.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(task, ensure_ascii=False, indent=2) + "\n")
        try:
            # A link into the same directory publishes only if the target does
            # not exist; a second sweeper cannot truncate the winner's result.
            _link(temporary, target)
        except FileExistsError:
            return False
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _past_its_deadline(task: dict[str, Any], now_epoch: float, grace_seconds: int) -> bool:
    """True when a pid-less record is old enough that nobody can be running it."""
    try:
        started = datetime.fromisoformat(str(task.get("started_at", ""))).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        # Missing metadata can be the window between claim and metadata write.
        return False
    try:
        timeout = int(task.get("timeout") or 3600)
    except (TypeError, ValueError, OverflowError):
        return False
    if timeout <= 0:
        return False
    return now_epoch - started > timeout + grace_seconds
