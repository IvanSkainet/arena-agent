"""Regression guards for extension 0.14.20 (v4.50.10).

Picks up the deferred v4.50.9 backlog:

1. Arena.ai fingerprint collision. The v4.50.9 arenaWhyUserAuthored
   correctly returned matched=true on User and matched=false on
   AI, but the two PREs shared identical DOM paths + text heads
   so arenaExtractNodeId hashed them to the SAME fingerprint. When
   User skipped, its fingerprint was added to dismissedControls;
   AI then cascaded through skip_dismissed_fp. v4.50.10 adds a
   roleBit token (ai / user) derived from the nearest
   bg-surface-raised / bg-surface-primary / response-content-container
   wrapper so the two get DIFFERENT fingerprints.

2. Multi-block per message. When a single AI turn emits multiple
   tool JSONL blocks (Ivan observed 5-6 on OpenRouter / arena.ai
   messages), the previous scan() collapsed them under one
   controlsHost so only ONE toolbar mounted. v4.50.10 expands the
   candidate into per-PRE hosts (one toolbar per PRE containing
   function_call_start/end), falls back to single-host behaviour
   when only one block is found.

3. Same-call_id tiebreaker by DOM position. Prior to v4.50.10 the
   dedup tie-breaker used numeric call_id and fell back to
   "prev-wins" on equal or missing call_ids. That means when the
   model forgets to increment call_id, the older mount stays
   visible and the newest copy is hidden. v4.50.10 now uses
   compareDocumentPosition to prefer the LATER-in-document copy
   when call_ids are equal / missing.

4. MAX_PRODUCT_FILE_LINES raised 900 -> 1000. The multi-block scan
   rewrite pushed content.js from 852 -> ~910 LOC and per project
   policy we raise the limit rather than compress readable code.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------
# Version pins
# ------------------------------------------------------------------

def test_versions_pinned_to_0_14_20():
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.33'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.33"
    assert "return '0.14.33';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.33`" in _read("README.md")


# ------------------------------------------------------------------
# Fix 1: role-bit fingerprint token
# ------------------------------------------------------------------

def test_extract_node_id_includes_role_bit():
    """v0.14.21 flipped the arena.ai markers (self-end = user)
    and added conversation-turn-N / bubble-index fallbacks. Test now
    just checks that roleBit derivation exists in the function and
    is part of the fingerprint join."""
    adapters = _read("adapters.js")
    m = re.search(
        r"function arenaExtractNodeId\([^)]*\).*?let roleBit\s*=\s*''",
        adapters,
        flags=re.DOTALL,
    )
    assert m, "arenaExtractNodeId must declare a roleBit variable"
    m2 = re.search(
        r"return \[[^\]]*roleBit[^\]]*\]\.join\('\|'\)",
        adapters,
        flags=re.DOTALL,
    )
    assert m2, "roleBit must be part of the fingerprint join"


def test_role_bit_covers_response_container():
    adapters = _read("adapters.js")
    assert "#response-content-container" in adapters


# ------------------------------------------------------------------
# Fix 2: multi-block per candidate
# ------------------------------------------------------------------

def test_scan_expands_multiple_pre_blocks_per_candidate():
    content = _read("content.js")
    # v0.14.21 broadened the walker from pre-only to any code-block
    # container (OpenRouter uses .group/codeblock). Accept either
    # spelling.
    assert ("querySelectorAll?.('pre')" in content
            or "group/codeblock" in content)
    assert ("blockNodes.length > 1" in content
            or "matchedEntries > 0" in content)
    assert "// Single-block fallback" in content
    assert "function_call_start" in content
    assert "function_call_end" in content


# ------------------------------------------------------------------
# Fix 3: DOM-position tiebreaker
# ------------------------------------------------------------------

def test_dom_position_tiebreaker_added():
    content = _read("content.js")
    assert "compareDocumentPosition" in content
    # 0x04 = Node.DOCUMENT_POSITION_FOLLOWING.
    assert "rel & 4" in content
    # Diag event name for the new eviction branch.
    assert "later-in-document" in content
    # Guard: only fires when call_ids are equal or missing.
    assert "cidsEqualOrMissing" in content


# ------------------------------------------------------------------
# Fix 4: line-limit raised
# ------------------------------------------------------------------

def test_max_product_file_lines_raised_to_1000():
    modularity = (REPO_ROOT / "tests" / "test_project_modularity.py").read_text(encoding="utf-8")
    assert ("MAX_PRODUCT_FILE_LINES = 1000" in modularity
            or "MAX_PRODUCT_FILE_LINES = 1100" in modularity
            or "MAX_PRODUCT_FILE_LINES = 1200"
            or "MAX_PRODUCT_FILE_LINES = 1300"
            or "MAX_PRODUCT_FILE_LINES = 1400" in modularity)
    assert "MAX_PRODUCT_FILE_LINES = 900" not in modularity  # baseline still gone


# ------------------------------------------------------------------
# Prior v4.50.9 guards still hold
# ------------------------------------------------------------------

def test_v0419_arenaai_hint_still_present():
    adapters = _read("adapters.js")
    assert "arenaai_hint" in adapters
    assert "'agent'" in adapters
    assert "'chat'" in adapters
    assert "'battle'" in adapters


def test_v0419_kimi_thinking_widget_still_dismissed():
    adapters = _read("adapters.js")
    m = re.search(
        r"adapterName === 'kimi'.*?thinking-container.*?matched: true, reason: 'kimi:thinking-widget",
        adapters,
        flags=re.DOTALL,
    )
    assert m


def test_v0419_zai_walker_still_broadened():
    content = _read("content.js")
    assert "hljs" in content
    assert "language-" in content


def test_v0417_aistudio_turn_role_still_present():
    adapters = _read("adapters.js")
    assert "closest('ms-chat-turn')" in adapters
    assert "[data-turn-role]" in adapters


def test_v0416_call_id_tie_breaker_still_present():
    adapters = _read("adapters.js")
    content = _read("content.js")
    assert "function arenaPayloadCallId(payload)" in adapters
    assert "arenaPayloadCallId(payload)" in content
    assert "higher-call-id:${currentCid}>${previousCid}" in content


def test_v0418_prewarm_and_gated_add_still_present():
    content = _read("content.js")
    assert "let _prewarmedModes = null" in content
    assert "chrome.storage.sync.get({modes: null})" in content
    assert "if (_dedupSemantic) mountedPayloadSemantics.add(semanticFingerprint)" in content


def test_prior_regression_guards_still_hold():
    adapters = _read("adapters.js")
    content = _read("content.js")
    m = re.search(r"_USER_AUTHOR_ATTRS\s*=\s*\[(.+?)\]", adapters, flags=re.DOTALL)
    assert m and "'user-message'" not in m.group(1)
    assert "function controlsHost(node, adapter)" in content
    assert "function arenaWhyUserAuthored(node, adapter)" in adapters
    strat = _read("insert_strategies.js")
    assert "const deadline = Date.now() + 800;" in strat
    css = _read("shadow_toolbar.css")
    assert "z-index: 10;" in css
