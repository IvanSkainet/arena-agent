"""Regression guards for extension 0.14.21 (v4.50.11).

Three retries after Ivan's v4.50.10 tour:

1. Arena.ai user filter markers were INVERTED in v4.50.10.
   Tailwind live scans prove `bg-surface-raised w-fit` is actually
   the User pill background, not AI. The definitive User marker
   is `self-end` (Tailwind flex right-align pattern) on any
   ancestor. AI is recognised by `#response-content-container` or
   by the wide-column `mx-auto max-w-[800px] w-full` pattern.

2. Multi-block on OpenRouter didn't work because v4.50.10 walker
   used `querySelectorAll('pre')` and OpenRouter renders each
   block as `<div class="group/codeblock">` without any <pre>
   ancestor (selector_hits pre.raw=0). The walker is broadened to
   also accept `.group/codeblock`, `.code-block`, `.codeBlock`,
   `.syntax-highlighter`, `.markdown-fenced-code` with tightest-
   node de-dup.

3. ChatGPT same-call_id tiebreaker never ran because both
   identical assistant PREs hashed to the SAME fingerprint --
   arenaNodePath 6-deep collapses the parent structure differences
   between conversation-turn-2 and conversation-turn-6. Ivan saw
   `skip_semantic_already_mounted` (not skip_semantic_prev_alive
   -> the tiebreaker branch never fires because semanticOwner
   === fingerprint short-circuits). Fix adds conversation-turn-N
   ordinal (or playground-message-list bubble index) as a roleBit
   fallback so two identical assistant echoes get distinct
   fingerprints.
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

def test_versions_pinned_to_0_14_21():
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.24'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.24"
    assert "return '0.14.24';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.24`" in _read("README.md")


# ------------------------------------------------------------------
# Fix 1: Arena.ai markers un-inverted; keyed on self-end
# ------------------------------------------------------------------

def test_arenaai_user_now_keyed_on_self_end():
    adapters = _read("adapters.js")
    assert "arenaai:self-end@DIV" in adapters
    # And the branch appears in arenaWhyUserAuthored (not just a
    # stray comment).
    m = re.search(
        r"adapterName === 'arenaai'.*?self-end.*?matched: true, reason: 'arenaai:self-end@DIV'",
        adapters,
        flags=re.DOTALL,
    )
    assert m, "User branch must fire on `self-end` ancestor"


def test_arenaai_ai_recognised_by_response_container_and_wide_column():
    adapters = _read("adapters.js")
    # AI fast-return still hits response-content-container.
    assert "#response-content-container" in adapters
    # Wide-column pattern (mx-auto max-w-[800px] w-full).
    assert "max-w-[800px]" in adapters
    assert "w-full" in adapters
    # The old inverted rule (return {matched: false} when
    # bg-surface-raised is an ancestor) must be gone. We check that
    # the specific v4.50.10 code pattern is no longer present.
    assert 'closest(\'#response-content-container, [class*="bg-surface-raised"]\')' not in adapters


# ------------------------------------------------------------------
# Fix 2: multi-block walker broadened
# ------------------------------------------------------------------

def test_multiblock_walker_recognises_group_codeblock():
    content = _read("content.js")
    assert "group/codeblock" in content
    # And the other alternative markers stay.
    assert "code-block" in content
    assert "syntax-highlighter" in content
    # Tightest-node de-dup logic present.
    assert "contains?." in content or "contains(" in content


# ------------------------------------------------------------------
# Fix 3: fingerprint fallback via turn ordinal
# ------------------------------------------------------------------

def test_extract_node_id_falls_back_to_conversation_turn_ordinal():
    adapters = _read("adapters.js")
    # New fallback: conversation-turn-N ordinal from data-testid.
    assert 'conversation-turn-' in adapters
    m = re.search(r"conversation-turn-\(\\d\+\)", adapters)
    assert m, "must capture conversation-turn-N with regex"


def test_extract_node_id_falls_back_to_bubble_index():
    adapters = _read("adapters.js")
    # Last-resort playground-message-list bubble index.
    assert 'playground-message-list' in adapters
    assert 'message-list-content' in adapters


def test_role_bit_still_present_in_fingerprint_join():
    adapters = _read("adapters.js")
    m = re.search(
        r"return \[[^\]]*roleBit[^\]]*\]\.join\('\|'\)",
        adapters,
        flags=re.DOTALL,
    )
    assert m


# ------------------------------------------------------------------
# Prior guards still hold
# ------------------------------------------------------------------

def test_v0420_multiblock_scan_still_present():
    content = _read("content.js")
    assert "// Multi-block path" in content or "Multi-block" in content
    assert "Single-block fallback" in content
    assert "function_call_start" in content


def test_v0420_dom_position_tiebreaker_still_present():
    content = _read("content.js")
    assert "compareDocumentPosition" in content
    assert "later-in-document" in content
    assert "cidsEqualOrMissing" in content


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


def test_v0418_prewarm_still_present():
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
