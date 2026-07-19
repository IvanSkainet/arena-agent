"""Regression guards for extension 0.14.26 (v4.50.16).

Single-line root-cause fix. Ivan's v4.50.15 Battle scan showed
BOTH AI PREs reporting `arenaai_hint.column.index: 0` even though
the carousel had 2 columns and the model emitted the tool call in
both. `later-in-document` tiebreaker evicted one because both
mounts shared the same semantic fingerprint (column part = 'c0').

Root cause: greedy `\\bcarousel\\b` regex matched the Tailwind
pseudo-utility `@[752px]/carousel:basis-1/2` living on child
column wrappers themselves. `arenaColumnIndex` short-circuited at
the wrong ancestor. Same greedy CSS selector `[class*="carousel"]`
poisoned the diagnostic snapshot -- `carousels: 3` even though
only ONE real carousel exists on the page.

Fix: tightened regex + added IS_REAL_CAROUSEL JS filter that
requires either `@container/carousel` or a `carousel-` / `battle-`
word-boundary token (NOT a Tailwind `carousel:` modifier).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_26():
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.29'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.29"
    assert "return '0.14.29';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.29`" in _read("README.md")


# ------------------------------------------------------------------
# Fix: tightened carousel regex in arenaColumnIndex
# ------------------------------------------------------------------

def test_column_index_regex_no_longer_matches_tailwind_modifier():
    adapters = _read("adapters.js")
    # New anchored regex.
    assert "(^|\\s)carousel(-|\\s|$)" in adapters
    assert "(^|\\s)battle(-|\\s|$)" in adapters
    # Old greedy \bcarousel\b pattern must be gone from the helper.
    m = re.search(
        r"function arenaColumnIndex\(node\).*?^\}",
        adapters,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert m, "helper must exist"
    body = m.group(0)
    # Strip comments so we check code only (mentioning the old regex
    # in the comment for context is fine).
    code_only = re.sub(r"//.*", "", body)
    assert "\\bcarousel\\b" not in code_only, (
        "greedy carousel regex must be gone from CODE -- matched Tailwind pseudo"
    )
    assert "\\bbattle\\b" not in code_only


def test_is_real_carousel_filter_added():
    adapters = _read("adapters.js")
    # Both call sites use the JS-level filter now.
    assert "IS_REAL_CAROUSEL" in adapters
    # Filter appears at least twice (diagnostic snapshot + top-up
    # pass in arenaCandidateNodes).
    assert adapters.count("IS_REAL_CAROUSEL") >= 4  # 2 declarations + 2 uses


def test_diagnostic_snapshot_now_filters_carousels():
    adapters = _read("adapters.js")
    # The querySelectorAll should no longer include the redundant
    # '[class*="@container/carousel"]' selector because
    # '[class*="carousel"]' already catches it and the JS filter
    # decides real vs pseudo.
    m = re.search(
        r"carouselSnapshot = null.*?carousels =",
        adapters,
        flags=re.DOTALL,
    )
    assert m, "diagnostic snapshot must exist"
    body = m.group(0)
    # We must .filter() after querySelectorAll now.
    m2 = re.search(
        r"Array\.from\(document\.querySelectorAll\([^)]+\)\)\.filter\(IS_REAL_CAROUSEL\)",
        adapters,
    )
    assert m2, "querySelectorAll must be piped through .filter(IS_REAL_CAROUSEL)"


# ------------------------------------------------------------------
# Prior guards still hold
# ------------------------------------------------------------------

def test_v0425_attach_controls_purge_still_present():
    content = _read("content.js")
    m = re.search(
        r"function attachControls\([^)]+\)\s*\{(?P<body>.*?)^\}",
        content,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert m
    body = m.group("body")
    assert "nextElementSibling" in body


def test_v0425_carousel_topup_still_present():
    adapters = _read("adapters.js")
    assert "Arena.ai Battle / Code multi-column" in adapters
    assert "pruned.slice(-8)" in adapters


def test_v0424_dom_sweep_still_present():
    content = _read("content.js")
    assert "querySelectorAll('[data-arena-tool-controls-mounted=\"1\"]')" in content
    assert "arenaSemanticFingerprint" in content


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
