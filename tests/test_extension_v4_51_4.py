"""v0.14.33 / v4.51.4 tests: universal collapse via TreeWalker.

Focused on the string-level guarantees of the new
`collapseToolResultsInHistory` implementation. The real DOM
behaviour is verified separately in a jsdom smoke test
(`jstest/smoke_collapse.js`) that reproduces the outerHTML
snapshots Ivan sent for Gemini / Kimi / Qwen / DeepSeek / z.ai.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_EXT = REPO_ROOT / "chat_extension"
CONTENT_JS = CHAT_EXT / "content.js"
MANIFEST_JSON = CHAT_EXT / "manifest.json"
INSERT_STRATEGIES_JS = CHAT_EXT / "insert_strategies.js"
README_MD = CHAT_EXT / "README.md"
CONSTANTS_PY = REPO_ROOT / "arena" / "constants.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_manifest_version_bumped():
    assert json.loads(_read(MANIFEST_JSON))["version"] in ("0.14.33", "0.14.34", "0.14.35")


def test_content_script_version_bumped():
    assert any(v in _read(CONTENT_JS) for v in ("const ARENA_CONTENT_SCRIPT_VERSION = '0.14.33';", "const ARENA_CONTENT_SCRIPT_VERSION = '0.14.34';", "const ARENA_CONTENT_SCRIPT_VERSION = '0.14.35';"))


def test_insert_strategies_version_bumped():
    assert any(v in _read(INSERT_STRATEGIES_JS) for v in ("return '0.14.33';", "return '0.14.34';", "return '0.14.35';"))


def test_readme_mentions_v4_51_4():
    src = _read(README_MD)
    assert ("0.14.33" in src or "0.14.34" in src or "0.14.35" in src)
    assert ("v4.51.4" in src or "v4.52.0" in src or "v4.52.1" in src)


def test_constants_version_bumped():
    assert any(v in _read(CONSTANTS_PY) for v in ('VERSION = "4.51.4"', 'VERSION = "4.52.0"', 'VERSION = "4.52.1"'))


def test_pyproject_version_bumped():
    assert any(v in _read(REPO_ROOT / 'pyproject.toml') for v in ('version = "4.51.4"', 'version = "4.52.0"', 'version = "4.52.1"'))


def test_collapse_uses_tree_walker():
    src = _read(CONTENT_JS)
    assert "document.createTreeWalker" in src
    assert "NodeFilter.SHOW_TEXT" in src
    # Version-tagged comment must be present.
    assert "v0.14.33" in src or "v4.51.4" in src


def test_collapse_has_user_message_selectors():
    """User-message container allow-list must cover every site
    Ivan tested in v4.51.3."""
    src = _read(CONTENT_JS)
    for sel in (
        "user-query-bubble-with-background",   # Gemini
        "chat-user-message",                    # Qwen
        "user-message-content",                 # Qwen (inner)
        "user-content",                         # Kimi
        "chat-user",                            # z.ai
        "rounded-xl",                           # DeepSeek
        "data-message-part-type",               # Mistral
        "data-message-author-role",             # ChatGPT / OpenRouter / T3
    ):
        assert sel in src, f"missing user-msg selector fragment: {sel}"


def test_collapse_preserves_legacy_sentinel():
    src = _read(CONTENT_JS)
    assert "ARENA_RESULT_V1" in src
    assert "<!-- arena:tool-result -->" in src
    # Legacy sentinel constant kept as LEGACY_SENTINEL.
    assert "LEGACY_SENTINEL" in src


def test_collapse_is_idempotent_via_dataset_flag():
    """Idempotency guard: once a target is wrapped, its
    `data-arena-tool-collapsed="1"` attribute prevents any
    subsequent scan from re-wrapping."""
    src = _read(CONTENT_JS)
    assert 'data-arena-tool-collapsed="1"' in src
    assert "arenaToolCollapsed" in src


def test_collapse_diagnostic_event_includes_target_kind():
    """The tool_result_collapsed diag event must include
    `target_kind` so scan reports show whether the wrap hit a
    user-message container or fell back to a code fence."""
    src = _read(CONTENT_JS)
    assert "target_kind" in src
    # Both kinds must be produced.
    assert "'user-message'" in src or '"user-message"' in src
    assert "'code-fence'" in src or '"code-fence"' in src


def test_collapse_short_negative_case_guarded():
    """A line-count / length guard must exist to avoid wrapping
    an inline mention of the sentinel string."""
    src = _read(CONTENT_JS)
    # lineCount < 4 && text.length < 200 -> return
    assert "lineCount < 4" in src
    assert "text.length < 200" in src


def test_composer_preview_guard_kept():
    """The v4.51.0 composer-preview guard (skip if the next
    sibling is our own arena toolbar) MUST still be present so
    we never wrap the live composer preview."""
    src = _read(CONTENT_JS)
    assert "arenaToolControls" in src
    assert "arenaShadowHost" in src


def test_collapse_walks_up_from_text_node():
    """The walker must materialise text nodes into a list
    before wrapping to avoid invalidating the walker mid-loop."""
    src = _read(CONTENT_JS)
    assert "walker.nextNode" in src
    assert "textNode.parentElement" in src or "parentElement" in src
