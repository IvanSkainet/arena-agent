"""Mission lineage helpers for parent/child iteration chains."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from arena.resources.mission_catalog import mission_dir, summarize_mission_dir



def _summaries(missions_dir: Path) -> list[dict[str, Any]]:
    if not missions_dir.exists():
        return []
    return [
        summarize_mission_dir(path)
        for path in sorted(missions_dir.iterdir())
        if path.is_dir() and (path / "mission.json").exists()
    ]



def build_followup_lineage(
    mission: dict[str, Any],
    *,
    origin: str = "followup",
    recovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = dict(mission.get("lineage") or {})
    parent_id = str(mission.get("id") or mission.get("name") or "").strip()
    root_id = str(current.get("root_mission_id") or parent_id or "").strip()
    inherited = [str(item).strip() for item in list(current.get("ancestor_ids") or []) if str(item).strip()]
    ancestor_ids = list(dict.fromkeys([*inherited, parent_id] if parent_id else inherited))
    lineage = {
        "origin": origin,
        "parent_mission_id": parent_id or None,
        "root_mission_id": root_id or None,
        "ancestor_ids": ancestor_ids,
        "depth": len(ancestor_ids),
        "source_mission_id": parent_id or None,
        "source_state": mission.get("state", ""),
        "source_template": mission.get("template", ""),
    }
    if recovery:
        lineage["recovery_suggested_action"] = recovery.get("suggested_action")
        suggested = dict(recovery.get("suggested_rerun") or {})
        if suggested.get("step") is not None:
            lineage["recovery_step"] = suggested.get("step")
    return lineage



def get_mission_lineage(missions_dir: Path, name: str) -> dict[str, Any]:
    try:
        path = mission_dir(missions_dir, name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "status": 400}
    if not path.exists() or not path.is_dir():
        return {"ok": False, "error": f"mission '{name}' not found", "status": 404}
    items = _summaries(missions_dir)
    index = {str(item.get("id") or item.get("name")): item for item in items}
    current = index.get(path.name) or summarize_mission_dir(path)
    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        parent_id = str(item.get("parent_mission_id") or "").strip()
        if parent_id:
            children_by_parent.setdefault(parent_id, []).append(item)
    ancestors: list[dict[str, Any]] = []
    seen: set[str] = set()
    parent_id = str(current.get("parent_mission_id") or "").strip()
    while parent_id and parent_id not in seen and parent_id in index:
        seen.add(parent_id)
        parent = index[parent_id]
        ancestors.append(parent)
        parent_id = str(parent.get("parent_mission_id") or "").strip()
    ancestors.reverse()
    children = sorted(children_by_parent.get(str(current.get("id") or current.get("name") or ""), []), key=lambda item: str(item.get("created_at", "") or item.get("last_activity_at", "")))
    descendants: list[dict[str, Any]] = []
    stack = list(children)
    while stack:
        item = stack.pop(0)
        descendants.append(item)
        stack.extend(children_by_parent.get(str(item.get("id") or item.get("name") or ""), []))
    siblings = []
    if current.get("parent_mission_id"):
        siblings = [item for item in children_by_parent.get(str(current.get("parent_mission_id")), []) if str(item.get("id") or item.get("name")) != str(current.get("id") or current.get("name"))]
    root = index.get(str(current.get("root_mission_id") or "")) or (ancestors[0] if ancestors else current)
    return {
        "ok": True,
        "mission": current,
        "root": root,
        "parent": ancestors[-1] if ancestors else None,
        "ancestors": ancestors,
        "children": children,
        "descendants": descendants,
        "siblings": siblings,
        "stats": {
            "depth": int(current.get("lineage_depth", 0) or 0),
            "ancestor_count": len(ancestors),
            "child_count": len(children),
            "descendant_count": len(descendants),
            "sibling_count": len(siblings),
            "family_size": 1 + len(ancestors) + len(descendants),
        },
    }


__all__ = ["build_followup_lineage", "get_mission_lineage"]
