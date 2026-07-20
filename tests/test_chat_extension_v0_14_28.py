"""Regression guards for extension 0.14.28 (v4.50.18).

Adds an opt-in toggle for the generic adapter that Ivan expressed
concern about after v4.50.17. Default OFF so unlisted sites see
zero mount attempts (v0.14.4 safety restored). Explicit true
required via popup Advanced/experimental to activate the
v0.14.27 passiveUnlessComposer + strictJsonlFencing logic.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_28():
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.38'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.38"
    assert "return '0.14.38';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.38`" in _read("README.md")


# ------------------------------------------------------------------
# Toggle plumbed everywhere
# ------------------------------------------------------------------

def test_settings_defaults_include_generic_toggle():
    src = _read("settings.js")
    assert "enableGenericAdapter: false" in src


def test_settings_normalizer_treats_toggle_as_boolean():
    src = _read("settings.js")
    assert "enableGenericAdapter: !!input.enableGenericAdapter" in src


def test_background_sync_defaults_include_toggle():
    src = _read("background.js")
    assert "enableGenericAdapter: false" in src
    assert "enableGenericAdapter: !!input.enableGenericAdapter" in src


def test_popup_html_has_toggle_checkbox():
    html = _read("popup.html")
    assert 'id="enableGenericAdapter"' in html
    assert "Enable generic adapter on unlisted sites" in html


def test_popup_js_reads_and_writes_toggle():
    js = _read("popup.js")
    assert "enableGenericAdapter: document.getElementById('enableGenericAdapter').checked" in js
    assert "document.getElementById('enableGenericAdapter').checked" in js


# ------------------------------------------------------------------
# Gate in mountControls: default off = skip
# ------------------------------------------------------------------

def test_content_gates_generic_behind_toggle():
    content = _read("content.js")
    assert "adapter.passiveUnlessComposer" in content
    # New gate: toggle must be true for the adapter to try mounting.
    assert "enableGenericAdapter === true" in content
    assert "skip_generic_toggle_off" in content


# ------------------------------------------------------------------
# Prior guards still hold
# ------------------------------------------------------------------

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


def test_v0427_generic_adapter_flags_still_present():
    sites = _read("adapter_sites.js")
    assert "passiveUnlessComposer: true" in sites
    assert "strictJsonlFencing: true" in sites


def test_v0426_column_regex_still_tightened():
    adapters = _read("adapters.js")
    assert "IS_REAL_CAROUSEL" in adapters


def test_v0425_attach_purge_still_present():
    content = _read("content.js")
    m = re.search(
        r"function attachControls\([^)]+\)\s*\{(?P<body>.*?)^\}",
        content,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert m
    body = m.group("body")
    assert "nextElementSibling" in body


def test_v0421_arenaai_self_end_still_present():
    adapters = _read("adapters.js")
    assert "arenaai:self-end@DIV" in adapters


def test_v0419_kimi_thinking_widget_still_dismissed():
    adapters = _read("adapters.js")
    m = re.search(
        r"adapterName === 'kimi'.*?thinking-container.*?matched: true, reason: 'kimi:thinking-widget",
        adapters,
        flags=re.DOTALL,
    )
    assert m


def test_v0417_aistudio_turn_role_still_present():
    adapters = _read("adapters.js")
    assert "closest('ms-chat-turn')" in adapters
