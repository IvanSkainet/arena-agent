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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from arena.private_state import write_private_json
from arena.tasks.ownership import _past_its_deadline, _windows_pid_is_alive

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
    task_path = inbox / f"{task_id}.json"
    write_private_json(task_path, task, replace=False)
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
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return True
    return True


@dataclass(frozen=True)
class RecoveryContext:
    failed: Path
    done: Path
    now_fn: Callable[[], str]
    alive: Callable[[int], bool]
    now_epoch: float
    grace_seconds: int


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
    failed.chmod(0o700)
    recovery = RecoveryContext(failed, done, now_fn, alive, time.time(), grace_seconds)
    for path in sorted(running.glob("*.json")):
        try:
            task_id = _reclaim_one(path, recovery)
        except OSError as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        if task_id is not None:
            reclaimed.append(task_id)
    result: dict[str, Any] = {"ok": not errors, "reclaimed": reclaimed}
    if errors:
        result["errors"] = errors
    return result


def _load_reclaim_candidate(path: Path, recovery: RecoveryContext) -> dict[str, Any] | None:
    try:
        task = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A claimant may still be writing; ambiguous records stay in place.
        return None
    if not isinstance(task, dict):
        return None
    pid = task.get("pid")
    if pid is None:
        return task if _past_its_deadline(task, recovery.now_epoch, recovery.grace_seconds) else None
    if type(pid) is not int:
        return None
    if pid <= 0:
        return None
    return None if recovery.alive(pid) else task


def _reclaim_one(path: Path, recovery: RecoveryContext) -> str | None:
    task = _load_reclaim_candidate(path, recovery)
    if task is None:
        return None
    if (recovery.done / path.name).exists() or (recovery.failed / path.name).exists():
        path.unlink(missing_ok=True)
        return None
    task["reason"] = "interrupted"
    task["state"] = "failed"
    if not isinstance(task.get("id"), str) or not task["id"]:
        task["id"] = path.stem
    task["finished_at"] = recovery.now_fn()
    if not _publish_failed_task(recovery.failed / path.name, task):
        return None  # an existing failed result or another sweeper won
    path.unlink()
    return task["id"]


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
