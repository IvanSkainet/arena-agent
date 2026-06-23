"""Mission schedule listing and manual tick execution."""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arena.resources.mission_schedule_store import delete_schedule_def, list_schedule_defs, save_schedule_def, write_schedule_result



def _parse_dt(value: str) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except Exception:
        return None



def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds")



def _view(schedule: dict[str, Any], *, now: dt.datetime) -> dict[str, Any]:
    entry = dict(schedule)
    next_run = _parse_dt(entry.get("next_run_at", ""))
    entry["due"] = bool(entry.get("enabled", True)) and next_run is not None and next_run <= now
    return entry



def list_mission_schedules_runtime(schedules_dir: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    now = dt.datetime.now(dt.timezone.utc)
    action = str(payload.get("action", "") or "").strip().lower()
    enabled = payload.get("enabled")
    due_only = bool(payload.get("due_only", False))
    limit = max(1, min(200, int(payload.get("limit", 100) or 100)))
    items = []
    for schedule in list_schedule_defs(schedules_dir):
        entry = _view(schedule, now=now)
        if action and entry.get("action") != action:
            continue
        if enabled is not None and bool(entry.get("enabled", True)) is not bool(enabled):
            continue
        if due_only and not entry.get("due"):
            continue
        items.append(entry)
    items.sort(key=lambda item: (str(item.get("next_run_at", "") or ""), str(item.get("id", "") or "")))
    return {"ok": True, "count": len(items[:limit]), "total": len(items), "schedules": items[:limit]}



def save_mission_schedule_runtime(schedules_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return save_schedule_def(schedules_dir, payload)



def delete_mission_schedule_runtime(schedules_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return delete_schedule_def(schedules_dir, str(payload.get("schedule_id", "") or payload.get("id", "") or ""))



def tick_mission_schedules_runtime(
    schedules_dir: Path,
    payload: dict[str, Any],
    *,
    run_sync: Callable[[dict[str, Any]], dict[str, Any]],
    rerun_sync: Callable[[dict[str, Any]], dict[str, Any]],
    iterate_sync: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    schedule_id = str(payload.get("schedule_id", "") or payload.get("id", "") or "").strip()
    force = bool(payload.get("force", False))
    limit = max(1, min(50, int(payload.get("limit", 10) or 10)))
    schedules = list_schedule_defs(schedules_dir)
    if schedule_id:
        schedules = [item for item in schedules if str(item.get("id", "")) == schedule_id]
        if not schedules:
            return {"ok": False, "error": f"schedule '{schedule_id}' not found", "status": 404}
    executed = []
    checked = 0
    for schedule in schedules:
        checked += 1
        entry = _view(schedule, now=now)
        if not force and (not entry.get("enabled", True) or not entry.get("due")):
            continue
        action = str(entry.get("action", "iterate") or "iterate")
        if action == "run":
            result = run_sync({"mission_id": entry.get("mission_id"), "timeout": payload.get("timeout", 180)})
        elif action == "rerun_failed":
            result = rerun_sync({"mission_id": entry.get("mission_id"), "failed_only": True, "timeout": payload.get("timeout", 180)})
        else:
            result = iterate_sync({
                "mission_id": entry.get("mission_id"),
                "notes": entry.get("notes", ""),
                "followup_goal": entry.get("followup_goal", ""),
                "followup_title": entry.get("followup_title", ""),
                "constraints": entry.get("constraints") or [],
                "memory_profile": entry.get("memory_profile"),
                "template": entry.get("template", ""),
                "max_steps": entry.get("max_steps", 8),
                "max_iterations": entry.get("max_iterations", 4),
                "compose_followup": True,
                "create_followup": True,
                "run_followup": False,
                "timeout": payload.get("timeout", 180),
            })
        next_run = now + dt.timedelta(minutes=int(entry.get("every_minutes", 60) or 60))
        updated = write_schedule_result(schedules_dir, entry, last_run_at=_iso(now), next_run_at=_iso(next_run), last_result={"ok": result.get("ok", False), "summary": {k: result.get(k) for k in ("mission_id", "step", "status", "mode") if k in result}})
        executed.append({"schedule": updated, "result": result})
        if len(executed) >= limit:
            break
    return {"ok": True, "checked": checked, "executed": len(executed), "results": executed}


__all__ = [
    "delete_mission_schedule_runtime",
    "list_mission_schedules_runtime",
    "save_mission_schedule_runtime",
    "tick_mission_schedules_runtime",
]
