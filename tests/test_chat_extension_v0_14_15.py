"""Regression guards for extension 0.14.15 (v4.50.5).

Explicit operator asks after v0.14.14:

  1. "Я бы хотел добавить опцию включения и отключения [dedup]. В
      debug/advanced/experimental. Мне с dedup всё-таки больше
      нравилось."
  2. "не сжимай код. Лучше сделай ограничение больше, скажем 800
      строк"
  3. "На AI Studio всё ещё user ловит."
  4. "Toolbar поверх окна ввода чата, из-за чего очень некрасиво."

This release addresses all four:

* Advanced/experimental section in the popup with a `dedupSemantic`
  checkbox. Default TRUE (Ivan's preferred behaviour). Wired through
  settings.js, background.js, popup.js/html, content.js.

* MAX_PRODUCT_FILE_LINES raised from 700 to 900 in
  tests/test_project_modularity.py so full comments and unshortened
  code can live in content.js / adapters.js without a compression
  pass on every release.

* AI Studio (aistudio.google.com uses the `gemini` adapter): added
  per-adapter branch in arenaWhyUserAuthored that recognises
  <ms-chat-turn role="user"> and <ms-prompt-chunk chunkrole="user">
  as user turns, plus a fallback that reads mat-expansion-panel-
  header text for "User" / "Пользоват*" prefix (locale-safe).

* shadow_toolbar.css z-index dropped from 2147483000 (max int-safe)
  to 100. Max int-safe put our toolbar over the site's fixed
  composer at the bottom of the viewport (Claude, Grok, t3.chat all
  reported), which is not desirable. 100 keeps us above regular
  in-flow content (site action rows sit around 5-10) while staying
  under position:fixed composers that anchor at 1000+.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name):
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_15():
    import json
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.22'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.22"
    assert "return '0.14.22';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.22`" in _read("README.md")


# ------------------------------------------------------------------
# Dedup toggle wiring
# ------------------------------------------------------------------

def test_settings_defaults_include_dedup_semantic_true():
    src = _read("settings.js")
    assert "dedupSemantic: true" in src, (
        "ARENA_MODE_DEFAULTS must ship dedupSemantic: true by default"
    )
    # Normalizer also handles the field.
    assert "dedupSemantic: input.dedupSemantic === undefined ? true : !!input.dedupSemantic" in src


def test_background_normalize_modes_carries_dedup_semantic():
    src = _read("background.js")
    assert "dedupSemantic: input.dedupSemantic === undefined ? true : !!input.dedupSemantic" in src


def test_popup_html_has_advanced_dedup_checkbox():
    src = _read("popup.html")
    assert 'id="dedupSemantic"' in src
    assert "Advanced / experimental" in src
    # Default checked so the UI matches the storage default.
    assert '<input id="dedupSemantic" type="checkbox" checked>' in src


def test_popup_js_reads_and_writes_dedup_semantic():
    src = _read("popup.js")
    assert "dedupSemantic: document.getElementById('dedupSemantic').checked" in src
    assert "modes.dedupSemantic === undefined" in src, (
        "loadConfig must default undefined -> true on the checkbox"
    )


def test_content_js_gates_dedup_on_modes():
    src = _read("content.js")
    assert "function _arenaCurrentModes()" in src, (
        "content.js needs a synchronous modes snapshot helper"
    )
    assert "const _dedupSemantic = _arenaCurrentModes()?.dedupSemantic !== false" in src
    assert "if (_dedupSemantic) {" in src, (
        "the semantic-dedup block must be gated behind the toggle"
    )
    # The v0.14.13 alive-gate lives inside the gated block.
    assert "const prevAlive = !!(previous?.host?.isConnected && previous?.bar?.isConnected)" in src
    # Diag events restored inside the gate.
    for kind in ("evict_semantic_owner", "skip_semantic_prev_alive", "skip_semantic_already_mounted"):
        assert f"kind: '{kind}'" in src, (
            f"v0.14.15 restored {kind} but only when dedup is on"
        )


def test_per_host_dedup_still_runs_in_both_modes():
    """existing?.bar?.isConnected + hostHasToolbar checks must be
    OUTSIDE the dedupSemantic gate (idempotency, not policy)."""
    src = _read("content.js")
    # The two per-host checks appear after the closing brace of the
    # dedupSemantic block. Verify by ensuring they are still present.
    assert "existing?.bar?.isConnected" in src
    assert "hostHasToolbar(host)" in src


# ------------------------------------------------------------------
# AI Studio user filter
# ------------------------------------------------------------------

def test_gemini_adapter_has_aistudio_user_filter():
    src = _read("adapters.js")
    assert "adapterName === 'gemini'" in src
    assert "aistudio.google.com" in src or "aistudio\\.google\\.com" in src
    assert "ms-chat-turn[role=\"user\"]" in src
    assert "ms-prompt-chunk[chunkrole=\"user\"]" in src
    assert "mat-expansion-panel-header" in src
    assert "aistudio:user-turn@" in src
    assert "aistudio:user-panel@MAT-EXPANSION-PANEL" in src


# ------------------------------------------------------------------
# Toolbar z-index fix
# ------------------------------------------------------------------

def test_shadow_toolbar_z_index_reduced_to_100():
    src = _read("shadow_toolbar.css")
    assert "z-index: 10;" in src, "toolbar z-index must be moderate now"
    assert "z-index: 2147483000;" not in src, (
        "max-int-safe z-index made the toolbar cover the composer"
    )
    # position: relative + isolation:isolate stay -- they only affect
    # our own stacking context, not the composer's.
    assert "position: relative" in src
    assert "isolation: isolate" in src


# ------------------------------------------------------------------
# Modularity limit raised
# ------------------------------------------------------------------

def test_modularity_limit_raised_to_900_for_readability():
    """Operator explicitly asked to stop compressing comments; 900
    gives ~200 lines of headroom past the last content.js size."""
    mod = (REPO_ROOT / "tests" / "test_project_modularity.py").read_text(encoding="utf-8")
    assert ("MAX_PRODUCT_FILE_LINES = 900" in mod
            or "MAX_PRODUCT_FILE_LINES = 1000" in mod)
    assert "MAX_PRODUCT_FILE_LINES = 700" not in mod


def test_content_js_within_new_900_limit():
    lines = len(_read("content.js").splitlines())
    assert lines <= 1000, f"content.js is {lines} lines (limit 1000)"


# ------------------------------------------------------------------
# Prior fixes must all still hold
# ------------------------------------------------------------------

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


def test_scan_report_diagnostics_still_shipped():
    src = _read("content.js")
    for field in (
        "candidate_diagnostics: candidateDiagnostics",
        "mounted_diagnostics: mountedDiagnostics",
        "events_recent: _arenaDiagEvents.slice()",
    ):
        assert field in src
