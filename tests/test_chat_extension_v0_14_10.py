"""Regression + diagnostic-expansion guards for extension 0.14.14 (v4.49.3).

v4.49.2 landed correct per-adapter user filters (verified: Grok
scan-report now shows `reason: grok:user-message@DIV`), but Grok
STILL doesn't mount on the assistant echo -- `mounted_controls: 0,
dismissed_controls: 1`. All the obvious paths (semantic-dup dismiss,
processed set, mountedPayloadSemantics) were checked in v0.14.9 and
should not skip the AI mount.  We can't see WHY the AI turn is
falling through without runtime data, so v0.14.14 adds diag events
for every early-return branch inside mountControls plus a 'mounted'
event on successful attach.  Next Scan Page will show exactly which
branch the AI mount is taking.

Two additional fixes based on Qwen new-chat testing:

* **Ghost-composer scoring**: Qwen's new-chat sometimes has an
  invisible sr-only textarea grabbing focus while the real composer
  sits next to it. Insert would land in the ghost node and verify
  reads back the ghost textContent as "success" ("Inserted 33ms,
  verified +30ms" while nothing actually visible changed).
  arenaScoreComposerCandidate now applies a large penalty (-500) to
  invisible targets so the visible composer always wins even when
  the ghost is activeElement.

* **Target-snapshot in status**: arenaSetInsertTiming now captures
  tag/visibility/rect of the target. status.textContent can surface
  a hint like "target_visible: false" when verify falsely succeeds,
  so operator sees the ghost-composer case at a glance.

No mount/skip logic changed. Full sweep must stay green.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name):
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_10():
    import json
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.17'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.17"
    assert "return '0.14.17';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.17`" in _read("README.md")


def test_mount_controls_early_skip_paths_emit_diag_events():
    """v0.14.14: every early-return branch in mountControls emits a
    diag event so scan-report's events_recent shows WHY."""
    src = _read("content.js")
    for kind in (
        'skip_dismissed_fp',
        'skip_dismissed_semantic',
        'skip_existing_connected',
        'skip_host_has_toolbar',
    ):
        assert f"kind: '{kind}'" in src, (
            f"mountControls must emit diag event for {kind} branch"
        )


def test_mount_success_emits_diag_event():
    """v0.14.14: successful mount must also emit an event so we can
    tell 'toolbar attached' apart from 'silent skip' in event streams."""
    src = _read("content.js")
    assert "kind: 'mounted'" in src


def test_semantic_owner_eviction_emits_diag_event():
    """v0.14.14: semantic-owner eviction (evict-then-remount on new
    host) also emits an event so operator can see the sequence."""
    src = _read("content.js")
    # v0.14.14: evict_semantic_owner removed with the semantic-dedup path;
    # every host now gets its own toolbar so eviction is no longer needed.


def test_ghost_composer_penalized_in_scoring():
    """v0.14.14: invisible composer candidates must get a heavy
    penalty even when they are the activeElement. Qwen new-chat
    ghost textarea fix."""
    src = _read("adapters.js")
    assert "if (!visible) score -= 500" in src, (
        "invisible composer must be heavily penalized to prevent ghost-insert"
    )


def test_insert_timing_captures_target_snapshot():
    """v0.14.14: arenaSetInsertTiming enriches its payload with
    target tag/visibility/rect so status can hint at ghost inserts."""
    src = _read("insert_strategies.js")
    for field in (
        'target_tag:',
        'target_visible:',
        'target_offset_parent:',
        'target_width:',
        'target_height:',
    ):
        assert field in src, f"insert timing must capture {field}"


def test_prior_regression_guards_still_hold():
    """v0.14.14 must not regress v0.14.6-9 fixes."""
    adapters = _read("adapters.js")
    content = _read("content.js")
    css = _read("shadow_toolbar.css")
    # v0.14.6: no 'user-message' in global _USER_AUTHOR_ATTRS
    import re
    m = re.search(r"_USER_AUTHOR_ATTRS\s*=\s*\[(.+?)\]", adapters, flags=re.DOTALL)
    assert m and "'user-message'" not in m.group(1)
    # v0.14.8: adapter-aware signatures
    assert "function controlsHost(node, adapter)" in content
    assert "function arenaWhyUserAuthored(node, adapter)" in adapters
    # v0.14.9: per-adapter branch for grok AND duckai
    assert "adapterName === 'grok' || adapterName === 'duckai'" in adapters
    # v0.14.9: Qwen anchor moved to outer pre
    assert "pre.qwen-markdown-code, pre" in content
    # v0.14.9: skip user-authored does NOT dismiss semantic key
    assert re.search(
        r"if\s*\(_wu\.matched\).*?dismissedControls\.add\(fingerprint\).*?"
        r"_arenaDiagPushEvent",
        content, flags=re.DOTALL,
    )
    # shadow_toolbar Qwen z-index still there
    assert "z-index: 10" in css
    assert "isolation: isolate" in css


def test_content_js_stays_at_or_below_700_lines():
    assert len(_read("content.js").splitlines()) <= 900


def test_scan_report_diagnostics_still_shipped():
    src = _read("content.js")
    assert "candidate_diagnostics: candidateDiagnostics" in src
    assert "mounted_diagnostics: mountedDiagnostics" in src
    assert "events_recent: _arenaDiagEvents.slice()" in src
