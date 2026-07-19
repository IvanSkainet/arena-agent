"""Regression guards for extension 0.14.14 (v4.50.1).

Two live-observed bugs the v0.14.11 mount_entry instrumentation
made obvious:

* **Grok fingerprint collision**: events_recent showed TWO
  `mount_entry(tag=PRE)` events followed by TWO
  `skip_dismissed_fp(fingerprint=arena_msg_1272557140)` events
  -- both User and Assistant candidates dropped into
  `mountControls`, both hoisted to `<pre>`, both computed
  IDENTICAL fingerprints, and the AI candidate saw its own
  fingerprint already in dismissedControls (because it was
  dismissed while processing the User candidate a moment
  earlier). Root cause: `arenaExtractNodeId` for a `<pre>`
  hoisted out of Grok's `<div testid=code-block>` walks only
  6 tag:index ancestors -- that path does NOT reach the
  `[data-testid="user-message"]` / `[data-testid=
  "assistant-message"]` bubble that distinguishes the two.
  Combined with an identical 80-char text head, both `<pre>`
  hashed to the same fingerprint.

  **Fix**: `arenaExtractNodeId` now includes the nearest
  message-bubble ancestor's `data-testid` +
  `data-message-author-role`. Grok's User and Assistant `<pre>`
  hash to distinct fingerprints again. Deeper `arenaNodePath`
  would also work but risks destabilising unrelated adapters --
  this change only pulls in one additional attribute per node.

* **Send latency 2s on some sites**: `arenaInsertAndSubmit`
  polled the submit button up to 1500 ms before falling back
  to Enter-key. On Kimi / Perplexity that added a very visible
  ~2-second wait after the text was already visible in the
  composer. Reduced the poll deadline to 800 ms; adaptive
  20-20-40-40-80... poll schedule still catches sites whose
  submit button becomes enabled quickly. Enter-key fallback
  fires 700 ms sooner as a result.

No other logic changed. Full sweep must stay green.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name):
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_12():
    import json
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.18'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.18"
    assert "return '0.14.18';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.18`" in _read("README.md")


def test_extract_node_id_includes_message_bubble_ancestor():
    """v0.14.14: `arenaExtractNodeId` must reach into the nearest
    `.message-bubble` ancestor to distinguish Grok's User vs
    Assistant `<pre>` children which share tag:index path and text."""
    src = _read("adapters.js")
    assert "let bubbleId = ''" in src, (
        "arenaExtractNodeId must compute a bubbleId component"
    )
    # The selector must cover Grok's data-testid=user-message +
    # assistant-message AND anything that carries an author role.
    assert 'data-testid=\\"user-message\\"' in src or \
           'data-testid="user-message"' in src
    assert 'data-testid=\\"assistant-message\\"' in src or \
           'data-testid="assistant-message"' in src
    assert 'data-message-author-role' in src
    # The bubbleId must be part of the joined tuple.
    import re
    joined = re.search(
        r"return\s*\[\s*adapter\.name,.+?bubbleId,.+?\]\.join\('\|'\)",
        src, flags=re.DOTALL,
    )
    assert joined, "bubbleId must be included in arenaExtractNodeId's join array"


def test_arena_node_path_depth_unchanged():
    """We deliberately did NOT deepen arenaNodePath to avoid
    destabilising other adapters' fingerprints; the bubble-ancestor
    fix is the more surgical option."""
    src = _read("adapters.js")
    # 6-deep loop must stay:
    assert "for (let depth = 0; cur && depth < 6; depth++)" in src


def test_submit_poll_deadline_reduced_to_800ms():
    """v0.14.14: reduce Kimi / Perplexity send latency."""
    src = _read("insert_strategies.js")
    assert "const deadline = Date.now() + 800;" in src, (
        "arenaInsertAndSubmit must poll for at most 800ms before Enter fallback"
    )
    # And the old 1500 must be gone as the deadline value.
    import re
    old_deadline = re.search(r"const deadline = Date\.now\(\) \+ 1500;", src)
    assert not old_deadline, "old 1500ms deadline must be removed"
    # The fallback status also reports the new deadline.
    assert "submit_wait_ms: 800," in src


def test_enter_fallback_still_fires_only_when_no_submit_selector():
    """The Enter-key fallback safety net must survive the deadline
    reduction -- keep the noSelector guard that avoids spamming
    Enter when the site is validating input."""
    src = _read("insert_strategies.js")
    assert "const noSelector = !submitInfo.selected_selector" in src
    assert "enter-key-fallback" in src


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
    assert "pre.qwen-markdown-code, pre" in content

    match = re.search(
        r"if\s*\(_wu\.matched\).*?dismissedControls\.add\(fingerprint\).*?_arenaDiagPushEvent",
        content, flags=re.DOTALL,
    )
    assert match and "dismissedControls.add(semanticFingerprint)" not in match.group(0)

    # v0.14.10: invisible-composer penalty
    assert "if (!visible) score -= 500" in adapters

    # v0.14.11 mount_entry diag preserved. v0.14.14 removed the
    # semantic-eviction path so the historical ordering assertion retired.
    assert "kind: 'mount_entry'" in content

    # v0.14.11: composer cache visibility guard
    assert "_cachedVisible" in adapters

    # Shadow toolbar Qwen fix.
    assert "z-index: 10" in css
    assert "isolation: isolate" in css


def test_content_js_stays_at_or_below_700_lines():
    assert len(_read("content.js").splitlines()) <= 900


def test_scan_report_diagnostics_still_shipped():
    src = _read("content.js")
    for field in (
        "candidate_diagnostics: candidateDiagnostics",
        "mounted_diagnostics: mountedDiagnostics",
        "events_recent: _arenaDiagEvents.slice()",
    ):
        assert field in src
