"""Workspace dashboard surface regressions."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_workspace_tab_is_wired_in_shell_and_bootstrap():
    # v3.90.0: nav built at boot from window.ARENA_TABS.
    # v3.91.0: script + body lists come from the auto-generated
    # /gui/assets/manifest.json, not from hardcoded arrays in
    # index.html.
    import re
    tabs = (ROOT / "dashboard" / "assets" / "00-tabs-registry.js").read_text(encoding="utf-8")
    assert re.search(r'name:\s*"workspace"', tabs), (
        "workspace tab must be declared in 00-tabs-registry.js "
        "(window.ARENA_TABS)."
    )
    from arena.gui.asset_manifest import build_manifest
    m = build_manifest(ROOT)
    scripts = {p.rsplit("/", 1)[-1] for p in m["scripts"]}
    bodies = {p.rsplit("/", 1)[-1] for p in m["bodies"]}
    assert "24-workspace.js" in scripts
    assert "body-01b-workspace.html" in bodies


def test_workspace_assets_exist():
    assert (ROOT / "dashboard" / "assets" / "24-workspace.js").is_file()
    assert (ROOT / "dashboard" / "assets" / "body-01b-workspace.html").is_file()
