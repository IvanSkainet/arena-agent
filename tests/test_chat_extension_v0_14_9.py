"""Regression guards for extension 0.14.14 (v4.49.2).

Three surgical corrections to the three v4.49.1 fixes based on the
operator's third round of scan-report data:

* **Grok skip-cascade fix**: v4.49.1 correctly filtered the User
  bubble, but ALSO added the payload's semanticFingerprint to
  dismissedControls -- and the AI echo of the same jsonl carries
  an identical semanticFingerprint, so the assistant bubble was
  silently rejected too. Scan report showed `dismissed_controls: 2`
  and `mounted_controls: 0`. Fix: dismiss ONLY the message
  fingerprint, not the semantic one.

* **DuckAI per-adapter user-message filter**: v4.49.1 hoisted
  DuckAI's toolbar out of `.overflow-hidden` correctly, but the
  toolbar was still landing on the User bubble (DuckAI tags user
  turns with `data-testid="user-message"` on the ACTUAL turn
  element -- our v4.48.6 interpretation was based on an older DOM
  shape). Adding DuckAI to the same per-adapter branch we added
  for Grok in v4.49.1. Reason strings become
  `grok:user-message@DIV` and `duckai:user-message@DIV`.

* **Qwen wrong anchor**: v4.49.1 hoisted to
  `.qwen-markdown-code-body` thinking it was OUTSIDE the code
  block. Scan report proved it is INSIDE the PRE
  (path was `PRE:0/.../qwen-markdown-code-body/DIV:1/DIV:1`), so
  the toolbar ended up nested deeper in the code block --
  overlapping everything. Fix: anchor on the outer
  `pre.qwen-markdown-code` so `attachControls`' `afterend`
  insertion drops the toolbar OUTSIDE the code block.

No other logic touched. Full sweep must stay green.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_9():
    import json
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.20'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.20"
    assert "return '0.14.20';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.20`" in _read("README.md")


def test_skip_user_authored_does_not_dismiss_semantic_fingerprint():
    """v0.14.14: skip_user_authored MUST dismiss only the message
    fingerprint. Adding semanticFingerprint would kill the AI echo
    of the same tool block (Grok/DuckAI both re-emit)."""
    src = _read("content.js")
    # There MUST NOT be a "dismissedControls.add(fingerprint); dismissedControls.add(semanticFingerprint);"
    # sequence in the skip_user_authored branch anymore.
    import re
    match = re.search(
        r"if\s*\(_wu\.matched\).*?dismissedControls\.add\(fingerprint\).*?_arenaDiagPushEvent",
        src, flags=re.DOTALL,
    )
    assert match, "skip_user_authored branch must still exist"
    block = match.group(0)
    assert "dismissedControls.add(semanticFingerprint)" not in block, (
        "semanticFingerprint must NOT be dismissed on skip_user_authored "
        "(kills AI echo of the same block)"
    )
    assert "dismissedControls.add(fingerprint)" in block


def test_duckai_gets_per_adapter_user_message_filter():
    """v0.14.14: DuckAI joins Grok in the per-adapter user-message check."""
    src = _read("adapters.js")
    assert "adapterName === 'grok' || adapterName === 'duckai'" in src, (
        "DuckAI must share the per-adapter user-message branch with Grok"
    )
    assert '`${adapterName}:user-message@DIV`' in src, (
        "skip reason must be templated with adapter name"
    )


def test_qwen_hoist_anchors_on_outer_pre_not_body():
    """v0.14.14: Qwen anchor is now the outer <pre.qwen-markdown-code>.
    The old .qwen-markdown-code-body path was INSIDE the PRE and
    made the toolbar nest deeper, overlapping everything (regression
    from v4.49.1)."""
    src = _read("content.js")
    # The old buggy anchor selector must be gone from the Qwen branch.
    assert "closest('.qwen-markdown-code-editor-viewport')" not in src, (
        "v4.49.1 anchor via .qwen-markdown-code-editor-viewport must be removed"
    )
    # And the new outer-<pre> anchor must be in place.
    assert "pre.qwen-markdown-code, pre" in src, (
        "Qwen branch must anchor on outer <pre.qwen-markdown-code>"
    )
    # And still gated per-adapter.
    assert "adapterName === 'qwen'" in src


def test_grok_per_adapter_branch_still_present():
    """v4.49.1 Grok fix must survive (widened to include DuckAI, but
    the Grok path must not regress out)."""
    src = _read("adapters.js")
    assert 'closest(\'[data-testid="user-message"]\')' in src, (
        "the per-adapter closest('[data-testid=user-message]') selector must live in adapters.js"
    )


def test_global_user_author_attrs_stays_free_of_testid_regression():
    """The v4.48.6 fix (no global testid user-message rule) is still
    correct because that rule was too broad -- per-adapter is safer."""
    import re
    src = _read("adapters.js")
    m = re.search(r"_USER_AUTHOR_ATTRS\s*=\s*\[(.+?)\]", src, flags=re.DOTALL)
    assert m
    assert "'user-message'" not in m.group(1)


def test_controls_host_signature_still_has_adapter_argument():
    src = _read("content.js")
    assert "function controlsHost(node, adapter)" in src
    import re
    bare = re.findall(r"controlsHost\([a-zA-Z_][a-zA-Z_0-9]*\)", src)
    assert not bare, f"bare controlsHost() calls resurfaced: {bare!r}"


def test_duckai_overflow_hidden_hoist_still_present():
    """v4.49.1 DuckAI hoist fix must survive."""
    src = _read("content.js")
    assert "adapterName === 'duckai'" in src
    assert ".overflow-hidden" in src


def test_shadow_toolbar_css_still_has_qwen_stacking_isolation():
    css = _read("shadow_toolbar.css")
    assert "z-index: 10" in css
    assert "isolation: isolate" in css


def test_content_js_stays_at_or_below_700_lines():
    lines = len(_read("content.js").splitlines())
    assert lines <= 1000, f"content.js is {lines} lines (limit 1000)"


def test_scan_report_diagnostics_v0_14_7_still_ship():
    src = _read("content.js")
    assert "candidate_diagnostics: candidateDiagnostics" in src
    assert "mounted_diagnostics: mountedDiagnostics" in src
