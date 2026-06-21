"""Workspace dashboard v2 surface regressions."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_v2_assets_exist_and_are_bootstrapped():
    index = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    body = (ROOT / "dashboard" / "assets" / "body-01b-workspace.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "assets" / "25-workspace-v2.js").read_text(encoding="utf-8")
    assert '/gui/assets/25-workspace-v2.js' in index
    assert 'workspaceProfileNotes' in body
    assert 'workspaceLessons' in body
    assert 'workspaceActivity' in body
    assert 'loadWorkspacePanels' in js
    assert 'saveWorkspaceNotes' in js
    assert 'addWorkspaceLesson' in js
