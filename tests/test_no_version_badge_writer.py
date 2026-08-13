"""Release metadata must not be maintained by a bot that pushes to master."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"


def _violations() -> list[str]:
    violations: list[str] = []
    if (WORKFLOWS / "version-badge.yml").exists():
        violations.append("version-badge.yml still exists")
    if (REPO / "docs" / "version.json").exists():
        violations.append("docs/version.json still exists")

    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        if "docs/version.json" in text:
            violations.append(f"{path.name} still writes or reads docs/version.json")
        if "chore(badge):" in text:
            violations.append(f"{path.name} still creates badge commits")
    return violations


def test_no_badge_workflow_can_push_release_metadata_to_master() -> None:
    assert _violations() == []


def test_readme_and_release_docs_use_github_latest_release_as_source() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    release = (REPO / "RELEASE.md").read_text(encoding="utf-8")
    assert "shields.io/github/v/release/IvanSkainet/arena-agent" in readme
    assert "releases/latest" in release
    assert "do NOT edit it manually" in release


def test_pre_release_guard_no_longer_depends_on_generated_badge_state() -> None:
    source = (REPO / "scripts" / "pre_release_check.py").read_text(encoding="utf-8")
    assert "docs/version.json" not in source
    assert "_check_version_json" not in source
