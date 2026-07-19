"""Regression guards for extension 0.14.27 (v4.50.17).

Two focused changes:

1. T3 chat duplicate REAL root cause. v0.14.24-25 didn't fix it.
   Ivan's v4.50.16 scan showed the duplicate still there. Reading
   the events carefully: two `mounted` events, ~1.3s apart, no
   `skip_semantic_already_mounted` between them -- meaning
   pruneMountedControls fired mid-stream and cleared the map,
   but the shadow-host DOM node was left behind (React re-
   parented it to the new bubble). Second mount attempt then
   attaches a NEW shadow-host to the fresh PRE and the orphan
   from the previous cycle stays visible.

   Fix at two spots:
     - pruneMountedControls now REMOVES the shadow-host / bar
       from the DOM when it prunes a stale map entry.
     - sweepDuplicateToolbars gets an orphan-shadow pass: any
       [data-arena-shadow-host] whose prevElementSibling isn't a
       mounted host is removed.

2. Generic adapter goes from `passive: true` to
   `passiveUnlessComposer: true` + `strictJsonlFencing: true`.
   Now mounts on any unlisted chat site with (a) a discoverable
   composer AND (b) tool block inside a chat-shaped ancestor.
   Safe against the v0.14.3 README-code-fence false-positive
   (documentation pages don't have both markers).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_27():
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.32'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.32"
    assert "return '0.14.32';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.32`" in _read("README.md")


# ------------------------------------------------------------------
# Fix 1: T3 duplicate -- prune removes DOM
# ------------------------------------------------------------------

def test_prune_removes_shadow_host_from_dom():
    content = _read("content.js")
    m = re.search(
        r"function pruneMountedControls\(\).*?^\}",
        content,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert m, "helper must exist"
    body = m.group(0)
    assert "info?.shadowHost?.isConnected" in body
    assert "info.shadowHost.remove()" in body


def test_sweep_has_orphan_shadow_pass():
    content = _read("content.js")
    assert "sweep_orphan_shadow_removed" in content
    assert 'querySelectorAll(\'[data-arena-shadow-host="1"]\')' in content
    # And an article-level dedup pass.
    assert "sweep_article_duplicate_removed" in content


# ------------------------------------------------------------------
# Fix 2: generic adapter passiveUnlessComposer
# ------------------------------------------------------------------

def test_generic_now_passive_unless_composer():
    sites = _read("adapter_sites.js")
    m = re.search(
        r"name: 'generic'.*?passiveUnlessComposer: true.*?strictJsonlFencing: true",
        sites,
        flags=re.DOTALL,
    )
    assert m, "generic adapter must declare both new flags"


def test_generic_no_longer_passive_only():
    sites = _read("adapter_sites.js")
    # The naked `passive: true` line under generic must be gone.
    m = re.search(
        r"name: 'generic'[^}]*passive:\s*true(?!\w)",
        sites,
        flags=re.DOTALL,
    )
    assert not m, "generic must no longer be passive-only"


def test_generic_has_broader_selectors():
    sites = _read("adapter_sites.js")
    # New chat-shape selectors.
    assert '[role="log"]' in sites
    assert '[class*="message"]' in sites
    assert '[class*="chat"]' in sites


def test_mount_controls_honors_new_flags():
    content = _read("content.js")
    # Composer discovery gate.
    assert "adapter.passiveUnlessComposer" in content
    assert "skip_generic_no_composer" in content
    # Chat-shape gate.
    assert "adapter.strictJsonlFencing" in content
    assert "skip_generic_not_in_chat" in content
    # Chat ancestor selectors present.
    assert '[role="article"]' in content
    assert '[class*="bubble" i]' in content


# ------------------------------------------------------------------
# Prior guards still hold
# ------------------------------------------------------------------

def test_v0426_column_regex_tightened_still_present():
    adapters = _read("adapters.js")
    assert "IS_REAL_CAROUSEL" in adapters
    assert "(^|\\s)carousel(-|\\s|$)" in adapters


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


def test_v0424_dom_sweep_still_present():
    content = _read("content.js")
    assert "querySelectorAll('[data-arena-tool-controls-mounted=\"1\"]')" in content


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


def test_max_product_file_lines_raised_to_1300():
    mod = (REPO_ROOT / "tests" / "test_project_modularity.py").read_text(encoding="utf-8")
    assert ("MAX_PRODUCT_FILE_LINES = 1300" in mod
            or "MAX_PRODUCT_FILE_LINES = 1400" in mod)
