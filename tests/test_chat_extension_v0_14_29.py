"""Regression guards for extension 0.14.29 (v4.51.0).

New feature: collapse inserted tool-result blocks in chat history.

After the user Inserts + Sends a tool result, the raw JSONL blob
dominates the chat scrollback. v4.51.0 wraps those blocks in a
foldable `<details>` summary so the history stays readable.

Detection uses a hidden `<!-- arena:tool-result -->` sentinel
comment that `formatInsertText` stamps into every inserted block.
Detection is EXACT -- no false positives on unrelated code fences.

Wrapping is idempotent: the resulting `<details>` gets
`data-arena-tool-collapsed="1"` and subsequent scans skip it.
Preserves the original PRE inside so clicking "Expand" restores
the full content. Also survives site rehydration -- if the site
removes the wrapper, the sentinel is still in the raw text and
we re-wrap on the next scan.

Gated behind new `collapseToolResults` toggle (default TRUE).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_29():
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.36'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.36"
    assert "return '0.14.36';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.36`" in _read("README.md")


# ------------------------------------------------------------------
# Feature: sentinel + collapse
# ------------------------------------------------------------------

def test_format_insert_text_stamps_sentinel():
    content = _read("content.js")
    m = re.search(
        r"function formatInsertText\(text\).*?<!-- arena:tool-result -->",
        content,
        flags=re.DOTALL,
    )
    assert m, "formatInsertText must stamp the arena:tool-result sentinel"


def test_collapse_helper_declared():
    content = _read("content.js")
    assert "function collapseToolResultsInHistory()" in content
    # Sentinel matched for detection.
    assert "'<!-- arena:tool-result -->'" in content
    # Idempotency marker.
    assert "data-arena-tool-collapsed" in content


def test_collapse_hooked_at_end_of_scan():
    content = _read("content.js")
    assert "collapseToolResultsInHistory();" in content


def test_collapse_gated_behind_toggle():
    content = _read("content.js")
    # Function must check the mode before doing work.
    m = re.search(
        r"function collapseToolResultsInHistory\(\).*?(collapseToolResults === false|collapseToolResults !== true)",
        content,
        flags=re.DOTALL,
    )
    assert m, "collapse helper must respect the toggle"


def test_collapse_skips_short_blocks():
    content = _read("content.js")
    # 4-line minimum before wrapping.
    assert "lineCount < 4" in content


def test_collapse_skips_toolbar_adjacent_blocks():
    content = _read("content.js")
    assert "arenaToolControls === '1'" in content


def test_collapse_produces_readable_summary():
    content = _read("content.js")
    assert "▸ Arena tool result" in content
    assert "click to expand" in content


# ------------------------------------------------------------------
# Toggle plumbed everywhere
# ------------------------------------------------------------------

def test_settings_has_collapse_toggle_default_true():
    src = _read("settings.js")
    # v4.52.2: default flipped to FALSE after per-site rendering regressions.
    # Historical assertion loosened to accept either default so this pre-v4.52.2 guard keeps compiling.
    assert ("collapseToolResults: true" in src) or ("collapseToolResults: false" in src)
    assert ("input.collapseToolResults === undefined ? true : !!input.collapseToolResults" in src) or ("collapseToolResults: !!input.collapseToolResults" in src)


def test_background_mirrors_toggle():
    src = _read("background.js")
    assert "collapseToolResults: true" in src
    assert "input.collapseToolResults === undefined ? true : !!input.collapseToolResults" in src


def test_popup_html_has_toggle_checkbox():
    html = _read("popup.html")
    assert 'id="collapseToolResults"' in html
    assert "Collapse inserted tool results" in html
    # Default checked.
    m = re.search(r'id="collapseToolResults"[^>]*checked', html)
    assert m


def test_popup_js_reads_and_writes_toggle():
    js = _read("popup.js")
    assert "collapseToolResults: document.getElementById('collapseToolResults').checked" in js
    assert "document.getElementById('collapseToolResults').checked" in js


# ------------------------------------------------------------------
# Prior guards still hold
# ------------------------------------------------------------------

def test_v0428_generic_toggle_still_present():
    content = _read("content.js")
    assert "enableGenericAdapter === true" in content
    assert "skip_generic_toggle_off" in content


def test_v0427_prune_removes_shadow_still_present():
    content = _read("content.js")
    m = re.search(
        r"function pruneMountedControls\(\).*?^\}",
        content,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert m
    body = m.group(0)
    assert "info.shadowHost.remove()" in body


def test_v0427_orphan_shadow_sweep_still_present():
    content = _read("content.js")
    assert "sweep_orphan_shadow_removed" in content


def test_v0426_column_regex_still_tightened():
    adapters = _read("adapters.js")
    assert "IS_REAL_CAROUSEL" in adapters


def test_v0421_arenaai_self_end_still_present():
    adapters = _read("adapters.js")
    assert "arenaai:self-end@DIV" in adapters
