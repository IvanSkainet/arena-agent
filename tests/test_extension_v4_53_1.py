"""v0.14.42 / v4.53.1 tests: description passthrough + per-call Copy chip.

Full DOM behaviour verified in jstest/smoke_v531.js.
"""
from __future__ import annotations

import json
from pathlib import Path
from tests._version_matrix import any_bridge_in, any_pyproject_in

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_EXT = REPO_ROOT / "chat_extension"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_manifest_version_bumped():
    assert json.loads(_read(CHAT_EXT / "manifest.json"))["version"] == "0.14.42"


def test_content_script_version_bumped():
    assert "const ARENA_CONTENT_SCRIPT_VERSION = '0.14.42';" in _read(CHAT_EXT / "content.js")


def test_insert_strategies_version_bumped():
    assert "return '0.14.42';" in _read(CHAT_EXT / "insert_strategies.js")


def test_readme_mentions_v4_53_1():
    src = _read(CHAT_EXT / "README.md")
    assert "0.14.42" in src
    assert "v4.53.1" in src


def test_constants_version_bumped():
    assert any_bridge_in(_read(REPO_ROOT / 'arena' / 'constants.py'))


def test_pyproject_version_bumped():
    assert any_pyproject_in(_read(REPO_ROOT / 'pyproject.toml'))


# ------------------------------------------------------------------
# content.js: description cache + annotator wiring
# ------------------------------------------------------------------

def test_content_has_description_cache():
    src = _read(CHAT_EXT / "content.js")
    assert "_arenaDescCachePromise" in src
    assert "_arenaDescLookup" in src


def test_description_cache_hits_instructions_endpoint():
    """The catalog endpoint is /v1/extension/instructions?category=all —
    we must reuse the existing arena.instructions message and set
    category:'all' to get every tool at once."""
    src = _read(CHAT_EXT / "content.js")
    # The message type + explicit category:'all' must appear
    # inside the description cache setup function.
    idx = src.index("_arenaDescCachePromise")
    slice_after = src[idx: idx + 1200]
    assert "arena.instructions" in slice_after
    assert "category: 'all'" in slice_after or 'category: "all"' in slice_after


def test_annotator_awaits_description_alongside_risk():
    """_arenaAnnotateCallsForPreview must ask for both risk AND
    description per call (Promise.all keeps latency single-frame)."""
    src = _read(CHAT_EXT / "content.js")
    idx = src.index("_arenaAnnotateCallsForPreview")
    slice_after = src[idx: idx + 800]
    assert "_arenaRiskLookup" in slice_after
    assert "_arenaDescLookup" in slice_after
    assert "Promise.all" in slice_after
    # Output carries `description` field.
    assert "description," in slice_after or "description:" in slice_after


# ------------------------------------------------------------------
# shadow_toolbar.js: per-call Copy chip
# ------------------------------------------------------------------

def test_preview_card_renders_copy_chip():
    src = _read(CHAT_EXT / "shadow_toolbar.js")
    assert "arena-preview-copy" in src
    # Chip is a proper <button type="button"> for a11y.
    assert "copyBtn.type = 'button'" in src
    assert "aria-label" in src


def test_copy_chip_writes_arena_tool_fenced_block():
    """Chip must serialise ONLY the current invocation, wrapped
    in an arena-tool fenced block ready to paste."""
    src = _read(CHAT_EXT / "shadow_toolbar.js")
    idx = src.index("arena-preview-copy")
    slice_after = src[idx: idx + 2000]
    assert "'```arena-tool" in slice_after
    assert 'bridge: \'arena\'' in slice_after
    assert "version: 1" in slice_after
    # navigator.clipboard.writeText is the only clipboard API we
    # use (no execCommand fallback needed in MV3 content scripts).
    assert "navigator.clipboard.writeText" in slice_after


def test_copy_chip_shows_success_and_failure_states():
    src = _read(CHAT_EXT / "shadow_toolbar.js")
    idx = src.index("arena-preview-copy")
    slice_after = src[idx: idx + 2000]
    assert "Copied" in slice_after
    assert "Copy failed" in slice_after
    # Success class is toggled so CSS can theme it.
    assert "arena-preview-copy--ok" in slice_after


def test_copy_chip_prevents_focus_theft():
    """pointerdown + mousedown preventDefault to stop the chip
    from stealing composer focus (same pattern as the toolbar
    buttons in makeButton())."""
    src = _read(CHAT_EXT / "shadow_toolbar.js")
    idx = src.index("arena-preview-copy")
    slice_after = src[idx: idx + 2000]
    assert "pointerdown" in slice_after
    assert "mousedown" in slice_after


# ------------------------------------------------------------------
# shadow_toolbar.css: chip styling
# ------------------------------------------------------------------

def test_shadow_toolbar_css_has_copy_chip_style():
    css = _read(CHAT_EXT / "shadow_toolbar.css")
    assert ".arena-preview-copy" in css
    assert ".arena-preview-copy:hover" in css
    assert ".arena-preview-copy:focus-visible" in css
    assert ".arena-preview-copy--ok" in css
    # Chip is pushed to the right of the header via margin-left: auto.
    assert "margin-left: auto" in css
