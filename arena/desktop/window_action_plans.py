"""Geometry planning helpers for higher-level desktop window actions."""
from __future__ import annotations

from typing import Any

from arena.desktop.displays import match_display
from arena.desktop.text_matching import coerce_geometry, point_in_geometry


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))



def _display_for_window(before: dict[str, Any] | None, displays: list[dict[str, Any]]) -> dict[str, Any] | None:
    named = match_display(displays, ((before or {}).get("display") or {}).get("name"))
    if named:
        return named
    geometry = coerce_geometry((before or {}).get("geometry"))
    if not geometry:
        return None
    center = {"x": geometry["x"] + geometry["width"] // 2, "y": geometry["y"] + geometry["height"] // 2}
    for display in displays:
        if point_in_geometry(center, display.get("geometry")):
            return display
    return None



def plan_window_action_geometry(action: str, *, before: dict[str, Any] | None, displays: list[dict[str, Any]], target_display: str = "") -> dict[str, Any]:
    action = str(action or "").strip().lower()
    geometry = coerce_geometry((before or {}).get("geometry"))
    if not geometry:
        return {"ok": False, "error": "missing_window_geometry", "status": 400}
    if not displays:
        return {"ok": False, "error": "missing_displays", "status": 500}
    source = _display_for_window(before, displays)
    destination = match_display(displays, target_display) if target_display else (source or next((d for d in displays if d.get("active")), displays[0]))
    if action == "move_to_display" and not target_display:
        return {"ok": False, "error": "missing_target_display", "status": 400}
    if not destination:
        return {"ok": False, "error": "target_display_not_found", "status": 404, "available_displays": displays}
    dest_geom = coerce_geometry(destination.get("geometry"))
    if not dest_geom:
        return {"ok": False, "error": "target_display_missing_geometry", "status": 500}
    width = min(geometry["width"], dest_geom["width"])
    height = min(geometry["height"], dest_geom["height"])
    if action == "center":
        x = dest_geom["x"] + max(0, (dest_geom["width"] - width) // 2)
        y = dest_geom["y"] + max(0, (dest_geom["height"] - height) // 2)
    elif action == "move_to_display":
        source_geom = coerce_geometry((source or {}).get("geometry"))
        rel_x = geometry["x"] - (source_geom["x"] if source_geom else 0)
        rel_y = geometry["y"] - (source_geom["y"] if source_geom else 0)
        max_x = dest_geom["x"] + max(0, dest_geom["width"] - width)
        max_y = dest_geom["y"] + max(0, dest_geom["height"] - height)
        x = _clamp(dest_geom["x"] + rel_x, dest_geom["x"], max_x)
        y = _clamp(dest_geom["y"] + rel_y, dest_geom["y"], max_y)
    else:
        return {"ok": False, "error": "unsupported_planned_action", "status": 400}
    return {
        "ok": True,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "source_display": None if not source else {"name": source.get("name"), "id": source.get("id")},
        "target_display": {"name": destination.get("name"), "id": destination.get("id")},
    }


__all__ = ["plan_window_action_geometry"]
