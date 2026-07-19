"""Regression guards for extension 0.14.22 (v4.50.12).

Big backlog release. Four related changes.

1. Arena.ai battle / side-by-side multi-model. Two models emitting
   identical tool calls in parallel carousel columns previously
   deduped to a single toolbar because arenaPayloadSemanticFingerprint
   was payload-only (same tool+arguments -> same hash). v4.50.12
   accepts an optional `node` parameter and mixes in a `cN`
   column index when the candidate is inside an
   `@container/carousel` / `carousel` / `side-by-side` container.
   arenaExtractNodeId's roleBit also gains an `ai_cN` variant so
   the message fingerprint splits along columns.

2. Partial-failure result rendering. resultToText now labels every
   call with its id/tool/status header so failures don't hide
   subsequent successful calls. Run + auto-run status lines show
   `X/Y call(s) in Nms · error: ...` on partial failure with
   timing preserved.

3. Bridge mission endpoints return actionable 400 JSON with
   `error`, `hint`, `required`, and `endpoint` fields.
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

def test_versions_pinned_to_0_14_22():
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.28'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.28"
    assert "return '0.14.28';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.28`" in _read("README.md")


# ------------------------------------------------------------------
# Fix 1: battle multi-model column ordinal
# ------------------------------------------------------------------

def test_semantic_fingerprint_accepts_node_and_carries_column():
    adapters = _read("adapters.js")
    # Signature now includes optional node.
    m = re.search(
        r"function arenaPayloadSemanticFingerprint\(payload,\s*adapter\s*=[^,]+,\s*node\s*=\s*null\)",
        adapters,
    )
    assert m, "semantic fingerprint must accept an optional node param"
    # Body must derive a column token from the carousel container.
    assert "@container/carousel" in adapters
    assert "side-by-side" in adapters


def test_role_bit_gets_column_variant_on_arena_ai_battle():
    adapters = _read("adapters.js")
    # roleBit now has an ai_cN variant when the AI PRE sits in a
    # multi-column layout.
    assert "'ai_c'" in adapters


def test_mount_controls_passes_host_to_semantic_fingerprint():
    content = _read("content.js")
    # The mountControls call site must pass `host` so battle columns
    # get different semantic hashes.
    assert "arenaPayloadSemanticFingerprint(payload, adapter, host)" in content


# ------------------------------------------------------------------
# Fix 2: partial failure preserves timing + shows per-call status
# ------------------------------------------------------------------

def test_result_to_text_labels_each_call_with_status_header():
    content = _read("content.js")
    # New per-call block header.
    assert "# call ${id} · ${tool} · ${okFlag}" in content or "# call ${id}" in content
    assert "call?.ok === false ? 'ERROR' : 'OK'" in content


def test_run_button_shows_partial_success_status():
    content = _read("content.js")
    # Partial success format.
    assert "Executed ${okCount}/${total} call(s)" in content
    # Timing always calculated (not gated behind result.ok).
    assert "const timing = bridgeMs > 0" in content


def test_auto_run_preserves_text_on_partial_failure():
    content = _read("content.js")
    # runAutoModes must render text even when result.ok is false.
    assert "Auto executed ${okCount}/${total} call(s)" in content


# ------------------------------------------------------------------
# Fix 3: bridge mission 400 hints (checked in bridge tests)
# ------------------------------------------------------------------

def test_bridge_mission_get_returns_actionable_400():
    handlers = (REPO_ROOT / "arena" / "resources" / "handlers.py").read_text(encoding="utf-8")
    # New shared helper.
    assert "_missing_name_error" in handlers
    assert "\"hint\":" in handlers
    assert "mission.catalog" in handlers
    assert "\"required\":" in handlers
    assert "\"endpoint\":" in handlers


def test_bridge_mission_family_returns_actionable_400():
    lifecycle = (REPO_ROOT / "arena" / "resources" / "mission_lifecycle_handlers.py").read_text(encoding="utf-8")
    assert "\"hint\":" in lifecycle
    assert "mission.catalog" in lifecycle
    assert "GET /v1/mission/family?name=" in lifecycle


# ------------------------------------------------------------------
# Prior regression guards still hold
# ------------------------------------------------------------------

def test_v0421_arenaai_self_end_still_present():
    adapters = _read("adapters.js")
    assert "arenaai:self-end@DIV" in adapters


def test_v0421_openrouter_group_codeblock_walker_still_present():
    content = _read("content.js")
    assert "group/codeblock" in content


def test_v0421_conversation_turn_ordinal_still_present():
    adapters = _read("adapters.js")
    assert "conversation-turn-" in adapters


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
    css = _read("shadow_toolbar.css")
    assert "z-index: 10;" in css
