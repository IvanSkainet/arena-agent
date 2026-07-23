"""Tests for scripts/version_sync.py — the four-source version drift guard."""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "version_sync.py"


def _candidate_root() -> Path:
    """Resolve the repo root whether the test is in tests/ or in a scratch dir."""
    _here = Path(__file__).resolve().parent
    for c in (_here, _here.parent):
        if (c / "scripts" / "version_sync.py").exists():
            return c
    return _here.parent


REPO = _candidate_root()
SCRIPT = REPO / "scripts" / "version_sync.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True,
    )


def _write(tmp_path: Path, constants_v: str, pyproject_v: str, bridge_versions: list[str]) -> None:
    (tmp_path / "arena").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "arena" / "constants.py").write_text(
        f'VERSION = "{constants_v}"\n', encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "{pyproject_v}"\n', encoding="utf-8",
    )
    body = ",\n    ".join(f'"{v}"' for v in bridge_versions)
    (tmp_path / "tests" / "_version_matrix.py").write_text(
        f"BRIDGE_VERSIONS: tuple[str, ...] = (\n    {body},\n)\n"
        "LATEST_BRIDGE: str = BRIDGE_VERSIONS[-1]\n",
        encoding="utf-8",
    )


def test_script_exists() -> None:
    assert SCRIPT.exists(), f"version_sync.py missing at {SCRIPT}"


def test_script_parses() -> None:
    ast.parse(SCRIPT.read_text())


def test_all_four_in_sync(tmp_path: Path) -> None:
    _write(tmp_path, "4.65.0", "4.65.0", ["4.63.0", "4.64.0", "4.65.0"])
    r = _run(["--repo-root", str(tmp_path)], tmp_path)
    assert r.returncode == 0
    assert "OK" in r.stdout
    assert "4.65.0" in r.stdout


def test_drift_constants_vs_pyproject(tmp_path: Path) -> None:
    _write(tmp_path, "4.65.0", "4.64.0", ["4.65.0"])
    r = _run(["--repo-root", str(tmp_path)], tmp_path)
    assert r.returncode == 1
    assert "FAIL" in r.stdout
    assert "drift" in r.stdout


def test_drift_bridge_versions_behind(tmp_path: Path) -> None:
    """bridge_versions[-1] is the source of truth for tests/ but a stale
    entry here would silently break the test matrix."""
    _write(tmp_path, "4.65.0", "4.65.0", ["4.64.0"])  # missing 4.65.0
    r = _run(["--repo-root", str(tmp_path)], tmp_path)
    assert r.returncode == 1
    assert "FAIL" in r.stdout


def test_json_output(tmp_path: Path) -> None:
    _write(tmp_path, "4.65.0", "4.65.0", ["4.65.0"])
    r = _run(["--repo-root", str(tmp_path), "--json"], tmp_path)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["in_sync"] is True
    assert data["unique_values"] == ["4.65.0"]


def test_json_output_drift(tmp_path: Path) -> None:
    _write(tmp_path, "4.66.0", "4.65.0", ["4.65.0"])
    r = _run(["--repo-root", str(tmp_path), "--json"], tmp_path)
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert data["in_sync"] is False
    assert set(data["unique_values"]) == {"4.65.0", "4.66.0"}


def test_missing_constants(tmp_path: Path) -> None:
    """If arena/constants.py doesn't have a VERSION literal, the guard
    should report the missing source — not crash."""
    (tmp_path / "arena").mkdir()
    (tmp_path / "arena" / "constants.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "4.65.0"\n', encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "_version_matrix.py").write_text(
        'BRIDGE_VERSIONS: tuple[str, ...] = ("4.65.0",)\nLATEST_BRIDGE: str = BRIDGE_VERSIONS[-1]\n',
        encoding="utf-8",
    )
    r = _run(["--repo-root", str(tmp_path)], tmp_path)
    # constants.py is None, so unique set has fewer than 4 entries — in_sync is False
    assert r.returncode == 1


def test_against_real_master() -> None:
    """Run the guard against the actual repo root (where v4.65.0 is shipped).
    This is the 'no false positive' check — if the released state fails
    its own guard, the guard is wrong."""
    if not (REPO / "arena" / "constants.py").exists():
        pytest.skip("not running inside the actual repo")
    r = _run(["--repo-root", str(REPO)], REPO)
    assert r.returncode == 0, f"version_sync.py failed against the real repo: {r.stdout}"
