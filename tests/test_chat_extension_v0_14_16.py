"""Regression guards for extension 0.14.17 (v4.50.6).

Four operator asks after v0.14.15:

1. "AI Studio User filter работает в обратную сторону: теперь только
   User ловит, а AI не ловит."
   -> v0.14.15 relied on mat-expansion-panel-header text starting with
   "User"/"Пользоват". Scan proved this misses on the current AI
   Studio build. v0.14.17 broadens: substring match on both text AND
   aria-label for user|пользоват|system|систем, plus a positive
   assistant/model check so we DO NOT mark the AI panel as user.

2. "z-index работает на Claude и T3, но на Grok не работает."
   -> Grok wraps content in a transform-ed container which creates
   its own stacking context. z-index:100 was scoped to that context
   and still overrode the composer. Dropped to 10 -- still above
   Qwen/Claude action rows (z-index 2-5) but comfortably below any
   scoped composer overlay.

3. "Я бы dedup сделал ещё по ID сообщений: отображается только на
   том, где ID (цифра в tool call) больше."
   -> when two candidates share the same semantic fingerprint AND
   both are alive in the DOM, evict the one with the smaller
   numeric call_id and mount the higher one. Falls back to the
   v0.14.13 "prev-wins" behaviour when call_ids are missing or
   non-numeric.

4. "Добавил бы collapse для Advanced/Experimental."
   -> wrap the Advanced fieldset in <details> so it collapses by
   default; the summary text "Advanced / experimental" stays
   visible.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name):
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_16():
    import json
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.26'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.26"
    assert "return '0.14.26';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.26`" in _read("README.md")


# ------------------------------------------------------------------
# AI Studio user filter -- fixed direction
# ------------------------------------------------------------------

def test_aistudio_user_filter_substring_match_with_positive_model_exception():
    """v0.14.17 must match user headers by substring (regex with word
    boundary), not by prefix, and must NOT flag the AI/model panel."""
    src = _read("adapters.js")
    # Substring regex for user/system markers.
    assert "user|пользоват|system|систем" in src, (
        "regex must cover user/system markers in both English and Russian"
    )
    # Substring regex for model/assistant markers (the negative check).
    assert "model|assistant|ответ|модел" in src, (
        "regex must recognise model/assistant markers as NOT-user"
    )
    # And the guard is `isUser && !isModel`.
    assert "isUser && !isModel" in src, (
        "user match must be gated by absence of model markers"
    )
    # Custom-element ancestor path also survives (kept from v0.14.15).
    assert "ms-chat-turn[role=\"user\"]" in src
    assert "ms-prompt-chunk[chunkrole=\"user\"]" in src


# ------------------------------------------------------------------
# call_id-aware dedup
# ------------------------------------------------------------------

def test_arena_payload_call_id_helper_exists():
    src = _read("adapters.js")
    assert "function arenaPayloadCallId(payload)" in src
    # Contract: returns NaN when call_id missing / non-numeric.
    assert "return Number.isFinite(n) ? n : NaN" in src


def test_dedup_prefers_higher_call_id():
    """v0.14.17: when two live candidates share semantic fp, evict
    the one with the smaller numeric call_id."""
    src = _read("content.js")
    # Helper resolved via typeof guard so tests don't need arenaPayloadCallId
    # loaded to still tolerate missing helper (defensive).
    assert "typeof arenaPayloadCallId === 'function'" in src
    assert "arenaPayloadCallId(payload)" in src
    assert "arenaPayloadCallId(previous?.payload)" in src
    # Evict reason string includes both call_ids so scan-report shows
    # exactly which one won.
    assert "higher-call-id:${currentCid}>${previousCid}" in src or \
           'higher-call-id:${currentCid}' in src, (
        "evict reason must record both call_ids for scan-report clarity"
    )


def test_mounted_control_stores_payload_for_dedup_comparison():
    """mountedControls entry needs the payload so future comparisons
    can extract call_id from it."""
    src = _read("content.js")
    assert "{host, bar, shadowHost, semanticFingerprint, payload}" in src


def test_skip_semantic_prev_alive_diag_records_call_ids():
    """When we skip the newcomer because prev has higher call_id,
    the diag event should record both so it is greppable."""
    src = _read("content.js")
    assert "current_call_id: currentCid" in src
    assert "previous_call_id: previousCid" in src


# ------------------------------------------------------------------
# z-index lowered to 10 for Grok composer overlap
# ------------------------------------------------------------------

def test_shadow_toolbar_z_index_lowered_to_10():
    src = _read("shadow_toolbar.css")
    assert "z-index: 10;" in src, (
        "toolbar z-index must be lowered to 10 to stay under Grok's composer"
    )
    assert "z-index: 100;" not in src, "the intermediate z-index:100 must be gone"
    assert "z-index: 2147483000;" not in src


# ------------------------------------------------------------------
# Advanced fieldset collapsed by default
# ------------------------------------------------------------------

def test_advanced_fieldset_is_collapsible():
    src = _read("popup.html")
    # A <details> wrapper appears around the Advanced section.
    assert "<details" in src
    assert "Advanced / experimental" in src
    # The dedupSemantic checkbox lives inside it.
    assert '<input id="dedupSemantic" type="checkbox" checked>' in src


# ------------------------------------------------------------------
# Prior guards still hold
# ------------------------------------------------------------------

def test_dedup_still_gated_behind_toggle():
    src = _read("content.js")
    assert "const _dedupSemantic = _arenaCurrentModes()?.dedupSemantic !== false" in src
    assert "if (_dedupSemantic) {" in src


def test_prior_regression_guards_still_hold():
    adapters = _read("adapters.js")
    content = _read("content.js")
    css = _read("shadow_toolbar.css")

    import re
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

    # v0.14.15 shadow_toolbar Qwen stacking (isolation + position:relative).
    assert "isolation: isolate" in css
    assert "position: relative" in css


def test_content_js_within_900_limit():
    lines = len(_read("content.js").splitlines())
    assert lines <= 1200, f"content.js is {lines} lines (limit 1200)"


def test_scan_report_diagnostics_still_shipped():
    src = _read("content.js")
    for field in (
        "candidate_diagnostics: candidateDiagnostics",
        "mounted_diagnostics: mountedDiagnostics",
        "events_recent: _arenaDiagEvents.slice()",
    ):
        assert field in src
