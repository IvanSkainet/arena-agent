"""Regression guards for extension 0.14.24 (v4.50.14).

Two focused fixes after v4.50.13 tour.

1. T3 chat duplicate NOT swept by v4.50.13. Live scan showed
   `mounted_controls: 2`, two mounted events for the same
   fingerprint `arena_msg_1326293718`. The v4.50.13 sweep was
   map-based (walked mountedControls.entries()) but
   mountedControls.set(fp, ...) OVERWRITES the prior entry when
   two mounts commit with the same message fingerprint -- the
   map ended up with 1 entry while the DOM had 2 shadow-hosts.
   v4.50.14 rewrites the sweep to walk
   `[data-arena-tool-controls-mounted]` in the DOM directly and
   groups by a new `data-arena-semantic-fingerprint` stamp on
   the host.

2. Arena.ai Battle diagnostics -- no Battle scan yet from Ivan,
   so v4.50.14 adds `arenaai_hint.carousel` block on every
   snapshot: reports total carousels on the page and per-column
   snapshot with `has_ai_bar` so the next Battle miss can be
   root-caused from one scan-report.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_24():
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.42'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.42"
    assert "return '0.14.42';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.42`" in _read("README.md")


# ------------------------------------------------------------------
# Fix 1: DOM-based sweep + semantic fingerprint stamp
# ------------------------------------------------------------------

def test_host_stamps_semantic_fingerprint():
    content = _read("content.js")
    assert "host.dataset.arenaSemanticFingerprint = semanticFingerprint" in content


def test_sweep_now_walks_dom():
    content = _read("content.js")
    assert "querySelectorAll('[data-arena-tool-controls-mounted=\"1\"]')" in content
    assert "arenaSemanticFingerprint" in content
    # The old map-based iteration must be gone from the sweep body.
    m = re.search(
        r"function sweepDuplicateToolbars\(\).*?^}",
        content,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert m
    body = m.group(0)
    assert "mountedControls.entries()" not in body, (
        "map-based iteration must be replaced with DOM walk"
    )
    # Sweep still keeps the LATER-in-document survivor.
    assert "compareDocumentPosition" in body


def test_sweep_evicts_shadow_host_wrapper():
    content = _read("content.js")
    # New: reach up to the arena-shadow-host wrapper when evicting.
    assert "arena-shadow-host" in content


# ------------------------------------------------------------------
# Fix 2: battle carousel diagnostic
# ------------------------------------------------------------------

def test_arenaai_hint_reports_carousel_snapshot():
    adapters = _read("adapters.js")
    # New carousel snapshot on the arenaai_hint block.
    assert "carousel: carouselSnapshot" in adapters
    assert "has_ai_bar" in adapters


def test_carousel_snapshot_gates_on_class_tokens():
    adapters = _read("adapters.js")
    # Snapshot must query for all the multi-column indicators we
    # already understand.
    assert '@container/carousel' in adapters
    assert '[class*="carousel"]' in adapters
    assert '[class*="side-by-side"]' in adapters
    assert '[class*="battle"]' in adapters


# ------------------------------------------------------------------
# Prior guards still hold
# ------------------------------------------------------------------

def test_v0423_sweep_helper_still_declared():
    content = _read("content.js")
    assert "function sweepDuplicateToolbars()" in content
    assert "sweep_duplicate_evicted" in content
    assert "sweepDuplicateToolbars();" in content


def test_v0423_arena_column_index_still_present():
    adapters = _read("adapters.js")
    assert "function arenaColumnIndex(node)" in adapters
    for token in ("@container/carousel", "carousel", "side-by-side",
                  "battle", "grid-cols-2", "flex-row"):
        assert token in adapters


def test_v0423_per_entry_finder_still_present():
    content = _read("content.js")
    assert "matchedEntries" in content
    assert "matchedEntries > 0 && entries.length > 1" in content


def test_v0422_partial_failure_status_still_present():
    content = _read("content.js")
    assert "Executed ${okCount}/${total} call(s)" in content
    assert "# call ${id}" in content


def test_v0421_arenaai_self_end_still_present():
    adapters = _read("adapters.js")
    assert "arenaai:self-end@DIV" in adapters


def test_v0420_dom_position_tiebreaker_still_present():
    content = _read("content.js")
    assert "compareDocumentPosition" in content
    assert "later-in-document" in content


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
    assert "[data-turn-role]" in adapters


def test_prior_regression_guards_still_hold():
    adapters = _read("adapters.js")
    content = _read("content.js")
    m = re.search(r"_USER_AUTHOR_ATTRS\s*=\s*\[(.+?)\]", adapters, flags=re.DOTALL)
    assert m and "'user-message'" not in m.group(1)
    assert "function controlsHost(node, adapter)" in content
    assert "function arenaWhyUserAuthored(node, adapter)" in adapters
    strat = _read("insert_strategies.js")
    assert "const deadline = Date.now() + 800;" in strat
