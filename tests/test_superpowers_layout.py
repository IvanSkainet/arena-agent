"""Guardrails for the unified superpowers vendored copy.

See docs/SUPERPOWERS.md for the intent: one directory (skills/superpowers/)
serves both the Arena Bridge and standalone IDE plugin consumers, tracking
upstream obra/superpowers verbatim.

v4.61.1: ``test_superpowers_doc_exists_and_reflects_unified_layout`` now
reads the doc as UTF-8 explicitly. The original ``read_text()`` used
the locale default (cp1251 on Russian Windows CI runners) and crashed
on the unicode box-drawing characters in the doc body.

Live-failed: v4.61.0 CI run id 30034756453 on
``windows-latest`` Python 3.10-3.14.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUPERPOWERS = REPO / "skills" / "superpowers"
SKILLS = SUPERPOWERS / "skills"


def test_superpowers_directory_exists():
    assert SUPERPOWERS.is_dir(), (
        f"skills/superpowers/ missing — required by install.sh, "
        f"stress-test-v3.sh, /v1/skills, and every IDE plugin manifest."
    )


def test_upstream_skills_present():
    """All upstream skills must be under skills/superpowers/skills/."""
    required = {
        "brainstorming",
        "dispatching-parallel-agents",
        "executing-plans",
        "finishing-a-development-branch",
        "receiving-code-review",
        "requesting-code-review",
        "subagent-driven-development",
        "systematic-debugging",
        "test-driven-development",
        "using-git-worktrees",
        "using-superpowers",
        "verification-before-completion",
        "writing-plans",
        "writing-skills",
    }
    have = {p.name for p in SKILLS.iterdir() if p.is_dir()}
    missing = required - have
    assert not missing, f"Upstream skills missing: {missing}"


def test_ide_plugin_manifests_present():
    """IDE plugin manifests must live inside skills/superpowers/."""
    required_files = [
        SUPERPOWERS / ".claude-plugin" / "plugin.json",
        SUPERPOWERS / ".codex-plugin" / "plugin.json",
        SUPERPOWERS / ".cursor-plugin" / "plugin.json",
        SUPERPOWERS / "gemini-extension.json",
        SUPERPOWERS / "package.json",
        SUPERPOWERS / "LICENSE",
    ]
    missing = [f.relative_to(REPO) for f in required_files if not f.is_file()]
    assert not missing, f"Plugin manifests missing: {missing}"


def test_no_arena_fork_directory_leaks_back():
    """Guard against re-introducing the old Arena fork layout."""
    arena_only_skills = ["using-arena-superpowers", "using-feature-branches"]
    for name in arena_only_skills:
        assert not (SKILLS / name).exists(), (
            f"Arena-only fork skill re-appeared: {name}. See docs/SUPERPOWERS.md — "
            f"we no longer maintain an Arena fork inside skills/superpowers/."
        )


def test_no_duplicate_tools_superpowers():
    """tools/superpowers/ must not come back — it was consolidated into skills/."""
    assert not (REPO / "tools" / "superpowers").exists(), (
        "tools/superpowers/ re-appeared. That directory was removed to eliminate "
        "the split with skills/superpowers/. Do not re-vendor upstream twice."
    )


def test_sync_script_exists_and_executable():
    script = REPO / "scripts" / "sync_superpowers_from_upstream.sh"
    assert script.is_file(), "scripts/sync_superpowers_from_upstream.sh missing"
    import os
    assert os.access(script, os.X_OK), "sync script must be executable (chmod +x)"


def test_superpowers_doc_exists_and_reflects_unified_layout():
    doc = REPO / "docs" / "SUPERPOWERS.md"
    assert doc.is_file(), "docs/SUPERPOWERS.md missing"
    # v4.61.1: explicit UTF-8 read. The doc contains box-drawing
    # characters that are not representable in cp1251 (the default
    # on Russian Windows CI runners).
    content = doc.read_text(encoding="utf-8")
    assert "skills/superpowers/" in content
    # Doc must explicitly state the one-directory model.
    assert "one" in content.lower() or "single" in content.lower()
    assert "upstream" in content.lower()
