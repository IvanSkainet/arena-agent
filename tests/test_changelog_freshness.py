"""Tests for scripts/changelog_freshness.py — the release-recency guard."""
from __future__ import annotations

import ast
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "changelog_freshness.py"


def _candidate_root() -> Path:
    _here = Path(__file__).resolve().parent
    for c in (_here, _here.parent):
        if (c / "scripts" / "changelog_freshness.py").exists():
            return c
    return _here.parent


REPO = _candidate_root()
SCRIPT = REPO / "scripts" / "changelog_freshness.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True,
    )


def _write_changelog(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_script_exists() -> None:
    assert SCRIPT.exists()


def test_script_parses() -> None:
    ast.parse(SCRIPT.read_text())


def test_recent_entry_passes(tmp_path: Path) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    _write_changelog(
        tmp_path / "CHANGELOG.md",
        f"## v4.65.0 - {today}\n\nFresh entry.\n",
    )
    r = _run(["--en", str(tmp_path / "CHANGELOG.md")], tmp_path)
    assert r.returncode == 0
    assert "OK" in r.stdout


def test_old_entry_fails(tmp_path: Path) -> None:
    old = (datetime.now(timezone.utc) - timedelta(days=120)).date().isoformat()
    _write_changelog(
        tmp_path / "CHANGELOG.md",
        f"## v4.0.0 - {old}\n\nOld entry.\n",
    )
    r = _run(["--en", str(tmp_path / "CHANGELOG.md")], tmp_path)
    assert r.returncode == 1
    assert "STALE" in r.stdout


def test_missing_file_does_not_fail(tmp_path: Path) -> None:
    """If the CHANGELOG file is missing, the guard warns but does not block
    (a brand-new repo wouldn't have a CHANGELOG yet)."""
    r = _run(["--en", str(tmp_path / "nonexistent.md")], tmp_path)
    assert r.returncode == 0
    assert "not found" in r.stdout


def test_no_date_literal_does_not_fail(tmp_path: Path) -> None:
    """A CHANGELOG without any date literal is treated as 'no signal',
    not as 'old entry' — better to allow than to false-positive."""
    _write_changelog(
        tmp_path / "CHANGELOG.md",
        "## v4.65.0\n\nSome entry without a date.\n",
    )
    r = _run(["--en", str(tmp_path / "CHANGELOG.md")], tmp_path)
    assert r.returncode == 0
    assert "no date literal" in r.stdout


def test_custom_max_age(tmp_path: Path) -> None:
    """A 30-day-old entry should fail with --max-age-days 10 but pass
    with --max-age-days 60."""
    old = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    _write_changelog(
        tmp_path / "CHANGELOG.md",
        f"## v4.0.0 - {old}\n\nOld entry.\n",
    )
    r1 = _run(["--en", str(tmp_path / "CHANGELOG.md"), "--max-age-days", "10"], tmp_path)
    assert r1.returncode == 1
    r2 = _run(["--en", str(tmp_path / "CHANGELOG.md"), "--max-age-days", "60"], tmp_path)
    assert r2.returncode == 0


def test_picks_latest_date(tmp_path: Path) -> None:
    """When multiple dates are present, the guard uses the latest one."""
    old = (datetime.now(timezone.utc) - timedelta(days=200)).date().isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(days=5)).date().isoformat()
    _write_changelog(
        tmp_path / "CHANGELOG.md",
        f"## v3.0.0 - {old}\n\nOld.\n\n## v4.0.0 - {recent}\n\nFresh.\n",
    )
    r = _run(["--en", str(tmp_path / "CHANGELOG.md")], tmp_path)
    assert r.returncode == 0
    assert recent in r.stdout


def test_against_real_master() -> None:
    if not (REPO / "CHANGELOG.md").exists():
        pytest.skip("not running inside the actual repo")
    r = _run([], REPO)
    assert r.returncode == 0, f"changelog_freshness failed against the real repo: {r.stdout}"


def test_iso8601_with_timezone_offset() -> None:
    """Regression: a date with a `+00:00` offset should parse, not crash."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    p = Path("/tmp/_cl_iso_test.md")
    p.write_text(f"captured_at: \"{today}\"\n## v4.0.0\n\nNo date here.\n", encoding="utf-8")
    r = _run(["--en", str(p), "--max-age-days", "30"], Path("/tmp"))
    p.unlink()
    assert r.returncode == 0
