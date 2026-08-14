"""Tests for scripts/pre_release_check.py — the release-readiness guard."""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _candidate_root() -> Path:
    _here = Path(__file__).resolve().parent
    for c in (_here, _here.parent):
        if (c / "scripts" / "pre_release_check.py").exists():
            return c
    return _here.parent


REPO = _candidate_root()
SCRIPT = REPO / "scripts" / "pre_release_check.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True,
    )


def _write_minimal_release(tmp_path: Path, version: str) -> None:
    (tmp_path / "arena").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "arena" / "constants.py").write_text(
        f'VERSION = "{version}"\n', encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "{version}"\n', encoding="utf-8",
    )
    (tmp_path / "tests" / "_version_matrix.py").write_text(
        f'BRIDGE_VERSIONS: tuple[str, ...] = ("{version}",)\nLATEST_BRIDGE: str = BRIDGE_VERSIONS[-1]\n',
        encoding="utf-8",
    )
    # CHANGELOG with top entry matching the version
    (tmp_path / "CHANGELOG.md").write_text(
        f"## v{version} - test\n\nBody.\n", encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.ru.md").write_text(
        f"## v{version} - test\n\nBody.\n", encoding="utf-8",
    )


def test_script_exists() -> None:
    assert SCRIPT.exists()


def test_script_parses() -> None:
    ast.parse(SCRIPT.read_text())


def test_fresh_repo_with_version_no_git_passes(tmp_path: Path) -> None:
    """A synchronized candidate with current changelogs passes without git."""
    _write_minimal_release(tmp_path, "4.65.0")
    r = _run(["--repo-root", str(tmp_path)], tmp_path)
    # The git check returns True (skipped, not failed) for non-git dirs.
    # All other checks pass. So overall returncode is 0.
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK: ready to tag and release" in r.stdout


def test_changelog_top_entry_doesnt_match(tmp_path: Path) -> None:
    """If the top CHANGELOG entry is for a different version, the guard
    must fail — this is the exact bug the v4.63.0 / v4.64.0 / v4.65.0
    follow-up chain kept catching."""
    _write_minimal_release(tmp_path, "4.65.0")
    (tmp_path / "CHANGELOG.md").write_text(
        "## v4.64.0 - old top entry\n\nStale.\n", encoding="utf-8",
    )
    r = _run(["--repo-root", str(tmp_path)], tmp_path)
    assert r.returncode == 1
    assert "FAIL" in r.stdout


def test_version_drift_fails(tmp_path: Path) -> None:
    _write_minimal_release(tmp_path, "4.65.0")
    # Bump pyproject.toml to a different version
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "4.66.0"\n', encoding="utf-8",
    )
    r = _run(["--repo-root", str(tmp_path)], tmp_path)
    assert r.returncode == 1
    assert "drift" in r.stdout


def test_annotated_release_tag_is_peeled_to_its_commit(tmp_path: Path) -> None:
    """An annotated tag points to a tag object; readiness must compare its commit."""
    _write_minimal_release(tmp_path, "4.65.0")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "candidate"], cwd=tmp_path, check=True)
    subprocess.run(["git", "tag", "-a", "v4.65.0", "-m", "release"], cwd=tmp_path, check=True)

    result = _run(["--repo-root", str(tmp_path)], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HEAD is already tagged" in result.stdout


def test_against_real_master() -> None:
    """Smoke-test stable release invariants against the actual repository.

    The git-tag state is tied to the exact release-cycle moment, so this test
    checks only the always-valid source/changelog relationship.

    In CI we assert the two parts that are stable across the release
    cycle: the version is in lockstep across the four sources (covered
    by tests/test_version_sync.py::test_against_real_master) and the
    top CHANGELOG entry matches the current VERSION.
    """
    if not (REPO / "arena" / "constants.py").exists():
        pytest.skip("not running inside the actual repo")
    import re as _re
    src = (REPO / "arena" / "constants.py").read_text(encoding="utf-8")
    m = _re.search(r'VERSION = "(\d+\.\d+\.\d+)"', src)
    assert m, "could not extract VERSION from arena/constants.py"
    cl = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## v{m.group(1)}" in cl, (
        f"top CHANGELOG entry doesn't match version {m.group(1)}"
    )


def test_release_checklist_does_not_embed_a_stale_test_count() -> None:
    release = (Path(__file__).resolve().parents[1] / "RELEASE.md").read_text(
        encoding="utf-8"
    )
    assert not re.search(r"currently \*\*[0-9, ]+\s+tests collected\*\*", release), (
        "RELEASE.md must report the collection count from the current full run "
        "instead of committing a number that becomes stale on the next test"
    )
