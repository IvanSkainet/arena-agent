"""Task queue runtime helpers.

These helpers own JSON task-file manipulation. They do not know about aiohttp or
bridge globals; callers pass queue directory paths explicitly.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable


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
