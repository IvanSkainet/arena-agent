"""Regression guards for extension 0.14.19 (v4.50.9).

Three retries from Ivan's v4.50.8 tour:

1. Kimi -- the v0.14.18 attempt to re-anchor on `.segment-assistant`
   sibling produced a huge empty toolbar column in saved chats
   because that segment DIV spans the whole message vertically.
   v0.14.19 approach: dismiss the thinking-widget candidate via
   arenaWhyUserAuthored (matched=true) so mountControls silently
   adds its fingerprint to dismissedControls and returns; the
   sibling `.segment-content` PRE (already a separate parsed
   candidate) gets the toolbar with no visual side-effects.

2. z.ai -- the v0.14.18 walker keyed on Kimi-specific class tokens
   (`.code-block`, `.syntax-highlighter`, `.segment-code`) that
   don't exist on z.ai. Broadened to include `<pre>`, `<code>`,
   `[class*="language-"]`, `[class*="hljs"]` AND require the
   element's text to contain `function_call_start` /
   `function_call_end` so we anchor exactly on the block.

3. Arena.ai -- the v0.14.18 `.chat-user`/`.chat-assistant` keys
   were z.ai's, not arena.ai's. Switched to arena.ai's actual
   Tailwind design-system tokens observed in the live scan:
   `bg-surface-raised` (AI wrapper, often paired with `w-fit`)
   and `bg-surface-primary`+`no-scrollbar` (User wrapper). Also
   added `arenaai_hint` diagnostic block (surface + wrapper chain)
   so `/agent/`, `/c/`, and `/battle/` regressions are visible.
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

def test_versions_pinned_to_0_14_19():
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.20'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.20"
    assert "return '0.14.20';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.20`" in _read("README.md")


# ------------------------------------------------------------------
# Fix 1: Kimi thinking-widget dismissed instead of hopped
# ------------------------------------------------------------------

def test_kimi_thinking_widget_dismissed_via_user_authored():
    """v0.14.19 must recognise the thinking-widget copy as an
    already-handled duplicate; arenaWhyUserAuthored is the vehicle."""
    adapters = _read("adapters.js")
    m = re.search(
        r"adapterName === 'kimi'.*?closest\('\.toolcall-container.*?thinking-container'\).*?return \{matched: true, reason: 'kimi:thinking-widget",
        adapters,
        flags=re.DOTALL,
    )
    assert m, "Kimi thinking-widget must return matched=true from arenaWhyUserAuthored"


def test_kimi_controls_host_no_longer_re_anchors_to_segment_assistant():
    """The v0.14.18 hop that caused the huge empty column must be
    gone. controlsHost should not walk out to `.segment-assistant`
    on Kimi anymore."""
    content = _read("content.js")
    # The old walker used `thinking.closest?.('.segment-assistant, ...')` --
    # confirm it's gone.
    assert "thinking.closest" not in content, (
        "v0.14.18 Kimi hop must be removed; thinking-widget handled elsewhere"
    )


# ------------------------------------------------------------------
# Fix 2: z.ai walker broadened
# ------------------------------------------------------------------

def test_zai_walker_recognises_pre_code_language_and_hljs():
    src = _read("content.js")
    # New markers.
    assert "class*=\"language-\"" in src or "'language-'" in src or 'language-' in src
    assert "hljs" in src
    # And the walker gates on JSONL text so we don't attach on
    # unrelated code fences.
    assert "function_call_start" in src
    assert "function_call_end" in src


# ------------------------------------------------------------------
# Fix 3: Arena.ai keyed on bg-surface-raised / bg-surface-primary
# ------------------------------------------------------------------

def test_arenaai_uses_bg_surface_raised_for_ai():
    adapters = _read("adapters.js")
    assert "bg-surface-raised" in adapters
    # AI branch still hits the response container as a fast-return.
    assert "#response-content-container" in adapters
    # And it fast-returns not-user for AI.
    m = re.search(
        r"adapterName === 'arenaai'.*?bg-surface-raised.*?return \{matched: false",
        adapters,
        flags=re.DOTALL,
    )
    assert m, "AI branch must fast-return {matched:false}"


def test_arenaai_user_keys_on_bg_surface_primary_or_no_scrollbar():
    adapters = _read("adapters.js")
    assert "bg-surface-primary" in adapters
    assert "no-scrollbar" in adapters
    assert "arenaai:user-wrap@DIV" in adapters


def test_diagnostic_snapshot_exposes_arenaai_hint():
    adapters = _read("adapters.js")
    assert "arenaai_hint" in adapters
    assert "response_container_ancestor" in adapters
    assert "bg_surface_raised_ancestor" in adapters
    assert "bg_surface_primary_ancestor" in adapters
    # Surface classifier so scan-reports separate /agent/, /c/, /battle/.
    assert "'agent'" in adapters
    assert "'chat'" in adapters
    assert "'battle'" in adapters


# ------------------------------------------------------------------
# Prior v4.50.8 guards still hold (no regression)
# ------------------------------------------------------------------

def test_v0418_arenaai_display_name_still_present():
    sites = _read("adapter_sites.js")
    m = re.search(r"name:\s*'arenaai'[^}]+displayName:\s*'Arena\.ai'", sites, flags=re.DOTALL)
    assert m


def test_v0418_prewarm_and_gated_add_still_present():
    content = _read("content.js")
    assert "let _prewarmedModes = null" in content
    assert "chrome.storage.sync.get({modes: null})" in content
    assert "if (_prewarmedModes) return _prewarmedModes" in content
    assert "if (_dedupSemantic) mountedPayloadSemantics.add(semanticFingerprint)" in content


def test_v0417_aistudio_turn_role_still_present():
    adapters = _read("adapters.js")
    assert "closest('ms-chat-turn')" in adapters
    assert "[data-turn-role]" in adapters


def test_v0416_call_id_tie_breaker_still_present():
    adapters = _read("adapters.js")
    content = _read("content.js")
    assert "function arenaPayloadCallId(payload)" in adapters
    assert "arenaPayloadCallId(payload)" in content


def test_prior_regression_guards_still_hold():
    adapters = _read("adapters.js")
    content = _read("content.js")
    m = re.search(r"_USER_AUTHOR_ATTRS\s*=\s*\[(.+?)\]", adapters, flags=re.DOTALL)
    assert m and "'user-message'" not in m.group(1)
    assert "function controlsHost(node, adapter)" in content
    assert "function arenaWhyUserAuthored(node, adapter)" in adapters
    assert "adapterName === 'grok' || adapterName === 'duckai'" in adapters
    assert "adapterName === 't3chat'" in adapters
    strat = _read("insert_strategies.js")
    assert "const deadline = Date.now() + 800;" in strat
    css = _read("shadow_toolbar.css")
    assert "z-index: 10;" in css
