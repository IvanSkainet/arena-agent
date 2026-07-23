"""Tests for scripts/pre_release_check.py — the release-readiness guard."""
from __future__ import annotations

import ast
import json
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
    (tmp_path / "docs").mkdir()
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
    # docs/version.json
    (tmp_path / "docs" / "version.json").write_text(json.dumps({
        "tag_name": f"v{version}",
        "semver": version,
        "updated_at": "2026-07-24T00:00:00Z",
    }), encoding="utf-8")


def test_script_exists() -> None:
    assert SCRIPT.exists()


def test_script_parses() -> None:
    ast.parse(SCRIPT.read_text())


def test_fresh_repo_with_version_no_git_passes(tmp_path: Path) -> None:
    """A brand-new release candidate (not in a git repo) where every
    version source is in sync, the CHANGELOG top entry matches, and
    docs/version.json matches, should pass — git state is optional."""
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


def test_version_json_mismatch_fails(tmp_path: Path) -> None:
    _write_minimal_release(tmp_path, "4.65.0")
    (tmp_path / "docs" / "version.json").write_text(json.dumps({
        "tag_name": "v4.64.0",  # stale
        "semver": "4.64.0",
        "updated_at": "2026-07-23T00:00:00Z",
    }), encoding="utf-8")
    r = _run(["--repo-root", str(tmp_path)], tmp_path)
    assert r.returncode == 1
    assert "tag_name" in r.stdout


def test_version_json_missing_is_ok(tmp_path: Path) -> None:
    """A repo without docs/version.json (e.g. a fork that doesn't
    have the badge workflow yet) should still pass."""
    _write_minimal_release(tmp_path, "4.65.0")
    (tmp_path / "docs" / "version.json").unlink()
    r = _run(["--repo-root", str(tmp_path)], tmp_path)
    assert r.returncode == 0
    assert "not present" in r.stdout


def test_against_real_master() -> None:
    if not (REPO / "arena" / "constants.py").exists():
        pytest.skip("not running inside the actual repo")
    r = _run(["--repo-root", str(REPO)], REPO)
    assert r.returncode == 0, f"pre_release_check failed against the real repo: {r.stdout}"
