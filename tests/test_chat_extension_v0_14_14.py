"""Regression guards for extension 0.14.14 (v4.50.4).

Operator explicit request after v0.14.13:

  "Сделай так, чтобы на всех вызовах отображались tool bar, потому
   что на всех сайтах не уследишь, как они монтируются, и приводит
   это, например, на Claude к тому, что на первом сообщении в чате
   отображается tool bar, а на следующий с аналогичной командой
   sys status не отображается, то есть оно, похоже, снизу вверх
   загружается."

Fix: strip the semantic-dedup path entirely. Every candidate host
that carries a parsed tool block now gets its own toolbar. The
per-host dedup that remains (existing?.bar?.isConnected +
hostHasToolbar(host)) prevents double-mounts on the SAME host but
never touches sibling / duplicate hosts.

Observations that motivated this:

* Claude scan report: 4 candidates with distinct fingerprints
  (call_id 1..4), only 2 got toolbars because semantic dedup
  killed the ones that shared a payload shape with an earlier
  siblig. Operator wanted all 4 to show up.
* AI Studio: v0.14.13 with the alive-gate ended up mounting only
  the User's copy (Thought Process panel rendered first). Operator
  wanted BOTH copies to have a toolbar so they can pick whichever
  is visible.
* T3 chat: sibling dup that IS in fact the same real message got
  correctly filtered by v0.14.13's t3chat user-prose filter, so
  the per-adapter filter still does the right thing there.

Cost: on sites where the same jsonl really IS a genuine duplicate
(some SPAs render both a preview and a full copy), the operator
now sees two toolbars for that message. They can click either;
Run on both will just execute the same tool twice which is
harmless for read-only tools and consent-gated for anything
risky. If a specific site wants back the dedup, we do it per-
adapter.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name):
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_14():
    import json
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.28'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.28"
    assert "return '0.14.28';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.28`" in _read("README.md")


def test_semantic_dedup_gated_behind_toggle_in_v14_15():
    """v0.14.14 stripped semantic dedup entirely. v0.14.15 restored
    it behind a runtime toggle (modes.dedupSemantic, default TRUE).
    So the diag kinds are back in the code -- but only fire when
    _dedupSemantic is true. Test the gate instead of absence."""
    src = _read("content.js")
    assert "if (_dedupSemantic) {" in src
    for kind in (
        "skip_semantic_prev_alive",
        "evict_semantic_owner",
        "skip_semantic_already_mounted",
    ):
        assert f"kind: '{kind}'" in src, (
            f"{kind} must live inside the _dedupSemantic gate in v0.14.15"
        )


def test_per_host_dedup_still_works():
    """The per-host dedup MUST still prevent a double-mount on the
    same host (otherwise scan loops would stack toolbars on top of
    each other). Two short-circuits kept: existing.bar.isConnected
    (same fingerprint already mounted) and hostHasToolbar(host)
    (dataset marker present in the DOM)."""
    src = _read("content.js")
    assert "existing?.bar?.isConnected" in src
    assert "hostHasToolbar(host)" in src
    # The mount_entry + dismissed-fp path stays intact.
    assert "kind: 'mount_entry'" in src
    assert "kind: 'skip_dismissed_fp'" in src


def test_per_adapter_user_filters_still_active():
    """v0.14.9 (grok/duckai) and v0.14.13 (t3chat) filters MUST
    still fire -- v0.14.14 only touched the semantic-dedup path."""
    src = _read("adapters.js")
    assert "adapterName === 'grok' || adapterName === 'duckai'" in src
    assert "adapterName === 't3chat'" in src
    assert "getAttribute('role') !== 'article'" in src


def test_prior_regression_guards_still_hold():
    """v0.14.6-13 fixes must all survive the dedup removal."""
    adapters = _read("adapters.js")
    content = _read("content.js")
    css = _read("shadow_toolbar.css")

    import re
    m = re.search(r"_USER_AUTHOR_ATTRS\s*=\s*\[(.+?)\]", adapters, flags=re.DOTALL)
    assert m and "'user-message'" not in m.group(1)

    assert "function controlsHost(node, adapter)" in content
    assert "function arenaWhyUserAuthored(node, adapter)" in adapters
    assert "pre.qwen-markdown-code, pre" in content

    match = re.search(
        r"if\s*\(_wu\.matched\).*?dismissedControls\.add\(fingerprint\).*?_arenaDiagPushEvent",
        content, flags=re.DOTALL,
    )
    assert match and "dismissedControls.add(semanticFingerprint)" not in match.group(0)

    assert "if (!visible) score -= 500" in adapters
    assert "_cachedVisible" in adapters
    assert "let bubbleId = ''" in adapters
    strat = _read("insert_strategies.js")
    assert "const deadline = Date.now() + 800;" in strat
    assert "z-index: 10" in css
    assert "isolation: isolate" in css


def test_content_js_stays_at_or_below_700_lines():
    assert len(_read("content.js").splitlines()) <= 1300


def test_scan_report_diagnostics_still_shipped():
    src = _read("content.js")
    for field in (
        "candidate_diagnostics: candidateDiagnostics",
        "mounted_diagnostics: mountedDiagnostics",
        "events_recent: _arenaDiagEvents.slice()",
    ):
        assert field in src
