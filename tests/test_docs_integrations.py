"""Docs-level integration recipe regressions."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INTEGRATIONS = DOCS / "integrations"


def test_integration_index_exists_and_links_core_recipes():
    text = (DOCS / "INTEGRATIONS.md").read_text(encoding="utf-8")
    assert "Arena Agent Mode" in text
    assert "Cursor" in text
    assert "Cline" in text
    assert "Windsurf" in text
    assert "Open Interpreter" in text


def test_integration_recipe_set_exists():
    expected = {
        "ARENA_AGENT_MODE.md",
        "CLAUDE_CHAT_PROMPT.md",
        "CURSOR.md",
        "CLINE.md",
        "WINDSURF.md",
        "OPEN_INTERPRETER.md",
        "LOCAL_MODELS.md",
    }
    found = {p.name for p in INTEGRATIONS.glob("*.md")}
    assert expected.issubset(found)


def test_integration_recipes_mention_memory_profiles():
    targets = [
        INTEGRATIONS / "ARENA_AGENT_MODE.md",
        INTEGRATIONS / "CLAUDE_CHAT_PROMPT.md",
        INTEGRATIONS / "CURSOR.md",
        INTEGRATIONS / "CLINE.md",
        INTEGRATIONS / "WINDSURF.md",
        INTEGRATIONS / "OPEN_INTERPRETER.md",
        INTEGRATIONS / "LOCAL_MODELS.md",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert "Memory Profile" in text or "Memory Profiles" in text or "profile" in text.lower(), path.name
