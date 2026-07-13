"""Guardrails for the two vendored superpowers copies.

See docs/SUPERPOWERS.md for the intent behind having both directories.
These tests protect that layout so refactors do not silently delete one
of them or drift them into pure duplicates.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ARENA_DIR = REPO / "skills" / "superpowers" / "skills"
UPSTREAM_DIR = REPO / "tools" / "superpowers"


def test_both_superpowers_dirs_exist():
    assert ARENA_DIR.is_dir(), (
        f"skills/superpowers/skills/ missing — required by install.sh, "
        f"stress-test-v3.sh, and /v1/skills."
    )
    assert UPSTREAM_DIR.is_dir(), (
        "tools/superpowers/ missing — required by the standalone plugin "
        "(Claude Code / Codex / Cursor / Gemini)."
    )


def test_arena_fork_has_arena_only_skills():
    """The Arena fork must retain the Arena-specific skills."""
    required = {"using-arena-superpowers", "using-feature-branches"}
    have = {p.name for p in ARENA_DIR.iterdir() if p.is_dir()}
    missing = required - have
    assert not missing, f"Arena fork lost Arena-only skills: {missing}"


def test_upstream_copy_has_plugin_manifests():
    """tools/superpowers/ must ship plugin manifests for IDEs."""
    required_files = [
        UPSTREAM_DIR / ".claude-plugin" / "plugin.json",
        UPSTREAM_DIR / "gemini-extension.json",
        UPSTREAM_DIR / "package.json",
        UPSTREAM_DIR / "LICENSE",
    ]
    for f in required_files:
        assert f.is_file(), f"tools/superpowers/ missing plugin manifest: {f.relative_to(REPO)}"


def test_upstream_and_arena_share_core_skills():
    """Sanity: both dirs implement the shared core skill set."""
    shared = {
        "brainstorming",
        "executing-plans",
        "test-driven-development",
        "verification-before-completion",
        "writing-plans",
        "writing-skills",
    }
    arena_skills = {p.name for p in ARENA_DIR.iterdir() if p.is_dir()}
    upstream_skills = {p.name for p in (UPSTREAM_DIR / "skills").iterdir() if p.is_dir()}
    missing_arena = shared - arena_skills
    missing_upstream = shared - upstream_skills
    assert not missing_arena, f"Arena fork missing core skills: {missing_arena}"
    assert not missing_upstream, f"Upstream copy missing core skills: {missing_upstream}"


def test_sync_script_exists_and_executable():
    script = REPO / "scripts" / "sync_superpowers_from_upstream.sh"
    assert script.is_file(), "scripts/sync_superpowers_from_upstream.sh missing"
    import os
    assert os.access(script, os.X_OK), "sync script must be executable (chmod +x)"


def test_superpowers_doc_exists():
    doc = REPO / "docs" / "SUPERPOWERS.md"
    assert doc.is_file(), "docs/SUPERPOWERS.md missing — layout must be documented"
    content = doc.read_text()
    assert "skills/superpowers/skills/" in content
    assert "tools/superpowers/" in content
    assert "Update flow" in content or "update flow" in content.lower()
