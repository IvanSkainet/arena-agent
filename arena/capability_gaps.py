"""Persistent capability gap tracker for the self-extending harness."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any


def _home() -> Path:
    return Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()


def _path() -> Path:
    p = _home() / "capability-gaps.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", str(text or "").strip()).strip("-").lower()[:64] or "gap"


def _load() -> list[dict[str, Any]]:
    p = _path()
    if not p.exists():
        return []
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return obj if isinstance(obj, list) else []
    except Exception:
        return []


def _save(items: list[dict[str, Any]]) -> None:
    _path().write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record(*, title: str, evidence: Any = None, suggested_tool: str = "", severity: str = "medium", scenario: str = "", status: str = "open", tags: Any = None) -> dict[str, Any]:
    if not title:
        return {"ok": False, "error": "title is required"}
    items = _load()
    gap_id = f"gap-{_slug(title)}-{uuid.uuid4().hex[:6]}"
    item = {
        "id": gap_id,
        "title": title,
        "evidence": evidence,
        "suggested_tool": suggested_tool,
        "severity": severity or "medium",
        "scenario": scenario,
        "status": status or "open",
        "tags": tags if isinstance(tags, list) else ([] if tags is None else [tags]),
        "created_at": _now(),
        "updated_at": _now(),
    }
    items.append(item)
    _save(items)
    return {"ok": True, "gap": item, "path": str(_path())}


def list_gaps(*, status: str = "", limit: int = 50) -> dict[str, Any]:
    items = _load()
    if status:
        items = [g for g in items if str(g.get("status")) == status]
    items = sorted(items, key=lambda g: str(g.get("updated_at", "")), reverse=True)[: max(1, int(limit or 50))]
    return {"ok": True, "count": len(items), "gaps": items, "path": str(_path())}


def resolve(*, gap_id: str, resolution: str = "", status: str = "resolved") -> dict[str, Any]:
    items = _load()
    for item in items:
        if item.get("id") == gap_id:
            item["status"] = status or "resolved"
            item["resolution"] = resolution
            item["updated_at"] = _now()
            _save(items)
            return {"ok": True, "gap": item, "path": str(_path())}
    return {"ok": False, "error": "gap_not_found", "gap_id": gap_id}


# ---------------------------------------------------------------------------
# v4.150.0: promote — convert a gap into an autopilot-ready task
# ---------------------------------------------------------------------------

def promote(*, gap_id: str, goal: str = "", steps: Any = None, run_now: bool = False, port: int = 8765, token: str = "") -> dict[str, Any]:
    """Promote a capability gap into an autopilot task.

    Marks the gap as ``promoted``, builds autopilot steps from the gap's
    metadata and optional user-provided goal/steps, and optionally launches
    an autopilot run immediately.
    """
    items = _load()
    target = None
    for item in items:
        if item.get("id") == gap_id:
            target = item
            break
    if target is None:
        return {"ok": False, "error": "gap_not_found", "gap_id": gap_id}
    if target.get("status") == "resolved":
        return {"ok": False, "error": "gap is already resolved", "gap_id": gap_id}

    # Mark as promoted
    target["status"] = "promoted"
    target["promoted_at"] = _now()
    target["updated_at"] = _now()
    _save(items)

    # Build goal from gap metadata
    effective_goal = goal or f"Resolve capability gap: {target.get('title', gap_id)}"

    result: dict[str, Any] = {
        "ok": True,
        "gap_id": gap_id,
        "goal": effective_goal,
        "status": "promoted",
    }

    if run_now:
        from arena import mission_autopilot as _ap
        ap_result = _ap.from_goal(
            goal=effective_goal,
            constraints=[f"gap:{gap_id}", f"severity:{target.get('severity', 'medium')}"],
            max_steps=12,
            timeout_per_step=60,
            create_record=True,
            scenario_name=f"gap-{_slug(gap_id)}",
            port=port,
            token=token,
        )
        result["autopilot"] = ap_result
        # Link the run back to the gap
        target["autopilot_run_id"] = ap_result.get("run_id")
        target["updated_at"] = _now()
        _save(items)

    result["gap"] = target
    result["path"] = str(_path())
    return result


def gap_report(*, limit: int = 50) -> dict[str, Any]:
    """Generate a structured report of all gaps grouped by status and severity."""
    items = _load()
    items = sorted(items, key=lambda g: str(g.get("updated_at", "")), reverse=True)[:max(1, int(limit or 50))]

    by_status: dict[str, list[dict[str, Any]]] = {}
    by_severity: dict[str, int] = {}
    for g in items:
        st = g.get("status", "unknown")
        sev = g.get("severity", "unknown")
        by_status.setdefault(st, []).append(g)
        by_severity[sev] = by_severity.get(sev, 0) + 1

    return {
        "ok": True,
        "total": len(items),
        "by_status": {k: len(v) for k, v in by_status.items()},
        "by_severity": by_severity,
        "gaps": items,
        "path": str(_path()),
    }


__all__ = ["gap_report", "list_gaps", "promote", "record", "resolve"]
