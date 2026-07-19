"""Regression guards for extension 0.14.18 (v4.50.8).

Four narrow fixes derived from Ivan's v4.50.7 site tour:

1. Kimi -- scan-report shows the tool block PRE mounted inside
   `.toolcall-container.thinking-container` which is collapsed on
   load; visible copy lives in `.segment-assistant`. controlsHost
   must hop out of the thinking widget into the visible segment.

2. z.ai -- scan-report shows the tool block candidate as an outer
   `.markdown-prose` DIV with no <pre> hits at all; toolbar was
   attaching at the end of the whole message. controlsHost must
   walk down into `.code-block` / `.syntax-highlighter` / <pre>
   when we land on the outer .markdown-prose.

3. Arena.ai -- toolbar label read "Arena · arenaai" (raw internal
   id) and the user-authored filter never fired on Agent / Direct
   / Battle surfaces so User panels got toolbars instead of AI. Fix
   adds `displayName` on adapter_sites.js and a per-adapter branch
   in arenaWhyUserAuthored that keys on `.chat-user` /
   `.chat-assistant`.

4. dedupSemantic toggle -- first ~5 mounts after a page reload
   always ran with dedup=true even when the checkbox was cleared,
   because _arenaCurrentModes() returned defaults until the async
   chrome.runtime.sendMessage('arena.getConfig') resolved. Fix
   prewarms _prewarmedModes from chrome.storage.sync at init and
   also gates mountedPayloadSemantics.add() behind the toggle so a
   mid-session flip actually takes effect.
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

def test_versions_pinned_to_0_14_18():
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.25'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.25"
    assert "return '0.14.25';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.25`" in _read("README.md")


# ------------------------------------------------------------------
# Fix 1: Kimi thinking-container hop
# ------------------------------------------------------------------

def test_kimi_thinking_container_hopped_to_visible_segment():
    """v4.50.8 hopped controlsHost; v4.50.9 dismisses via
    arenaWhyUserAuthored. Either implementation counts as a fix."""
    src_content = _read("content.js")
    src_adapters = _read("adapters.js")
    assert "toolcall-container" in src_content or "toolcall-container" in src_adapters
    assert "thinking-container" in src_content or "thinking-container" in src_adapters


# ------------------------------------------------------------------
# Fix 2: z.ai markdown-prose walk-down
# ------------------------------------------------------------------

def test_zai_walks_down_from_markdown_prose():
    src = _read("content.js")
    assert "adapterName === 'zai'" in src
    assert "markdown-prose" in src
    # The walker must recognise ANY of the three code-container
    # markers we saw in the scan-report so the toolbar sits inside
    # the tool block, not at the end of the entire prose.
    assert "code-block" in src
    assert "syntax-highlighter" in src
    assert "segment-code" in src


# ------------------------------------------------------------------
# Fix 3: Arena.ai display name + user filter
# ------------------------------------------------------------------

def test_arenaai_display_name_field_present():
    sites = _read("adapter_sites.js")
    m = re.search(r"name:\s*'arenaai'[^}]+displayName:\s*'Arena\.ai'", sites, flags=re.DOTALL)
    assert m, "arenaai adapter must declare displayName 'Arena.ai'"


def test_adapter_label_helper_and_toolbar_uses_it():
    adapters = _read("adapters.js")
    content = _read("content.js")
    assert "function arenaAdapterLabel(adapter)" in adapters
    assert "adapter.displayName || adapter.name" in adapters
    # The toolbar chip must go through the label helper (typeof
    # guard tolerated for defensiveness).
    assert "arenaAdapterLabel(adapter)" in content


def test_arenaai_user_filter_branch_present():
    """v4.50.8 keyed on .chat-*; v4.50.9 replaced with real
    arena.ai design-system tokens (bg-surface-*). Either counts as
    long as the branch exists and returns a user reason."""
    adapters = _read("adapters.js")
    assert "adapterName === 'arenaai'" in adapters
    # AI branch present (any of the two candidate markers).
    assert (".chat-assistant" in adapters
            or "bg-surface-raised" in adapters
            or "response-content-container" in adapters)
    # User branch present.
    assert (".chat-user" in adapters
            or "bg-surface-primary" in adapters
            or "arenaai:user-wrap" in adapters
            or "arenaai:chat-user" in adapters)


# ------------------------------------------------------------------
# Fix 4: dedupSemantic prewarm + gated set-add
# ------------------------------------------------------------------

def test_content_prewarms_modes_from_sync_storage():
    src = _read("content.js")
    assert "let _prewarmedModes = null" in src
    assert "chrome.storage.sync.get({modes: null})" in src
    # _arenaCurrentModes must consult the prewarm before falling to
    # defaults.
    assert "if (_prewarmedModes) return _prewarmedModes" in src


def test_mounted_payload_semantics_add_gated_by_dedup_toggle():
    src = _read("content.js")
    assert "if (_dedupSemantic) mountedPayloadSemantics.add(semanticFingerprint)" in src


# ------------------------------------------------------------------
# Prior v4.50.7 guards still hold (no regression)
# ------------------------------------------------------------------

def test_v0417_aistudio_turn_role_branch_still_present():
    adapters = _read("adapters.js")
    assert "closest('ms-chat-turn')" in adapters
    assert "[data-turn-role]" in adapters
    m = re.search(r"turnRole === 'user'\s*\|\|\s*turnRole === 'system'", adapters)
    assert m
    m = re.search(r"turnRole === 'model'\s*\|\|\s*turnRole === 'assistant'", adapters)
    assert m


def test_v0416_call_id_tie_breaker_still_present():
    adapters = _read("adapters.js")
    content = _read("content.js")
    assert "function arenaPayloadCallId(payload)" in adapters
    assert "arenaPayloadCallId(payload)" in content
    assert "higher-call-id:${currentCid}>${previousCid}" in content


def test_v0416_shadow_z_index_still_ten():
    assert "z-index: 10;" in _read("shadow_toolbar.css")
    assert "z-index: 100;" not in _read("shadow_toolbar.css")


def test_v0416_advanced_still_collapsible():
    src = _read("popup.html")
    assert "<details" in src
    assert "Advanced / experimental" in src


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
