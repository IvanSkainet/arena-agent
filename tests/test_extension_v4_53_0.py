"""v0.14.42 / v4.53.0 tests: MCP-SA-style pretty preview + inline result.

Full DOM behaviour verified in jstest/smoke_v530.js.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_EXT = REPO_ROOT / "chat_extension"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_manifest_version_bumped():
    assert json.loads(_read(CHAT_EXT / "manifest.json"))["version"] in ("0.14.42",)


def test_content_script_version_bumped():
    assert "const ARENA_CONTENT_SCRIPT_VERSION = '0.14.42';" in _read(CHAT_EXT / "content.js")


def test_insert_strategies_version_bumped():
    assert "return '0.14.42';" in _read(CHAT_EXT / "insert_strategies.js")


def test_readme_mentions_v4_53_0():
    src = _read(CHAT_EXT / "README.md")
    assert "0.14.42" in src
    assert ("v4.53.0" in src or "v4.53.1" in src)


def test_constants_version_bumped():
    assert any(v in _read(REPO_ROOT / 'arena' / 'constants.py') for v in ('VERSION = "4.53.0"', 'VERSION = "4.53.1"', 'VERSION = "4.54.0"', 'VERSION = "4.54.1"', 'VERSION = "4.55.0"', 'VERSION = "4.55.1"', 'VERSION = "4.56.0"', 'VERSION = "4.57.0"', 'VERSION = "4.58.0"', 'VERSION = "4.59.0"'))


def test_pyproject_version_bumped():
    assert any(v in _read(REPO_ROOT / 'pyproject.toml') for v in ('version = "4.53.0"', 'version = "4.53.1"', 'version = "4.54.0"', 'version = "4.54.1"', 'version = "4.55.0"', 'version = "4.55.1"', 'version = "4.56.0"', 'version = "4.57.0"', 'version = "4.58.0"', 'version = "4.59.0"', 'version = "4.58.0"', 'version = "4.59.0"'))


# ------------------------------------------------------------------
# shadow_toolbar.js: new helpers
# ------------------------------------------------------------------

def test_shadow_toolbar_exports_preview_helper():
    src = _read(CHAT_EXT / "shadow_toolbar.js")
    assert "function arenaShadowToolbarPreview" in src
    assert "window.arenaShadowToolbarPreview" in src


def test_shadow_toolbar_exports_result_helper():
    src = _read(CHAT_EXT / "shadow_toolbar.js")
    assert "function arenaShadowToolbarResult" in src
    assert "window.arenaShadowToolbarResult" in src


def test_preview_helper_is_idempotent():
    """Second call must REPLACE the previous preview, not stack."""
    src = _read(CHAT_EXT / "shadow_toolbar.js")
    # The `.arena-preview` selector query + remove-before-insert
    # pattern is the idempotency guard.
    assert "shadowRoot.querySelector('.arena-preview')" in src
    assert "preview.remove()" in src


def test_result_helper_is_idempotent():
    src = _read(CHAT_EXT / "shadow_toolbar.js")
    assert "shadowRoot.querySelector('.arena-result')" in src


def test_preview_renders_risk_topic_name_params():
    src = _read(CHAT_EXT / "shadow_toolbar.js")
    for kw in ("arena-preview-risk", "arena-preview-name",
               "arena-preview-id", "arena-preview-params",
               "arena-preview-card"):
        assert kw in src, f"missing preview element class: {kw}"


def test_preview_attributes_credit_mcp_superassistant():
    """MCP SuperAssistant is MIT-licensed — attribution must
    stay in the source so the port is traceable."""
    src = _read(CHAT_EXT / "shadow_toolbar.js")
    assert "MCP SuperAssistant" in src
    assert "functionBlock.ts" in src


def test_preview_truncates_long_param_values():
    """Long arg values must be truncated to keep the preview
    from dominating the chat message. 320-char cap."""
    src = _read(CHAT_EXT / "shadow_toolbar.js")
    assert "repr.length > 320" in src
    assert ".slice(0, 317) + '\u2026'" in src or "slice(0, 317)" in src


# ------------------------------------------------------------------
# shadow_toolbar.css: new sections
# ------------------------------------------------------------------

def test_shadow_toolbar_css_has_preview_section():
    css = _read(CHAT_EXT / "shadow_toolbar.css")
    for sel in (".arena-preview", ".arena-preview-card",
                ".arena-preview-header", ".arena-preview-risk",
                ".arena-preview-name", ".arena-preview-params",
                ".arena-preview-risk--safe",
                ".arena-preview-risk--medium",
                ".arena-preview-risk--dangerous"):
        assert sel in css, f"missing CSS selector: {sel}"


def test_shadow_toolbar_css_has_result_section():
    css = _read(CHAT_EXT / "shadow_toolbar.css")
    assert ".arena-result " in css or ".arena-result{" in css or ".arena-result\n" in css
    assert ".arena-result-body" in css


# ------------------------------------------------------------------
# content.js: wiring
# ------------------------------------------------------------------

def test_content_has_risk_lookup_cache():
    src = _read(CHAT_EXT / "content.js")
    assert "_arenaRiskCachePromise" in src
    assert "_arenaRiskLookup" in src
    assert "arena.policies" in src


def test_content_annotates_calls_with_risk():
    src = _read(CHAT_EXT / "content.js")
    assert "_arenaAnnotateCallsForPreview" in src


def test_content_captures_shadowRoot_from_helper():
    """content.js must destructure shadowRoot from
    arenaCreateShadowToolbar (previously threw away)."""
    src = _read(CHAT_EXT / "content.js")
    assert "shadowRoot = parts.shadowRoot" in src


def test_content_renders_preview_on_mount():
    src = _read(CHAT_EXT / "content.js")
    assert "arenaShadowToolbarPreview(shadowRoot" in src


def test_content_mirrors_result_on_run():
    src = _read(CHAT_EXT / "content.js")
    # Both the manual Run path and the auto-execute path must
    # push the result into the inline panel.
    manual = "arenaShadowToolbarResult(shadowRoot, {text: lastExecutionText"
    auto   = "arenaShadowToolbarResult(shadowRoot, {text}"
    assert manual in src, "manual Run path missing result mirror"
    assert auto   in src, "auto-execute path missing result mirror"


def test_content_re_renders_result_on_remount():
    """If a semantic re-mount happens and we already have a
    cached execution result, the panel should paint straight
    away (no need to Run again)."""
    src = _read(CHAT_EXT / "content.js")
    assert "if (shadowRoot && lastExecutionText && typeof arenaShadowToolbarResult" in src
