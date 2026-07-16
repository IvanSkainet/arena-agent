"""Workspace dashboard surface regressions."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_workspace_tab_is_wired_in_shell_and_bootstrap():
    # v3.90.0: nav is built at boot from window.ARENA_TABS in
    # 00-tabs-registry.js, not hardcoded in body-00-shell.html.
    # Verify the workspace tab is declared in the registry and its
    # asset files are loaded by index.html.
    import re
    tabs = (ROOT / "dashboard" / "assets" / "00-tabs-registry.js").read_text(encoding="utf-8")
    index = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert re.search(r'name:\s*"workspace"', tabs), (
        "workspace tab must be declared in 00-tabs-registry.js "
        "(window.ARENA_TABS)."
    )
    assert '/gui/assets/24-workspace.js' in index
    assert '/gui/assets/body-01b-workspace.html' in index


def test_workspace_assets_exist():
    assert (ROOT / "dashboard" / "assets" / "24-workspace.js").is_file()
    assert (ROOT / "dashboard" / "assets" / "body-01b-workspace.html").is_file()
