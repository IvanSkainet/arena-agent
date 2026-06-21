"""Workspace dashboard surface regressions."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_workspace_tab_is_wired_in_shell_and_bootstrap():
    shell = (ROOT / "dashboard" / "assets" / "body-00-shell.html").read_text(encoding="utf-8")
    index = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert 'data-tab="workspace"' in shell
    assert '/gui/assets/24-workspace.js' in index
    assert '/gui/assets/body-01b-workspace.html' in index


def test_workspace_assets_exist():
    assert (ROOT / "dashboard" / "assets" / "24-workspace.js").is_file()
    assert (ROOT / "dashboard" / "assets" / "body-01b-workspace.html").is_file()
