"""Workspace dashboard v3 mission loop surface regressions."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_v3_mission_loop_assets_exist_and_are_bootstrapped():
    index = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    body = (ROOT / "dashboard" / "assets" / "body-01b-workspace.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "assets" / "26-workspace-v3.js").read_text(encoding="utf-8")
    assert '/gui/assets/26-workspace-v3.js' in index
    assert 'workspaceMissionId' in body
    assert 'workspaceMissionCatalog' in body
    assert 'workspaceMissionLineage' in body
    assert 'workspaceMissionSchedules' in body
    assert 'workspaceMissionLoopResult' in body
    assert 'runWorkspaceMissionFollowup' in js
    assert 'runWorkspaceMissionIterate' in js
    assert 'loadWorkspaceMissionLineage' in js
    assert 'loadWorkspaceMissionFamily' in js
    assert 'saveWorkspaceMissionSchedule' in js
    assert 'tickWorkspaceMissionSchedules' in js
