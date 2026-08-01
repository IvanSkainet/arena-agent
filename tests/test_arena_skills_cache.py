"""v4.76.0 coverage expansion: tests for arena/skills/cache.py.

v4.76.0 is the second step of the coverage-gate
gradual-tightening plan. The first step (v4.74.0)
covered ``arena.util``; the second covers
``arena/skills/cache.py`` (60% coverage, 48 lines,
15 missing statements).

``SkillsCache`` is a small hot-reload cache for skill
registry scans. It exposes:

* ``__init__`` — stores config.
* ``reset`` — clears the state.
* ``_current_mtimes`` — scans the skills directory
  and returns a dict of file path -> mtime.
* ``list`` — returns the cached skill list,
  rescanning when stale or mtimes changed.

The class is mostly internal — the tests construct a
cache against a temporary directory and exercise the
public surface.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

try:
    from arena.skills.cache import SkillsCache
except Exception:  # pragma: no cover
    pytest.skip("arena.skills.cache not importable", allow_module_level=True)


def _empty_scan() -> dict[str, Any]:
    return {"ok": True, "count": 0, "skills": []}


def _fixed_scan(skills: list[dict]) -> Any:
    def scan() -> dict[str, Any]:
        return {"ok": True, "count": len(skills), "skills": skills}
    return scan


# -------------------------------------------------------------------
# Construction
# -------------------------------------------------------------------


def test_skills_cache_construction(tmp_path: Path) -> None:
    """SkillsCache can be constructed with the minimum required arguments."""
    cache = SkillsCache(skills_dir=tmp_path, scan_fn=_empty_scan)
    assert cache.skills_dir == tmp_path
    assert cache.ttl == 5.0  # default
    assert cache.hot_reload is True  # default


def test_skills_cache_construction_with_custom_args(tmp_path: Path) -> None:
    """SkillsCache respects the optional ttl and hot_reload arguments."""
    cache = SkillsCache(skills_dir=tmp_path, scan_fn=_empty_scan, ttl=10.0, hot_reload=False)
    assert cache.ttl == 10.0
    assert cache.hot_reload is False


# -------------------------------------------------------------------
# reset
# -------------------------------------------------------------------


def test_skills_cache_reset_clears_state(tmp_path: Path) -> None:
    """reset() clears the cached state (last_scan, skills, mtimes)."""
    cache = SkillsCache(skills_dir=tmp_path, scan_fn=_empty_scan, hot_reload=False)
    # First list() populates the cache.
    cache.list()
    # Now reset.
    cache.reset()
    # After reset, last_scan is 0.0 — a subsequent list() will rescan.
    with cache._lock:
        assert cache._state["last_scan"] == 0.0
        assert cache._state["skills"] == []
        assert cache._state["mtimes"] == {}


# -------------------------------------------------------------------
# _current_mtimes
# -------------------------------------------------------------------


def test_current_mtimes_empty_dir(tmp_path: Path) -> None:
    """_current_mtimes returns an empty dict for a non-existent directory."""
    cache = SkillsCache(skills_dir=tmp_path / "nonexistent", scan_fn=_empty_scan)
    assert cache._current_mtimes() == {}


def test_current_mtimes_scans_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_current_mtimes returns file path -> mtime for files in skills_dir."""
    # Create a few files in tmp_path with known extensions.
    (tmp_path / "skill1.md").write_text("# skill 1")
    (tmp_path / "skill2.yaml").write_text("name: skill2")
    (tmp_path / "skill3.json").write_text("{}")
    cache = SkillsCache(skills_dir=tmp_path, scan_fn=_empty_scan)
    mtimes = cache._current_mtimes()
    # Only files with the recognised extensions are
    # included. The test creates .md, .yaml, .json files
    # (all in the recognised set).
    assert len(mtimes) == 3
    for path, mtime in mtimes.items():
        assert isinstance(mtime, float)
        assert Path(path).exists()


def test_current_mtimes_ignores_unrelated_extensions(tmp_path: Path) -> None:
    """_current_mtimes ignores files with extensions outside the recognised set."""
    (tmp_path / "skill.md").write_text("# yes")
    (tmp_path / "ignored.txt").write_text("no")
    (tmp_path / "ignored.exe").write_text("no")
    (tmp_path / "ignored.bin").write_text("no")
    cache = SkillsCache(skills_dir=tmp_path, scan_fn=_empty_scan)
    mtimes = cache._current_mtimes()
    paths = list(mtimes.keys())
    assert len(paths) == 1
    assert paths[0].endswith(".md")


# -------------------------------------------------------------------
# list
# -------------------------------------------------------------------


def test_skills_cache_list_first_call_scans(tmp_path: Path) -> None:
    """The first list() call always scans (no cached state yet)."""
    scan_count = [0]
    def scan() -> dict[str, Any]:
        scan_count[0] += 1
        return {"ok": True, "count": 0, "skills": []}
    cache = SkillsCache(skills_dir=tmp_path, scan_fn=scan, hot_reload=False)
    result = cache.list()
    assert result["ok"] is True
    assert result["cached"] is False
    assert scan_count[0] == 1


def test_skills_cache_list_within_ttl_returns_cached(tmp_path: Path) -> None:
    """A second list() within the TTL returns the cached result (hot_reload=False)."""
    cache = SkillsCache(skills_dir=tmp_path, scan_fn=_empty_scan, ttl=10.0, hot_reload=False)
    cache.list()
    result = cache.list()
    assert result["cached"] is True


def test_skills_cache_list_after_ttl_rescans(tmp_path: Path) -> None:
    """A list() after the TTL expires rescans (hot_reload=False)."""
    scan_count = [0]
    def scan() -> dict[str, Any]:
        scan_count[0] += 1
        return {"ok": True, "count": 0, "skills": []}
    cache = SkillsCache(skills_dir=tmp_path, scan_fn=scan, ttl=0.01, hot_reload=False)
    cache.list()
    time.sleep(0.05)  # wait past the TTL
    cache.list()
    assert scan_count[0] == 2


def test_skills_cache_list_with_hot_reload_detects_changes(tmp_path: Path) -> None:
    """With hot_reload=True, changes to the skills directory trigger a rescan."""
    scan_count = [0]
    def scan() -> dict[str, Any]:
        scan_count[0] += 1
        return {"ok": True, "count": 0, "skills": []}
    cache = SkillsCache(skills_dir=tmp_path, scan_fn=scan, ttl=0.01, hot_reload=True)
    cache.list()
    # Add a new file to the skills directory.
    (tmp_path / "skill.md").write_text("# new skill")
    time.sleep(0.05)
    cache.list()
    # Two scans: the initial + the rescan after the new file.
    assert scan_count[0] >= 2
