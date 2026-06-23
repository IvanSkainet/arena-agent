"""Persisted mission schedule definitions."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any


_ACTIONS = {"run", "rerun_failed", "iterate"}



def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)



def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds")



def _schedule_path(schedules_dir: Path, schedule_id: str) -> Path:
    if ".." in schedule_id or "/" in schedule_id or "\\" in schedule_id or schedule_id.startswith("."):
        raise ValueError("invalid schedule id")
    return schedules_dir / f"{schedule_id}.json"



def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", str(text or "").strip()).strip("-").lower() or "schedule"



def _load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None



def list_schedule_defs(schedules_dir: Path) -> list[dict[str, Any]]:
    if not schedules_dir.exists():
        return []
    items = []
    for path in sorted(schedules_dir.glob("*.json")):
        data = _load(path)
        if isinstance(data, dict):
            items.append(data)
    return items



def save_schedule_def(schedules_dir: Path, data: dict[str, Any]) -> dict[str, Any]:
    mission_id = str(data.get("mission_id", "") or data.get("id", "") or "").strip()
    if not mission_id:
        return {"ok": False, "error": "missing mission_id", "status": 400}
    action = str(data.get("action", "iterate") or "iterate").strip().lower()
    if action not in _ACTIONS:
        return {"ok": False, "error": f"invalid action: {action}", "status": 400}
    every_minutes = max(1, int(data.get("every_minutes", 60) or 60))
    now = _now()
    schedule_id = str(data.get("schedule_id", "") or data.get("id", "") or "").strip() or _slug(f"{mission_id}-{action}")
    try:
        path = _schedule_path(schedules_dir, schedule_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "status": 400}
    current = _load(path) if path.exists() else {}
    if current and not isinstance(current, dict):
        current = {}
    next_run_at = str(data.get("next_run_at", "") or current.get("next_run_at", "") or _iso(now + dt.timedelta(minutes=every_minutes)))
    schedule = {
        "id": schedule_id,
        "title": str(data.get("title", "") or current.get("title", "") or f"{action}:{mission_id}"),
        "mission_id": mission_id,
        "action": action,
        "every_minutes": every_minutes,
        "enabled": bool(data.get("enabled", current.get("enabled", True))),
        "notes": str(data.get("notes", "") or current.get("notes", "") or ""),
        "followup_goal": str(data.get("followup_goal", "") or current.get("followup_goal", "") or ""),
        "followup_title": str(data.get("followup_title", "") or current.get("followup_title", "") or ""),
        "constraints": list(data.get("constraints") if data.get("constraints") is not None else current.get("constraints") or []),
        "memory_profile": str(data.get("memory_profile", "") or current.get("memory_profile", "") or ""),
        "template": str(data.get("template", "") or current.get("template", "") or ""),
        "max_steps": int(data.get("max_steps", current.get("max_steps", 8)) or 8),
        "max_iterations": int(data.get("max_iterations", current.get("max_iterations", 4)) or 4),
        "created_at": str(current.get("created_at", "") or _iso(now)),
        "updated_at": _iso(now),
        "next_run_at": next_run_at,
        "last_run_at": str(current.get("last_run_at", "") or ""),
        "last_result": current.get("last_result"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schedule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "schedule": schedule, "path": str(path)}



def delete_schedule_def(schedules_dir: Path, schedule_id: str) -> dict[str, Any]:
    schedule_id = str(schedule_id or "").strip()
    if not schedule_id:
        return {"ok": False, "error": "missing schedule_id", "status": 400}
    try:
        path = _schedule_path(schedules_dir, schedule_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "status": 400}
    if not path.exists():
        return {"ok": False, "error": f"schedule '{schedule_id}' not found", "status": 404}
    path.unlink()
    return {"ok": True, "schedule_id": schedule_id}



def write_schedule_result(schedules_dir: Path, schedule: dict[str, Any], *, last_run_at: str, next_run_at: str, last_result: dict[str, Any]) -> dict[str, Any]:
    updated = dict(schedule)
    updated["updated_at"] = last_run_at
    updated["last_run_at"] = last_run_at
    updated["next_run_at"] = next_run_at
    updated["last_result"] = last_result
    path = _schedule_path(schedules_dir, str(updated.get("id", "") or ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return updated


__all__ = ["delete_schedule_def", "list_schedule_defs", "save_schedule_def", "write_schedule_result"]
