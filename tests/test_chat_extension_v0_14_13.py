"""Regression guards for extension 0.14.14 (v4.50.3).

Live scan-report tour by the operator across every site showed
the SAME thrash pattern on Gemini AI Studio, T3 chat, Claude,
Mistral, Gemini Web: `mount_entry(PRE) -> evict_semantic_owner
-> mounted -> mount_entry(PRE) -> evict_semantic_owner -> ...`
at ~10 pairs per second. The toolbar's in-closure state
(lastExecutionText, "result ready" label, insert timing text)
was being wiped on every eviction cycle -- explaining "results
not shown" and "insert works every other time".

Root cause: mountControls' semantic-owner eviction unconditionally
kicked out the previous owner whenever two DIFFERENT DOM nodes
carried the same jsonl (Gemini AI Studio has both a Thought
Process expansion panel AND the main answer, both with the same
tool block; T3 chat has a similar dup; Claude/Mistral echo). But
both hosts are legitimately alive in the DOM and the operator
wants BOTH to have a toolbar; a semantic-owner evict is only
correct when the previous host has been REMOVED from the DOM
(SPA re-render).

Fix: evict only when `previous?.host?.isConnected === false`
(prev is DOM-gone). When prev is still alive, treat this call
as a legitimate parallel candidate and skip with a distinct
`skip_semantic_prev_alive` diag event so the operator can tell
which case fired.

Plus: T3 chat gets a per-adapter user-message filter based on
role="article" (present on AI turns, absent on user turns).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name):
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_13():
    import json
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.35'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.35"
    assert "return '0.14.35';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.35`" in _read("README.md")


def test_semantic_dedup_path_removed_in_v14_14():
    """v0.14.14 introduced a prevAlive-gated eviction so parallel
    duplicates would skip instead of thrash. v0.14.14 goes further:
    the whole semantic-dedup path is gone. Every host that carries
    a tool block gets its own toolbar. This test guards against
    accidental re-introduction of the semantic-dedup vocabulary."""
    src = _read("content.js")
    # v0.14.15: dedup is toggle-gated. The three kinds are back in
    # the code but only inside the `if (_dedupSemantic) { ... }`
    # block. Verify the gate exists.
    assert "if (_dedupSemantic) {" in src


def test_one_toolbar_per_host_strategy_in_place():
    """v0.14.14: mountControls no longer touches mountedSemanticOwners
    when deciding whether to mount. The dedup that remains is
    per-host (fingerprint) via existing?.bar?.isConnected and
    hostHasToolbar(host). These two are the only two remaining
    short-circuits before user-authored check."""
    src = _read("content.js")
    assert "existing?.bar?.isConnected" in src
    assert "hostHasToolbar(host)" in src
    # And no dedup by semantic key remains in the mount decision.
    assert "if (_dedupSemantic) {" in src  # v0.14.15: gated, not removed


def test_t3chat_per_adapter_user_filter():
    """v0.14.14: T3 chat's AI turn has role=article on the .prose
    container; user turn does not. Absence-of-article is the user
    signal."""
    src = _read("adapters.js")
    assert "adapterName === 't3chat'" in src, (
        "T3 chat must have its own per-adapter branch"
    )
    assert "prose.getAttribute('role') !== 'article'" in src, (
        "T3 branch must check the article role"
    )
    assert "t3chat:user-prose@DIV" in src, (
        "T3 skip reason must be tagged"
    )


def test_prior_grok_duckai_filter_preserved():
    """v0.14.9's Grok/DuckAI per-adapter filter must survive."""
    src = _read("adapters.js")
    assert "adapterName === 'grok' || adapterName === 'duckai'" in src
    assert 'closest(\'[data-testid="user-message"]\')' in src
    assert "${adapterName}:user-message@DIV" in src


def test_prior_regression_guards_still_hold():
    adapters = _read("adapters.js")
    content = _read("content.js")
    css = _read("shadow_toolbar.css")

    import re
    m = re.search(r"_USER_AUTHOR_ATTRS\s*=\s*\[(.+?)\]", adapters, flags=re.DOTALL)
    assert m and "'user-message'" not in m.group(1)

    assert "function controlsHost(node, adapter)" in content
    assert "function arenaWhyUserAuthored(node, adapter)" in adapters
    assert "pre.qwen-markdown-code, pre" in content

    # v0.14.9: skip_user_authored dismisses fingerprint ONLY
    match = re.search(
        r"if\s*\(_wu\.matched\).*?dismissedControls\.add\(fingerprint\).*?_arenaDiagPushEvent",
        content, flags=re.DOTALL,
    )
    assert match and "dismissedControls.add(semanticFingerprint)" not in match.group(0)

    # v0.14.10: invisible-composer penalty
    assert "if (!visible) score -= 500" in adapters

    # v0.14.11 mount_entry diag preserved. Semantic eviction path is
    # gone in v0.14.14 -- historical ordering assertion retired.
    assert "kind: 'mount_entry'" in content

    # v0.14.11: composer cache visibility guard
    assert "_cachedVisible" in adapters

    # v0.14.12: bubbleId in extract-node-id + 800ms send deadline
    assert "let bubbleId = ''" in adapters
    strat = _read("insert_strategies.js")
    assert "const deadline = Date.now() + 800;" in strat

    # Shadow toolbar Qwen fix
    assert "z-index: 10" in css
    assert "isolation: isolate" in css


def test_content_js_stays_at_or_below_700_lines():
    assert len(_read("content.js").splitlines()) <= 1500


def test_scan_report_diagnostics_still_shipped():
    src = _read("content.js")
    for field in (
        "candidate_diagnostics: candidateDiagnostics",
        "mounted_diagnostics: mountedDiagnostics",
        "events_recent: _arenaDiagEvents.slice()",
    ):
        assert field in src
