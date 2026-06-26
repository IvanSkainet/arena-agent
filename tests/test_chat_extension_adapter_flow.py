"""Chat extension adapter flow regressions."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_chat_extension_adapter_helpers_exist():
    adapters = (ROOT / "chat_extension" / "adapters.js").read_text(encoding="utf-8")
    content = (ROOT / "chat_extension" / "content.js").read_text(encoding="utf-8")
    assert 'arenaHasArenaToolBlock' in adapters
    assert 'arenaIsAssistantNode' in adapters
    assert 'arenaMessageFingerprint' in adapters
    assert 'chatgpt.com' in adapters
    assert 'arenaInsertAndSubmit' in adapters
    assert 'scheduleScan' in content
    assert 'data-arena-tool-controls' in content
    assert 'MutationObserver' in content


def test_chat_extension_readme_tracks_scaffold_version_and_features():
    readme = (ROOT / "chat_extension" / "README.md").read_text(encoding="utf-8")
    assert 'Current scaffold extension version: `0.6.0`.' in readme
    assert 'Insert & Submit' in readme
    assert 'side panel UI' in readme
