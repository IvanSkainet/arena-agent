"""Regression guards for extension 0.14.17 (v4.50.7).

v0.14.16 broadened the AI Studio user filter to substring regex on
`mat-expansion-panel-header` text + aria-label, gated by a positive
model-marker exclusion. Live scan proved that on the current AI
Studio build **neither** the header-text regex nor the legacy
`ms-chat-turn[role="user"]` selector fires; `why_user_authored` came
back `{matched: false, reason: ""}` on BOTH candidates. The stable
selector confirmed by third-party userscripts is a Pascal-case
`data-turn-role` attribute on an inner element of `ms-chat-turn`:

    ms-chat-turn:has([data-turn-role="User"])   -- user turn
    ms-chat-turn:has([data-turn-role="Model"])  -- model turn

v0.14.17 adds a new AI-Studio branch that reads that attribute first
and short-circuits with an explicit not-user return when the value is
"model"/"assistant". Ancestor-snapshot depth also raised 4 -> 8 and a
new `aistudio_hint` block added to `arenaDiagnosticSnapshot` so
future regressions surface in scan-report without a Chrome inspector.
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

def test_versions_pinned_to_0_14_17():
    assert 'ARENA_CONTENT_SCRIPT_VERSION = "0.14.38"' in _read("content.js") \
        or "ARENA_CONTENT_SCRIPT_VERSION = '0.14.38'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.38"
    assert "return '0.14.38';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.38`" in _read("README.md")


# ------------------------------------------------------------------
# AI Studio: turn-role selector primary branch
# ------------------------------------------------------------------

def test_aistudio_turn_role_selector_is_primary_branch():
    src = _read("adapters.js")
    # Primary branch reads data-turn-role from inner element of ms-chat-turn.
    assert "closest('ms-chat-turn')" in src, "must walk up to ms-chat-turn"
    assert "[data-turn-role]" in src, "must query the inner data-turn-role element"
    assert "getAttribute?.('data-turn-role')" in src \
        or "getAttribute('data-turn-role')" in src, (
        "must read the data-turn-role attribute"
    )


def test_aistudio_user_and_system_turns_flagged_as_user_authored():
    src = _read("adapters.js")
    # Reason string embeds the role for scan-report readability.
    assert "aistudio:turn-role=" in src
    # Both 'user' and 'system' treated as user-authored (bridge tools
    # are never expected in system-instructions blocks either).
    m = re.search(r"turnRole === 'user'\s*\|\|\s*turnRole === 'system'", src)
    assert m, "user + system turn-roles must be treated as user-authored"


def test_aistudio_model_turn_returns_explicit_not_user():
    """Fast-return when data-turn-role is model/assistant -- prevents
    the legacy header-text fallback from false-positive matching on
    Russian localisation."""
    src = _read("adapters.js")
    m = re.search(r"turnRole === 'model'\s*\|\|\s*turnRole === 'assistant'", src)
    assert m, "model/assistant turn-roles must short-circuit as not-user"


def test_aistudio_class_token_fallback_present():
    """Some AI Studio revisions expose .user-turn / .model-turn class
    tokens on ms-chat-turn root instead of the data attribute."""
    src = _read("adapters.js")
    assert "class-turn@MS-CHAT-TURN" in src


def test_aistudio_legacy_fallbacks_survive():
    """v0.14.15 role=user selector and v0.14.16 header-text regex kept
    as later-priority fallbacks so old AI Studio builds keep working."""
    src = _read("adapters.js")
    assert 'ms-chat-turn[role="user"]' in src
    assert 'ms-prompt-chunk[chunkrole="user"]' in src
    assert "user|пользоват|system|систем" in src
    assert "model|assistant|ответ|модел" in src
    assert "isUser && !isModel" in src


# ------------------------------------------------------------------
# Diagnostic snapshot upgrades
# ------------------------------------------------------------------

def test_diagnostic_snapshot_ancestor_depth_is_eight():
    src = _read("adapters.js")
    # New cap: 8; the loop condition is `i < 8`.
    m = re.search(r"for \(let i = 0; cur && i < 8; i\+\+\)", src)
    assert m, "ancestor loop must walk up to 8 levels (was 4 in v0.14.16)"


def test_diagnostic_snapshot_exposes_aistudio_hint():
    src = _read("adapters.js")
    assert "aistudio_hint" in src, "snapshot must include aistudio_hint block"
    # The hint surfaces the exact signals we now key on.
    assert "has_ms_chat_turn" in src
    assert "chat_turn_class" in src
    assert "data_turn_role" in src
    assert "panel_header_text" in src
    assert "panel_header_aria" in src


# ------------------------------------------------------------------
# Prior v4.50.6 guards still hold (do not regress)
# ------------------------------------------------------------------

def test_v0416_call_id_tie_breaker_still_present():
    content = _read("content.js")
    adapters = _read("adapters.js")
    assert "function arenaPayloadCallId(payload)" in adapters
    assert "typeof arenaPayloadCallId === 'function'" in content
    assert "arenaPayloadCallId(payload)" in content
    assert "arenaPayloadCallId(previous?.payload)" in content


def test_v0416_dedup_toggle_still_gated():
    content = _read("content.js")
    assert "const _dedupSemantic = _arenaCurrentModes()?.dedupSemantic !== false" in content
    assert "if (_dedupSemantic) {" in content


def test_v0416_shadow_z_index_still_ten():
    css = _read("shadow_toolbar.css")
    assert "z-index: 10;" in css
    assert "z-index: 100;" not in css
    assert "z-index: 2147483000;" not in css


def test_v0416_advanced_still_collapsible():
    src = _read("popup.html")
    assert "<details" in src
    assert "Advanced / experimental" in src
    assert '<input id="dedupSemantic" type="checkbox" checked>' in src


def test_prior_regression_guards_still_hold():
    adapters = _read("adapters.js")
    content = _read("content.js")

    m = re.search(r"_USER_AUTHOR_ATTRS\s*=\s*\[(.+?)\]", adapters, flags=re.DOTALL)
    assert m and "'user-message'" not in m.group(1)

    assert "function controlsHost(node, adapter)" in content
    assert "function arenaWhyUserAuthored(node, adapter)" in adapters
    assert "adapterName === 'grok' || adapterName === 'duckai'" in adapters
    assert "adapterName === 't3chat'" in adapters
    assert "pre.qwen-markdown-code, pre" in content

    assert "if (!visible) score -= 500" in adapters
    assert "let bubbleId = ''" in adapters
    strat = _read("insert_strategies.js")
    assert "const deadline = Date.now() + 800;" in strat
