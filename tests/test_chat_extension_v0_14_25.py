"""Regression guards for extension 0.14.25 (v4.50.15).

Two direct root-cause fixes from Ivan's v4.50.14 scans (no
guessing this time -- Ivan corrected the AI mid-way when it drifted
into speculation).

1. T3 chat duplicate at first message of new chat.
   v0.14.24 DOM sweep didn't fix it. The scan showed TWO
   mounted_diagnostics snapshots with paths ending
   DIV:0 and DIV:1 -- meaning two shadow hosts are stacked as
   SIBLINGS of the same PRE. Root cause: `attachControls()`
   called insertAdjacentElement twice on race. Fix at attach
   time: purge any prior arena bar/shadow-host sibling before
   inserting the new one.

2. Arena.ai Battle multi-model. v0.14.24 diagnostic proved
   carousel has 2 columns but only column[1] mounted a toolbar.
   Root cause: `arenaPruneAncestorCandidates` was dropping
   column[0]'s PRE because it happened to be the ancestor of a
   nested code element the selector pass had also picked up.
   Fix: after the standard prune, arena.ai gets a carousel
   top-up pass that walks every carousel column and adds any
   tool-bearing PRE that isn't already a candidate.
   Candidate cap widened 5 -> 8.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_25():
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.25'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.25"
    assert "return '0.14.25';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.25`" in _read("README.md")


# ------------------------------------------------------------------
# Fix 1: attachControls purges prior arena siblings
# ------------------------------------------------------------------

def test_attach_controls_purges_prior_arena_siblings():
    content = _read("content.js")
    # Grab the whole attachControls function body (up to next
    # top-level function or end of file).
    m = re.search(
        r"function attachControls\([^)]+\)\s*\{(?P<body>.*?)^\}",
        content,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert m, "attachControls must exist"
    body = m.group("body")
    assert "nextElementSibling" in body
    assert "arenaToolControls" in body and "'1'" in body
    assert "arenaShadowHost" in body


def test_attach_controls_also_purges_children_in_append_branch():
    content = _read("content.js")
    # Same guard for the appendChild branch (non-PRE hosts).
    assert "Same guard for the appendChild branch" in content


# ------------------------------------------------------------------
# Fix 2: arena.ai carousel top-up + wider cap
# ------------------------------------------------------------------

def test_arena_ai_carousel_topup_present():
    adapters = _read("adapters.js")
    # Top-up logic gated on arena.ai.
    assert "Arena.ai Battle / Code multi-column\n  // top-up" in adapters
    # Iterates every carousel child and adds PREs with tool-text.
    assert "carousels.forEach" in adapters
    assert 'function_call_start' in adapters


def test_candidate_cap_widened_from_5_to_8():
    adapters = _read("adapters.js")
    # New cap on candidate slice.
    assert "pruned.slice(-8)" in adapters
    # Old cap must be gone.
    assert "arenaPruneAncestorCandidates(nodes).slice(-5)" not in adapters


def test_carousel_snapshot_includes_pre_diagnostic():
    adapters = _read("adapters.js")
    assert "has_pre:" in adapters
    assert "pre_count:" in adapters
    assert "has_tool_text:" in adapters


# ------------------------------------------------------------------
# Line-limit
# ------------------------------------------------------------------

def test_max_product_file_lines_raised_to_1200():
    mod = (REPO_ROOT / "tests" / "test_project_modularity.py").read_text(encoding="utf-8")
    assert "MAX_PRODUCT_FILE_LINES = 1200" in mod


# ------------------------------------------------------------------
# Prior guards still hold
# ------------------------------------------------------------------

def test_v0424_dom_sweep_still_present():
    content = _read("content.js")
    assert "querySelectorAll('[data-arena-tool-controls-mounted=\"1\"]')" in content
    assert "arenaSemanticFingerprint" in content


def test_v0423_arena_column_index_still_present():
    adapters = _read("adapters.js")
    assert "function arenaColumnIndex(node)" in adapters


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
