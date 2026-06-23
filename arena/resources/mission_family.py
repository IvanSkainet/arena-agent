"""Mission family summaries built on persisted lineage metadata."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from arena.resources.mission_catalog import summarize_mission_dir
from arena.resources.mission_lineage import get_mission_lineage



def get_mission_family(missions_dir: Path, name: str) -> dict[str, Any]:
    lineage = get_mission_lineage(missions_dir, name)
    if not lineage.get("ok"):
        return lineage
    root = lineage.get("root") or lineage.get("mission") or {}
    root_id = str(root.get("id") or root.get("name") or "").strip()
    if not root_id:
        return {"ok": False, "error": "family root unavailable", "status": 500}
    members = []
    if missions_dir.exists():
        for path in sorted(missions_dir.iterdir()):
            if not path.is_dir() or not (path / "mission.json").exists():
                continue
            item = summarize_mission_dir(path)
            if str(item.get("root_mission_id") or item.get("id") or item.get("name") or "") == root_id:
                members.append(item)
    members.sort(key=lambda item: (int(item.get("lineage_depth", 0) or 0), str(item.get("created_at", "") or ""), str(item.get("name", "") or "")))
    index = {str(item.get("id") or item.get("name") or ""): item for item in members}
    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    for item in members:
        parent = str(item.get("parent_mission_id") or "").strip()
        if parent:
            children_by_parent.setdefault(parent, []).append(item)
    leaves = [item for item in members if not children_by_parent.get(str(item.get("id") or item.get("name") or ""))]
    states: dict[str, int] = {}
    templates: dict[str, int] = {}
    origins: dict[str, int] = {}
    branches = []
    for item in members:
        states[item.get("state", "unknown")] = states.get(item.get("state", "unknown"), 0) + 1
        templates[item.get("template", "") or "unknown"] = templates.get(item.get("template", "") or "unknown", 0) + 1
        origins[item.get("origin", "manual") or "manual"] = origins.get(item.get("origin", "manual") or "manual", 0) + 1
    for leaf in leaves:
        path_ids = []
        current = leaf
        seen: set[str] = set()
        while current:
            cid = str(current.get("id") or current.get("name") or "")
            if not cid or cid in seen:
                break
            seen.add(cid)
            path_ids.append(cid)
            parent_id = str(current.get("parent_mission_id") or "").strip()
            current = index.get(parent_id)
        branches.append({
            "leaf_id": str(leaf.get("id") or leaf.get("name") or ""),
            "depth": int(leaf.get("lineage_depth", 0) or 0),
            "state": leaf.get("state", "unknown"),
            "path": list(reversed(path_ids)),
        })
    branches.sort(key=lambda item: (int(item.get("depth", 0) or 0), item.get("leaf_id", "")))
    return {
        "ok": True,
        "mission": lineage.get("mission"),
        "root": root,
        "members": members,
        "leaves": leaves,
        "branches": branches,
        "stats": {
            "total": len(members),
            "leaf_count": len(leaves),
            "branch_count": len(branches),
            "max_depth": max((int(item.get("lineage_depth", 0) or 0) for item in members), default=0),
            "states": states,
            "templates": templates,
            "origins": origins,
        },
    }


__all__ = ["get_mission_family"]
