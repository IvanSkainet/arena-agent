"""v0.14.34 / v4.52.0 tests: sidepanel UI redesign with tabs.

Focuses on string-level guarantees for the new sidepanel HTML +
JS. Tabs are lazy-loaded, so we only need to verify the
declarative side (tab elements, handler wiring, per-tab controls).
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_EXT = REPO_ROOT / "chat_extension"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_manifest_version_bumped():
    assert json.loads(_read(CHAT_EXT / "manifest.json"))["version"] in ("0.14.34", "0.14.35", "0.14.42")


def test_content_script_version_bumped():
    assert any(v in _read(CHAT_EXT / 'content.js') for v in ("const ARENA_CONTENT_SCRIPT_VERSION = '0.14.34';", "const ARENA_CONTENT_SCRIPT_VERSION = '0.14.35';", "const ARENA_CONTENT_SCRIPT_VERSION = '0.14.42';"))


def test_insert_strategies_version_bumped():
    assert any(v in _read(CHAT_EXT / 'insert_strategies.js') for v in ("return '0.14.34';", "return '0.14.35';", "return '0.14.42';"))


def test_readme_mentions_v4_52_0():
    src = _read(CHAT_EXT / "README.md")
    assert ("0.14.34" in src or "0.14.35" in src or "0.14.42" in src)
    assert ("v4.52.0" in src or "v4.52.1" in src or "v4.52.2" in src or "v4.52.3" in src or "v4.52.4" in src or "v4.52.5" in src or "v4.52.6" in src or "v4.53.0" in src or "v4.53.1" in src)


def test_constants_version_bumped():
    assert any(v in _read(REPO_ROOT / 'arena' / 'constants.py') for v in ('VERSION = "4.52.0"', 'VERSION = "4.52.1"', 'VERSION = "4.52.2"', 'VERSION = "4.52.3"', 'VERSION = "4.52.4"', 'VERSION = "4.52.5"', 'VERSION = "4.52.6"', 'VERSION = "4.53.0"', 'VERSION = "4.53.1"', 'VERSION = "4.54.0"', 'VERSION = "4.54.1"'))


def test_pyproject_version_bumped():
    assert any(v in _read(REPO_ROOT / 'pyproject.toml') for v in ('version = "4.52.0"', 'version = "4.52.1"', 'version = "4.52.2"', 'version = "4.52.3"', 'version = "4.52.4"', 'version = "4.52.5"', 'version = "4.52.6"', 'version = "4.53.0"', 'version = "4.53.1"', 'version = "4.54.0"', 'version = "4.54.1"'))


# ------------------------------------------------------------------
# Sidepanel HTML: tabs + per-tab controls
# ------------------------------------------------------------------

def test_sidepanel_has_four_tabs():
    html = _read(CHAT_EXT / "sidepanel.html")
    for tab_name in ("status", "tools", "instructions", "history"):
        assert f'data-tab="{tab_name}"' in html, f"missing tab: {tab_name}"
        assert f'id="tab-{tab_name}"' in html, f"missing tab panel: {tab_name}"


def test_sidepanel_default_tab_is_status():
    html = _read(CHAT_EXT / "sidepanel.html")
    # Status tab must carry both the header active class and the
    # panel active class on initial render.
    assert 'arena-tab-active" data-tab="status"' in html
    assert 'id="tab-status" class="arena-tab-panel arena-tab-panel-active"' in html


def test_sidepanel_has_tools_controls():
    html = _read(CHAT_EXT / "sidepanel.html")
    assert 'id="toolsCategory"' in html
    assert 'id="toolsSearch"' in html
    assert 'id="toolsReloadBtn"' in html
    assert 'id="toolsList"' in html


def test_sidepanel_has_instructions_controls():
    html = _read(CHAT_EXT / "sidepanel.html")
    assert 'id="instructionsCategory"' in html
    assert 'id="instructionsFormat"' in html
    assert 'id="instructionsCopyBtn"' in html
    assert 'id="instructionsPreview"' in html


def test_sidepanel_history_controls_kept():
    """History tab controls must not have been dropped in the port."""
    html = _read(CHAT_EXT / "sidepanel.html")
    for eid in ("kindFilter", "siteFilter", "adapterFilter",
                "applyFilterBtn", "clearBtn", "historyBox",
                "payloadBox", "resultBox"):
        assert f'id="{eid}"' in html, f"lost history control: {eid}"


def test_sidepanel_header_has_connectivity_badge():
    html = _read(CHAT_EXT / "sidepanel.html")
    assert 'id="arena-conn-badge"' in html


# ------------------------------------------------------------------
# Sidepanel JS: handlers + lazy load
# ------------------------------------------------------------------

def test_sidepanel_js_wires_all_tab_handlers():
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "activateTab" in src
    assert "TAB_LOAD_HOOKS" in src
    assert "TAB_LOADED" in src
    # Each of tools/instructions/history has a loader registered.
    assert "TAB_LOAD_HOOKS.tools" in src
    assert "TAB_LOAD_HOOKS.instructions" in src
    assert "TAB_LOAD_HOOKS.history" in src


def test_sidepanel_js_uses_instructions_endpoint_for_tools():
    """Tools tab must hit the same instructions endpoint (with
    category=…) and read `catalog[]` -- do not add a second
    endpoint just for Tools."""
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "arena.instructions" in src
    assert "loadTools" in src
    assert "TOOLS_CACHE" in src
    assert "renderToolsList" in src


def test_sidepanel_js_instructions_tab_has_live_preview():
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "loadInstructions" in src
    assert "copyInstructions" in src
    assert "INSTRUCTIONS_CACHE" in src


def test_sidepanel_js_per_tool_copy_actions():
    """Per-tool 'Copy call template' + 'Copy CSN line' must be
    present so the user can paste ready-to-use tool blocks."""
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "Copy call template" in src
    assert "Copy CSN line" in src


def test_sidepanel_js_history_wiring_preserved():
    """History tab handlers must be intact (regression guard)."""
    src = _read(CHAT_EXT / "sidepanel.js")
    for name in ("loadHistory", "renderHistory", "clearHistory",
                 "groupCommandHistory", "runHistoryAction",
                 "renderPayload", "renderResult"):
        assert name in src, f"lost history helper: {name}"


def test_sidepanel_css_has_tab_and_tool_styles():
    css = _read(CHAT_EXT / "popup.css")
    assert ".arena-tab" in css
    assert ".arena-tab-active" in css
    assert ".arena-tab-panel-active" in css
    assert ".arena-tool-card" in css
    assert ".arena-tool-name" in css
    assert ".arena-badge-risk-safe" in css
    assert ".arena-badge-risk-medium" in css
    assert ".arena-badge-risk-dangerous" in css
