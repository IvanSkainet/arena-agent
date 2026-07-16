"""Workspace dashboard v2 surface regressions."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_v2_assets_exist_and_are_bootstrapped():
    # v3.91.0: script list comes from the manifest, not from index.html.
    from arena.gui.asset_manifest import build_manifest
    m = build_manifest(ROOT)
    scripts = {p.rsplit("/", 1)[-1] for p in m["scripts"]}
    body = (ROOT / "dashboard" / "assets" / "body-01b-workspace.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "assets" / "25-workspace-v2.js").read_text(encoding="utf-8")
    assert "25-workspace-v2.js" in scripts
    assert 'workspaceProfileNotes' in body
    assert 'workspaceLessons' in body
    assert 'workspaceActivity' in body
    assert 'loadWorkspacePanels' in js
    assert 'saveWorkspaceNotes' in js
    assert 'addWorkspaceLesson' in js
