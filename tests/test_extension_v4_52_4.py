"""v0.14.42 / v4.52.4 tests: Scan Now broad-query + diagnostic dump.

Full DOM behaviour verified in jstest/smoke_v524.js.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_EXT = REPO_ROOT / "chat_extension"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_manifest_version_bumped():
    assert json.loads(_read(CHAT_EXT / "manifest.json"))["version"] in ("0.14.42",)


def test_content_script_version_bumped():
    assert "const ARENA_CONTENT_SCRIPT_VERSION = '0.14.42';" in _read(CHAT_EXT / "content.js")


def test_insert_strategies_version_bumped():
    assert "return '0.14.42';" in _read(CHAT_EXT / "insert_strategies.js")


def test_readme_mentions_v4_52_4():
    src = _read(CHAT_EXT / "README.md")
    assert ("0.14.42" in src)
    assert ("v4.52.4" in src or "v4.52.5" in src or "v4.52.6" in src or "v4.53.0" in src or "v4.53.1" in src)


def test_constants_version_bumped():
    assert any(v in _read(REPO_ROOT / "arena" / "constants.py") for v in ('VERSION = "4.52.4"', 'VERSION = "4.52.5"', 'VERSION = "4.52.6"', 'VERSION = "4.53.0"', 'VERSION = "4.53.1"', 'VERSION = "4.54.0"', 'VERSION = "4.54.1"', 'VERSION = "4.55.0"', 'VERSION = "4.55.1"', 'VERSION = "4.56.0"', 'VERSION = "4.57.0"', 'VERSION = "4.58.0"', 'VERSION = "4.59.0"', 'VERSION = "4.59.1"', 'VERSION = "4.60.0"', 'VERSION = "4.60.1"'))


def test_pyproject_version_bumped():
    assert any(v in _read(REPO_ROOT / "pyproject.toml") for v in ('version = "4.52.4"', 'version = "4.52.5"', 'version = "4.52.6"', 'version = "4.53.0"', 'version = "4.53.1"', 'version = "4.54.0"', 'version = "4.54.1"', 'version = "4.55.0"', 'version = "4.55.1"', 'version = "4.56.0"', 'version = "4.57.0"', 'version = "4.58.0"', 'version = "4.59.0"', 'version = "4.59.1"', 'version = "4.58.0"', 'version = "4.59.0"', 'version = "4.59.1"', 'version = "4.60.0"', 'version = "4.60.1"'))


# ------------------------------------------------------------------
# Background: broad-query tab resolver
# ------------------------------------------------------------------

def test_background_uses_broad_tab_query():
    """No more heuristic queries. `chrome.tabs.query({})`
    returns every tab; we rank ourselves."""
    src = _read(CHAT_EXT / "background.js")
    assert "chrome.tabs.query({})" in src


def test_background_queries_windows_metadata():
    src = _read(CHAT_EXT / "background.js")
    assert "chrome.windows?.getAll" in src


def test_background_diagnostic_envelope_shape():
    """Failure path must return a diagnostic object with
    tabs_seen, chat_tabs_seen, windows, tabs_sample."""
    src = _read(CHAT_EXT / "background.js")
    assert "diagnostic:" in src
    for field in ("tabs_seen", "chat_tabs_seen", "tabs_sample"):
        assert field in src, f"missing diagnostic field: {field}"


def test_background_url_redaction_present():
    """URLs must be redacted to scheme://host before diag dump
    -- do not leak full URLs / query strings."""
    src = _read(CHAT_EXT / "background.js")
    assert "const redact" in src
    assert "parsed.host" in src
    # Sensitive fields (title truncated, url redacted) surfaced
    # via a helper.
    assert "tabSummary" in src


def test_background_ranks_by_active_and_normal_window():
    """Ranking must prefer active tab in a normal-type,
    focused window."""
    src = _read(CHAT_EXT / "background.js")
    assert "score += 100" in src   # active
    assert "windowType" in src
    assert "w?.focused" in src or "w?.focused" in src


def test_background_sendActive_dropped_v4_52_3_heuristics():
    """sendActiveTabMessage must not use lastFocusedWindow or
    currentWindow anymore (both failed on Ivan's setup).
    `openSidePanel` may still use currentWindow legitimately
    (it's popup-only)."""
    src = _read(CHAT_EXT / "background.js")
    block_start = src.index("async function sendActiveTabMessage")
    block_end   = src.index("async function openSidePanel")
    block = src[block_start:block_end]
    assert "lastFocusedWindow" not in block
    assert "currentWindow" not in block


def test_background_bad_url_protos_include_view_source():
    """view-source: pages are also excluded (would fail with
    Chrome sendMessage anyway)."""
    src = _read(CHAT_EXT / "background.js")
    assert "view-source:" in src


# ------------------------------------------------------------------
# Sidepanel: diagnostic renderer
# ------------------------------------------------------------------

def test_sidepanel_reads_diagnostic_field():
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "res?.diagnostic" in src


def test_sidepanel_renders_diagnostic_summary_and_sample():
    src = _read(CHAT_EXT / "sidepanel.js")
    # Summary line surfaces tabs_seen + chat_tabs_seen counts.
    assert "tabs seen" in src or "tabs_seen" in src
    # Sample tabs rendered as event-style rows.
    assert "sample tabs" in src
    # Non-normal window type must be flagged in the row.
    assert "w=${t.windowType}" in src


def test_sidepanel_still_handles_ok_and_needs_reload_paths():
    """Happy path + `Receiving end does not exist` classifier
    must still work (regression guard)."""
    js = _read(CHAT_EXT / "sidepanel.js")
    # OK path.
    assert "_sidepanelScanSummaryParts(res)" in js
    # Needs-reload path surfaces tab_url.
    assert "picked URL" in js or "tab_url" in js
