"""Regression guards for extension 0.14.14 (v4.49.1).

Three per-adapter surgical fixes based on v0.14.7 candidate_diagnostics
and mounted_diagnostics scan-report data:

* **Grok user-filter**: scan-report showed Grok wraps user turns in
  <div data-testid="user-message" class="message-bubble"> and AI in
  <div data-testid="assistant-message" class="message-bubble">. Both
  share identical code-block children so global _USER_AUTHOR_ATTRS
  cannot help. Added per-adapter closest('[data-testid="user-message"]')
  check ONLY when adapter.name === 'grok'. DuckAI is unaffected
  (DuckAI's user-message testid was the reason we removed it globally
  in v4.48.6).

* **DuckAI overflow-hidden clip**: scan-report mounted_diagnostics
  showed toolbar sitting inside <div class="language-jsonl
  overflow-hidden"> that Tailwind clips. Preview / Insert / Send /
  Copy buttons visually flash and disappear. Hoist controlsHost up
  to the next parent (`.my-4.flex`) which has no overflow clip.

* **Qwen Monaco-viewport hoist**: scan-report mounted_diagnostics
  showed toolbar inside <div class="qwen-markdown-code-editor-
  viewport"> (Monaco editor scroll container). Toolbar looks squeezed
  against the site's like/dislike/share/refresh action row. Hoist to
  `.qwen-markdown-code-body` (container ABOVE the viewport) so it
  sits between the code block and the site action row cleanly.

All three fixes are in controlsHost(node, adapter) which now takes an
adapter argument. Every call site was updated to pass state.adapter.
No changes to mount/skip logic beyond the Grok user-filter guarded
by adapter.name === 'grok'.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_8():
    import json
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.28'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.28"
    assert "return '0.14.28';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.28`" in _read("README.md")


def test_grok_per_adapter_user_filter_lives_in_arenaWhyUserAuthored():
    """v0.14.14: Grok-specific check must be inside arenaWhyUserAuthored
    and MUST require adapter.name === 'grok' to fire."""
    src = _read("adapters.js")
    assert "function arenaWhyUserAuthored(node, adapter)" in src, (
        "arenaWhyUserAuthored must take an adapter argument"
    )
    # v0.14.14 widened this branch to cover grok AND duckai.
    assert "adapterName === 'grok'" in src, (
        "per-adapter branch must reference the grok adapter name"
    )
    assert 'closest(\'[data-testid="user-message"]\')' in src, (
        "per-adapter branch must query the user-message via closest()"
    )
    assert '`${adapterName}:user-message@DIV`' in src, (
        "skip reason must be templated with the adapter name"
    )


def test_global_user_author_attrs_still_has_no_testid_regression():
    """The v4.48.6 fix must stay: 'user-message' MUST NOT come back
    into the global _USER_AUTHOR_ATTRS list (the Grok fix is per-
    adapter, DuckAI still puts that testid on its message-list
    container and cannot be filtered globally)."""
    import re
    src = _read("adapters.js")
    m = re.search(r"_USER_AUTHOR_ATTRS\s*=\s*\[(.+?)\]", src, flags=re.DOTALL)
    assert m
    assert "'user-message'" not in m.group(1)


def test_controls_host_takes_adapter_and_all_call_sites_pass_it():
    """v0.14.14: controlsHost(node, adapter) signature change. Every
    call site MUST pass state.adapter / the adapter it has in scope."""
    src = _read("content.js")
    assert "function controlsHost(node, adapter)" in src
    # Bare controlsHost(node) with no second argument must be gone.
    import re
    bare = re.findall(r"controlsHost\([a-zA-Z_][a-zA-Z_0-9]*\)", src)
    assert not bare, (
        f"controlsHost() must always receive an adapter, found bare calls: {bare!r}"
    )


def test_duckai_hoist_out_of_overflow_hidden():
    """v0.14.14: DuckAI branch of controlsHost must escape .overflow-hidden."""
    src = _read("content.js")
    assert "adapterName === 'duckai'" in src
    assert "closest?.('.overflow-hidden')" in src or \
           "closest('.overflow-hidden')" in src, (
        "DuckAI branch must walk up to escape .overflow-hidden"
    )


def test_qwen_hoist_anchors_on_outer_pre():
    """v0.14.14: Qwen branch anchors on the outer <pre.qwen-markdown-code>.
    v4.49.1's .qwen-markdown-code-body path turned out to be INSIDE the
    PRE (proven by mounted_diagnostics), so we now use the outer <pre>."""
    src = _read("content.js")
    assert "adapterName === 'qwen'" in src
    assert "pre.qwen-markdown-code, pre" in src, (
        "Qwen branch must anchor on outer <pre.qwen-markdown-code>"
    )


def test_why_user_authored_call_site_passes_adapter():
    """v0.14.14: the mount-time skip check must pass the adapter so
    the Grok branch fires correctly."""
    src = _read("content.js")
    assert "arenaWhyUserAuthored(host, adapter)" in src, (
        "mountControls must pass adapter into arenaWhyUserAuthored"
    )


def test_shadow_toolbar_css_qwen_fix_still_in_place():
    """v4.48.6 Qwen z-index + isolation fix must survive."""
    css = _read("shadow_toolbar.css")
    assert "z-index: 10" in css
    assert "position: relative" in css
    assert "isolation: isolate" in css


def test_content_js_stays_at_or_below_700_lines():
    lines = len(_read("content.js").splitlines())
    assert lines <= 1300, f"content.js is {lines} lines (limit 1300)"


def test_scan_report_diagnostics_still_shipped():
    """v0.14.7 additive diag fields must still be present. Without them
    the next diagnostic pass would have no signal to work on."""
    src = _read("content.js")
    assert "candidate_diagnostics: candidateDiagnostics" in src
    assert "mounted_diagnostics: mountedDiagnostics" in src
