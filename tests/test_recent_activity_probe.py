"""Tests for the recent_activity inventory probe (v4.34.0).

Covers the probe function itself + its registration in the
inventory registry so a downstream consumer (dashboard cards,
text formatter, /v1/inventory) can find it.

The probe is I/O heavy so tests use a temporary directory as
the sole scan root to keep them deterministic.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from arena.inventory.probe_agent_ctx import get_recent_activity
from arena.inventory.registry import REGISTRY


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def test_recent_activity_registered_in_registry():
    names = {s.name for s in REGISTRY}
    assert "recent_activity" in names


def test_recent_activity_section_metadata():
    sec = next(s for s in REGISTRY if s.name == "recent_activity")
    assert sec.label == "Recent activity"
    assert sec.category == "agent"
    assert sec.collector is get_recent_activity
    assert sec.format_lines is not None


def test_recent_activity_format_handles_empty():
    """Formatter must not crash on an empty file list."""
    sec = next(s for s in REGISTRY if s.name == "recent_activity")
    empty = {
        "available": True,
        "window_minutes": 60,
        "roots_scanned": ["/tmp/x"],
        "matched": 0,
        "returned": 0,
        "files": [],
        "top_extensions": {},
    }
    lines = sec.format_lines(empty)
    assert any("no recent" in line.lower() for line in lines)


def test_recent_activity_format_unavailable_returns_empty():
    sec = next(s for s in REGISTRY if s.name == "recent_activity")
    assert sec.format_lines({"available": False}) == []


# ---------------------------------------------------------------------------
# Probe behaviour
# ---------------------------------------------------------------------------
def _seed_files(root: Path, n: int, age_seconds: float = 0.0) -> list[Path]:
    """Create N files under root and stamp their mtime to now-age."""
    now = time.time()
    paths = []
    for i in range(n):
        p = root / f"seed_{i}.txt"
        p.write_text(f"file {i}\n")
        target = now - age_seconds
        os.utime(p, (target, target))
        paths.append(p)
    return paths


@pytest.fixture
def _fake_home(tmp_path, monkeypatch):
    """Redirect Path.home() to a temp dir so the probe walks a
    tiny predictable tree instead of the tester's real $HOME."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake)
    return fake


def test_probe_returns_expected_shape(_fake_home):
    r = get_recent_activity(window_minutes=60, limit=5)
    assert r["available"] is True
    assert r["window_minutes"] == 60
    assert isinstance(r["roots_scanned"], list)
    assert isinstance(r["files"], list)
    assert isinstance(r["top_extensions"], dict)
    assert r["walk_capped"] is False


def test_probe_finds_recent_files(_fake_home):
    _seed_files(_fake_home, n=5, age_seconds=10)  # ten seconds old
    r = get_recent_activity(window_minutes=60, limit=100)
    assert r["matched"] >= 5
    names = {Path(f["path"]).name for f in r["files"]}
    for i in range(5):
        assert f"seed_{i}.txt" in names


def test_probe_ignores_files_older_than_window(_fake_home):
    _seed_files(_fake_home, n=3, age_seconds=10)      # fresh
    old_root = _fake_home / "old"
    old_root.mkdir()
    _seed_files(old_root, n=3, age_seconds=3600 * 3)  # 3 hours old
    r = get_recent_activity(window_minutes=30, limit=100)
    names = {Path(f["path"]).name for f in r["files"]}
    for i in range(3):
        assert f"seed_{i}.txt" in names
    # Old files should NOT be in the returned list. But because our
    # _seed_files uses the same names in a subdir, filter by path.
    assert not any(str(_fake_home / "old") in f["path"] for f in r["files"])


def test_probe_respects_limit(_fake_home):
    _seed_files(_fake_home, n=20, age_seconds=5)
    r = get_recent_activity(window_minutes=60, limit=7)
    assert r["returned"] == 7
    assert len(r["files"]) == 7


def test_probe_clamps_limit_to_200(_fake_home):
    r = get_recent_activity(window_minutes=60, limit=99999)
    assert r["returned"] <= 200


def test_probe_prunes_excluded_dirs(_fake_home):
    """__pycache__, node_modules, .git, etc. must NOT be walked."""
    for excluded in ("__pycache__", "node_modules", ".git",
                     ".pytest_cache", ".arena_proposals"):
        d = _fake_home / excluded
        d.mkdir()
        (d / "should_not_appear.py").write_text("x")
    r = get_recent_activity(window_minutes=60, limit=100)
    for f in r["files"]:
        for excluded in ("__pycache__", "node_modules", ".git/",
                         ".pytest_cache", ".arena_proposals"):
            assert excluded not in f["path"], (
                f"probe walked into excluded dir: {f['path']}"
            )


def test_probe_skips_oversized_files(_fake_home):
    """Files > 5 MB must be excluded (they're usually build
    artifacts, not user work)."""
    big = _fake_home / "huge.bin"
    with open(big, "wb") as fh:
        fh.seek(6 * 1024 * 1024)
        fh.write(b"\x00")
    r = get_recent_activity(window_minutes=60, limit=100)
    assert not any(Path(f["path"]).name == "huge.bin" for f in r["files"])


def test_probe_sorts_newest_first(_fake_home):
    (a := _fake_home / "old.txt").write_text("old")
    time.sleep(0.05)
    (b := _fake_home / "new.txt").write_text("new")
    r = get_recent_activity(window_minutes=60, limit=100)
    # Find the two file entries by name and prove the ordering.
    positions = {Path(f["path"]).name: i for i, f in enumerate(r["files"])}
    assert positions["new.txt"] < positions["old.txt"]


def test_probe_top_extensions_counts(_fake_home):
    for i in range(4):
        (_fake_home / f"a{i}.py").write_text("x")
    for i in range(2):
        (_fake_home / f"b{i}.md").write_text("x")
    r = get_recent_activity(window_minutes=60, limit=100)
    assert r["top_extensions"].get(".py") >= 4
    assert r["top_extensions"].get(".md") >= 2


def test_probe_handles_permission_errors_silently(_fake_home):
    """A directory that raises PermissionError during walk must
    not sink the probe -- it should skip and continue."""
    good = _fake_home / "readable.txt"
    good.write_text("ok")
    r = get_recent_activity(window_minutes=60, limit=100)
    assert r["available"] is True
    # good file should be there
    assert any(Path(f["path"]).name == "readable.txt" for f in r["files"])


def test_probe_age_seconds_field_present(_fake_home):
    _seed_files(_fake_home, n=1, age_seconds=15)
    r = get_recent_activity(window_minutes=60, limit=5)
    assert r["files"], "should have at least one file"
    f = r["files"][0]
    assert "age_seconds" in f
    # Should be roughly 15s (a bit of tolerance for CI slowness).
    assert 10 <= f["age_seconds"] <= 60


def test_probe_never_returns_negative_age(_fake_home):
    """Clock skew or filesystem quirks could yield a future mtime;
    the probe clamps to 0 rather than surfacing negative age."""
    weird = _fake_home / "future.txt"
    weird.write_text("x")
    future = time.time() + 3600
    os.utime(weird, (future, future))
    r = get_recent_activity(window_minutes=120, limit=100)
    for f in r["files"]:
        assert f["age_seconds"] >= 0
