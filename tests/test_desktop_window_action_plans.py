"""Higher-level desktop window action planning regressions."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.desktop.window_action_plans import plan_window_action_geometry  # noqa: E402


WINDOW = {
    "geometry": {"x": 100, "y": 120, "width": 800, "height": 600},
    "display": {"name": "DP-1", "id": "DP-1"},
}
DISPLAYS = [
    {"name": "DP-1", "id": "DP-1", "geometry": {"x": 0, "y": 0, "width": 2560, "height": 1440}, "active": True},
    {"name": "HDMI-A-1", "id": "HDMI-A-1", "geometry": {"x": 2560, "y": 0, "width": 1920, "height": 1080}, "active": False},
]



def test_plan_center_uses_current_display_when_target_missing():
    result = plan_window_action_geometry("center", before=WINDOW, displays=DISPLAYS)
    assert result["ok"] is True
    assert result["target_display"]["name"] == "DP-1"
    assert result["x"] == (2560 - 800) // 2
    assert result["y"] == (1440 - 600) // 2



def test_plan_move_to_display_preserves_relative_offset_and_clamps():
    result = plan_window_action_geometry("move_to_display", before=WINDOW, displays=DISPLAYS, target_display="HDMI-A-1")
    assert result["ok"] is True
    assert result["source_display"]["name"] == "DP-1"
    assert result["target_display"]["name"] == "HDMI-A-1"
    assert result["x"] == 2560 + 100
    assert result["y"] == 120

    oversized = {"geometry": {"x": 20, "y": 30, "width": 2200, "height": 1200}, "display": {"name": "DP-1", "id": "DP-1"}}
    clamped = plan_window_action_geometry("move_to_display", before=oversized, displays=DISPLAYS, target_display="HDMI-A-1")
    assert clamped["ok"] is True
    assert clamped["width"] == 1920
    assert clamped["height"] == 1080
    assert clamped["x"] == 2560
    assert clamped["y"] == 0



def test_plan_move_to_display_requires_target_display():
    result = plan_window_action_geometry("move_to_display", before=WINDOW, displays=DISPLAYS)
    assert result["ok"] is False
    assert result["error"] == "missing_target_display"
