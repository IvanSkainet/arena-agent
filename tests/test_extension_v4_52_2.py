"""v0.14.36 / v4.52.2 tests: collapse hardening + UI polish.

Focus: collapseToolResults is now default OFF, gated behind an
explicit `=== true` check, site-skip list is honoured, wrapper
styling is minimal (all: revert). Full DOM behaviour verified in
`jstest/smoke_v522.js`.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_EXT = REPO_ROOT / "chat_extension"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_manifest_version_bumped():
    assert json.loads(_read(CHAT_EXT / "manifest.json"))["version"] in ("0.14.36", "0.14.42")


def test_content_script_version_bumped():
    assert any(v in _read(CHAT_EXT / 'content.js') for v in ("const ARENA_CONTENT_SCRIPT_VERSION = '0.14.36';", "const ARENA_CONTENT_SCRIPT_VERSION = '0.14.42';"))


def test_insert_strategies_version_bumped():
    assert any(v in _read(CHAT_EXT / 'insert_strategies.js') for v in ("return '0.14.36';", "return '0.14.42';"))


def test_readme_mentions_v4_52_2():
    src = _read(CHAT_EXT / "README.md")
    assert ("0.14.36" in src or "0.14.42" in src)
    assert ("v4.52.2" in src or "v4.52.3" in src or "v4.52.5" in src or "v4.52.6" in src or "v4.53.0" in src or "v4.53.1" in src)


def test_constants_version_bumped():
    assert any(v in _read(REPO_ROOT / 'arena' / 'constants.py') for v in ('VERSION = "4.52.2"', 'VERSION = "4.52.3"', 'VERSION = "4.52.4"', 'VERSION = "4.52.5"', 'VERSION = "4.52.6"', 'VERSION = "4.53.0"', 'VERSION = "4.53.1"', 'VERSION = "4.54.0"', 'VERSION = "4.54.1"', 'VERSION = "4.55.0"', 'VERSION = "4.55.1"', 'VERSION = "4.56.0"', 'VERSION = "4.57.0"', 'VERSION = "4.58.0"', 'VERSION = "4.59.0"', 'VERSION = "4.59.1"', 'VERSION = "4.60.0"'))


def test_pyproject_version_bumped():
    assert any(v in _read(REPO_ROOT / 'pyproject.toml') for v in ('version = "4.52.2"', 'version = "4.52.3"', 'version = "4.52.4"', 'version = "4.52.5"', 'version = "4.52.6"', 'version = "4.53.0"', 'version = "4.53.1"', 'version = "4.54.0"', 'version = "4.54.1"', 'version = "4.55.0"', 'version = "4.55.1"', 'version = "4.56.0"', 'version = "4.57.0"', 'version = "4.58.0"', 'version = "4.59.0"', 'version = "4.59.1"', 'version = "4.58.0"', 'version = "4.59.0"', 'version = "4.59.1"', 'version = "4.60.0"'))


# ------------------------------------------------------------------
# Collapse hardening
# ------------------------------------------------------------------

def test_settings_default_collapse_is_false():
    """Default flipped from TRUE to FALSE in v4.52.2."""
    src = _read(CHAT_EXT / "settings.js")
    # ARENA_MODE_DEFAULTS entry.
    assert "collapseToolResults: false" in src
    # Normalizer must not carry the old "undefined -> TRUE" path.
    assert "collapseToolResults: !!input.collapseToolResults" in src
    assert "collapseToolResults === undefined ? true" not in src


def test_content_collapse_requires_explicit_true():
    """Runtime guard must use strict `!== true` (i.e. any
    undefined / false / missing config means the collapse is
    OFF)."""
    src = _read(CHAT_EXT / "content.js")
    assert "collapseToolResults !== true" in src


def test_content_has_site_skip_list_including_gemini():
    src = _read(CHAT_EXT / "content.js")
    assert "ARENA_COLLAPSE_SKIP_HOSTS" in src
    assert "gemini.google.com" in src


def test_content_collapse_wrapper_uses_minimal_styling():
    src = _read(CHAT_EXT / "content.js")
    # `all: revert` must be used to escape per-site CSS.
    assert "all: revert" in src
    # Prior explicit background / border-radius must be gone
    # (they were the source of Qwen pink-purple + Kimi bar).
    assert "details.style.background" not in src
    assert "details.style.borderRadius" not in src
    assert "details.style.padding = '4px 8px'" not in src


# ------------------------------------------------------------------
# Settings tab: collapse moved to Advanced/experimental
# ------------------------------------------------------------------

def test_collapse_toggle_now_lives_in_advanced_section():
    html = _read(CHAT_EXT / "sidepanel.html")
    # Toggle must still be rendered.
    assert 'id="mCollapseToolResults"' in html
    # But it must be BELOW the "Advanced / experimental" heading,
    # not under "UI polish".
    ui_start = html.index("<h2>UI polish</h2>")
    adv_start = html.index("<h2>Advanced / experimental</h2>")
    collapse_pos = html.index('id="mCollapseToolResults"')
    assert adv_start < collapse_pos, "collapse toggle must sit inside the Advanced section"
    # And it must NOT sit in UI polish anymore.
    ui_section = html[ui_start:adv_start]
    assert "mCollapseToolResults" not in ui_section


def test_advanced_section_has_experimental_hint_for_collapse():
    html = _read(CHAT_EXT / "sidepanel.html")
    adv = html[html.index("<h2>Advanced"):]
    # Explanation must mention the sites Ivan reported.
    for kw in ("experimental", "Default OFF", "Qwen", "Kimi", "Gemini"):
        assert kw in adv, f"missing advanced-section hint keyword: {kw}"


# ------------------------------------------------------------------
# UI polish (CSS)
# ------------------------------------------------------------------

def test_css_header_has_gradient_dot():
    css = _read(CHAT_EXT / "popup.css")
    assert ".arena-header h1::before" in css
    assert "linear-gradient" in css


def test_css_tabs_are_pill_shaped_container():
    css = _read(CHAT_EXT / "popup.css")
    # New tabs container has background + border + border-radius.
    assert ".arena-tabs{" in css
    tab_block_start = css.index(".arena-tabs{")
    tab_block = css[tab_block_start:tab_block_start + 300]
    assert "border-radius" in tab_block
    assert "background" in tab_block


def test_css_buttons_no_longer_turn_blue_on_hover():
    """v4.52.1 css turned every button blue on hover. Now buttons
    lift to a lighter slate; the blue is reserved for
    `.arena-btn-primary`."""
    css = _read(CHAT_EXT / "popup.css")
    # Global button:hover must NOT be blue.
    hover_line = [l for l in css.split("\n") if l.strip().startswith("button:hover{")]
    assert hover_line, "button:hover rule missing"
    assert "#2563eb" not in hover_line[0]
    # Primary-button class must exist for the blue accent.
    assert ".arena-btn-primary" in css


def test_css_inputs_have_focus_ring():
    css = _read(CHAT_EXT / "popup.css")
    assert "input:focus,select:focus" in css
    assert "box-shadow" in css
