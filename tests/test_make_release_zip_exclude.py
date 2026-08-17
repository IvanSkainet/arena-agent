"""v4.83.0 — release-zip exclusion of rotated runtime logs.

While cutting v4.83.0 a tracked ``requests.jsonl.2`` (a logrotate-style
rotated request log) leaked into the release zip: ``should_exclude``
matched the exact base name ``requests.jsonl`` but not the rotated
``requests.jsonl.2``. The fix matches runtime logs on a prefix so any
rotation suffix is excluded. These tests pin that behaviour.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import zipfile
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


def test_legacy_version_json_never_ships() -> None:
    assert _mod.should_exclude("version.json") is True
    assert _mod.should_exclude("nested/version.json") is True


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


def test_release_provenance_rejects_malformed_version(monkeypatch):
    monkeypatch.setenv("ARENA_SOURCE_COMMIT", "a" * 40)
    monkeypatch.setenv("ARENA_CANDIDATE_RUN_ID", "12345")
    for malformed in ("9.9", "v9.9.9", "9.9.9-rc1", "９.９.９"):
        with pytest.raises(SystemExit, match="strict X.Y.Z"):
            _mod.release_provenance(malformed)


def test_release_zip_is_byte_reproducible_and_preserves_index_modes(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "arena").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "install.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    (root / "arena" / "z.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "arena" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
    (root / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")

    modes = {
        "install.sh": "100755",
        "arena/z.py": "100644",
        "arena/a.py": "100644",
        "docs/guide.md": "100644",
    }
    monkeypatch.setattr(_mod, "ROOT", root)
    monkeypatch.setattr(_mod, "untracked_files", lambda: [])
    monkeypatch.setattr(_mod, "tracked_modes", lambda: modes)
    monkeypatch.setenv("ARENA_SOURCE_COMMIT", "a" * 40)
    monkeypatch.setenv("ARENA_CANDIDATE_RUN_ID", "12345")

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    assert _mod.main(["make_release_zip.py", "9.9.9", str(first)]) == 0

    # Checkout time, filesystem iteration order, and umask must not affect bytes.
    for index, path in enumerate(sorted(root.rglob("*"))):
        if path.is_file():
            os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
            path.chmod(0o600)
    assert _mod.main(["make_release_zip.py", "9.9.9", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()

    with zipfile.ZipFile(first) as archive:
        infos = archive.infolist()
        assert [info.filename for info in infos] == sorted(info.filename for info in infos)
        assert {info.date_time for info in infos} == {(1980, 1, 1, 0, 0, 0)}
        by_name = {info.filename: info for info in infos}
        assert (by_name["arena-bridge/install.sh"].external_attr >> 16) & 0o777 == 0o755
        assert (by_name["arena-bridge/arena/a.py"].external_attr >> 16) & 0o777 == 0o644


@pytest.mark.parametrize("directory_target", [False, True])
def test_release_zip_rejects_tracked_symlinks(tmp_path, monkeypatch, directory_target):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "target"
    if directory_target:
        target.mkdir()
        (target / "nested.txt").write_text("nested", encoding="utf-8")
    else:
        target.write_text("target", encoding="utf-8")
    link = root / "link"
    try:
        link.symlink_to(target, target_is_directory=directory_target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    monkeypatch.setattr(_mod, "ROOT", root)
    monkeypatch.setattr(_mod, "untracked_files", lambda: [])
    monkeypatch.setattr(
        _mod,
        "tracked_modes",
        lambda: {"link": "120000", "target": "100644"},
    )

    def forbidden_walk(*_args, **_kwargs):
        raise AssertionError("os.walk must not run before tracked modes are validated")

    monkeypatch.setattr(_mod.os, "walk", forbidden_walk)
    with pytest.raises(SystemExit, match="unsupported git mode"):
        _mod.main(["make_release_zip.py", "9.9.9", str(tmp_path / "bad.zip")])
