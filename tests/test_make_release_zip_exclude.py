"""v4.83.0 — release-zip exclusion of rotated runtime logs.

While cutting v4.83.0 a tracked ``requests.jsonl.2`` (a logrotate-style
rotated request log) leaked into the release zip: ``should_exclude``
matched the exact base name ``requests.jsonl`` but not the rotated
``requests.jsonl.2``. The fix matches runtime logs on a prefix so any
rotation suffix is excluded. These tests pin that behaviour.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _load():
    spec = importlib.util.spec_from_file_location(
        "make_release_zip", REPO / "scripts" / "make_release_zip.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load()


def test_exact_runtime_logs_excluded():
    for name in ("requests.jsonl", "audit.jsonl", "bridge.log",
                 "token.txt", "facts.jsonl", "history.jsonl"):
        assert _mod.should_exclude(name) is True, name


def test_coverage_xml_never_ships_from_a_post_test_release_tree():
    """The first v4.169.43 clean-tag archive carried the ignored 1.9 MB report."""
    assert _mod.should_exclude("coverage.xml") is True
    assert _mod.should_exclude("nested/coverage.xml") is True
    assert _mod.should_exclude(".coverage") is True


def test_workspace_guard_queries_ignored_files_too(monkeypatch):
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        if "--ignored" in argv:
            return Result("coverage.xml\n.future-tool-output\n")
        return Result("ordinary-untracked.txt\n")

    monkeypatch.setattr(_mod.subprocess, "run", fake_run)
    assert _mod.untracked_files() == [
        ".future-tool-output",
        "coverage.xml",
        "ordinary-untracked.txt",
    ]
    assert len(calls) == 2
    assert "--ignored" not in calls[0]
    assert "--ignored" in calls[1]


def test_workspace_guard_fails_closed_when_git_cannot_measure(monkeypatch):
    class Failed:
        returncode = 1
        stdout = ""
        stderr = "not a work tree"

    monkeypatch.setattr(_mod.subprocess, "run", lambda *_args, **_kwargs: Failed())
    with pytest.raises(SystemExit, match="cannot verify release workspace"):
        _mod.untracked_files()


def test_rotated_runtime_logs_excluded():
    # The actual v4.83.0 regression: rotated logs must not ship.
    for name in ("requests.jsonl.1", "requests.jsonl.2", "audit.jsonl.3",
                 "bridge.log.1", "bridge.log.12"):
        assert _mod.should_exclude(name) is True, name


def test_rotated_logs_excluded_even_under_arena_bridge_prefix():
    assert _mod.should_exclude("arena-bridge/requests.jsonl.2") is True


def test_normal_files_are_kept():
    for name in ("arena/mobile/recording.py", "unified_bridge.py",
                 "arena/constants.py", "install.sh", "README.md"):
        assert _mod.should_exclude(name) is False, name


def test_tests_and_vcs_dirs_still_excluded():
    assert _mod.should_exclude("tests/test_foo.py") is True
    assert _mod.should_exclude(".git/config") is True
    assert _mod.should_exclude("arena/__pycache__/x.pyc") is True


def test_tool_cache_directories_never_ship():
    """v4.157.0 — `.ruff_cache/` shipped inside every release zip.

    EXCLUDE_SUBDIRS enumerated caches by name (`__pycache__`, `.pytest_cache`,
    `node_modules`, `.mypy_cache`), so each new tool's cache was excluded only
    if someone remembered to add it. ruff's was not: the v4.156.0 archive
    carried 17 files / 316 KB of hashed cache blobs. The rule is now shaped
    ("dot-prefixed directory ending in _cache/-cache"), not enumerated.
    """
    for path in (
        ".ruff_cache/CACHEDIR.TAG",
        ".ruff_cache/0.16.1/15276370199070142989",
        "arena/.ruff_cache/nested",
        ".pyrefly_cache/anything",       # not yet emitted here; must not regress
        ".hypothesis/unicode_data/x",    # v4.158.0: 600 files rode along once
        ".hypothesis/examples/abc123",
        "arena/.hypothesis/nested",
        ".tox/py312/lib/x.py",
        ".nox/session/x.py",
        ".hypothesis-cache/x",
        ".mypy_cache/x",
        "__pycache__/x.pyc",
    ):
        assert _mod.should_exclude(path) is True, path


def test_real_sources_are_not_mistaken_for_caches():
    """The cache rule must not swallow shipped files that merely say 'cache'."""
    for path in (
        "arena/util.py",
        "dashboard/assets/00-core.js",
        "docs/cache_notes.md",
        "arena/my_cache/data.json",      # no dot prefix -> a real package dir
        "arena/cache_manager.py",
        "arena/hypothesis_helper.py",    # 'hypothesis' in the name is not a cache
    ):
        assert _mod.should_exclude(path) is False, path
