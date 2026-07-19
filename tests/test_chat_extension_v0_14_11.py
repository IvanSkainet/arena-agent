"""Regression guards for extension 0.14.12 (v4.49.4).

Third-round scan-report revealed two distinct real bugs that the
v0.14.10 diag events made visible:

* **DuckAI thrash cycle** (~10 evict/mount pairs per second):
  events_recent showed the pattern
  `skip_dismissed_fp(User) → mounted(AI) → evict_semantic_owner
  (User evicts AI) → skip_dismissed_fp(User) → mounted(AI) → ...`
  Root cause: `mountControls` evicted the semantic-owner BEFORE
  checking `dismissedControls`. When the User bubble re-entered
  (its fp already in dismissedControls after the first skip), the
  evict step still ran and destroyed the freshly-mounted AI
  toolbar; then the dismissed-fp check finally short-circuited the
  User call and the toolbar stayed gone until the next scan cycle
  mounted it again. This is why "результаты не видно" -- the AI
  toolbar's closure state (lastExecutionText, mounted status
  message) got wiped every ~400ms.

  **Fix**: check `dismissedControls.has(fingerprint)` and
  `dismissedControls.has(semanticFingerprint)` BEFORE the
  semantic-owner eviction. Existing evict path preserved for
  the "another host owns this semantic and this call IS going
  to mount" case.

* **Qwen composer cache returning invisible ghost**:
  `arenaComposerSelection` had a 2s cache keyed on `.isConnected`
  and time only. When the ghost sr-only textarea landed in the
  cache slot (before v0.14.10 penalised invisibles), it stayed
  there for 2s regardless of the scorer's opinion -- insert
  landed in the ghost, verify read back its textContent, status
  said "Inserted +30ms" but the visible composer stayed empty.

  **Fix**: cache check now also demands the cached target still
  passes `arenaElementVisible()`. Falsely-live invisible targets
  are evicted from the cache immediately.

* **Grok deep instrumentation**: events_recent still only shows
  the User fingerprint. AI candidate is in candidate_diagnostics
  but its mountControls call apparently never fires. Added a
  `mount_entry` diag emitted at the very top of `mountControls`
  (before any early return) so the next scan proves whether AI's
  mountControls is even called.

No mount/skip logic changed beyond re-ordering the guard checks.
Full sweep must stay green.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name):
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_11():
    import json
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.12'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.12"
    assert "return '0.14.12';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.12`" in _read("README.md")


def test_mount_entry_diag_event_at_top_of_mount_controls():
    """v0.14.12: mountControls must emit mount_entry BEFORE any
    early-return so the operator's next scan proves reachability."""
    src = _read("content.js")
    assert "kind: 'mount_entry'" in src
    # Contract: the entry event must include tag + testid so we can
    # tell Grok's code-block DIVs apart in the events stream.
    assert "tag: host?.tagName" in src
    assert "testid: host?.getAttribute?.('data-testid')" in src


def test_dismissed_checks_run_before_semantic_owner_eviction():
    """v0.14.12: the two `dismissedControls.has(...)` short-circuits
    MUST appear BEFORE the `mountedSemanticOwners.get(...)` block.
    That order is the DuckAI thrash fix."""
    src = _read("content.js")
    dismissed_fp_pos = src.find("dismissedControls.has(fingerprint)")
    dismissed_semantic_pos = src.find("dismissedControls.has(semanticFingerprint)")
    evict_pos = src.find("mountedSemanticOwners.get(semanticFingerprint)")
    assert dismissed_fp_pos > 0 and evict_pos > 0
    assert dismissed_fp_pos < evict_pos, (
        "dismissed-fp check must run before semantic-owner eviction "
        "(v0.14.12 DuckAI thrash fix)"
    )
    assert dismissed_semantic_pos > 0 and dismissed_semantic_pos < evict_pos, (
        "dismissed-semantic check must also run before eviction"
    )


def test_semantic_owner_eviction_still_present_after_reorder():
    """The eviction path must still exist -- just gated by the
    dismissed checks first. Verifies we didn't accidentally delete
    the block during reordering."""
    src = _read("content.js")
    assert "kind: 'evict_semantic_owner'" in src
    assert "mountedControls.delete(semanticOwner)" in src
    assert "mountedSemanticOwners.delete(semanticFingerprint)" in src


def test_composer_cache_invalidates_on_invisible_target():
    """v0.14.12: arenaComposerSelection's 2s cache must additionally
    check that the cached target still passes arenaElementVisible().
    Qwen new-chat ghost-composer regression fix."""
    src = _read("adapters.js")
    assert "_cachedVisible" in src, (
        "cached-visible guard must live inside arenaComposerSelection"
    )
    assert "arenaElementVisible(_cachedComposerResult.target)" in src, (
        "cache guard must ask the shared visibility helper"
    )
    # And the visibility guard must gate the early return.
    import re
    # Match the enlarged cache condition that includes _cachedVisible
    assert re.search(
        r"if\s*\(_cachedComposerResult\s*\n\s*&&\s*_cachedComposerResult\.target\?\.isConnected"
        r"\s*\n\s*&&\s*_cachedVisible",
        src,
    ) or "&& _cachedVisible" in src, (
        "cache early-return must include the _cachedVisible check"
    )


def test_prior_regression_guards_still_hold():
    """v0.14.12 must not regress any prior fix."""
    adapters = _read("adapters.js")
    content = _read("content.js")
    css = _read("shadow_toolbar.css")

    import re
    m = re.search(r"_USER_AUTHOR_ATTRS\s*=\s*\[(.+?)\]", adapters, flags=re.DOTALL)
    assert m and "'user-message'" not in m.group(1)

    assert "function controlsHost(node, adapter)" in content
    assert "function arenaWhyUserAuthored(node, adapter)" in adapters
    assert "adapterName === 'grok' || adapterName === 'duckai'" in adapters
    assert "pre.qwen-markdown-code, pre" in content

    # v0.14.9: skip_user_authored dismisses fingerprint ONLY.
    match = re.search(
        r"if\s*\(_wu\.matched\).*?dismissedControls\.add\(fingerprint\).*?_arenaDiagPushEvent",
        content, flags=re.DOTALL,
    )
    assert match and "dismissedControls.add(semanticFingerprint)" not in match.group(0)

    # v0.14.10: invisible penalty stays.
    assert "if (!visible) score -= 500" in adapters

    # shadow_toolbar Qwen fix.
    assert "z-index: 2147483000" in css
    assert "isolation: isolate" in css


def test_content_js_stays_at_or_below_700_lines():
    assert len(_read("content.js").splitlines()) <= 700


def test_scan_report_diagnostic_fields_still_shipped():
    src = _read("content.js")
    for field in (
        "candidate_diagnostics: candidateDiagnostics",
        "mounted_diagnostics: mountedDiagnostics",
        "events_recent: _arenaDiagEvents.slice()",
    ):
        assert field in src


def test_v0_14_10_early_skip_diag_events_preserved():
    """v0.14.10 mountControls-branch diag events must survive the
    reorder in v0.14.12 -- otherwise the next diagnostic pass loses
    all its signal."""
    src = _read("content.js")
    for kind in (
        'skip_dismissed_fp',
        'skip_dismissed_semantic',
        'skip_semantic_already_mounted',
        'skip_existing_connected',
        'skip_host_has_toolbar',
        'mounted',
        'evict_semantic_owner',
    ):
        assert f"kind: '{kind}'" in src, (
            f"v0.14.10 diag event {kind} must survive the v0.14.12 reorder"
        )
